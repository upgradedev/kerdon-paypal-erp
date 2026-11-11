"""Unit and integration tests for Kerdon MSP AWS runtime adapters and HTTP API v2."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import kerdon as kd  # noqa: E402
import kerdon_aws as kaws  # noqa: E402


class _FakeAgentCoreClient:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def create_event(self, **kwargs: object) -> dict[str, str]:
        self.events.append(kwargs)
        return {"eventId": "ev-1"}


class TestHttpApiV2AndTrapT6(unittest.TestCase):
    def setUp(self) -> None:
        self.store = kaws.MultiTenantStore()
        self.tid = self.store.workspace.default_tenant_id

    def test_stage_prefix_stripping_and_head_routes(self) -> None:
        for raw_path in ("/Prod/health", "/prod/health", "/health"):
            res = kaws.lambda_reader(
                {"requestContext": {"http": {"method": "GET", "path": raw_path}}, "rawPath": raw_path},
                store=self.store,
            )
            self.assertEqual(res["statusCode"], 200)
            body = json.loads(res["body"])
            self.assertEqual(body["status"], "ok")

        head_res = kaws.lambda_reader(
            {"requestContext": {"http": {"method": "HEAD", "path": "/Prod/DEPLOYED_SHA"}}, "rawPath": "/Prod/DEPLOYED_SHA"},
            store=self.store,
        )
        self.assertEqual(head_res["statusCode"], 200)
        self.assertEqual(head_res["body"], "")

        cockpit_get = kaws.lambda_reader(
            {"requestContext": {"http": {"method": "GET", "path": "/Prod"}}, "rawPath": "/Prod"},
            store=self.store,
        )
        self.assertEqual(cockpit_get["statusCode"], 200)
        self.assertIn("Sofia Marinou", cockpit_get["body"])

    def test_payload_16kb_cap_and_strict_dict_json_validation(self) -> None:
        oversized = "x" * (kaws.MAX_BODY_BYTES + 100)
        res_413 = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST", "path": "/Prod/tenants/onboard"}},
                "rawPath": "/Prod/tenants/onboard",
                "body": oversized,
            },
            store=self.store,
        )
        self.assertEqual(res_413["statusCode"], 413)

        for non_dict_body in ("[]", '"scalar"', "123", "{bad-json"):
            res_400 = kaws.lambda_writer(
                {
                    "requestContext": {"http": {"method": "POST", "path": "/Prod/tenants/onboard"}},
                    "rawPath": "/Prod/tenants/onboard",
                    "body": non_dict_body,
                },
                store=self.store,
            )
            self.assertEqual(res_400["statusCode"], 400)

        # Base64 encoded valid dict body
        b64_payload = base64.b64encode(
            json.dumps(
                {
                    "slug": "b64-tenant",
                    "display_name": "Base64 Tenant SA",
                    "tax_id": "EL990011990",
                }
            ).encode("utf-8")
        ).decode("ascii")
        res_201 = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST", "path": "/Prod/tenants/onboard"}},
                "rawPath": "/Prod/tenants/onboard",
                "isBase64Encoded": True,
                "body": b64_payload,
            },
            store=self.store,
        )
        self.assertEqual(res_201["statusCode"], 201)

    def test_least_privilege_reader_and_evaluator_refuse_mutations_a7(self) -> None:
        mut_event = {
            "requestContext": {"http": {"method": "POST", "path": f"/Prod/tenants/{self.tid}/treasury/execute"}},
            "rawPath": f"/Prod/tenants/{self.tid}/treasury/execute",
            "body": json.dumps({"approval_id": "apr-aegean-mobility-comm-oct"}),
        }
        r_res = kaws.lambda_reader(mut_event, store=self.store)
        self.assertEqual(r_res["statusCode"], 403)

        e_res = kaws.lambda_evaluator(mut_event, store=self.store)
        self.assertEqual(e_res["statusCode"], 403)

        # Seller role lacks approve_payouts capability
        seller_event = {
            "requestContext": {"http": {"method": "POST", "path": f"/Prod/tenants/{self.tid}/treasury/execute"}},
            "rawPath": f"/Prod/tenants/{self.tid}/treasury/execute",
            "headers": {"x-kerdon-role": "SELLER", "x-kerdon-actor": "slr-1"},
            "body": json.dumps({"approval_id": "apr-aegean-mobility-comm-oct"}),
        }
        w_res = kaws.lambda_writer(seller_event, store=self.store)
        self.assertEqual(w_res["statusCode"], 403)

    def test_all_reader_evaluator_writer_routes_and_changed_evidence_invalidation(self) -> None:
        for subpath in (
            "/tenants",
            f"/tenants/{self.tid}/overview",
            f"/tenants/{self.tid}/ledger",
            f"/tenants/{self.tid}/commissions",
            f"/tenants/{self.tid}/completeness",
            f"/tenants/{self.tid}/board-pack",
            f"/tenants/{self.tid}/treasury",
            f"/tenants/{self.tid}/documents/doc-aegean-mobility-sal-101/link",
        ):
            r = kaws.lambda_reader({"rawPath": subpath}, store=self.store)
            self.assertEqual(r["statusCode"], 200, subpath)

        # Evaluator routes
        ev_res = kaws.lambda_evaluator(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/evaluate",
                "body": json.dumps({"period": "2026-10"}),
            },
            store=self.store,
        )
        self.assertEqual(ev_res["statusCode"], 200)
        self.assertEqual(len(json.loads(ev_res["body"])["stages"]), 8)

        q_res = kaws.lambda_evaluator(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/query",
                "body": json.dumps({"question": "What is our EBITDA and VAT?"}),
            },
            store=self.store,
        )
        self.assertEqual(q_res["statusCode"], 200)

        sim_res = kaws.lambda_evaluator(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/commissions/simulate",
                "body": json.dumps({"sales_cents": 3_000_000}),
            },
            store=self.store,
        )
        self.assertEqual(sim_res["statusCode"], 200)

        # Writer: ingest email
        ing_res = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/ingest/email",
                "body": json.dumps(
                    {
                        "message_id": "msg-api-1",
                        "sender": "billing@vendor.gr",
                        "subject": "October Bill",
                    }
                ),
            },
            store=self.store,
        )
        self.assertEqual(ing_res["statusCode"], 201)

        # Writer: credit note invalidates supplier payout approval ONLY
        cn_res = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/credit-notes",
                "body": json.dumps(
                    {
                        "credit_note_id": "cn-oct-99",
                        "counterparty_id": "sup-aegean-mobility-01",
                        "net_cents": 20_000,
                        "vat_cents": 4_800,
                        "gross_cents": 24_800,
                        "referenced_invoice_id": "doc-aegean-mobility-pur-201",
                    }
                ),
            },
            store=self.store,
        )
        self.assertEqual(cn_res["statusCode"], 200)
        cn_data = json.loads(cn_res["body"])
        self.assertEqual(cn_data["invalidated_approval_ids"], ["apr-aegean-mobility-sup-201"])

        # Attempting to execute invalidated supplier approval returns HTTP 409
        stale_exec = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/treasury/execute",
                "body": json.dumps({"approval_id": "apr-aegean-mobility-sup-201"}),
            },
            store=self.store,
        )
        self.assertEqual(stale_exec["statusCode"], 409)

        # Executing unaffected commission payout approval returns HTTP 200 with Aletheia receipt
        ok_exec = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/treasury/execute",
                "body": json.dumps({"approval_id": "apr-aegean-mobility-comm-oct"}),
            },
            store=self.store,
        )
        self.assertEqual(ok_exec["statusCode"], 200)
        self.assertIn("aletheia_receipt", json.loads(ok_exec["body"]))

        # Four-eyes commission approval: self-approval -> 403, distinct approver -> 200
        self_app = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/commissions/approve",
                "body": json.dumps({"submitted_by": "mgr-1", "approver_id": "mgr-1"}),
            },
            store=self.store,
        )
        self.assertEqual(self_app["statusCode"], 403)

        ok_app = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/commissions/approve",
                "body": json.dumps({"submitted_by": "mgr-1", "approver_id": "act-sofia-marinou"}),
            },
            store=self.store,
        )
        self.assertEqual(ok_app["statusCode"], 200)

        # Step Functions month-end close invocation
        sfn_res = kaws.lambda_writer(
            {"action": "month_end_close", "tenant_id": self.tid}, store=self.store
        )
        self.assertEqual(sfn_res["status"], "SUCCEEDED")

    def test_strands_bedrock_and_agentcore_memory_adapters(self) -> None:
        state = self.store.get_tenant_state(self.tid)
        fake_ac = _FakeAgentCoreClient()
        old_mem = os.environ.get("AGENTCORE_MEMORY_ID")
        os.environ["AGENTCORE_MEMORY_ID"] = "mem-kerdon-01"
        try:
            wf = kaws.run_eight_stage_erp_workflow(
                state,
                model_invoker=lambda sys_p, usr_p: "Vendor courier debit cleared 48h prior to billing cycle.",
                memory_client_factory=lambda svc, region_name="eu-west-1": fake_ac,
            )
            self.assertEqual(wf.source, "strands-bedrock")
            self.assertEqual(wf.agentcore_memory_status, "recorded:mem-kerdon-01")
            self.assertEqual(len(fake_ac.events), 1)

            ans = kaws.answer_query_with_bedrock(
                "Summarize October performance",
                state.fact_sheet,
                model_invoker=lambda sys_p, usr_p: f"Verified EBITDA is {kd.format_eur(state.fact_sheet.ebitda_cents)}.",
            )
            self.assertEqual(ans.source, "strands-bedrock-grounded")
        finally:
            if old_mem is None:
                os.environ.pop("AGENTCORE_MEMORY_ID", None)
            else:
                os.environ["AGENTCORE_MEMORY_ID"] = old_mem

    def test_hexagonal_ports_and_swap_test_refusal_k1(self) -> None:
        self.assertIsInstance(self.store, kd.WorkspaceRepositoryPort)
        self.assertIsInstance(self.store, kd.EvidenceBlobStorePort)
        snap = self.store.save_snapshot(self.tid)
        self.assertEqual(snap["tenant_id"], self.tid)
        uri = self.store.put_evidence_blob(self.tid, "a" * 64, b"PDF-BYTES")
        self.assertIn(self.tid, uri)

        state = self.store.get_tenant_state(self.tid)
        # Persona 01 K1 Swap Test: when require_live=True and synthesizer fails, refuse silent fallback
        with self.assertRaises(RuntimeError):
            kaws.run_eight_stage_erp_workflow(
                state,
                require_live=True,
                model_invoker=lambda _s, _u: (_ for _ in ()).throw(
                    ConnectionError("Simulated Bedrock outage")
                ),
            )

    def test_cross_tenant_isolation_writer_guard_and_reset_mf4(self) -> None:
        # Writer refuses GET and evaluator-only routes (A7)
        w_get = kaws.lambda_writer(
            {"requestContext": {"http": {"method": "GET", "path": "/Prod/health"}}, "rawPath": "/Prod/health"},
            store=self.store,
        )
        self.assertEqual(w_get["statusCode"], 403)

        w_eval = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST", "path": f"/Prod/tenants/{self.tid}/evaluate"}},
                "rawPath": f"/Prod/tenants/{self.tid}/evaluate",
                "body": "{}",
            },
            store=self.store,
        )
        self.assertEqual(w_eval["statusCode"], 403)

        # Cross-tenant body spoofing rejected with HTTP 403 (MF-4)
        x_res = kaws.lambda_evaluator(
            {
                "requestContext": {"http": {"method": "POST", "path": f"/Prod/tenants/{self.tid}/evaluate"}},
                "rawPath": f"/Prod/tenants/{self.tid}/evaluate",
                "body": json.dumps({"tenant_id": "tnt-other-spoofed"}),
            },
            store=self.store,
        )
        self.assertEqual(x_res["statusCode"], 403)

        # Reset route restores default workspace state
        rst_res = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST", "path": f"/Prod/tenants/{self.tid}/reset"}},
                "rawPath": f"/Prod/tenants/{self.tid}/reset",
                "body": "{}",
            },
            store=self.store,
        )
        self.assertEqual(rst_res["statusCode"], 200)

    def test_phase27_codex_remediation_guarantees(self) -> None:
        from unittest.mock import patch
        from kerdon_aws.connectors_adapter import ExternalProviderError, PayPalConnectorPlugin

        # 1. PayPal live OAuth/HTTP failure must raise ExternalProviderError (502), never silently succeed
        plugin_live = PayPalConnectorPlugin(
            client_id="bad-id",
            client_secret="bad-secret",
            base_url="http://127.0.0.1:1",
        )
        with self.assertRaises(ExternalProviderError):
            plugin_live.capture_order(
                tenant_id=self.tid,
                order_id="PPORD-1",
                document_id="doc-1",
                gross_cents=1000,
                currency="EUR",
            )

        # 2. Journal replay isolation: 1 payout POST + 2 cold GETs = 1 provider call total
        call_counter = {"count": 0}
        orig_exec = PayPalConnectorPlugin.execute_batch_payout

        def _counting_payout(self_pp, **kwargs):
            call_counter["count"] += 1
            return orig_exec(self_pp, **kwargs)

        ap_id = f"apr-{self.store.get_tenant_state(self.tid).tenant.slug}-comm-oct"
        payout_body = {
            "approval_id": ap_id,
            "executor_id": "act-nikos-alexiou",
            "recipient_email": "seller-payout-sb@kerdon-synth.eu",
        }
        with patch.object(PayPalConnectorPlugin, "execute_batch_payout", _counting_payout):
            r_pay = kaws.lambda_writer(
                {
                    "requestContext": {"http": {"method": "POST"}},
                    "rawPath": f"/tenants/{self.tid}/connectors/paypal/payout",
                    "body": json.dumps(payout_body),
                },
                store=self.store,
            )
            self.assertEqual(r_pay["statusCode"], 200)
            self.assertEqual(call_counter["count"], 1)

            # Simulate 2 cold-start replays using the recorded journal body (with _replay_provider_receipt)
            journal_Items = [
                {
                    "sk": "0000000001#1",
                    "path": f"/tenants/{self.tid}/connectors/paypal/payout",
                    "body_json": json.dumps(
                        {
                            **payout_body,
                            "_journal_actor_id": "act-sofia-marinou",
                            "_replay_provider_receipt": {
                                "payout_batch_id": "PPBATCH-REPLAY01",
                                "sender_batch_id": "sb-1",
                                "status": "SUCCESS",
                                "provider_mode": "paypal-sandbox-simulated",
                            },
                        }
                    ),
                    "role": "MSP_FINOPS_DIRECTOR",
                }
            ]
            from unittest.mock import MagicMock

            for _ in range(2):
                mock_ddb = MagicMock()
                mock_ddb.query.return_value = {
                    "Items": [
                        {
                            "sk": {"S": item["sk"]},
                            "path": {"S": item["path"]},
                            "body_json": {"S": item["body_json"]},
                            "role": {"S": item["role"]},
                        }
                        for item in journal_Items
                    ]
                }
                cold_store = kaws.MultiTenantStore(
                    app_table_name="kerdon-msp-app", ddb_client=mock_ddb
                )
                r_get = kaws.lambda_reader(
                    {"rawPath": f"/tenants/{self.tid}/connectors"},
                    store=cold_store,
                )
                self.assertEqual(r_get["statusCode"], 200)
            self.assertEqual(call_counter["count"], 1)

        # 3. Invented executor_id rejected with 403; nonexistent payable rejected with 400
        r_bad_exec = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/connectors/paypal/payout",
                "body": json.dumps({"approval_id": ap_id, "executor_id": "act-invented-hacker"}),
            },
            store=self.store,
        )
        self.assertEqual(r_bad_exec["statusCode"], 403)

        r_bad_payable = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/treasury/approvals",
                "body": json.dumps(
                    {
                        "approval_id": "apr-fake-1",
                        "counterparty_id": "sup-aegean-mobility-01",
                        "invoice_or_case_id": "doc-does-not-exist-999",
                        "amount_cents": 5000,
                        "evidence_sha256": "b" * 64,
                    }
                ),
            },
            store=self.store,
        )
        self.assertEqual(r_bad_payable["statusCode"], 400)

        # 4. Same actor creating and executing an approval via /treasury/approvals -> /treasury/execute is blocked (403)
        r_ap_ok = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/treasury/approvals",
                "body": json.dumps(
                    {
                        "approval_id": "apr-self-test-1",
                        "counterparty_id": "sup-aegean-mobility-01",
                        "invoice_or_case_id": "doc-aegean-mobility-pur-201",
                        "amount_cents": 5000,
                        "evidence_sha256": "c" * 64,
                    }
                ),
            },
            store=self.store,
        )
        self.assertEqual(r_ap_ok["statusCode"], 201)
        r_self_exec = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/treasury/execute",
                "body": json.dumps({"approval_id": "apr-self-test-1"}),
            },
            store=self.store,
        )
        self.assertEqual(r_self_exec["statusCode"], 403)

        # 5. Rolling 7-day idempotency lock across week boundary (604_799 -> 604_801)
        eng = kd.TreasuryEngine(tenant_id="tnt-1")
        eng.configure_pocket("EUR", balance_cents=1_000_000, reserve_floor_cents=0)
        eng.create_approval(
            approval_id="ap-w1",
            counterparty_id="sup-1",
            invoice_or_case_id="inv-1",
            amount_cents=10_000,
            currency="EUR",
            evidence_sha256="d" * 64,
            approver_id="act-1",
            now_epoch=604_799,
        )
        eng.execute_payout(approval_id="ap-w1", now_epoch=604_799)
        eng.create_approval(
            approval_id="ap-w2",
            counterparty_id="sup-1",
            invoice_or_case_id="inv-1",
            amount_cents=10_000,
            currency="EUR",
            evidence_sha256="d" * 64,
            approver_id="act-1",
            now_epoch=604_801,
        )
        with self.assertRaises(kd.DuplicateIdempotencyError):
            eng.execute_payout(approval_id="ap-w2", now_epoch=604_801)

        # 6. Braille receipt encodes currency, amount, and approver; STORE_MANAGER RBAC redacts payroll & blocks treasury
        rcpt_b = kd.seal_aletheia_receipt(
            tenant_id=self.tid,
            subject_id="sub-1",
            approver_id="act-sofia",
            amount_cents=12345,
            currency="EUR",
            evidence_hashes=("e" * 64,),
        )
        self.assertGreater(len(rcpt_b.braille_ascii), 20)
        self.assertNotEqual(
            rcpt_b.braille_ascii,
            kd.seal_aletheia_receipt(
                tenant_id=self.tid,
                subject_id="sub-1",
                approver_id="act-sofia",
                amount_cents=99999,
                currency="EUR",
                evidence_hashes=("e" * 64,),
            ).braille_ascii,
        )
        mgr_hdr = {"x-kerdon-role": "STORE_MANAGER", "x-kerdon-actor": "act-aegean-manager"}
        r_mgr_ov = kaws.lambda_reader(
            {"rawPath": f"/tenants/{self.tid}/overview", "headers": mgr_hdr},
            store=self.store,
        )
        self.assertEqual(r_mgr_ov["statusCode"], 200)
        self.assertTrue(json.loads(r_mgr_ov["body"])["workforce_fusion"].get("redacted"))
        r_mgr_tr = kaws.lambda_reader(
            {"rawPath": f"/tenants/{self.tid}/treasury", "headers": mgr_hdr},
            store=self.store,
        )
        self.assertEqual(r_mgr_tr["statusCode"], 403)

    def test_phase28_live_bedrock_extraction_agentcore_and_gtm_marketplace(self) -> None:
        """Verify Phase 28 Bedrock extraction routing, AgentCore read-back, email candidate extraction, and GTM Marketplace."""
        # 1. EvaluatorFunction handles /erp/ai/extract-document while WriterFunction refuses it (Least Privilege A7)
        ext_body = json.dumps(
            {
                "raw_text": "Vendor: Olympos Cloud Hosting\nInvoice #INV-2026-991\nDate: 2026-10-30\nCloud Nodes: EUR 1500.00 (24% VAT)",
                "module": "purchases",
            }
        )
        r_writer_ext = kaws.lambda_writer(
            {"requestContext": {"http": {"method": "POST"}}, "rawPath": "/erp/ai/extract-document", "body": ext_body},
            store=self.store,
        )
        self.assertEqual(r_writer_ext["statusCode"], 403)
        r_eval_ext = kaws.lambda_evaluator(
            {"requestContext": {"http": {"method": "POST"}}, "rawPath": "/erp/ai/extract-document", "body": ext_body},
            store=self.store,
        )
        self.assertEqual(r_eval_ext["statusCode"], 200)
        draft = json.loads(r_eval_ext["body"])["extracted_draft"]
        self.assertEqual(draft["counterparty_name"], "Olympos Cloud Hosting")
        self.assertEqual(draft["invoice_number"], "INV-2026-991")
        self.assertEqual(draft["total_gross_cents"], 186000)

        # Direct test of extract_document_with_bedrock enrichment + require_live refusal
        state = self.store.get_tenant_state(self.tid)
        enriched = kaws.bedrock_adapter.extract_document_with_bedrock(
            state,
            "Vendor: Olympos Cloud Hosting\nInvoice #INV-2026-991\nCloud Nodes: EUR 1500.00 (24% VAT)",
            llm_mode="bedrock",
            model_invoker=lambda _s, _u: '{"counterparty_name":"Olympos Cloud Hosting SA","invoice_number":"INV-2026-991","issued_date":"2026-10-30","due_date":"2026-11-30","description":"Dedicated GPU Nodes"}',
        )
        self.assertTrue(enriched.extraction_engine.startswith("strands-bedrock:"))
        self.assertEqual(enriched.counterparty_name, "Olympos Cloud Hosting SA")
        self.assertEqual(enriched.total_gross_cents, 186000)
        with self.assertRaises(RuntimeError):
            kaws.bedrock_adapter.extract_document_with_bedrock(
                state,
                "Vendor: Olympos Cloud Hosting\nCloud Nodes: EUR 100.00",
                llm_mode="bedrock",
                model_invoker=lambda _s, _u: "",
                require_live=True,
            )

        # 2. AgentCore Memory create_event + list_events read-back
        class _FakeAgentCoreClient:
            def __init__(self) -> None:
                self.events: list[dict[str, object]] = []

            def create_event(self, **kwargs: object) -> dict[str, object]:
                self.events.append(kwargs)
                return {"eventId": "ev-ac-1"}

            def list_events(self, **_kwargs: object) -> dict[str, object]:
                return {"events": self.events}

        fake_ac = _FakeAgentCoreClient()
        mem_st = kaws.record_agentcore_memory_event(
            tenant_id=self.tid,
            session_id="sess-1",
            event_summary="Close completed",
            memory_id="kerdon_msp_memory_01",
            client_factory=lambda *_a, **_kw: fake_ac,
        )
        self.assertEqual(mem_st, "recorded:kerdon_msp_memory_01:events=1")
        read_st, read_events = kaws.bedrock_adapter.retrieve_agentcore_memory_events(
            tenant_id=self.tid,
            session_id="sess-1",
            memory_id="kerdon_msp_memory_01",
            client_factory=lambda *_a, **_kw: fake_ac,
        )
        self.assertEqual(read_st, "active:kerdon_msp_memory_01:events=1")
        self.assertEqual(len(read_events), 1)

        # 3. GTM Readiness, AWS Marketplace metering, Opening Trial Balance, and Email Candidate Extraction
        r_gtm = kaws.lambda_reader({"rawPath": "/gtm/readiness"}, store=self.store)
        self.assertEqual(r_gtm["statusCode"], 200)
        self.assertEqual(len(json.loads(r_gtm["body"])["pillars"]), 6)

        r_mp = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": "/gtm/marketplace/resolve-customer",
                "body": json.dumps({"registration_token": "tok-test-123"}),
            },
            store=self.store,
        )
        self.assertEqual(r_mp["statusCode"], 200)
        mp_cust = json.loads(r_mp["body"])["entitlement"]["customer_identifier"]
        r_mtr = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": "/gtm/marketplace/meter-usage",
                "body": json.dumps({"customer_identifier": mp_cust, "period": "2026-10"}),
            },
            store=self.store,
        )
        self.assertEqual(r_mtr["statusCode"], 200)
        self.assertEqual(len(json.loads(r_mtr["body"])["records"]), 3)

        r_ob = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/onboarding/opening-balance",
                "body": json.dumps(
                    {
                        "as_of_date": "2026-10-01",
                        "rows": [
                            {"account": "1000_CASH", "debit_cents": 250000, "credit_cents": 0},
                            {"account": "2000_ACCOUNTS_PAYABLE", "debit_cents": 0, "credit_cents": 250000},
                        ],
                    }
                ),
            },
            store=self.store,
        )
        self.assertEqual(r_ob["statusCode"], 201)

        r_ing = kaws.lambda_writer(
            {
                "requestContext": {"http": {"method": "POST"}},
                "rawPath": f"/tenants/{self.tid}/ingest/email",
                "body": json.dumps(
                    {
                        "message_id": "msg-unit-extract-1",
                        "sender": "ap@olympos.eu",
                        "subject": "Vendor: Olympos Cloud Invoice #INV-77",
                        "attachment_content": "Vendor: Olympos Cloud\nInvoice #INV-77\nServer Hosting: EUR 400.00 (24% VAT)",
                    }
                ),
            },
            store=self.store,
        )
        self.assertEqual(r_ing["statusCode"], 201)
        self.assertEqual(json.loads(r_ing["body"])["extracted_candidate"]["gross_cents"], 49600)


if __name__ == "__main__":
    unittest.main()
