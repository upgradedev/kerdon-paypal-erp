"""Pure-domain ERP operational services for Parties, Drafts, Multi-Line Mixed-VAT Invoices,
Expenses, Receipts/Payments with Many-to-Many Allocations, Bank Accounts, and Targets.

Zero cloud, network, LLM, or wall-clock SDK imports (STANDARDS Gate A5).
All monetary arithmetic executes in 100% deterministic integer cents.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import hashlib
from typing import Any

from .commissions import AttributionStatus
from .crm import CreditNote, Customer, DocumentRegisterEntry, Supplier
from .docgen import build_cfo_board_pack, format_eur
from .fiscal import STATUTORY_VAT_RATES_PCT, summarize_vat_and_einvoice
from .ledger import AccountCode, FinancialEvent, LedgerLine
from .query import build_fact_sheet
from .tenancy import Direction
from .treasury import DuplicateIdempotencyError

ALLOWED_EXPENSE_ACCOUNTS: dict[str, AccountCode] = {
    "6200_GENERAL_OPERATING_EXPENSE": AccountCode.OPEX_GENERAL_6200,
    "6100_RENT_AND_UTILITIES": AccountCode.OPEX_RENT_UTILITIES_6100,
    "6000_WORKFORCE_EMPLOYER_COST": AccountCode.OPEX_WORKFORCE_6000,
    "5000_COST_OF_GOODS_SOLD": AccountCode.COGS_5000,
    "6050_SELLER_COMMISSION_EXPENSE": AccountCode.OPEX_COMMISSION_6050,
}


@dataclass(frozen=True)
class InvoiceLineItem:
    """Single commercial line item with deterministic integer-cent VAT calculation."""

    line_number: int
    description: str
    quantity: int
    unit_price_cents: int
    net_cents: int
    vat_rate_pct: int
    vat_cents: int
    gross_cents: int
    account_code: str = "4000_SALES_REVENUE"
    measurement_unit: int = 1


@dataclass(frozen=True)
class ErpDraftRecord:
    """Durable non-posting draft with explicit lifecycle state (`DRAFT` -> `APPROVED` -> `POSTED`)."""

    draft_id: str
    tenant_id: str
    module: str
    counterparty_id: str
    invoice_number: str
    issued_date: str
    due_date: str
    currency: str
    description: str
    lines: tuple[InvoiceLineItem, ...]
    net_cents: int
    vat_cents: int
    gross_cents: int
    status: str
    version: int
    created_by: str
    approved_by: str = ""
    posted_document_id: str = ""
    attachment_sha256: str = ""


@dataclass(frozen=True)
class BankAccountRecord:
    """Tenant cash or bank account mapped to GL `1000_CASH`."""

    bank_account_id: str
    tenant_id: str
    name: str
    iban: str
    currency: str
    gl_account: str = AccountCode.CASH_1000.value
    opening_balance_cents: int = 0


@dataclass(frozen=True)
class AllocationSlice:
    """Allocation of a receipt or payment against an open invoice or bill."""

    document_id: str
    allocated_cents: int


@dataclass(frozen=True)
class SettlementRecord:
    """Posted customer receipt or supplier payment with partial/many-to-many allocations."""

    settlement_id: str
    tenant_id: str
    kind: str  # "receipt" or "payment"
    counterparty_id: str
    bank_account_id: str
    posted_date: str
    currency: str
    gross_cash_cents: int
    fee_cents: int
    allocated_total_cents: int
    unapplied_advance_cents: int
    allocations: tuple[AllocationSlice, ...]
    ledger_event_id: str
    bank_execution_status: str  # "JOURNAL_ONLY" | "SANDBOX_SUBMITTED" | "SETTLED_AT_BANK"
    external_transfer_id: str = ""


@dataclass(frozen=True)
class SalesTargetRecord:
    """Durable monthly company, store, or seller revenue target with versioning."""

    target_id: str
    tenant_id: str
    period: str
    scope_kind: str  # "company" | "store" | "seller"
    scope_id: str
    target_cents: int
    currency: str
    version: int
    updated_by: str


@dataclass
class TenantErpExtensions:
    """Additive operational state attached per tenant for lines, drafts, settlements, and targets."""

    party_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    document_lines: dict[str, tuple[InvoiceLineItem, ...]] = field(default_factory=dict)
    document_status: dict[str, str] = field(default_factory=dict)
    drafts: dict[str, ErpDraftRecord] = field(default_factory=dict)
    bank_accounts: dict[str, BankAccountRecord] = field(default_factory=dict)
    settlements: dict[str, SettlementRecord] = field(default_factory=dict)
    targets: dict[str, SalesTargetRecord] = field(default_factory=dict)


_EXTENSIONS_BY_TENANT: dict[tuple[int, str], TenantErpExtensions] = {}


def get_erp_extensions(state: Any) -> TenantErpExtensions:
    tid = state.tenant.tenant_id
    ext = getattr(state, "_erp_extensions", None)
    if isinstance(ext, TenantErpExtensions):
        return ext
    key = (id(state), tid)
    ext = _EXTENSIONS_BY_TENANT.get(key)
    if ext is None:
        ext = TenantErpExtensions()
        ext.bank_accounts[f"bnk-{state.tenant.slug}-eur"] = BankAccountRecord(
            bank_account_id=f"bnk-{state.tenant.slug}-eur",
            tenant_id=tid,
            name=f"{state.tenant.display_name} Primary EUR Operating",
            iban=f"GR16011012500000000{abs(hash(tid)) % 100000000:08d}",
            currency="EUR",
        )
        _EXTENSIONS_BY_TENANT[key] = ext
    try:
        setattr(state, "_erp_extensions", ext)
    except Exception:
        pass
    return ext


def reset_erp_extensions() -> None:
    _EXTENSIONS_BY_TENANT.clear()
    from .connectors import reset_connector_states

    reset_connector_states()


def parse_and_compute_lines(
    raw_lines: list[dict[str, Any]] | None,
    *,
    fallback_net_cents: int | None = None,
    fallback_vat_rate_pct: int = 24,
    fallback_description: str = "Commercial line item",
    default_account_code: str = "4000_SALES_REVENUE",
) -> tuple[tuple[InvoiceLineItem, ...], int, int, int]:
    """Validate and compute per-line integer-cent net, VAT, and gross totals."""
    if not raw_lines:
        if (
            fallback_net_cents is None
            or isinstance(fallback_net_cents, bool)
            or not isinstance(fallback_net_cents, int)
            or fallback_net_cents <= 0
        ):
            raise ValueError("At least one positive line item or positive net_cents is required")
        if (
            isinstance(fallback_vat_rate_pct, bool)
            or not isinstance(fallback_vat_rate_pct, int)
            or fallback_vat_rate_pct not in STATUTORY_VAT_RATES_PCT
        ):
            raise ValueError("vat_rate_pct must be one of 0, 6, 13, 24")
        vat_c = (fallback_net_cents * fallback_vat_rate_pct) // 100
        gross_c = fallback_net_cents + vat_c
        single = InvoiceLineItem(
            1,
            fallback_description.strip() or "Commercial line item",
            1,
            fallback_net_cents,
            fallback_net_cents,
            fallback_vat_rate_pct,
            vat_c,
            gross_c,
            default_account_code,
        )
        return (single,), fallback_net_cents, vat_c, gross_c

    built: list[InvoiceLineItem] = []
    for idx, item in enumerate(raw_lines, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Line {idx} must be an object")
        desc = str(item.get("description") or f"Line {idx}").strip()
        qty = item.get("quantity", 1)
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValueError(f"Line {idx} quantity must be a positive integer")
        net_c = item.get("net_cents")
        unit_c = item.get("unit_price_cents")
        if net_c is None and unit_c is not None:
            if isinstance(unit_c, bool) or not isinstance(unit_c, int) or unit_c <= 0:
                raise ValueError(f"Line {idx} unit_price_cents must be a positive integer")
            net_c = qty * unit_c
        if isinstance(net_c, bool) or not isinstance(net_c, int) or net_c <= 0:
            raise ValueError(f"Line {idx} net_cents must be a positive integer")
        if unit_c is None:
            unit_c = net_c // qty
        rate = item.get("vat_rate_pct", fallback_vat_rate_pct)
        if isinstance(rate, bool) or not isinstance(rate, int) or rate not in STATUTORY_VAT_RATES_PCT:
            raise ValueError(f"Line {idx} vat_rate_pct must be one of 0, 6, 13, 24")
        vat_c = (net_c * rate) // 100
        gross_c = net_c + vat_c
        acct = str(item.get("account_code") or default_account_code).strip()
        built.append(
            InvoiceLineItem(idx, desc, qty, int(unit_c), net_c, rate, vat_c, gross_c, acct, int(item.get("measurement_unit", 1)))
        )
    return (
        tuple(built),
        sum(l.net_cents for l in built),
        sum(l.vat_cents for l in built),
        sum(l.gross_cents for l in built),
    )


def upsert_party_record(
    state: Any,
    *,
    kind: str,
    party_id: str,
    legal_name: str,
    tax_id: str,
    email: str = "",
    phone: str = "",
    address: str = "",
    payment_terms_days: int = 30,
    credit_limit_cents: int = 5_000_000,
    iban: str = "",
    category: str = "General Commercial",
    country_code: str = "GR",
    doy: str = "",
    gemi_number: str = "",
    branch_id: int = 0,
    city: str = "",
    postal_code: str = "",
    version: int = 1,
) -> dict[str, Any]:
    """Create or update a Customer or Supplier with commercial terms and audit metadata."""
    tid = state.tenant.tenant_id
    clean_kind = str(kind or "").strip().lower()
    if clean_kind not in ("customer", "supplier"):
        raise ValueError("Party kind must be 'customer' or 'supplier'")
    clean_name = str(legal_name or "").strip()
    clean_tax = "".join(ch for ch in str(tax_id or "").upper().strip() if ch.isalnum())
    if not clean_name or len(clean_tax) < 5:
        raise ValueError("legal_name and valid alphanumeric tax_id (>=5 chars) are required")
    if isinstance(payment_terms_days, bool) or not isinstance(payment_terms_days, int) or payment_terms_days < 0:
        raise ValueError("payment_terms_days must be a non-negative integer")
    if isinstance(credit_limit_cents, bool) or not isinstance(credit_limit_cents, int) or credit_limit_cents < 0:
        raise ValueError("credit_limit_cents must be a non-negative integer")

    ext = get_erp_extensions(state)
    if clean_kind == "customer":
        pid = party_id.strip() if party_id else f"cus-{state.tenant.slug}-{len(state.crm.customers) + 1:02d}"
        if pid in state.crm.suppliers:
            raise ValueError(f"Party ID {pid} is already registered as a supplier")
        cust = Customer(
            pid,
            tid,
            clean_name,
            clean_tax,
            str(email or f"billing@{clean_tax.lower()}.example.com").strip(),
            payment_terms_days,
            credit_limit_cents,
        )
        state.crm.upsert_customer(cust)
        base = {**asdict(cust), "id": pid, "kind": "customer"}
    else:
        pid = party_id.strip() if party_id else f"sup-{state.tenant.slug}-{len(state.crm.suppliers) + 1:02d}"
        if pid in state.crm.customers:
            raise ValueError(f"Party ID {pid} is already registered as a customer")
        clean_iban = str(iban or "GR1601101250000000012300695").strip().replace(" ", "")
        if len(clean_iban) < 10:
            raise ValueError("Supplier IBAN must be at least 10 characters")
        existing = state.crm.suppliers.get(pid)
        sup = Supplier(
            pid,
            tid,
            clean_name,
            clean_tax,
            clean_iban,
            str(category or "General Commercial").strip(),
            existing.historical_invoice_cents if existing else (),
            existing.recurring_monthly if existing else False,
        )
        state.crm.upsert_supplier(sup)
        base = {**asdict(sup), "id": pid, "kind": "supplier"}

    cc = str(country_code or state.tenant.fiscal_identity.country_code or "GR").upper().strip()
    meta = {
        "email": str(email or "").strip(),
        "phone": str(phone or "").strip(),
        "address": str(address or "").strip(),
        "payment_terms_days": payment_terms_days,
        "credit_limit_cents": credit_limit_cents,
        "iban": str(iban or "").strip(),
        "category": str(category or "General Commercial").strip(),
        "country_code": cc,
        "doy": str(doy or ("Athens Corporate Tax Office (KEFODE Attikis)" if cc == "GR" else "")).strip(),
        "gemi_number": str(gemi_number or ("129044101000" if cc == "GR" else "")).strip(),
        "branch_id": max(0, int(branch_id or 0)),
        "city": str(city or ("Athens" if cc == "GR" else "Berlin")).strip(),
        "postal_code": str(postal_code or ("10563" if cc == "GR" else "10117")).strip(),
        "version": version,
    }
    ext.party_metadata[pid] = meta
    return {**base, **meta}


def refresh_derived_period_state(state: Any, period: str, latest_sha: str) -> None:
    """Recompute P&L, MoM trend, VAT summary, BoardPack, and FactSheet after a ledger post."""
    tid = state.tenant.tenant_id
    pnl = state.ledger.summarize_period(period)
    prior_period = date.fromordinal(date.fromisoformat(f"{period}-01").toordinal() - 1).isoformat()[:7]
    mom = state.ledger.compute_mom_trend(period, prior_period)
    state.vat_summary = summarize_vat_and_einvoice(tid, period, tuple(state.crm.documents.values()))
    state.board_pack = build_cfo_board_pack(
        tenant_id=tid,
        period=period,
        pnl=pnl,
        mom_trend=mom,
        vat_summary=state.vat_summary,
        commission_case=state.commission_case,
        digest=state.digest,
        document_sha256s=(latest_sha, state.board_pack.handoff_packet.merkle_root_sha256),
    )
    state.fact_sheet = build_fact_sheet(
        tenant_name=state.tenant.display_name,
        pnl=pnl,
        mom_trend=mom,
        vat_summary=state.vat_summary,
        commission_case=state.commission_case,
        gaps=state.gaps,
    )


def reverse_posted_document(
    state: Any, *, document_id: str, reversal_date: str, reason: str, actor_id: str
) -> dict[str, Any]:
    """Post an exact reversing double-entry FinancialEvent for an existing document."""
    tid = state.tenant.tenant_id
    doc = state.crm.documents.get(document_id)
    if doc is None:
        raise KeyError(f"Unknown document_id: {document_id}")
    ext = get_erp_extensions(state)
    if ext.document_status.get(document_id) == "REVERSED":
        raise DuplicateIdempotencyError(f"Document {document_id} has already been reversed")
    orig_ev = next(
        (e for e in state.ledger.events if e.source_document_id == document_id and not e.event_id.startswith("rev-")),
        None,
    )
    if orig_ev is None:
        raise KeyError(f"No posted ledger event found for document {document_id}")
    rev_event_id = f"rev-{orig_ev.event_id}"
    if any(e.event_id == rev_event_id for e in state.ledger.events):
        raise DuplicateIdempotencyError(f"Reversal event {rev_event_id} already exists")

    iso_date = date.fromisoformat(str(reversal_date)).isoformat()
    rev_lines = tuple(
        LedgerLine(
            line.account,
            line.credit_cents,
            line.debit_cents,
            line.counterparty_id,
            line.store_id,
            f"Reversal of {orig_ev.event_id}: {reason}",
        )
        for line in orig_ev.lines
    )
    rev_sha = hashlib.sha256(f"{tid}:{rev_event_id}:{orig_ev.source_sha256}:{actor_id}".encode("utf-8")).hexdigest()
    rev_ev = FinancialEvent(
        rev_event_id,
        tid,
        iso_date[:7],
        iso_date,
        f"Reverse {document_id}: {reason}",
        document_id,
        rev_sha,
        rev_lines,
    )
    state.ledger.post(rev_ev)
    ext.document_status[document_id] = "REVERSED"

    cn_id = f"cn-rev-{document_id}"
    cn = CreditNote(
        cn_id,
        tid,
        doc.direction,
        doc.counterparty_id,
        doc.net_cents,
        doc.vat_cents,
        doc.gross_cents,
        doc.currency,
        iso_date,
        rev_sha,
        document_id,
    )
    state.crm.register_credit_note(cn)
    invalidated = state.treasury.notify_changed_evidence(
        counterparty_id=doc.counterparty_id,
        new_evidence_sha256=rev_sha,
        reason=f"Document {document_id} reversed ({format_eur(doc.gross_cents)})",
        invoice_or_case_id=document_id,
    )
    refresh_derived_period_state(state, iso_date[:7], rev_sha)
    return {
        "document_id": document_id,
        "status": "REVERSED",
        "reversal_event": asdict(rev_ev),
        "credit_note": asdict(cn),
        "invalidated_approval_ids": list(invalidated),
    }


def post_direct_expense_bill(
    state: Any,
    *,
    document_id: str,
    supplier_id: str,
    invoice_number: str,
    issued_date: str,
    due_date: str,
    description: str,
    expense_account_key: str,
    raw_lines: list[dict[str, Any]] | None,
    fallback_net_cents: int | None,
    fallback_vat_rate_pct: int,
    now_ts: int,
) -> dict[str, Any]:
    """Post a supplier purchase/expense bill with explicit expense account mapping and mixed-VAT lines."""
    tid = state.tenant.tenant_id
    if supplier_id not in state.crm.suppliers:
        raise ValueError("Supplier must belong to this tenant")
    sup = state.crm.suppliers[supplier_id]
    iso_issued = date.fromisoformat(str(issued_date)).isoformat()
    iso_due = date.fromisoformat(str(due_date)).isoformat()
    if iso_due < iso_issued:
        raise ValueError("Due date must not precede issued date")

    acct_enum = ALLOWED_EXPENSE_ACCOUNTS.get(expense_account_key, AccountCode.OPEX_GENERAL_6200)
    lines_tuple, net_cents, vat_cents, gross_cents = parse_and_compute_lines(
        raw_lines,
        fallback_net_cents=fallback_net_cents,
        fallback_vat_rate_pct=fallback_vat_rate_pct,
        fallback_description=description,
        default_account_code=acct_enum.value,
    )
    if document_id in state.crm.documents or any(e.event_id == f"ev-{document_id}" for e in state.ledger.events):
        raise DuplicateIdempotencyError("Expense document already exists; not posted twice")

    doc_sha = hashlib.sha256(f"{tid}:{document_id}:{supplier_id}:{gross_cents}:{now_ts}".encode("utf-8")).hexdigest()
    entry = DocumentRegisterEntry(
        document_id,
        tid,
        Direction.PURCHASE_EXPENSE,
        supplier_id,
        sup.legal_name,
        sup.tax_id,
        invoice_number or f"EXP-{now_ts % 100000}",
        net_cents,
        vat_cents,
        gross_cents,
        0,
        "EUR",
        iso_issued,
        iso_due,
        doc_sha,
        f"MARK-{now_ts % 1000000}",
        f"str-{state.tenant.slug}-01",
    )
    state.crm.register_document(entry)
    ext = get_erp_extensions(state)
    ext.document_lines[document_id] = lines_tuple
    ext.document_status[document_id] = "OPEN"

    gl_lines: list[LedgerLine] = [
        LedgerLine(
            ALLOWED_EXPENSE_ACCOUNTS.get(l_item.account_code, acct_enum),
            debit_cents=l_item.net_cents,
            counterparty_id=supplier_id,
            memo=l_item.description,
        )
        for l_item in lines_tuple
    ]
    if vat_cents > 0:
        gl_lines.append(
            LedgerLine(AccountCode.VAT_INPUT_1400, debit_cents=vat_cents, counterparty_id=supplier_id, memo=f"Input VAT for {document_id}")
        )
    gl_lines.append(
        LedgerLine(AccountCode.AP_2000, credit_cents=gross_cents, counterparty_id=supplier_id, memo=f"AP for {document_id}")
    )
    ev = FinancialEvent(
        f"ev-{document_id}",
        tid,
        iso_issued[:7],
        iso_issued,
        description or f"Expense bill {entry.doc_type}",
        document_id,
        doc_sha,
        tuple(gl_lines),
    )
    state.ledger.post(ev)
    refresh_derived_period_state(state, iso_issued[:7], doc_sha)
    return {"document": asdict(entry), "lines": [asdict(l) for l in lines_tuple], "event": asdict(ev)}


def post_settlement_with_allocations(
    state: Any,
    *,
    settlement_id: str,
    kind: str,
    counterparty_id: str,
    posted_date: str,
    gross_cash_cents: int,
    fee_cents: int = 0,
    allocations: list[dict[str, Any]] | None = None,
    bank_account_id: str = "",
    description: str = "",
    now_ts: int = 0,
) -> SettlementRecord:
    """Post a customer cash receipt or supplier cash payment with partial/many-to-many allocations."""
    tid = state.tenant.tenant_id
    clean_kind = str(kind or "").strip().lower()
    if clean_kind not in ("receipt", "payment"):
        raise ValueError("Settlement kind must be 'receipt' or 'payment'")
    if isinstance(gross_cash_cents, bool) or not isinstance(gross_cash_cents, int) or gross_cash_cents <= 0:
        raise ValueError("gross_cash_cents must be a positive integer")
    if isinstance(fee_cents, bool) or not isinstance(fee_cents, int) or fee_cents < 0 or fee_cents >= gross_cash_cents:
        raise ValueError("fee_cents must be a non-negative integer less than gross_cash_cents")

    iso_date = date.fromisoformat(str(posted_date)).isoformat()
    ext = get_erp_extensions(state)
    if settlement_id in ext.settlements or any(e.event_id == f"ev-{settlement_id}" for e in state.ledger.events):
        raise DuplicateIdempotencyError(f"Settlement {settlement_id} already posted")

    if clean_kind == "receipt":
        if counterparty_id not in state.crm.customers:
            raise ValueError("Receipt counterparty must belong to tenant customers")
        expected_dir = Direction.SALES_REVENUE
    else:
        if counterparty_id not in state.crm.suppliers:
            raise ValueError("Payment counterparty must belong to tenant suppliers")
        expected_dir = Direction.PURCHASE_EXPENSE

    parsed_allocs: list[AllocationSlice] = []
    allocated_total = 0
    seen_doc_ids: set[str] = set()
    for item in allocations or []:
        doc_id = str(item.get("document_id") or "").strip()
        alloc_c = item.get("allocated_cents")
        if not doc_id or isinstance(alloc_c, bool) or not isinstance(alloc_c, int) or alloc_c <= 0:
            raise ValueError("Each allocation requires document_id and positive integer allocated_cents")
        if doc_id in seen_doc_ids:
            raise ValueError(f"Duplicate document_id {doc_id} in allocations")
        seen_doc_ids.add(doc_id)
        doc = state.crm.documents.get(doc_id)
        if doc is None or doc.tenant_id != tid:
            raise ValueError(f"Allocated document {doc_id} does not exist in this tenant")
        if doc.direction != expected_dir or doc.counterparty_id != counterparty_id:
            raise ValueError(f"Document {doc_id} does not match counterparty {counterparty_id} and direction")
        if ext.document_status.get(doc_id) == "REVERSED":
            raise ValueError(f"Cannot allocate against reversed document {doc_id}")
        if alloc_c > doc.outstanding_cents:
            raise ValueError(f"Allocation {alloc_c}c exceeds open balance {doc.outstanding_cents}c on {doc_id}")
        parsed_allocs.append(AllocationSlice(doc_id, alloc_c))
        allocated_total += alloc_c

    total_settlement_power = (
        gross_cash_cents + fee_cents
        if clean_kind == "receipt"
        else gross_cash_cents - fee_cents
    )
    if allocated_total > total_settlement_power:
        raise ValueError("Total allocated_cents cannot exceed settlement amount")

    unapplied_cents = total_settlement_power - allocated_total
    ev_id = f"ev-{settlement_id}"
    sha = hashlib.sha256(f"{tid}:{settlement_id}:{counterparty_id}:{gross_cash_cents}:{now_ts}".encode("utf-8")).hexdigest()

    gl_lines: list[LedgerLine] = []
    if clean_kind == "receipt":
        gl_lines.append(LedgerLine(AccountCode.CASH_1000, debit_cents=gross_cash_cents, counterparty_id=counterparty_id, memo=f"Cash receipt {settlement_id}"))
        if fee_cents > 0:
            gl_lines.append(LedgerLine(AccountCode.OPEX_GENERAL_6200, debit_cents=fee_cents, counterparty_id=counterparty_id, memo=f"Bank fee on {settlement_id}"))
        ar_credit = allocated_total if parsed_allocs else total_settlement_power
        unapplied_ar = unapplied_cents if parsed_allocs else 0
        if ar_credit > 0:
            gl_lines.append(LedgerLine(AccountCode.AR_1100, credit_cents=ar_credit, counterparty_id=counterparty_id, memo=f"AR settlement {settlement_id}"))
        if unapplied_ar > 0:
            gl_lines.append(LedgerLine(AccountCode.CUSTOMER_DEPOSITS_2100, credit_cents=unapplied_ar, counterparty_id=counterparty_id, memo=f"Unapplied customer advance on {settlement_id}"))
        else:
            unapplied_cents = 0
    else:
        ap_debit = gross_cash_cents - fee_cents
        gl_lines.append(LedgerLine(AccountCode.AP_2000, debit_cents=ap_debit, counterparty_id=counterparty_id, memo=f"AP settlement {settlement_id}"))
        if fee_cents > 0:
            gl_lines.append(LedgerLine(AccountCode.OPEX_GENERAL_6200, debit_cents=fee_cents, counterparty_id=counterparty_id, memo=f"Bank transfer fee on {settlement_id}"))
        gl_lines.append(LedgerLine(AccountCode.CASH_1000, credit_cents=gross_cash_cents, counterparty_id=counterparty_id, memo=f"Cash outflow {settlement_id}"))

    ev = FinancialEvent(
        ev_id,
        tid,
        iso_date[:7],
        iso_date,
        description or f"Posted {clean_kind} {settlement_id}",
        parsed_allocs[0].document_id if len(parsed_allocs) == 1 else settlement_id,
        sha,
        tuple(gl_lines),
    )
    state.ledger.post(ev)

    for sl in parsed_allocs:
        old_doc = state.crm.documents[sl.document_id]
        new_paid = old_doc.paid_cents + sl.allocated_cents
        updated_doc = DocumentRegisterEntry(
            old_doc.document_id,
            old_doc.tenant_id,
            old_doc.direction,
            old_doc.counterparty_id,
            old_doc.counterparty_name,
            old_doc.counterparty_tax_id,
            old_doc.doc_type,
            old_doc.net_cents,
            old_doc.vat_cents,
            old_doc.gross_cents,
            new_paid,
            old_doc.currency,
            old_doc.issued_date,
            old_doc.due_date,
            old_doc.source_sha256,
            old_doc.einvoice_mark,
            old_doc.store_id,
        )
        state.crm.register_document(updated_doc)
        ext.document_status[sl.document_id] = "PAID" if new_paid >= old_doc.gross_cents else "PART_PAID"

    default_bank = next(iter(ext.bank_accounts), f"bnk-{state.tenant.slug}-eur")
    record = SettlementRecord(
        settlement_id,
        tid,
        clean_kind,
        counterparty_id,
        bank_account_id or default_bank,
        iso_date,
        "EUR",
        gross_cash_cents,
        fee_cents,
        allocated_total,
        unapplied_cents,
        tuple(parsed_allocs),
        ev_id,
        "JOURNAL_ONLY",
    )
    ext.settlements[settlement_id] = record
    refresh_derived_period_state(state, iso_date[:7], sha)
    return record


def upsert_sales_target(
    state: Any, *, period: str, scope_kind: str, scope_id: str, target_cents: int, updated_by: str, version: int = 1
) -> SalesTargetRecord:
    """Persist a versioned monthly company, store, or seller revenue target."""
    tid = state.tenant.tenant_id
    clean_scope = str(scope_kind or "company").strip().lower()
    if clean_scope not in ("company", "store", "seller"):
        raise ValueError("scope_kind must be 'company', 'store', or 'seller'")
    if isinstance(target_cents, bool) or not isinstance(target_cents, int) or target_cents <= 0:
        raise ValueError("target_cents must be a positive integer")
    if len(str(period or "")) != 7 or str(period)[4] != "-":
        raise ValueError("period must be YYYY-MM")
    clean_id = str(scope_id or tid).strip()
    target_id = f"tgt-{tid}-{period}-{clean_scope}-{clean_id}"
    ext = get_erp_extensions(state)
    rec = SalesTargetRecord(target_id, tid, period, clean_scope, clean_id, target_cents, "EUR", version, updated_by)
    ext.targets[target_id] = rec
    return rec


def evaluate_targets_vs_actuals(state: Any, start: str, end: str) -> dict[str, Any]:
    """Compare saved monthly company/store/seller targets against posted ledger & approved attribution."""
    ext = get_erp_extensions(state)
    rev_accounts = (AccountCode.REVENUE_SALES_4000, AccountCode.REVENUE_COMMISSION_4100)
    company_actual_cents = 0
    store_actuals: dict[str, int] = {}
    source_event_ids: list[str] = []

    for ev in state.ledger.events:
        if start <= ev.posted_date <= end:
            ev_rev = sum(l.credit_cents - l.debit_cents for l in ev.lines if l.account in rev_accounts)
            if ev_rev != 0:
                company_actual_cents += ev_rev
                source_event_ids.append(ev.event_id)
                for l in ev.lines:
                    if l.account in rev_accounts and l.store_id:
                        store_actuals[l.store_id] = store_actuals.get(l.store_id, 0) + (l.credit_cents - l.debit_cents)

    approved_by_sale = {a.sale_id: a.seller_id for a in state.attributions if a.status == AttributionStatus.APPROVED}
    seller_actuals: dict[str, int] = {}
    for s_ev in state.sales_events:
        seller_id = approved_by_sale.get(s_ev.sale_id)
        if seller_id:
            seller_actuals[seller_id] = seller_actuals.get(seller_id, 0) + s_ev.net_revenue_cents

    comparisons = []
    for tgt in sorted(ext.targets.values(), key=lambda t: t.target_id):
        actual = (
            company_actual_cents
            if tgt.scope_kind == "company"
            else store_actuals.get(tgt.scope_id, 0)
            if tgt.scope_kind == "store"
            else seller_actuals.get(tgt.scope_id, 0)
        )
        attainment_bps = int((actual * 10_000) // tgt.target_cents) if tgt.target_cents > 0 else 0
        comparisons.append(
            {
                **asdict(tgt),
                "actual_cents": actual,
                "remaining_cents": max(0, tgt.target_cents - actual),
                "attainment_pct": round(attainment_bps / 100.0, 2),
                "source_event_ids": source_event_ids,
            }
        )
    return {
        "company_actual_revenue_cents": company_actual_cents,
        "store_actuals_cents": store_actuals,
        "seller_approved_actuals_cents": seller_actuals,
        "saved_targets": comparisons,
        "source_event_ids": source_event_ids,
    }
