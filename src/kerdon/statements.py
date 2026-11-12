"""IAS 7 Cash Flow Statement, Cash Account Statement, Counterparty Ledger Cards, and CFO Ratios.

Pure deterministic domain module. Zero cloud, LLM, network, or clock SDK imports.
All monetary calculations execute in integer cents and reconcile 100% to GeneralLedger.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .crm import CommercialRegistry, Customer, DocumentRegisterEntry, Supplier
from .ledger import AccountCode, FinancialEvent, GeneralLedger, LedgerLine
from .tenancy import Direction, Tenant


def validate_statement_period(start: str, end: str) -> int:
    """Validate ISO date bounds and return inclusive day count (>= 1)."""
    d_start = date.fromisoformat(start)
    d_end = date.fromisoformat(end)
    if d_start > d_end:
        raise ValueError("Start date must not follow end date")
    return max(1, (d_end - d_start).days + 1)


def seed_counterparty_ledger_activity(
    *,
    tenant: Tenant,
    crm: CommercialRegistry,
    ledger: GeneralLedger,
    primary_sha: str,
    scale: int,
    store_id: str,
    cust_2: Customer,
    cust_3: Customer,
    sup_rent: Supplier,
    sup_ops: Supplier,
) -> None:
    """Post balanced 2-step Invoice + Settlement legs for secondary counterparties.

    Ensures every registered customer and supplier has real double-entry AR/AP
    history while preserving the intentional October missing-rent completeness gap
    on `sup_rent` (`issued_date` in `2026-09`, settled in `2026-09`).
    """
    tid = tenant.tenant_id
    slug = tenant.slug

    # 1. Customer 2: October B2B fleet invoice + full bank/card collection
    c2_net = 180_000 * scale // 100
    c2_vat = c2_net * 24 // 100
    c2_gross = c2_net + c2_vat
    doc_c2 = DocumentRegisterEntry(
        document_id=f"doc-{slug}-sal-102",
        tenant_id=tid,
        direction=Direction.SALES_REVENUE,
        counterparty_id=cust_2.customer_id,
        counterparty_name=cust_2.legal_name,
        counterparty_tax_id=cust_2.tax_id,
        doc_type="SALES_INVOICE",
        net_cents=c2_net,
        vat_cents=c2_vat,
        gross_cents=c2_gross,
        paid_cents=c2_gross,
        currency="EUR",
        issued_date="2026-10-06",
        due_date="2026-10-20",
        source_sha256=primary_sha,
        einvoice_mark="MARK-400099112234",
        store_id=store_id,
    )
    crm.register_document(doc_c2)
    ledger.post_sales_invoice(
        event_id=f"ev-{slug}-sal-102",
        period="2026-10",
        posted_date="2026-10-06",
        document_id=doc_c2.document_id,
        source_sha256=primary_sha,
        customer_id=cust_2.customer_id,
        net_cents=c2_net,
        vat_cents=c2_vat,
        gross_cents=c2_gross,
        store_id=store_id,
    )
    ledger.post(
        FinancialEvent(
            event_id=f"ev-{slug}-rcpt-102",
            tenant_id=tid,
            period="2026-10",
            posted_date="2026-10-16",
            description=f"Customer SEPA settlement for {doc_c2.document_id}",
            source_document_id=doc_c2.document_id,
            source_sha256=primary_sha,
            lines=(
                LedgerLine(account=AccountCode.CASH_1000, debit_cents=c2_gross, counterparty_id=cust_2.customer_id),
                LedgerLine(account=AccountCode.AR_1100, credit_cents=c2_gross, counterparty_id=cust_2.customer_id),
            ),
        )
    )

    # 2. Customer 3: October franchise supply invoice + full settlement
    c3_net = 120_000 * scale // 100
    c3_vat = c3_net * 24 // 100
    c3_gross = c3_net + c3_vat
    doc_c3 = DocumentRegisterEntry(
        document_id=f"doc-{slug}-sal-103",
        tenant_id=tid,
        direction=Direction.SALES_REVENUE,
        counterparty_id=cust_3.customer_id,
        counterparty_name=cust_3.legal_name,
        counterparty_tax_id=cust_3.tax_id,
        doc_type="SALES_INVOICE",
        net_cents=c3_net,
        vat_cents=c3_vat,
        gross_cents=c3_gross,
        paid_cents=c3_gross,
        currency="EUR",
        issued_date="2026-10-10",
        due_date="2026-10-25",
        source_sha256=primary_sha,
        einvoice_mark="MARK-400099112235",
        store_id=store_id,
    )
    crm.register_document(doc_c3)
    ledger.post_sales_invoice(
        event_id=f"ev-{slug}-sal-103",
        period="2026-10",
        posted_date="2026-10-10",
        document_id=doc_c3.document_id,
        source_sha256=primary_sha,
        customer_id=cust_3.customer_id,
        net_cents=c3_net,
        vat_cents=c3_vat,
        gross_cents=c3_gross,
        store_id=store_id,
    )
    ledger.post(
        FinancialEvent(
            event_id=f"ev-{slug}-rcpt-103",
            tenant_id=tid,
            period="2026-10",
            posted_date="2026-10-23",
            description=f"Franchise remittance receipt for {doc_c3.document_id}",
            source_document_id=doc_c3.document_id,
            source_sha256=primary_sha,
            lines=(
                LedgerLine(account=AccountCode.CASH_1000, debit_cents=c3_gross, counterparty_id=cust_3.customer_id),
                LedgerLine(account=AccountCode.AR_1100, credit_cents=c3_gross, counterparty_id=cust_3.customer_id),
            ),
        )
    )

    # 3. Landlord Supplier (sup_rent): September lease invoice + September settlement
    # October 2026-10 lease invoice remains intentionally absent so missing_document_family fires.
    rent_net = 350_000 * scale // 100
    rent_vat = 0
    rent_gross = rent_net
    doc_rent = DocumentRegisterEntry(
        document_id=f"doc-{slug}-rent-sep",
        tenant_id=tid,
        direction=Direction.PURCHASE_EXPENSE,
        counterparty_id=sup_rent.supplier_id,
        counterparty_name=sup_rent.legal_name,
        counterparty_tax_id=sup_rent.tax_id,
        doc_type="PURCHASE_INVOICE",
        net_cents=rent_net,
        vat_cents=rent_vat,
        gross_cents=rent_gross,
        paid_cents=rent_gross,
        currency="EUR",
        issued_date="2026-09-03",
        due_date="2026-09-10",
        source_sha256=primary_sha,
        einvoice_mark="MARK-400099004411",
        store_id=store_id,
    )
    crm.register_document(doc_rent)
    ledger.post_purchase_invoice(
        event_id=f"ev-{slug}-rent-sep",
        period="2026-09",
        posted_date="2026-09-03",
        document_id=doc_rent.document_id,
        source_sha256=primary_sha,
        supplier_id=sup_rent.supplier_id,
        net_cents=rent_net,
        vat_cents=rent_vat,
        gross_cents=rent_gross,
        expense_account=AccountCode.OPEX_RENT_UTILITIES_6100,
        store_id=store_id,
    )
    ledger.post(
        FinancialEvent(
            event_id=f"ev-{slug}-rent-sep-pay",
            tenant_id=tid,
            period="2026-09",
            posted_date="2026-09-10",
            description=f"September flagship lease wire for {doc_rent.document_id}",
            source_document_id=doc_rent.document_id,
            source_sha256=primary_sha,
            lines=(
                LedgerLine(account=AccountCode.AP_2000, debit_cents=rent_gross, counterparty_id=sup_rent.supplier_id),
                LedgerLine(account=AccountCode.CASH_1000, credit_cents=rent_gross, counterparty_id=sup_rent.supplier_id),
            ),
        )
    )

    # 4. Managed Ops & Utilities Supplier (sup_ops): October utility bill + October settlement
    ops_net = 200_000 * scale // 100
    ops_vat = ops_net * 24 // 100
    ops_gross = ops_net + ops_vat
    doc_ops = DocumentRegisterEntry(
        document_id=f"doc-{slug}-pur-202",
        tenant_id=tid,
        direction=Direction.PURCHASE_EXPENSE,
        counterparty_id=sup_ops.supplier_id,
        counterparty_name=sup_ops.legal_name,
        counterparty_tax_id=sup_ops.tax_id,
        doc_type="PURCHASE_INVOICE",
        net_cents=ops_net,
        vat_cents=ops_vat,
        gross_cents=ops_gross,
        paid_cents=ops_gross,
        currency="EUR",
        issued_date="2026-10-05",
        due_date="2026-10-20",
        source_sha256=primary_sha,
        einvoice_mark="MARK-400099443323",
        store_id=store_id,
    )
    crm.register_document(doc_ops)
    ledger.post_purchase_invoice(
        event_id=f"ev-{slug}-pur-202",
        period="2026-10",
        posted_date="2026-10-05",
        document_id=doc_ops.document_id,
        source_sha256=primary_sha,
        supplier_id=sup_ops.supplier_id,
        net_cents=ops_net,
        vat_cents=ops_vat,
        gross_cents=ops_gross,
        expense_account=AccountCode.OPEX_RENT_UTILITIES_6100,
        store_id=store_id,
    )
    ledger.post(
        FinancialEvent(
            event_id=f"ev-{slug}-pay-202",
            tenant_id=tid,
            period="2026-10",
            posted_date="2026-10-18",
            description=f"Supplier bank disbursement for {doc_ops.document_id}",
            source_document_id=doc_ops.document_id,
            source_sha256=primary_sha,
            lines=(
                LedgerLine(account=AccountCode.AP_2000, debit_cents=ops_gross, counterparty_id=sup_ops.supplier_id),
                LedgerLine(account=AccountCode.CASH_1000, credit_cents=ops_gross, counterparty_id=sup_ops.supplier_id),
            ),
        )
    )


def compute_counterparty_ledger_balances(
    state: Any, as_of: str | None = None
) -> dict[str, dict[str, Any]]:
    """Compute signed Debit/Credit ledger summaries per counterparty from posted GL."""
    summary: dict[str, dict[str, Any]] = {}
    tracked_accounts = (
        AccountCode.AR_1100,
        AccountCode.CUSTOMER_DEPOSITS_2100,
        AccountCode.AP_2000,
    )
    for ev in sorted(state.ledger.events, key=lambda e: (e.posted_date, e.event_id)):
        if as_of and ev.posted_date > as_of:
            continue
        for line in ev.lines:
            if not line.counterparty_id or line.account not in tracked_accounts:
                continue
            slot = summary.setdefault(
                line.counterparty_id,
                {
                    "debit_cents": 0,
                    "credit_cents": 0,
                    "ar_debit_cents": 0,
                    "ar_credit_cents": 0,
                    "ap_debit_cents": 0,
                    "ap_credit_cents": 0,
                    "deposit_credit_cents": 0,
                    "movement_count": 0,
                },
            )
            slot["debit_cents"] += int(line.debit_cents)
            slot["credit_cents"] += int(line.credit_cents)
            slot["movement_count"] += 1
            if line.account == AccountCode.AR_1100:
                slot["ar_debit_cents"] += int(line.debit_cents)
                slot["ar_credit_cents"] += int(line.credit_cents)
            elif line.account == AccountCode.AP_2000:
                slot["ap_debit_cents"] += int(line.debit_cents)
                slot["ap_credit_cents"] += int(line.credit_cents)
            elif line.account == AccountCode.CUSTOMER_DEPOSITS_2100:
                slot["deposit_credit_cents"] += int(line.credit_cents) - int(line.debit_cents)
    for pid, slot in summary.items():
        net_dr_minus_cr = slot["debit_cents"] - slot["credit_cents"]
        slot["net_dr_minus_cr_cents"] = net_dr_minus_cr
        slot["balance_side"] = (
            "DR" if net_dr_minus_cr > 0 else ("CR" if net_dr_minus_cr < 0 else "ZERO")
        )
        slot["abs_balance_cents"] = abs(net_dr_minus_cr)
    return summary


def build_cash_account_statement(state: Any, start: str, end: str) -> dict[str, Any]:
    """Chronological Cash & PayPal Account Statement (GL 1000_CASH) with running balance."""
    validate_statement_period(start, end)
    opening_cents = 0
    running_cents = 0
    total_debit = 0
    total_credit = 0
    total_fees_withheld = 0
    rows: list[dict[str, Any]] = []

    for ev in sorted(state.ledger.events, key=lambda e: (e.posted_date, e.event_id)):
        if ev.tenant_id != state.tenant.tenant_id:
            raise ValueError("Cross-tenant ledger event")
        if ev.posted_date > end:
            continue
        cash_lines = [l for l in ev.lines if l.account == AccountCode.CASH_1000]
        if not cash_lines:
            continue
        dr = sum(int(l.debit_cents) for l in cash_lines)
        cr = sum(int(l.credit_cents) for l in cash_lines)
        delta = dr - cr
        if delta == 0 and dr == 0 and cr == 0:
            continue
        running_cents += delta
        if ev.posted_date < start:
            opening_cents = running_cents
            continue
        fee_cents = sum(
            int(l.debit_cents)
            for l in ev.lines
            if l.account == AccountCode.OPEX_GENERAL_6200 and dr > 0
        )
        cp_id = next((l.counterparty_id for l in ev.lines if l.counterparty_id), "")
        low_desc = f"{ev.event_id} {ev.description}".lower()
        channel = "PayPal" if "paypal" in low_desc else "Bank / SEPA"
        total_debit += dr
        total_credit += cr
        total_fees_withheld += fee_cents
        rows.append(
            {
                "event_id": ev.event_id,
                "date": ev.posted_date,
                "source_document_id": ev.source_document_id,
                "counterparty_id": cp_id,
                "channel": channel,
                "description": ev.description,
                "debit_cents": dr,
                "credit_cents": cr,
                "processor_fee_cents": fee_cents,
                "balance_cents": running_cents,
                "balance_side": "DR" if running_cents > 0 else ("CR" if running_cents < 0 else "ZERO"),
            }
        )

    return {
        "tenant_id": state.tenant.tenant_id,
        "account_code": AccountCode.CASH_1000.value,
        "start": start,
        "end": end,
        "currency": "EUR",
        "opening_cents": opening_cents,
        "total_debit_cents": total_debit,
        "total_credit_cents": total_credit,
        "net_change_cents": total_debit - total_credit,
        "closing_cents": running_cents,
        "memorandum_processor_fees_cents": total_fees_withheld,
        "reconciled": (opening_cents + total_debit - total_credit) == running_cents,
        "rows": rows,
    }


def build_cash_flow_statement(state: Any, start: str, end: str) -> dict[str, Any]:
    """IAS 7 Direct-Method Statement of Cash Flows reconciled 100% to GL 1000_CASH."""
    validate_statement_period(start, end)
    opening_cash = 0
    closing_cash = 0

    customer_receipts = 0
    supplier_payments = 0
    workforce_payments = 0
    rent_opex_payments = 0
    tax_vat_payments = 0
    other_operating = 0
    investing_net = 0
    financing_net = 0
    processor_fees_memo = 0

    for ev in sorted(state.ledger.events, key=lambda e: (e.posted_date, e.event_id)):
        if ev.tenant_id != state.tenant.tenant_id:
            raise ValueError("Cross-tenant ledger event")
        if ev.posted_date > end:
            continue
        cash_delta = sum(
            int(l.debit_cents) - int(l.credit_cents)
            for l in ev.lines
            if l.account == AccountCode.CASH_1000
        )
        if cash_delta == 0:
            continue
        closing_cash += cash_delta
        if ev.posted_date < start:
            opening_cash = closing_cash
            continue

        non_cash_accts = {
            l.account for l in ev.lines if l.account != AccountCode.CASH_1000
        }
        if cash_delta > 0:
            fee_leg = sum(
                int(l.debit_cents)
                for l in ev.lines
                if l.account == AccountCode.OPEX_GENERAL_6200
            )
            processor_fees_memo += fee_leg
            if non_cash_accts & {
                AccountCode.AR_1100,
                AccountCode.CUSTOMER_DEPOSITS_2100,
                AccountCode.REVENUE_SALES_4000,
                AccountCode.REVENUE_COMMISSION_4100,
            }:
                customer_receipts += cash_delta
            else:
                other_operating += cash_delta
        else:
            if non_cash_accts & {
                AccountCode.PAYROLL_PAYABLE_2500,
                AccountCode.SOCIAL_SECURITY_PAYABLE_2510,
                AccountCode.WITHHELD_TAX_PAYABLE_2520,
                AccountCode.OPEX_WORKFORCE_6000,
                AccountCode.OPEX_COMMISSION_6050,
            }:
                workforce_payments += cash_delta
            elif non_cash_accts & {
                AccountCode.VAT_OUTPUT_2400,
                AccountCode.VAT_INPUT_1400,
                AccountCode.INTEREST_AND_TAX_6900,
            } and AccountCode.AP_2000 not in non_cash_accts:
                tax_vat_payments += cash_delta
            elif non_cash_accts & {
                AccountCode.OPEX_RENT_UTILITIES_6100,
                AccountCode.OPEX_GENERAL_6200,
            } and AccountCode.AP_2000 not in non_cash_accts:
                rent_opex_payments += cash_delta
            elif non_cash_accts & {AccountCode.AP_2000, AccountCode.COGS_5000}:
                supplier_payments += cash_delta
            else:
                other_operating += cash_delta

    net_operating = (
        customer_receipts
        + supplier_payments
        + workforce_payments
        + rent_opex_payments
        + tax_vat_payments
        + other_operating
    )
    net_change = net_operating + investing_net + financing_net
    return {
        "standard": "IAS 7 Statement of Cash Flows (Direct Method)",
        "start": start,
        "end": end,
        "currency": "EUR",
        "opening_cash_cents": opening_cash,
        "operating_activities": {
            "receipts_from_customers_cents": customer_receipts,
            "payments_to_suppliers_cents": supplier_payments,
            "payments_for_workforce_and_taxes_cents": workforce_payments,
            "payments_for_rent_and_opex_cents": rent_opex_payments,
            "vat_and_income_tax_settlements_cents": tax_vat_payments,
            "other_operating_cash_cents": other_operating,
            "net_operating_cash_cents": net_operating,
        },
        "investing_activities": {
            "capex_and_asset_acquisitions_cents": 0,
            "net_investing_cash_cents": investing_net,
        },
        "financing_activities": {
            "debt_and_equity_financing_cents": 0,
            "net_financing_cash_cents": financing_net,
        },
        "memorandum_items": {
            "payment_processor_fees_deducted_at_source_cents": processor_fees_memo,
        },
        "net_change_in_cash_cents": net_change,
        "closing_cash_cents": closing_cash,
        "reconciled": (opening_cash + net_change) == closing_cash,
    }


def redact_operations_for_seller(payload: dict[str, Any]) -> dict[str, Any]:
    """Scope operational read payload for SELLER role (VIEW_OWN_SALES only)."""
    scoped = dict(payload)
    recs = dict(scoped.get("records") or {})
    for hidden_mod in ("suppliers", "purchases", "expenses", "payments"):
        recs[hidden_mod] = []
    scoped["records"] = recs
    scoped["settlements"] = []
    scoped["bank_accounts"] = []
    scoped["trial_balance"] = []
    dash = dict(scoped.get("dashboard") or {})
    kpis = dict(dash.get("kpis") or {})
    kpis["cash"] = {"cents": 0, "event_ids": []}
    kpis["payables"] = {"cents": 0, "event_ids": []}
    dash["kpis"] = kpis
    scoped["dashboard"] = dash
    scoped["profitability"] = {
        "start": dash.get("start", ""),
        "end": dash.get("end", ""),
        "revenue_cents": kpis.get("revenue", {}).get("cents", 0),
        "gross_profit_cents": 0,
        "ebitda_cents": 0,
        "redacted_for_role": "SELLER",
    }
    scoped["role_scope"] = "SELLER_RESTRICTED"
    return scoped

