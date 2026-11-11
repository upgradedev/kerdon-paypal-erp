"""Unit, boundary (C6), and integration tests for Kerdon MSP pure domain core (M1-M8)."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import kerdon as kd  # noqa: E402
import run_erp_benchmark  # noqa: E402


class TestTenancyAndAuthM1(unittest.TestCase):
    def test_fiscal_direction_classification(self) -> None:
        ident = kd.FiscalIdentity(
            tenant_id="tnt-1",
            legal_name="AEGEAN MOBILITY SA",
            tax_id="EL 998877665",
            aliases=("AEGEAN MOBILITY",),
        )
        self.assertFalse(ident.matches_name("   "))
        sale = kd.classify_fiscal_direction(
            ident,
            issuer_tax_id="el998877665",
            issuer_name="Aegean Mobility",
            recipient_tax_id="EL112233445",
            recipient_name="Customer Corp",
        )
        self.assertEqual(sale.direction, kd.Direction.SALES_REVENUE)

        purchase = kd.classify_fiscal_direction(
            ident,
            issuer_tax_id="EL556677889",
            issuer_name="Vendor Corp",
            recipient_tax_id="",
            recipient_name="aegean mobility sa",
        )
        self.assertEqual(purchase.direction, kd.Direction.PURCHASE_EXPENSE)

        internal = kd.classify_fiscal_direction(
            ident,
            issuer_tax_id="EL998877665",
            issuer_name="Aegean Mobility",
            recipient_tax_id="EL998877665",
            recipient_name="Aegean Mobility",
        )
        self.assertEqual(internal.direction, kd.Direction.INTERNAL_TRANSFER)

        stl = kd.classify_fiscal_direction(
            ident,
            issuer_tax_id="EL000111222",
            issuer_name="Principal Carrier",
            recipient_tax_id="EL998877665",
            recipient_name="Aegean Mobility",
            is_principal_settlement=True,
        )
        self.assertEqual(stl.direction, kd.Direction.PRINCIPAL_SETTLEMENT)

        unknown = kd.classify_fiscal_direction(
            ident,
            issuer_tax_id="EL111",
            issuer_name="Other A",
            recipient_tax_id="EL222",
            recipient_name="Other B",
        )
        self.assertEqual(unknown.direction, kd.Direction.UNKNOWN)

    def test_tenancy_hierarchy_and_least_privilege_roles(self) -> None:
        cat = kd.TenancyCatalog("msp-1")
        with self.assertRaises(ValueError):
            cat.onboard_tenant(slug="  ", display_name="X", legal_name="X", tax_id="EL1")

        hq = cat.onboard_tenant(
            slug="alpha-group",
            display_name="Alpha Group HQ",
            legal_name="ALPHA GROUP SA",
            tax_id="EL123456789",
        )
        child = cat.onboard_tenant(
            slug="alpha-kifisia",
            display_name="Alpha Kifisia Franchise",
            legal_name="ALPHA KIFISIA IKE",
            tax_id="EL987654321",
            parent_tenant_id=hq.tenant_id,
        )
        self.assertEqual(hq.tier, kd.TenantTier.CLIENT_HQ)
        self.assertEqual(child.tier, kd.TenantTier.FRANCHISE_STORE)
        self.assertEqual(hq.inbox_address, "docs@alpha-group.kerdon.ai")

        with self.assertRaises(KeyError):
            cat.register_store(kd.StoreLocation("s0", "bad-tnt", "bad-tnt", "N", "C", 100))
        store = kd.StoreLocation("str-1", child.tenant_id, hq.tenant_id, "Kifisia", "Athens", 100_000)
        cat.register_store(store)
        self.assertEqual(len(cat.child_stores_for(hq.tenant_id)), 1)

        with self.assertRaises(KeyError):
            cat.register_team(kd.SalesTeam("t0", child.tenant_id, "bad-str", "T", "l1", 100))
        team = kd.SalesTeam("tm-1", child.tenant_id, store.store_id, "Retail", "slr-1", 100_000)
        cat.register_team(team)

        with self.assertRaises(KeyError):
            cat.register_seller(kd.SellerProfile("slr-0", child.tenant_id, store.store_id, "bad-tm", "N", "E1"))
        seller = kd.SellerProfile("slr-1", child.tenant_id, store.store_id, team.team_id, "N", "E1")
        cat.register_seller(seller)

        auditor = kd.Actor("u-pub", "Public Judge", kd.Role.PUBLIC_AUDITOR, frozenset({hq.tenant_id}))
        reader = kd.Reader(auditor)
        evaluator = kd.Evaluator(auditor)
        self.assertFalse(hasattr(reader, "execute"))
        self.assertFalse(hasattr(evaluator, "execute"))
        self.assertEqual(reader.read(hq.tenant_id, lambda: 42), 42)
        self.assertEqual(evaluator.evaluate(hq.tenant_id, lambda: "ok"), "ok")

        with self.assertRaises(kd.PermissionDeniedError):
            reader.read("tnt-unauthorized", lambda: 1)

        writer_unpriv = kd.Writer(auditor)
        with self.assertRaises(kd.PermissionDeniedError):
            writer_unpriv.execute(hq.tenant_id, kd.Capability.EXECUTE_PAYOUTS, "tok-1", lambda: 1)

        owner = kd.Actor("u-own", "Owner", kd.Role.CLIENT_OWNER, frozenset({hq.tenant_id}))
        writer_priv = kd.Writer(owner)
        with self.assertRaises(kd.PermissionDeniedError):
            writer_priv.execute(hq.tenant_id, kd.Capability.EXECUTE_PAYOUTS, "   ", lambda: 1)
        self.assertEqual(
            writer_priv.execute(hq.tenant_id, kd.Capability.EXECUTE_PAYOUTS, "apr-valid", lambda: "done"),
            "done",
        )


class TestInboxM2AndCrmM3(unittest.TestCase):
    def test_recursive_email_unpack_dedup_and_html_guard(self) -> None:
        inbox = kd.EvidenceInbox("tnt-1")
        pdf_bytes = b"%PDF-1.7 synthetic invoice bytes"
        leaf_msg = kd.RawEmailEnvelope(
            message_id="msg-leaf",
            tenant_id="tnt-1",
            sender="billing@vendor.eu",
            recipient="docs@tnt-1.kerdon.ai",
            subject="Inner Invoice",
            received_at_epoch=1000,
            attachments=(
                kd.AttachmentPayload("att-leaf-1", "inv.pdf", "application/pdf", pdf_bytes),
            ),
        )
        outer_msg = kd.RawEmailEnvelope(
            message_id="msg-outer",
            tenant_id="tnt-1",
            sender="forwarder@client.eu",
            recipient="docs@tnt-1.kerdon.ai",
            subject="Fw: Inner Invoice",
            received_at_epoch=1100,
            html_body_tables=("<table><tr><td>Sale</td><td>100</td></tr></table>",),
            attachments=(
                kd.AttachmentPayload("att-nested", "fw.eml", "message/rfc822", b"raw", nested_message=leaf_msg),
                kd.AttachmentPayload("att-dup", "inv_copy.pdf", "application/pdf", pdf_bytes),
            ),
        )
        hashes = inbox.ingest_email(outer_msg)
        self.assertEqual(len(hashes), 2)
        self.assertEqual(hashes[0], hashes[1])
        blob = inbox.blobs_by_sha256[hashes[0]]
        self.assertEqual(len(blob.source_edges), 2)
        self.assertEqual(inbox.messages_by_id["msg-leaf"].parent_message_id, "msg-outer")
        self.assertEqual(len(inbox.sales_table_evidence), 1)

        with self.assertRaises(ValueError):
            inbox.ingest_email(
                kd.RawEmailEnvelope("m-bad", "tnt-other", "a", "b", "s", 100)
            )

        bad_cand = kd.ExtractedCandidate(
            candidate_id="cand-bad",
            tenant_id="tnt-1",
            doc_kind=kd.CandidateDocKind.SALES_INVOICE,
            source_kind=kd.EvidenceSourceKind.HTML_BODY_TABLE,
            counterparty_name="Client",
            counterparty_tax_id="EL111",
            net_cents=10_000,
            vat_cents=2_400,
            gross_cents=12_400,
            currency="EUR",
            issued_date="2026-10-01",
            due_date="2026-10-15",
            provenance=kd.FieldProvenance("msg-outer", "html-0", hashes[0]),
        )
        with self.assertRaises(kd.HtmlBodyPostingError):
            inbox.register_candidate(bad_cand)

        good_cand = kd.ExtractedCandidate(
            candidate_id="cand-ok",
            tenant_id="tnt-1",
            doc_kind=kd.CandidateDocKind.SALES_INVOICE,
            source_kind=kd.EvidenceSourceKind.PDF_ATTACHMENT,
            counterparty_name="Client",
            counterparty_tax_id="EL111",
            net_cents=10_000,
            vat_cents=2_400,
            gross_cents=12_400,
            currency="EUR",
            issued_date="2026-10-01",
            due_date="2026-10-15",
            provenance=kd.FieldProvenance("msg-outer", "att-dup", hashes[0]),
        )
        self.assertEqual(inbox.register_candidate(good_cand).candidate_id, "cand-ok")

    def test_crm_signed_link_offset_window_c6(self) -> None:
        """C6: fixture starts at non-zero independent offset (epoch 41_234_567)."""
        crm = kd.CommercialRegistry("tnt-1")
        sup_even = kd.Supplier(
            "sup-ev", "tnt-1", "Even Vendor", "EL2", "GR1", "Ops", (100_000, 200_000)
        )
        sup_empty = kd.Supplier("sup-em", "tnt-1", "Empty Vendor", "EL3", "GR2", "Ops", ())
        self.assertEqual(sup_even.median_invoice_cents, 150_000)
        self.assertEqual(sup_empty.median_invoice_cents, 0)
        crm.upsert_supplier(sup_even)
        crm.register_credit_note(
            kd.CreditNote("cn-1", "tnt-1", kd.Direction.SALES_REVENUE, "cus-1", 1000, 240, 1240, "EUR", "2026-10-01", "a" * 64, "doc-99")
        )

        doc = kd.DocumentRegisterEntry(
            document_id="doc-99",
            tenant_id="tnt-1",
            direction=kd.Direction.SALES_REVENUE,
            counterparty_id="cus-1",
            counterparty_name="Cust",
            counterparty_tax_id="EL111",
            doc_type="SALES_INVOICE",
            net_cents=10_000,
            vat_cents=2_400,
            gross_cents=12_400,
            paid_cents=2_400,
            currency="EUR",
            issued_date="2026-10-01",
            due_date="2026-10-31",
            source_sha256="a" * 64,
        )
        crm.register_document(doc)
        self.assertEqual(doc.outstanding_cents, 10_000)

        with self.assertRaises(KeyError):
            crm.mint_signed_download_link("unknown-doc", now_epoch=41_234_567)
        with self.assertRaises(ValueError):
            crm.upsert_customer(kd.Customer("c", "other-tnt", "N", "EL", "e@e"))

        link = crm.mint_signed_download_link("doc-99", now_epoch=41_234_567)
        self.assertFalse(link.is_valid_at(41_234_566))
        self.assertTrue(link.is_valid_at(41_234_567))
        self.assertTrue(link.is_valid_at(41_234_866))
        self.assertFalse(link.is_valid_at(41_234_867))


class TestLedgerAndFiscalM4(unittest.TestCase):
    def test_unbalanced_entry_rejected_and_pnl_rollup(self) -> None:
        with self.assertRaises(kd.UnbalancedEntryError):
            kd.LedgerLine(kd.AccountCode.CASH_1000, debit_cents=-10)
        with self.assertRaises(kd.UnbalancedEntryError):
            kd.LedgerLine(kd.AccountCode.CASH_1000, debit_cents=10, credit_cents=10)
        with self.assertRaises(kd.UnbalancedEntryError):
            kd.FinancialEvent(
                event_id="ev-1line",
                tenant_id="tnt-1",
                period="2026-10",
                posted_date="2026-10-01",
                description="One line",
                source_document_id="d1",
                source_sha256="a" * 64,
                lines=(kd.LedgerLine(kd.AccountCode.CASH_1000, debit_cents=100),),
            )
        with self.assertRaises(kd.UnbalancedEntryError):
            kd.FinancialEvent(
                event_id="ev-bad",
                tenant_id="tnt-1",
                period="2026-10",
                posted_date="2026-10-01",
                description="Unbalanced",
                source_document_id="d1",
                source_sha256="a" * 64,
                lines=(
                    kd.LedgerLine(kd.AccountCode.CASH_1000, debit_cents=100),
                    kd.LedgerLine(kd.AccountCode.REVENUE_SALES_4000, credit_cents=99),
                ),
            )

        gl = kd.GeneralLedger("tnt-1")
        with self.assertRaises( kd.UnbalancedEntryError):
            gl.post_sales_invoice(
                event_id="e-bad", period="2026-10", posted_date="2026-10-01",
                document_id="d", source_sha256="a" * 64, customer_id="c",
                net_cents=100, vat_cents=24, gross_cents=125
            )
        with self.assertRaises(kd.UnbalancedEntryError):
            gl.post_purchase_invoice(
                event_id="e-bad2", period="2026-10", posted_date="2026-10-01",
                document_id="d", source_sha256="a" * 64, supplier_id="s",
                net_cents=100, vat_cents=24, gross_cents=125
            )

        gl.post_sales_invoice(
            event_id="ev-s1",
            period="2026-09",
            posted_date="2026-09-10",
            document_id="d-s1",
            source_sha256="a" * 64,
            customer_id="c1",
            net_cents=100_000,
            vat_cents=24_000,
            gross_cents=124_000,
        )
        gl.post_sales_invoice(
            event_id="ev-s2",
            period="2026-10",
            posted_date="2026-10-10",
            document_id="d-s2",
            source_sha256="a" * 64,
            customer_id="c1",
            net_cents=150_000,
            vat_cents=36_000,
            gross_cents=186_000,
        )
        gl.post_purchase_invoice(
            event_id="ev-p2",
            period="2026-10",
            posted_date="2026-10-12",
            document_id="d-p2",
            source_sha256="b" * 64,
            supplier_id="sup1",
            net_cents=50_000,
            vat_cents=12_000,
            gross_cents=62_000,
        )
        oct_pnl = gl.summarize_period("2026-10")
        self.assertEqual(oct_pnl.revenue_cents, 150_000)
        self.assertEqual(oct_pnl.ebitda_cents, 100_000)
        self.assertEqual(oct_pnl.vat_net_payable_cents, 24_000)
        trend = gl.compute_mom_trend("2026-10", "2026-09")
        self.assertEqual(trend.revenue_delta_cents, 50_000)
        self.assertEqual(trend.revenue_delta_bps, 5000)

        self.assertFalse(kd.validate_vat_breakdown(-1, 0, 10).is_valid)
        self.assertFalse(kd.validate_vat_breakdown(0, 10, 10).is_valid)


class TestTreasuryOffsetAndWorkspaceM5ToM8(unittest.TestCase):
    def test_fx_quote_and_idempotency_offset_c6(self) -> None:
        """C6: FX quote window and 7-day idempotency tested from offset 98_765_432."""
        eng = kd.TreasuryEngine("tnt-fx")
        eng.configure_pocket("EUR", balance_cents=2_000_000, reserve_floor_cents=200_000)
        self.assertEqual(eng.pockets["EUR"].available_above_floor_cents, 1_800_000)
        with self.assertRaises(ValueError):
            eng.create_approval(
                approval_id="bad", counterparty_id="s", invoice_or_case_id="i",
                amount_cents=0, currency="EUR", evidence_sha256="a", approver_id="u", now_epoch=1
            )
        apr = eng.create_approval(
            approval_id="apr-usd-1",
            counterparty_id="sup-us",
            invoice_or_case_id="inv-us-1",
            amount_cents=108_000,
            currency="USD",
            evidence_sha256="c" * 64,
            approver_id="sofia",
            now_epoch=98_765_000,
        )
        with self.assertRaises(ValueError):
            eng.execute_payout(approval_id=apr.approval_id, now_epoch=98_765_500, funding_currency="EUR")

        quote = kd.FxQuote(
            quote_id="fx-1",
            sell_currency="EUR",
            buy_currency="USD",
            rate_micros=1_080_000,
            issued_at_epoch=98_765_432,
            expires_at_epoch=98_765_732,
        )
        with self.assertRaises(kd.ExpiredFxQuoteError):
            eng.execute_payout(
                approval_id=apr.approval_id,
                now_epoch=98_765_732,
                funding_currency="EUR",
                fx_quote=quote,
            )

        rcpt = eng.execute_payout(
            approval_id=apr.approval_id,
            now_epoch=98_765_500,
            funding_currency="EUR",
            fx_quote=quote,
        )
        self.assertEqual(rcpt.debited_cents, 100_000)
        self.assertEqual(rcpt.remaining_balance_cents, 1_900_000)

        with self.assertRaises(kd.DuplicateIdempotencyError):
            eng.execute_payout(
                approval_id=apr.approval_id,
                now_epoch=98_765_510,
                funding_currency="EUR",
                fx_quote=quote,
            )

    def test_full_msp_demo_workspace_and_aletheia_receipt(self) -> None:
        ws = kd.build_default_msp_workspace()
        self.assertEqual(len(ws.tenant_states), 3)
        state = ws.tenant_states[ws.default_tenant_id]
        self.assertGreater(state.board_pack.pnl.revenue_cents, 0)
        self.assertGreater(len(state.gaps), 0)
        self.assertEqual(len(state.gaps), len(state.outbound_drafts))
        self.assertEqual(
            kd.reconcile_commission_to_payroll(state.commission_case, state.commission_case.total_payable_cents),
            0,
        )
        li = kd.build_line_item("Managed FinOps Retainer", 2, 50_000, 24)
        self.assertEqual(li.gross_cents, 124_000)

        q_comm = kd.answer_grounded_query("What are seller commissions this month?", state.fact_sheet)
        self.assertIn("EUR", q_comm.answer_text)
        q_vat = kd.answer_grounded_query("What is our net VAT payable?", state.fact_sheet)
        self.assertIn("VAT", q_vat.answer_text)
        q_gap = kd.answer_grounded_query("Any missing documents or gaps?", state.fact_sheet)
        self.assertIn("completeness", q_gap.answer_text)
        q_wf = kd.answer_grounded_query("How much is payroll workforce cost?", state.fact_sheet)
        self.assertIn("workforce", q_wf.answer_text)
        q_gen = kd.answer_grounded_query("Give me the October overview", state.fact_sheet)
        self.assertIn("EBITDA", q_gen.answer_text)

        rcpt = kd.seal_aletheia_receipt(
            tenant_id=state.tenant.tenant_id,
            subject_id=state.commission_case.case_id,
            approver_id="act-sofia-marinou",
            amount_cents=state.commission_case.total_payable_cents,
            currency="EUR",
            evidence_hashes=("a" * 64,),
        )
        self.assertIn("Aletheia Merkle receipt sealed", rcpt.spoken_transcript)
        self.assertTrue(len(rcpt.braille_ascii) > 4)

    def test_benchmark_90_cases_all_pass(self) -> None:
        summary = run_erp_benchmark.run_benchmark()
        self.assertEqual(summary["total_cases"], 90)
        self.assertEqual(summary["passed_cases"], 90)
        self.assertEqual(summary["failed_cases"], 0)


if __name__ == "__main__":
    unittest.main()
