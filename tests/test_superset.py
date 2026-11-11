"""Unit and HTTP API v2 integration tests for the Kerdon + Archon Complete Superset."""
from __future__ import annotations

import json
import unittest

import kerdon as kd
from kerdon_aws.handlers import dispatch_http_event, lambda_evaluator
from kerdon_aws.persistence import MultiTenantStore
from kerdon_aws.superset_routes import reset_superset_runtime


def _http_event(
    method: str,
    path: str,
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    query: str = "",
) -> dict:
    return {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": query,
        "requestContext": {"http": {"method": method, "path": path}},
        "headers": headers or {},
        "body": json.dumps(body) if body is not None else None,
    }


class TestKerdonArchonSuperset(unittest.TestCase):
    """Verify A1-A6 (Kerdon) and B1-B5 (Archon) capabilities end-to-end."""

    def setUp(self) -> None:
        reset_superset_runtime()
        self.store = MultiTenantStore(workspace=kd.build_default_msp_workspace())
        self.tid = self.store.workspace.default_tenant_id
        self.state = self.store.get_tenant_state(self.tid)

    def test_a1_typed_quantity_and_settlement_supersession(self) -> None:
        q_amb = kd.parse_typed_quantity(0, zero_is_verified=False)
        self.assertEqual(q_amb.state, kd.QuantityState.LEGACY_AMBIGUOUS)
        self.assertIsNone(q_amb.value)

        q_ver = kd.parse_typed_quantity(0, zero_is_verified=True)
        self.assertEqual(q_ver.state, kd.QuantityState.KNOWN)
        self.assertEqual(q_ver.value, 0)

        res = dispatch_http_event(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/commissions/supersede",
                {
                    "authority_rank": "OFFICIAL_SETTLEMENT",
                    "captured_date": "2026-11-01",
                    "reward_net_cents": 1_920_000,
                    "tnps_score": 81,
                },
            ),
            store=self.store,
        )
        self.assertEqual(res["statusCode"], 200)
        payload = json.loads(res["body"])["supersession"]
        self.assertEqual(payload["finality_status"], "official")
        self.assertEqual(payload["winning_revision"]["reward_net_cents"], 1_920_000)
        self.assertGreaterEqual(len(payload["superseded_revision_ids"]), 2)

    def test_a2_plan_version_diff_and_seller_private_dispute(self) -> None:
        sim_res = lambda_evaluator(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/commissions/plan-diff",
                {"mode": "RETROACTIVE", "rate_boost_bps": 50},
            ),
            store=self.store,
        )
        self.assertEqual(sim_res["statusCode"], 200)
        sim_data = json.loads(sim_res["body"])["simulation"]
        self.assertEqual(sim_data["candidate_mode"], "RETROACTIVE")
        self.assertGreater(sim_data["total_delta_cents"], 0)

        # Seller role can view their own private statement and submit a dispute
        disp_res = dispatch_http_event(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/commissions/dispute",
                {"reason_text": "Ζητώ επανέλεγχο της πώλησης FTTH #101."},
                headers={"x-kerdon-role": "SELLER", "x-kerdon-actor": "sel-nikos-papadakis"},
            ),
            store=self.store,
        )
        self.assertEqual(disp_res["statusCode"], 200)
        priv = json.loads(disp_res["body"])["seller_private_view"]
        self.assertTrue(priv["payroll_register_redacted"])
        self.assertEqual(len(priv["disputes"]), 1)

        get_priv = dispatch_http_event(
            _http_event(
                "GET",
                f"/tenants/{self.tid}/commissions/seller-statement",
                headers={"x-kerdon-role": "SELLER", "x-kerdon-actor": "sel-nikos-papadakis"},
            ),
            store=self.store,
        )
        self.assertEqual(get_priv["statusCode"], 200)

    def test_a3_b5_pdf_rendering_and_durable_send_ledger(self) -> None:
        draft_id = self.state.outbound_drafts[0].draft_id
        pdf_res = dispatch_http_event(
            _http_event("GET", f"/tenants/{self.tid}/docgen/{draft_id}/pdf"),
            store=self.store,
        )
        self.assertEqual(pdf_res["statusCode"], 200)
        pdf_data = json.loads(pdf_res["body"])
        self.assertTrue(pdf_data["pdf_header"].startswith("%PDF-1.4"))
        self.assertGreater(pdf_data["size_bytes"], 400)

        # First dispatch succeeds and reserves tokens
        send1 = dispatch_http_event(
            _http_event("POST", f"/tenants/{self.tid}/docgen/{draft_id}/send", {}),
            store=self.store,
        )
        self.assertEqual(send1["statusCode"], 200)

        # Second dispatch of the same draft is blocked by DurableSendLedger (409)
        send2 = dispatch_http_event(
            _http_event("POST", f"/tenants/{self.tid}/docgen/{draft_id}/send", {}),
            store=self.store,
        )
        self.assertEqual(send2["statusCode"], 409)
        self.assertEqual(json.loads(send2["body"])["code"], "DUPLICATE_SEND_BLOCKED")

    def test_b1_b2_archon_six_reader_gate_remittances_and_dispute_hold(self) -> None:
        # 1. Verify equal instalment with distinct transfer_reference is allowed
        inst_res = dispatch_http_event(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/remittances/classify",
                {
                    "amount_cents": 50_000,
                    "value_date": "2026-10-18",
                    "transfer_reference": "SEPA-TRF-20261018-9999-INST2",
                },
            ),
            store=self.store,
        )
        self.assertEqual(inst_res["statusCode"], 200)
        self.assertEqual(
            json.loads(inst_res["body"])["decision"]["classification"],
            "VALID_INSTALMENT",
        )

        # 2. Attest the unverified remittance so its hold is cleared
        att_res = dispatch_http_event(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/remittances/attest",
                {"verified_transfer_reference": "SEPA-ATTESTED-20261022-9901"},
            ),
            store=self.store,
        )
        self.assertEqual(att_res["statusCode"], 200)

        # 3. Hallucinated amount in prose is blocked by the Deterministic Release Gate
        bad_gate = lambda_evaluator(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/strands-gate/verify",
                {"candidate_prose": "Please pay EUR 999,999.00 immediately."},
            ),
            store=self.store,
        )
        self.assertEqual(bad_gate["statusCode"], 200)
        verdict = json.loads(bad_gate["body"])["release_gate_verdict"]
        self.assertFalse(verdict["allowed"])
        self.assertEqual(verdict["blocked_reason"], "NUMERIC_DRIFT_IN_PROSE")

        # 4. Client dispute reply places a Collection Hold, and resolving it restores ALLOWED
        hold_res = dispatch_http_event(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/disputes/hold",
                {"action": "place_hold"},
            ),
            store=self.store,
        )
        self.assertEqual(hold_res["statusCode"], 200)
        self.assertEqual(
            json.loads(hold_res["body"])["release_gate_verdict"]["blocked_reason"],
            "CLIENT_DISPUTE_COLLECTION_HOLD",
        )

        rel_res = dispatch_http_event(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/disputes/hold",
                {"action": "resolve"},
            ),
            store=self.store,
        )
        self.assertEqual(rel_res["statusCode"], 200)
        self.assertTrue(
            json.loads(rel_res["body"])["release_gate_verdict"]["allowed"]
        )

    def test_b3_b4_a6_portfolio_240_evidence_bundle_invites_and_subscription(self) -> None:
        port_res = dispatch_http_event(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/portfolio/mode",
                {"mode": "FULL_240_PORTFOLIO"},
            ),
            store=self.store,
        )
        self.assertEqual(port_res["statusCode"], 200)
        p_data = json.loads(port_res["body"])["portfolio"]
        self.assertEqual(p_data["total_records"], 240)
        self.assertEqual(p_data["customer_count"], 16)
        self.assertEqual(p_data["supplier_count"], 10)

        ev_res = dispatch_http_event(
            _http_event("GET", f"/tenants/{self.tid}/evidence-bundle"),
            store=self.store,
        )
        self.assertEqual(ev_res["statusCode"], 200)
        ev_data = json.loads(ev_res["body"])
        self.assertEqual(
            ev_data["schema"], "KERDON_ARCHON_REDACTED_EVIDENCE_BUNDLE_V1"
        )
        self.assertEqual(len(ev_data["bundle_sha256"]), 64)

        inv_res = dispatch_http_event(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/invites",
                {"action": "create", "email": "cfo@aegean-mobility.gr", "role": "ACCOUNTANT"},
            ),
            store=self.store,
        )
        self.assertEqual(inv_res["statusCode"], 200)
        inv_id = json.loads(inv_res["body"])["invite"]["invite_id"]

        claim_res = dispatch_http_event(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/invites",
                {"action": "claim", "invite_id": inv_id},
            ),
            store=self.store,
        )
        self.assertEqual(claim_res["statusCode"], 200)
        self.assertEqual(json.loads(claim_res["body"])["invite"]["status"], "CLAIMED")

        sub_res = dispatch_http_event(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/billing/subscription",
                {"plan_code": "pro"},
            ),
            store=self.store,
        )
        self.assertEqual(sub_res["statusCode"], 200)
        sub_data = json.loads(sub_res["body"])
        self.assertEqual(sub_data["monthly_price_eur"], 79)
        self.assertIn("six_reader_strands_release_gate", sub_data["entitlements"])

    def test_m9_inventory_stock_movements_cogs_and_reorder_po(self) -> None:
        inv_get = dispatch_http_event(
            _http_event("GET", f"/tenants/{self.tid}/inventory"),
            store=self.store,
        )
        self.assertEqual(inv_get["statusCode"], 200)
        inv_data = json.loads(inv_get["body"])["inventory"]
        self.assertEqual(len(inv_data["sku_items"]), 4)
        self.assertGreater(inv_data["total_stock_valuation_cents"], 0)
        self.assertGreaterEqual(len(inv_data["alerts"]), 2)
        self.assertGreaterEqual(len(inv_data["draft_purchase_orders"]), 2)

        # Receive +10 units of SKU-ONT-WIFI6-PRO
        gr_res = dispatch_http_event(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/inventory/movement",
                {
                    "sku_code": "SKU-ONT-WIFI6-PRO",
                    "movement_kind": "GOODS_RECEIPT",
                    "quantity": 10,
                    "unit_cost_cents": 6_400,
                },
            ),
            store=self.store,
        )
        self.assertEqual(gr_res["statusCode"], 200)
        gr_body = json.loads(gr_res["body"])
        self.assertEqual(gr_body["updated_sku"]["on_hand_qty"], 24)

        # Dispatch -5 units of SKU-ONT-WIFI6-PRO -> posts COGS and revenue
        sd_res = dispatch_http_event(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/inventory/movement",
                {
                    "sku_code": "SKU-ONT-WIFI6-PRO",
                    "movement_kind": "SALE_DISPATCH",
                    "quantity": 5,
                    "unit_sale_price_cents": 11_900,
                },
            ),
            store=self.store,
        )
        self.assertEqual(sd_res["statusCode"], 200)
        sd_body = json.loads(sd_res["body"])
        self.assertEqual(sd_body["updated_sku"]["on_hand_qty"], 19)
        self.assertGreater(sd_body["movement"]["cogs_cents"], 0)
        self.assertEqual(sd_body["movement"]["revenue_cents"], 59_500)

        # Excessive sale dispatch is blocked by deterministic negative stock guard
        neg_res = dispatch_http_event(
            _http_event(
                "POST",
                f"/tenants/{self.tid}/inventory/movement",
                {
                    "sku_code": "SKU-ONT-WIFI6-PRO",
                    "movement_kind": "SALE_DISPATCH",
                    "quantity": 9999,
                },
            ),
            store=self.store,
        )
        self.assertEqual(neg_res["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
