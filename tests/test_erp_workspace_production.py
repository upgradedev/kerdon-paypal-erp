"""Production readiness test suite for `feat/erp-workspace` Steps 1-9 (`docs/ANTIGRAVITY_HANDOFF.md`).

Covers:
1. Production Identity (JWT Authorizer claims, signed HS256 Bearer tokens, strict fail-closed 401/403,
   ignored client role headers in strict mode, tenant list & fleet filtering, seller statement privacy,
   and empty-state production tenant onboarding).
2. Persistence Hardening (zero suppressed errors -> HTTP 503, paginated DynamoDB journal hydration,
   fail-closed replay & cross-tenant journal audit, optimistic entity versioning -> HTTP 409,
   globally scoped idempotency keys, and SHA-256 verified backup/restore).
3. Party CRUD, Durable Drafts, Multi-Line Mixed-VAT Invoices, Direct Expenses & Document Reversals.
4. Customer Receipts & Supplier Payments with Partial/Many-to-Many Allocations, Unapplied Advances,
   Bank Fees, Approved Sandbox Payment Provider & Signed Webhook Reconciliation.
5. Durable Monthly Targets (Company/Store/Seller), Due-Date AR/AP Aging, Profitability & Cash Forecast.
"""
from __future__ import annotations

import json
from typing import Any
import unittest

import kerdon as kd
from kerdon.erp_services import reset_erp_extensions
from kerdon_aws import MultiTenantStore, dispatch_http_event
from kerdon_aws.identity import mint_hs256_jwt
from kerdon_aws.persistence import PersistenceReplayError
from kerdon_aws.sandbox_provider import reset_sandbox_runtime, sign_webhook_payload


class FakeDynamoClient:
    """In-memory mock DynamoDB client supporting pagination, conditional checks, and failure injection."""

    def __init__(self, *, fail_writes: bool = False, page_size: int = 2) -> None:
        self.fail_writes = fail_writes
        self.page_size = page_size
        self.items: list[dict[str, Any]] = []

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail_writes:
            raise RuntimeError("Simulated DynamoDB ProvisionedThroughputExceededException")
        item = kwargs["Item"]
        cond = kwargs.get("ConditionExpression", "")
        pk = item["pk"]["S"]
        sk = item.get("sk", {}).get("S", "")
        existing = next(
            (x for x in self.items if x["pk"]["S"] == pk and x.get("sk", {}).get("S", "") == sk),
            None,
        )
        if "attribute_not_exists(pk)" in cond and existing is not None:
            raise RuntimeError("ConditionalCheckFailedException: item already exists")
        if "entity_version = :expected" in cond:
            expected_v = kwargs["ExpressionAttributeValues"][":expected"]["N"]
            if existing is None or existing.get("entity_version", {}).get("N") != expected_v:
                raise RuntimeError("ConditionalCheckFailedException: version mismatch")
        if existing is not None:
            self.items.remove(existing)
        self.items.append(item)
        return {}

    def query(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail_writes:
            raise RuntimeError("Simulated DynamoDB query outage")
        pk_val = kwargs["ExpressionAttributeValues"][":pk"]["S"]
        matching = [x for x in self.items if x["pk"]["S"] == pk_val]
        start_idx = 0
        eks = kwargs.get("ExclusiveStartKey")
        if eks:
            start_idx = int(eks["offset"])
        slice_items = matching[start_idx : start_idx + self.page_size]
        out: dict[str, Any] = {"Items": slice_items}
        if start_idx + self.page_size < len(matching):
            out["LastEvaluatedKey"] = {"offset": str(start_idx + self.page_size)}
        return out


class ErpWorkspaceProductionTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_erp_extensions()
        reset_sandbox_runtime()
        self.store = MultiTenantStore()
        self.tid = self.store.workspace.default_tenant_id
        self.state = self.store.get_tenant_state(self.tid)

    def req(
        self,
        path: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        jwt_claims: dict[str, Any] | None = None,
        query: str = "",
        store: MultiTenantStore | None = None,
    ) -> dict[str, Any]:
        req_ctx: dict[str, Any] = {"http": {"method": method, "path": path}}
        if jwt_claims is not None:
            req_ctx["authorizer"] = {"jwt": {"claims": jwt_claims}}
        ev = {
            "rawPath": path,
            "rawQueryString": query,
            "headers": headers or {},
            "requestContext": req_ctx,
            "body": json.dumps(body) if body is not None else "",
        }
        return dispatch_http_event(ev, store=store or self.store)

    def test_step1_cockpit_base_url_and_workspace_head_routes(self) -> None:
        r_root = self.req("/", "GET")
        self.assertEqual(r_root["statusCode"], 200)
        self.assertIn("Kerdon | ERP Operations", r_root["body"])
        r_root_head = self.req("/", "HEAD")
        self.assertEqual(r_root_head["statusCode"], 200)
        self.assertEqual(r_root_head["body"], "")
        r_cockpit = self.req("/cockpit", "GET")
        self.assertEqual(r_cockpit["statusCode"], 301)
        self.assertEqual(r_cockpit["headers"]["location"], "/")
        r_ws_head = self.req("/workspace", "HEAD")
        self.assertEqual(r_ws_head["statusCode"], 301)
        self.assertEqual(r_ws_head["body"], "")

    def test_step2_strict_auth_fails_closed_and_ignores_spoofed_role_headers(self) -> None:
        strict_hdrs = {
            "x-kerdon-auth-mode": "strict",
            "x-kerdon-role": "MSP_FINOPS_DIRECTOR",
            "x-kerdon-actor": "spoofed-director",
        }
        # Public health/shell paths remain 200 (and legacy paths 301 redirect cleanly)
        self.assertEqual(self.req("/health", headers=strict_hdrs)["statusCode"], 200)
        self.assertEqual(self.req("/", headers=strict_hdrs)["statusCode"], 200)
        self.assertEqual(self.req("/workspace", headers=strict_hdrs)["statusCode"], 301)
        # Protected data routes fail closed with 401 when no verified JWT is present
        self.assertEqual(self.req("/tenants", headers=strict_hdrs)["statusCode"], 401)
        self.assertEqual(
            self.req(f"/tenants/{self.tid}/operations", headers=strict_hdrs)["statusCode"],
            401,
        )

        # Signed HS256 Bearer token for single-tenant Aegean Owner succeeds on Aegean
        token = mint_hs256_jwt({"sub": "usr-aegean-owner"}, ttl_seconds=600)
        auth_hdrs = {
            "x-kerdon-auth-mode": "strict",
            "authorization": f"Bearer {token}",
            "x-kerdon-role": "MSP_FINOPS_DIRECTOR",  # Spoof attempt ignored
        }
        r_tenants = self.req("/tenants", headers=auth_hdrs)
        self.assertEqual(r_tenants["statusCode"], 200)
        tenants_list = json.loads(r_tenants["body"])["tenants"]
        self.assertEqual([t["tenant_id"] for t in tenants_list], [self.tid])

        # Cross-tenant access to another tenant is rejected with 403
        other_tid = next(
            k for k in self.store.workspace.catalog.tenants.keys() if k != self.tid
        )
        r_cross = self.req(f"/tenants/{other_tid}/operations", headers=auth_hdrs)
        self.assertEqual(r_cross["statusCode"], 403)

        # Full-state fleet summary is filtered to only Aegean Mobility
        r_full = self.req(f"/tenants/{self.tid}/full-state", headers=auth_hdrs)
        self.assertEqual(r_full["statusCode"], 200)
        fleet_ids = [t["tenant_id"] for t in json.loads(r_full["body"])["fleet_summary"]]
        self.assertEqual(fleet_ids, [self.tid])

        # Expired JWT is rejected with 401
        expired_tok = mint_hs256_jwt(
            {"sub": "usr-aegean-owner"}, ttl_seconds=10, now_epoch=1000
        )
        self.assertEqual(
            self.req(
                "/tenants",
                headers={
                    "x-kerdon-auth-mode": "strict",
                    "authorization": f"Bearer {expired_tok}",
                },
            )["statusCode"],
            401,
        )

        # Unknown JWT subject is rejected with 403
        unknown_tok = mint_hs256_jwt({"sub": "usr-unknown-intruder"}, ttl_seconds=600)
        self.assertEqual(
            self.req(
                "/tenants",
                headers={
                    "x-kerdon-auth-mode": "strict",
                    "authorization": f"Bearer {unknown_tok}",
                },
            )["statusCode"],
            403,
        )

    def test_step2_seller_isolation_and_empty_production_onboarding(self) -> None:
        # API Gateway Authorizer JWT claims for Seller 01
        seller_claims = {"sub": "usr-seller-01"}
        r_own = self.req(
            f"/tenants/{self.tid}/commissions/seller-statement",
            query="seller_id=slr-aegean-mobility-01",
            jwt_claims=seller_claims,
        )
        self.assertEqual(r_own["statusCode"], 200)

        # Seller 01 attempting to read Seller 02 statement -> 403
        r_other = self.req(
            f"/tenants/{self.tid}/commissions/seller-statement",
            query="seller_id=slr-aegean-mobility-02",
            jwt_claims=seller_claims,
        )
        self.assertEqual(r_other["statusCode"], 403)

        # Seller 01 attempting to read company P&L / operations -> 403
        self.assertEqual(
            self.req(f"/tenants/{self.tid}/operations", jwt_claims=seller_claims)["statusCode"],
            403,
        )

        # Production onboarding (strict mode / empty_state=True) starts with 0 events/docs
        dir_claims = {"sub": "usr-sofia-marinou"}
        r_onb = self.req(
            "/tenants/onboard",
            "POST",
            {
                "slug": "clean-prod-co",
                "display_name": "Clean Prod Co",
                "legal_name": "Clean Prod Single Member PC",
                "tax_id": "887766554",
                "empty_state": True,
            },
            jwt_claims=dir_claims,
        )
        self.assertEqual(r_onb["statusCode"], 201)
        onb_data = json.loads(r_onb["body"])
        self.assertTrue(onb_data["empty_state"])
        new_tid = onb_data["tenant"]["tenant_id"]
        r_ops = self.req(f"/tenants/{new_tid}/operations", jwt_claims=dir_claims)
        self.assertEqual(r_ops["statusCode"], 200)
        ops_payload = json.loads(r_ops["body"])
        self.assertEqual(ops_payload["ledger"], [])
        self.assertEqual(ops_payload["records"]["customers"], [])
        self.assertEqual(ops_payload["records"]["sales"], [])

    def test_step3_persistence_errors_paginated_replay_versioning_and_backup(self) -> None:
        # 1. Suppressed errors eliminated: failing DynamoDB raises 503 and does not mark journal applied
        failing_store = MultiTenantStore(
            app_table_name="kerdon-msp-app",
            ddb_client=FakeDynamoClient(fail_writes=True),
        )
        r_fail = self.req(
            f"/tenants/{self.tid}/parties",
            "POST",
            {"kind": "customer", "legal_name": "Fail Co", "tax_id": "123456789"},
            store=failing_store,
        )
        self.assertEqual(r_fail["statusCode"], 503)
        self.assertEqual(len(failing_store.applied_journal_sks), 0)

        # 2. Paginated journal hydration across multiple pages (page_size=2) into fresh worker
        shared_ddb = FakeDynamoClient(page_size=2)
        writer_store = MultiTenantStore(
            app_table_name="kerdon-msp-app", ddb_client=shared_ddb
        )
        for idx in range(1, 5):
            res = self.req(
                f"/tenants/{self.tid}/parties",
                "POST",
                {
                    "kind": "customer",
                    "party_id": f"cus-paged-{idx}",
                    "legal_name": f"Paged Customer {idx}",
                    "tax_id": f"90000000{idx}",
                },
                store=writer_store,
            )
            self.assertEqual(res["statusCode"], 201)

        reader_store = MultiTenantStore(
            app_table_name="kerdon-msp-app", ddb_client=shared_ddb
        )
        r_hydrated = self.req(
            f"/tenants/{self.tid}/operations", store=reader_store
        )
        self.assertEqual(r_hydrated["statusCode"], 200)
        cust_ids = {
            c["id"]
            for c in json.loads(r_hydrated["body"])["records"]["customers"]
        }
        for idx in range(1, 5):
            self.assertIn(f"cus-paged-{idx}", cust_ids)

        # 3. Backup export & tamper detection
        backup = writer_store.export_tenant_backup(self.tid)
        fresh_store = MultiTenantStore()
        restored = fresh_store.verify_and_restore_backup(
            backup,
            lambda p, b, r: self.req(p, "POST", b, store=fresh_store),
        )
        self.assertEqual(restored["replayed_entries"], 4)
        tampered = {**backup, "ledger_event_count": 999999}
        with self.assertRaises(PersistenceReplayError):
            fresh_store.verify_and_restore_backup(tampered, lambda p, b, r: None)

        # 4. Cross-tenant journal segregation audit blocks poisoned journal entry
        bad_ddb = FakeDynamoClient()
        bad_ddb.items.append(
            {
                "pk": {"S": "WORKSPACE#JOURNAL"},
                "sk": {"S": "SEQ#00000000000000000001#bad"},
                "seq_ns": {"N": "1"},
                "tenant_id": {"S": "tnt-hellenic-solar"},
                "path": {"S": f"/tenants/{self.tid}/parties"},
                "role": {"S": "MSP_FINOPS_DIRECTOR"},
                "body_json": {"S": '{"kind":"customer","legal_name":"X","tax_id":"12345"}'},
            }
        )
        poisoned_store = MultiTenantStore(
            app_table_name="kerdon-msp-app", ddb_client=bad_ddb
        )
        r_poison = self.req(f"/tenants/{self.tid}/operations", store=poisoned_store)
        self.assertEqual(r_poison["statusCode"], 503)
        self.assertEqual(len(poisoned_store.applied_journal_sks), 0)

    def test_step4_party_versioning_drafts_mixed_vat_lines_expenses_and_reversal(self) -> None:
        # 1. Party CRUD with optimistic concurrency version checking & idempotency
        r_p1 = self.req(
            f"/tenants/{self.tid}/parties",
            "POST",
            {
                "kind": "customer",
                "party_id": "cus-ver-01",
                "legal_name": "Versioned Client SA",
                "tax_id": "EL112233445",
                "payment_terms_days": 45,
                "credit_limit_cents": 8_000_000,
                "idempotency_key": "idem-party-01",
            },
        )
        self.assertEqual(r_p1["statusCode"], 201)
        self.assertEqual(json.loads(r_p1["body"])["party"]["version"], 1)

        # Duplicate idempotency key blocked with 409
        self.assertEqual(
            self.req(
                f"/tenants/{self.tid}/parties",
                "POST",
                {
                    "kind": "customer",
                    "party_id": "cus-ver-01",
                    "legal_name": "Versioned Client SA",
                    "tax_id": "EL112233445",
                    "idempotency_key": "idem-party-01",
                },
            )["statusCode"],
            409,
        )

        # Stale expected_version=99 rejected with 409
        self.assertEqual(
            self.req(
                f"/tenants/{self.tid}/parties",
                "POST",
                {
                    "kind": "customer",
                    "party_id": "cus-ver-01",
                    "legal_name": "Versioned Client Updated",
                    "tax_id": "EL112233445",
                    "expected_version": 99,
                },
            )["statusCode"],
            409,
        )

        # Correct expected_version=1 increments to v2
        r_p2 = self.req(
            f"/tenants/{self.tid}/parties",
            "POST",
            {
                "kind": "customer",
                "party_id": "cus-ver-01",
                "legal_name": "Versioned Client v2 SA",
                "tax_id": "EL112233445",
                "expected_version": 1,
            },
        )
        self.assertEqual(r_p2["statusCode"], 201)
        self.assertEqual(json.loads(r_p2["body"])["party"]["version"], 2)

        # 2. Durable non-posting draft + Four-Eyes check
        ledger_before = len(self.state.ledger.events)
        r_drf = self.req(
            f"/tenants/{self.tid}/drafts",
            "POST",
            {
                "draft_id": "drf-test-01",
                "module": "sales",
                "counterparty_id": "cus-ver-01",
                "invoice_number": "DRF-001",
                "lines": [
                    {"description": "Managed Cloud", "net_cents": 10000, "vat_rate_pct": 24},
                    {"description": "Training Book", "net_cents": 5000, "vat_rate_pct": 6},
                ],
            },
        )
        self.assertEqual(r_drf["statusCode"], 201)
        self.assertEqual(len(self.state.ledger.events), ledger_before)
        # Self-approval when enforce_four_eyes=True is rejected with 403
        self.assertEqual(
            self.req(
                f"/tenants/{self.tid}/drafts",
                "POST",
                {"draft_id": "drf-test-01", "action": "approve", "enforce_four_eyes": True},
            )["statusCode"],
            403,
        )

        # 3. Multi-line Mixed-VAT Invoice (24%, 13%, 0%) persisted and read back
        r_inv = self.req(
            f"/tenants/{self.tid}/invoices",
            "POST",
            {
                "document_id": "doc-mixed-vat-01",
                "direction": "SALES_REVENUE",
                "counterparty_id": "cus-ver-01",
                "invoice_number": "INV-MIX-01",
                "issued_date": "2026-10-20",
                "due_date": "2026-11-20",
                "lines": [
                    {"description": "Standard Service 24%", "quantity": 2, "unit_price_cents": 10000, "vat_rate_pct": 24},
                    {"description": "Reduced Hardware 13%", "quantity": 1, "unit_price_cents": 10000, "vat_rate_pct": 13},
                    {"description": "Exempt Export 0%", "quantity": 1, "unit_price_cents": 5000, "vat_rate_pct": 0},
                ],
            },
        )
        self.assertEqual(r_inv["statusCode"], 201)
        inv_doc = json.loads(r_inv["body"])["document"]
        # net = 20000 + 10000 + 5000 = 35000; vat = 4800 + 1300 + 0 = 6100; gross = 41100
        self.assertEqual(inv_doc["net_cents"], 35000)
        self.assertEqual(inv_doc["vat_cents"], 6100)
        self.assertEqual(inv_doc["gross_cents"], 41100)

        # Read back line_items from /operations
        ops_data = json.loads(self.req(f"/tenants/{self.tid}/operations")["body"])
        read_doc = next(
            d for d in ops_data["records"]["sales"] if d["document_id"] == "doc-mixed-vat-01"
        )
        self.assertEqual(len(read_doc["line_items"]), 3)

        # 4. Direct Expense Bill mapped to 6100_RENT_AND_UTILITIES
        sup_id = next(iter(self.state.crm.suppliers))
        r_exp = self.req(
            f"/tenants/{self.tid}/expenses",
            "POST",
            {
                "document_id": "exp-rent-oct",
                "counterparty_id": sup_id,
                "invoice_number": "RENT-2026-10",
                "issued_date": "2026-10-22",
                "due_date": "2026-11-05",
                "expense_account": "6100_RENT_AND_UTILITIES",
                "net_cents": 120000,
                "vat_rate_pct": 24,
            },
        )
        self.assertEqual(r_exp["statusCode"], 201)
        exp_ev = json.loads(r_exp["body"])["event"]
        self.assertEqual(exp_ev["lines"][0]["account"], "6100_RENT_AND_UTILITIES")
        self.assertEqual(exp_ev["lines"][0]["debit_cents"], 120000)

        # 5. Reverse posted invoice -> posts reversing event and marks REVERSED
        stmt_before = json.loads(
            self.req(
                f"/tenants/{self.tid}/operations",
                query="party=cus-ver-01&kind=customer&start=2026-10-01&end=2026-10-31",
            )["body"]
        )["statement"]
        self.assertEqual(stmt_before["closing_cents"], 41100)

        r_rev = self.req(
            f"/tenants/{self.tid}/invoices/doc-mixed-vat-01/reverse",
            "POST",
            {"reversal_date": "2026-10-25", "reason": "Customer order cancelled"},
        )
        self.assertEqual(r_rev["statusCode"], 200)
        stmt_after = json.loads(
            self.req(
                f"/tenants/{self.tid}/operations",
                query="party=cus-ver-01&kind=customer&start=2026-10-01&end=2026-10-31",
            )["body"]
        )["statement"]
        self.assertEqual(stmt_after["closing_cents"], 0)

    def test_step5_and_6_allocations_unapplied_cash_sandbox_webhook_and_targets(self) -> None:
        cust_id = next(iter(self.state.crm.customers))
        # Issue two sales invoices: 12,400c and 24,800c
        self.req(
            f"/tenants/{self.tid}/invoices",
            "POST",
            {
                "document_id": "inv-alloc-1",
                "direction": "SALES_REVENUE",
                "counterparty_id": cust_id,
                "net_cents": 10000,
                "vat_rate_pct": 24,
                "issued_date": "2026-10-10",
                "due_date": "2026-10-20",
            },
        )
        self.req(
            f"/tenants/{self.tid}/invoices",
            "POST",
            {
                "document_id": "inv-alloc-2",
                "direction": "SALES_REVENUE",
                "counterparty_id": cust_id,
                "net_cents": 20000,
                "vat_rate_pct": 24,
                "issued_date": "2026-10-12",
                "due_date": "2026-10-25",
            },
        )

        # Post a single customer receipt of 29,800c cash + 200c bank fee (= 30,000c settlement power)
        # allocating 12,400c (full) to inv-alloc-1, 10,000c (partial) to inv-alloc-2,
        # leaving 7,600c unapplied customer advance deposit (2100_CUSTOMER_ADVANCE_DEPOSITS)
        r_rcpt = self.req(
            f"/tenants/{self.tid}/receipts",
            "POST",
            {
                "settlement_id": "rcpt-multi-01",
                "counterparty_id": cust_id,
                "posted_date": "2026-10-18",
                "gross_cash_cents": 29800,
                "fee_cents": 200,
                "allocations": [
                    {"document_id": "inv-alloc-1", "allocated_cents": 12400},
                    {"document_id": "inv-alloc-2", "allocated_cents": 10000},
                ],
            },
        )
        self.assertEqual(r_rcpt["statusCode"], 201)
        stl = json.loads(r_rcpt["body"])["settlement"]
        self.assertEqual(stl["allocated_total_cents"], 22400)
        self.assertEqual(stl["unapplied_advance_cents"], 7600)
        self.assertEqual(stl["bank_execution_status"], "JOURNAL_ONLY")
        self.assertEqual(self.state.crm.documents["inv-alloc-1"].paid_cents, 12400)
        self.assertEqual(self.state.crm.documents["inv-alloc-2"].paid_cents, 10000)

        # Sandbox payment provider submission + HMAC-signed webhook reconciliation
        ap_id = f"apr-{self.state.tenant.slug}-comm-oct"
        # Self-approval / creator release check
        self.assertEqual(
            self.req(
                f"/tenants/{self.tid}/treasury/sandbox-submit",
                "POST",
                {"approval_id": ap_id, "created_by": "act-sofia-marinou"},
            )["statusCode"],
            403,
        )
        r_sbx = self.req(
            f"/tenants/{self.tid}/treasury/sandbox-submit",
            "POST",
            {"approval_id": ap_id, "created_by": "act-store-manager"},
        )
        self.assertEqual(r_sbx["statusCode"], 200)
        trf = json.loads(r_sbx["body"])["transfer"]
        self.assertEqual(trf["status"], "SUBMITTED_TO_SANDBOX")

        webhook_body = {
            "webhook_event_id": "wh-evt-001",
            "transfer_id": trf["transfer_id"],
            "status": "SETTLED_AT_BANK",
            "bank_settlement_ref": "SEPA-SETTLED-991",
        }
        # Unsigned webhook rejected with 403
        self.assertEqual(
            self.req(
                f"/tenants/{self.tid}/treasury/webhooks/sandbox", "POST", webhook_body
            )["statusCode"],
            403,
        )
        # Signed webhook reconciles to SETTLED_AT_BANK
        sig = sign_webhook_payload(webhook_body)
        r_wh = self.req(
            f"/tenants/{self.tid}/treasury/webhooks/sandbox",
            "POST",
            webhook_body,
            headers={"x-kerdon-webhook-signature": sig},
        )
        self.assertEqual(r_wh["statusCode"], 200)
        self.assertEqual(
            json.loads(r_wh["body"])["transfer"]["status"], "SETTLED_AT_BANK"
        )
        # Duplicate webhook replay rejected with 409
        self.assertEqual(
            self.req(
                f"/tenants/{self.tid}/treasury/webhooks/sandbox",
                "POST",
                webhook_body,
                headers={"x-kerdon-webhook-signature": sig},
            )["statusCode"],
            409,
        )

        # Durable monthly targets + aging + profitability/cash forecast in /operations
        r_tgt = self.req(
            f"/tenants/{self.tid}/targets",
            "POST",
            {
                "period": "2026-10",
                "scope_kind": "company",
                "scope_id": self.tid,
                "target_cents": 15_000_000,
            },
        )
        self.assertEqual(r_tgt["statusCode"], 201)
        ops = json.loads(
            self.req(
                f"/tenants/{self.tid}/operations",
                query="start=2026-10-01&end=2026-10-31",
            )["body"]
        )
        self.assertEqual(len(ops["targets_summary"]["saved_targets"]), 1)
        self.assertGreater(
            ops["targets_summary"]["company_actual_revenue_cents"], 0
        )
        self.assertIn("receivables_aging", ops["aging"])
        self.assertIn("cash_forecast", ops["profitability"])

    def test_step7_pluggable_connectors_paypal_and_aade_mydata(self) -> None:
        # 1. Inspect default pluggable connectors via GET /tenants/{id}/connectors
        r_get = self.req(f"/tenants/{self.tid}/connectors")
        self.assertEqual(r_get["statusCode"], 200)
        conn_payload = json.loads(r_get["body"])
        self.assertEqual(conn_payload["config"]["payment_connector"], "PAYPAL")
        self.assertEqual(conn_payload["config"]["tax_connector"], "AADE_MYDATA")
        self.assertEqual(len(conn_payload["available_payment_connectors"]), 4)
        self.assertEqual(len(conn_payload["available_tax_connectors"]), 3)

        # 2. Switch payment_connector to BANK_IBAN -> PayPal checkout order must fail closed (400)
        r_cfg = self.req(
            f"/tenants/{self.tid}/connectors/config",
            "POST",
            {"payment_connector": "BANK_IBAN", "tax_connector": "AADE_MYDATA"},
        )
        self.assertEqual(r_cfg["statusCode"], 200)
        self.assertEqual(json.loads(r_cfg["body"])["config"]["payment_connector"], "BANK_IBAN")

        cust_id = next(iter(self.state.crm.customers))
        self.req(
            f"/tenants/{self.tid}/invoices",
            "POST",
            {
                "document_id": "inv-pp-mydata-01",
                "direction": "SALES_REVENUE",
                "counterparty_id": cust_id,
                "net_cents": 100_000,
                "vat_rate_pct": 24,
                "issued_date": "2026-10-28",
                "due_date": "2026-11-28",
            },
        )
        # PayPal capture blocked when tenant selected BANK_IBAN
        self.assertEqual(
            self.req(
                f"/tenants/{self.tid}/connectors/paypal/order",
                "POST",
                {"document_id": "inv-pp-mydata-01", "auto_capture": True},
            )["statusCode"],
            400,
        )

        # 3. Re-enable PAYPAL plugin & execute Orders v2 checkout + capture with 3-line fee GL split
        self.req(
            f"/tenants/{self.tid}/connectors/config",
            "POST",
            {"payment_connector": "PAYPAL", "paypal_fee_rate_bps": 290, "paypal_fixed_fee_cents": 35},
        )
        r_pp = self.req(
            f"/tenants/{self.tid}/connectors/paypal/order",
            "POST",
            {"document_id": "inv-pp-mydata-01", "auto_capture": True},
        )
        self.assertEqual(r_pp["statusCode"], 201)
        pp_order = json.loads(r_pp["body"])["order"]
        # Gross = 124,000c (1,240.00 EUR); fee = round(124000 * 0.029) + 35 = 3596 + 35 = 3631c; net = 120,369c
        self.assertEqual(pp_order["gross_cents"], 124_000)
        self.assertEqual(pp_order["paypal_fee_cents"], 3_631)
        self.assertEqual(pp_order["net_settled_cents"], 120_369)
        self.assertEqual(self.state.crm.documents["inv-pp-mydata-01"].paid_cents, 124_000)

        # 4. Transmit invoice to Greek IAPR AADE myDATA REST v1.0.8 XML & stamp MARK
        r_md = self.req(
            f"/tenants/{self.tid}/connectors/mydata/transmit",
            "POST",
            {"document_id": "inv-pp-mydata-01", "series": "A", "aa": "501"},
        )
        self.assertEqual(r_md["statusCode"], 201)
        md_tx = json.loads(r_md["body"])["mydata_transmission"]
        self.assertTrue(md_tx["invoice_mark"].startswith("MARK-4"))
        self.assertEqual(md_tx["classification_type"], "E3_561_001")
        self.assertIn("<InvoicesDoc", md_tx["xml_preview"])
        self.assertEqual(
            self.state.crm.documents["inv-pp-mydata-01"].einvoice_mark,
            md_tx["invoice_mark"],
        )

        # Cancel MARK (`CancelInvoice`)
        r_mdc = self.req(
            f"/tenants/{self.tid}/connectors/mydata/cancel",
            "POST",
            {"document_id": "inv-pp-mydata-01", "reason": "Issuance correction"},
        )
        self.assertEqual(r_mdc["statusCode"], 200)
        self.assertTrue(
            json.loads(r_mdc["body"])["mydata_cancellation"]["cancellation_mark"].startswith("MARK-9")
        )

        # 5. PayPal Customer Dispute -> Seller Commission Clawback
        r_disp = self.req(
            f"/tenants/{self.tid}/connectors/paypal/dispute",
            "POST",
            {
                "dispute_id": "PPDISP-901",
                "document_id": "inv-pp-mydata-01",
                "disputed_amount_cents": 124_000,
            },
        )
        self.assertEqual(r_disp["statusCode"], 201)
        self.assertEqual(
            json.loads(r_disp["body"])["dispute"]["clawback_commission_cents"], 6_200
        )

        # 6. Four-Eyes Governed PayPal Batch Payout (`v1/payments/payouts`) with Braille receipt
        ap_id = f"apr-{self.state.tenant.slug}-comm-oct"
        # Self-approval rejected with 403
        self.assertEqual(
            self.req(
                f"/tenants/{self.tid}/connectors/paypal/payout",
                "POST",
                {"approval_id": ap_id, "executor_id": "act-sofia-marinou"},
            )["statusCode"],
            403,
        )
        r_pay = self.req(
            f"/tenants/{self.tid}/connectors/paypal/payout",
            "POST",
            {
                "approval_id": ap_id,
                "executor_id": "act-nikos-alexiou",
                "recipient_email": "seller-payout@kerdon-synth.eu",
            },
        )
        self.assertEqual(r_pay["statusCode"], 200)
        payout_rec = json.loads(r_pay["body"])["payout"]
        self.assertEqual(payout_rec["status"], "SUCCESS")
        self.assertTrue(len(payout_rec["braille_receipt"]) > 0)

    def test_step8_jwt_tenant_resolution_multi_org_creation_and_scoped_collaborator_invites(self) -> None:
        founder_jwt = mint_hs256_jwt({"sub": "usr-founder-alex", "email": "alex@founder.gr"})
        f_hdr = {"authorization": f"Bearer {founder_jwt}", "x-kerdon-auth-mode": "strict"}
        # 1. Brand-new founder creates two independent organizations via /erp/organizations (no tenant in URL)
        r_o1 = self.req("/erp/organizations", "POST", {"display_name": "Alpha Tech AE", "tax_id": "EL123456789"}, headers=f_hdr)
        r_o2 = self.req("/erp/organizations", "POST", {"display_name": "Beta Retail IKE", "tax_id": "EL987654321"}, headers=f_hdr)
        self.assertEqual(r_o1["statusCode"], 201)
        self.assertEqual(r_o2["statusCode"], 201)
        org1_id = json.loads(r_o1["body"])["organization"]["tenant_id"]
        org2_id = json.loads(r_o2["body"])["organization"]["tenant_id"]
        self.assertNotEqual(org1_id, org2_id)

        # 2. Invite Maria as ACCOUNTANT to Org 1 & PUBLIC_AUDITOR to Org 2; Kostas as STORE_MANAGER only to Org 2
        inv1 = json.loads(self.req("/erp/members/invite", "POST", {"email": "maria@firm.gr", "target_sub": "usr-maria", "role": "ACCOUNTANT"}, headers={**f_hdr, "x-active-tenant": org1_id})["body"])["invitation"]
        inv2 = json.loads(self.req("/erp/members/invite", "POST", {"email": "kostas@sales.gr", "target_sub": "usr-kostas", "role": "STORE_MANAGER"}, headers={**f_hdr, "x-active-tenant": org2_id})["body"])["invitation"]
        inv3 = json.loads(self.req("/erp/members/invite", "POST", {"email": "maria@firm.gr", "target_sub": "usr-maria", "role": "PUBLIC_AUDITOR"}, headers={**f_hdr, "x-active-tenant": org2_id})["body"])["invitation"]

        m_hdr = {"authorization": f"Bearer {mint_hs256_jwt({'sub': 'usr-maria', 'email': 'maria@firm.gr'})}", "x-kerdon-auth-mode": "strict"}
        k_hdr = {"authorization": f"Bearer {mint_hs256_jwt({'sub': 'usr-kostas', 'email': 'kostas@sales.gr'})}", "x-kerdon-auth-mode": "strict"}
        self.assertEqual(self.req("/erp/invites/accept", "POST", {"invite_token": inv1["invite_token"]}, headers=m_hdr)["statusCode"], 200)
        self.assertEqual(self.req("/erp/invites/accept", "POST", {"invite_token": inv3["invite_token"]}, headers=m_hdr)["statusCode"], 200)
        self.assertEqual(self.req("/erp/invites/accept", "POST", {"invite_token": inv2["invite_token"]}, headers=k_hdr)["statusCode"], 200)

        # 3. Kostas (STORE_MANAGER only in Org 2) calls /erp/operations without any tenant header -> resolves Org 2 from JWT!
        r_k_ops = self.req("/erp/operations", headers=k_hdr)
        self.assertEqual(r_k_ops["statusCode"], 200)
        self.assertEqual(json.loads(r_k_ops["body"])["tenant"]["tenant_id"], org2_id)
        # Kostas blocked from Org 1 (403) and blocked from inviting collaborators in Org 2 (403)
        self.assertEqual(self.req("/erp/operations", headers={**k_hdr, "x-active-tenant": org1_id})["statusCode"], 403)
        self.assertEqual(self.req("/erp/members/invite", "POST", {"email": "x@y.gr", "role": "ACCOUNTANT"}, headers=k_hdr)["statusCode"], 403)

        # 4. Maria is ACCOUNTANT in Org 1 (can create party: 201) and PUBLIC_AUDITOR in Org 2 (blocked from party write: 403)
        self.assertEqual(self.req("/erp/parties", "POST", {"kind": "customer", "legal_name": "Org1 Client SA", "tax_id": "EL111222333"}, headers={**m_hdr, "x-active-tenant": org1_id})["statusCode"], 201)
        self.assertEqual(self.req("/erp/parties", "POST", {"kind": "customer", "legal_name": "Org2 Client SA", "tax_id": "EL444555666"}, headers={**m_hdr, "x-active-tenant": org2_id})["statusCode"], 403)

        # 5. Founder revokes Maria from Org 2 -> Maria gets 403 on Org 2 while keeping Org 1 access
        self.assertEqual(self.req("/erp/members/remove", "POST", {"sub": "usr-maria"}, headers={**f_hdr, "x-active-tenant": org2_id})["statusCode"], 200)
        self.assertEqual(self.req("/erp/operations", headers={**m_hdr, "x-active-tenant": org2_id})["statusCode"], 403)
        self.assertEqual(self.req("/erp/operations", headers={**m_hdr, "x-active-tenant": org1_id})["statusCode"], 200)


if __name__ == "__main__":
    unittest.main()
