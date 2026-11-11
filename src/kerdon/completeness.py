"""M6: 24-Rule Deterministic Completeness and Financial Anomaly Engine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from .commissions import (
    AttributionStatus,
    ClawbackEvent,
    MonthlyCommissionCase,
    PrincipalSettlement,
    SalesAttribution,
    SalesEvent,
)
from .crm import (
    BookingStatus,
    ClientBooking,
    CreditNote,
    DocumentRegisterEntry,
    Supplier,
)
from .fiscal import WorkforceCostFusion, validate_vat_breakdown
from .inbox import CandidateDocKind, EvidenceSourceKind, ExtractedCandidate

DUPLICATE_WINDOW_DAYS = 7
OUTLIER_MEDIAN_MULTIPLIER = 5


class GapSeverity(str, Enum):
    """Operational urgency of a detected financial completeness or anomaly gap."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class GapRuleId(str, Enum):
    """The 24 deterministic completeness and anomaly rules in Kerdon MSP."""

    PAYMENT_WITHOUT_DOCUMENT = "payment_without_document"
    INVOICE_UNPAID = "invoice_unpaid"
    AMOUNT_MISMATCH = "amount_mismatch"
    SETTLEMENT_NOT_INVOICED = "settlement_not_invoiced"
    SETTLEMENT_UNRECEIVED = "settlement_unreceived"
    UNINVOICED_CLIENT_DEPOSIT = "uninvoiced_client_deposit"
    MISSING_DOCUMENT_FAMILY = "missing_document_family"
    DUPLICATE_PAYMENT = "duplicate_payment"
    AMOUNT_OUTLIER = "amount_outlier"
    VAT_INCONSISTENCY = "vat_inconsistency"
    UNLINKED_CREDIT_NOTE = "unlinked_credit_note"
    COMMISSION_PAYOUT_MISMATCH = "commission_payout_mismatch"
    RESERVE_FLOOR_BREACH = "reserve_floor_breach"
    PAYROLL_MISSING_APD = "payroll_missing_apd"
    PAYROLL_MISSING_FMY = "payroll_missing_fmy"
    PAYROLL_NET_TRANSFER_MISMATCH = "payroll_net_transfer_mismatch"
    EINVOICE_MARK_MISSING = "einvoice_mark_missing"
    HTML_BODY_INVOICE_BLOCKED = "html_body_invoice_blocked"
    UNATTRIBUTED_STORE_SALE = "unattributed_store_sale"
    CLAWBACK_UNAPPLIED = "clawback_unapplied"
    STALE_FX_QUOTE_ON_PAYOUT = "stale_fx_quote_on_payout"
    SELF_APPROVAL_ATTEMPT_DETECTED = "self_approval_attempt_detected"
    INTER_STORE_IMBALANCE = "inter_store_imbalance"
    BOOKING_BALANCE_OVERDUE = "booking_balance_overdue"


@dataclass(frozen=True)
class BankMovement:
    """Single bank debit or credit line used for reconciliation and duplicate checks."""

    movement_id: str
    tenant_id: str
    counterparty_id: str
    counterparty_name: str
    amount_cents: int
    is_debit: bool
    value_date: str
    linked_document_id: str = ""
    currency: str = "EUR"


@dataclass(frozen=True)
class CompletenessGap:
    """Deterministic finding emitted by the 24-rule completeness engine."""

    gap_id: str
    tenant_id: str
    period: str
    rule_id: GapRuleId
    severity: GapSeverity
    counterparty_id: str
    counterparty_name: str
    amount_cents: int
    currency: str
    subject_id: str
    summary: str


@dataclass(frozen=True)
class TenantAuditInput:
    """Immutable snapshot of a tenant's period records fed into the 24-rule scan."""

    tenant_id: str
    period: str
    as_of_date: str
    documents: tuple[DocumentRegisterEntry, ...] = ()
    suppliers: tuple[Supplier, ...] = ()
    bank_movements: tuple[BankMovement, ...] = ()
    settlements: tuple[PrincipalSettlement, ...] = ()
    bookings: tuple[ClientBooking, ...] = ()
    credit_notes: tuple[CreditNote, ...] = ()
    workforce_fusion: WorkforceCostFusion | None = None
    commission_case: MonthlyCommissionCase | None = None
    payroll_commission_paid_cents: int | None = None
    sales_events: tuple[SalesEvent, ...] = ()
    attributions: tuple[SalesAttribution, ...] = ()
    clawbacks: tuple[ClawbackEvent, ...] = ()
    raw_candidates: tuple[ExtractedCandidate, ...] = ()
    reserve_breaches: tuple[tuple[str, int, int], ...] = ()
    stale_fx_payout_ids: tuple[str, ...] = ()
    self_approval_attempt_ids: tuple[str, ...] = ()
    inter_store_net_imbalance_cents: int = 0


def _days_between(d1: str, d2: str) -> int:
    return abs((date.fromisoformat(d1) - date.fromisoformat(d2)).days)


def run_completeness_scan(audit: TenantAuditInput) -> tuple[CompletenessGap, ...]:
    """Run all 24 deterministic completeness and anomaly rules in stable order."""
    gaps: list[CompletenessGap] = []
    docs_by_id = {d.document_id: d for d in audit.documents}
    suppliers_by_id = {s.supplier_id: s for s in audit.suppliers}

    # 1. payment_without_document & 3. amount_mismatch & 8. duplicate_payment
    debits = [m for m in audit.bank_movements if m.is_debit]
    for mov in debits:
        if not mov.linked_document_id:
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-pwd-{mov.movement_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.PAYMENT_WITHOUT_DOCUMENT,
                    severity=GapSeverity.HIGH,
                    counterparty_id=mov.counterparty_id,
                    counterparty_name=mov.counterparty_name,
                    amount_cents=mov.amount_cents,
                    currency=mov.currency,
                    subject_id=mov.movement_id,
                    summary=f"Bank debit {mov.movement_id} to {mov.counterparty_name} has no linked invoice.",
                )
            )
        else:
            linked = docs_by_id.get(mov.linked_document_id)
            if linked is not None and linked.gross_cents != mov.amount_cents:
                diff = abs(linked.gross_cents - mov.amount_cents)
                gaps.append(
                    CompletenessGap(
                        gap_id=f"gap-{audit.tenant_id}-mm-{mov.movement_id}",
                        tenant_id=audit.tenant_id,
                        period=audit.period,
                        rule_id=GapRuleId.AMOUNT_MISMATCH,
                        severity=GapSeverity.HIGH,
                        counterparty_id=mov.counterparty_id,
                        counterparty_name=mov.counterparty_name,
                        amount_cents=diff,
                        currency=mov.currency,
                        subject_id=mov.movement_id,
                        summary=(
                            f"Payment {mov.movement_id} ({mov.amount_cents}c) differs from "
                            f"invoice {linked.document_id} ({linked.gross_cents}c) by {diff}c."
                        ),
                    )
                )

    for i, first in enumerate(debits):
        for second in debits[i + 1 :]:
            if (
                first.counterparty_id == second.counterparty_id
                and first.amount_cents == second.amount_cents
                and _days_between(first.value_date, second.value_date)
                <= DUPLICATE_WINDOW_DAYS
            ):
                gaps.append(
                    CompletenessGap(
                        gap_id=f"gap-{audit.tenant_id}-dup-{first.movement_id}-{second.movement_id}",
                        tenant_id=audit.tenant_id,
                        period=audit.period,
                        rule_id=GapRuleId.DUPLICATE_PAYMENT,
                        severity=GapSeverity.CRITICAL,
                        counterparty_id=first.counterparty_id,
                        counterparty_name=first.counterparty_name,
                        amount_cents=first.amount_cents,
                        currency=first.currency,
                        subject_id=second.movement_id,
                        summary=(
                            f"Duplicate debit of {first.amount_cents}c to {first.counterparty_name} "
                            f"between {first.movement_id} and {second.movement_id} within 7 days."
                        ),
                    )
                )

    # 2. invoice_unpaid, 9. amount_outlier, 10. vat_inconsistency, 17. einvoice_mark_missing
    for doc in audit.documents:
        if doc.outstanding_cents > 0 and doc.due_date < audit.as_of_date:
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-unpaid-{doc.document_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.INVOICE_UNPAID,
                    severity=GapSeverity.MEDIUM,
                    counterparty_id=doc.counterparty_id,
                    counterparty_name=doc.counterparty_name,
                    amount_cents=doc.outstanding_cents,
                    currency=doc.currency,
                    subject_id=doc.document_id,
                    summary=(
                        f"Invoice {doc.document_id} ({doc.counterparty_name}) is overdue since "
                        f"{doc.due_date} with {doc.outstanding_cents}c unpaid."
                    ),
                )
            )
        sup = suppliers_by_id.get(doc.counterparty_id)
        if (
            sup is not None
            and sup.median_invoice_cents > 0
            and doc.gross_cents > sup.median_invoice_cents * OUTLIER_MEDIAN_MULTIPLIER
        ):
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-outlier-{doc.document_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.AMOUNT_OUTLIER,
                    severity=GapSeverity.HIGH,
                    counterparty_id=doc.counterparty_id,
                    counterparty_name=doc.counterparty_name,
                    amount_cents=doc.gross_cents,
                    currency=doc.currency,
                    subject_id=doc.document_id,
                    summary=(
                        f"Document {doc.document_id} ({doc.gross_cents}c) exceeds 5x historical "
                        f"median ({sup.median_invoice_cents}c) for {doc.counterparty_name}."
                    ),
                )
            )
        vat_check = validate_vat_breakdown(doc.net_cents, doc.vat_cents, doc.gross_cents)
        if not vat_check.is_valid:
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-vat-{doc.document_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.VAT_INCONSISTENCY,
                    severity=GapSeverity.CRITICAL,
                    counterparty_id=doc.counterparty_id,
                    counterparty_name=doc.counterparty_name,
                    amount_cents=doc.vat_cents,
                    currency=doc.currency,
                    subject_id=doc.document_id,
                    summary=f"VAT anomaly on {doc.document_id}: {vat_check.reason}",
                )
            )
        if not doc.einvoice_mark.strip():
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-mark-{doc.document_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.EINVOICE_MARK_MISSING,
                    severity=GapSeverity.MEDIUM,
                    counterparty_id=doc.counterparty_id,
                    counterparty_name=doc.counterparty_name,
                    amount_cents=doc.gross_cents,
                    currency=doc.currency,
                    subject_id=doc.document_id,
                    summary=f"Document {doc.document_id} is missing statutory e-invoice MARK/UID.",
                )
            )

    # 4. settlement_not_invoiced & 5. settlement_unreceived
    for stl in audit.settlements:
        if not stl.is_invoiced:
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-stlinv-{stl.settlement_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.SETTLEMENT_NOT_INVOICED,
                    severity=GapSeverity.HIGH,
                    counterparty_id=stl.principal_tax_id,
                    counterparty_name=stl.principal_name,
                    amount_cents=stl.gross_cents,
                    currency="EUR",
                    subject_id=stl.settlement_id,
                    summary=(
                        f"Principal commission settlement {stl.settlement_id} from "
                        f"{stl.principal_name} ({stl.gross_cents}c) has no issued sales invoice."
                    ),
                )
            )
        elif not stl.is_collected:
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-stlrcpt-{stl.settlement_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.SETTLEMENT_UNRECEIVED,
                    severity=GapSeverity.MEDIUM,
                    counterparty_id=stl.principal_tax_id,
                    counterparty_name=stl.principal_name,
                    amount_cents=stl.gross_cents,
                    currency="EUR",
                    subject_id=stl.settlement_id,
                    summary=(
                        f"Invoiced commission settlement {stl.settlement_id} ({stl.gross_cents}c) "
                        f"has not been received in bank movements."
                    ),
                )
            )

    # 6. uninvoiced_client_deposit & 24. booking_balance_overdue & 20. clawback_unapplied
    clawback_sale_ids = {cb.original_sale_id for cb in audit.clawbacks}
    for bk in audit.bookings:
        if bk.has_uninvoiced_deposit:
            diff = bk.advance_deposit_cents - bk.invoiced_cents
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-dep-{bk.booking_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.UNINVOICED_CLIENT_DEPOSIT,
                    severity=GapSeverity.MEDIUM,
                    counterparty_id=bk.customer_id,
                    counterparty_name=bk.customer_id,
                    amount_cents=diff,
                    currency="EUR",
                    subject_id=bk.booking_id,
                    summary=f"Booking {bk.booking_id} holds {diff}c of uninvoiced client advance deposit.",
                )
            )
        if (
            bk.status in (BookingStatus.CONFIRMED, BookingStatus.DELIVERED)
            and bk.remaining_balance_cents > 0
            and bk.delivery_date < audit.as_of_date
        ):
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-bkbal-{bk.booking_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.BOOKING_BALANCE_OVERDUE,
                    severity=GapSeverity.MEDIUM,
                    counterparty_id=bk.customer_id,
                    counterparty_name=bk.customer_id,
                    amount_cents=bk.remaining_balance_cents,
                    currency="EUR",
                    subject_id=bk.booking_id,
                    summary=(
                        f"Booking {bk.booking_id} past delivery {bk.delivery_date} has "
                        f"{bk.remaining_balance_cents}c unpaid balance."
                    ),
                )
            )
        if (
            bk.status == BookingStatus.CANCELLED
            and bk.booking_id not in clawback_sale_ids
        ):
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-claw-{bk.booking_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.CLAWBACK_UNAPPLIED,
                    severity=GapSeverity.HIGH,
                    counterparty_id=bk.seller_id,
                    counterparty_name=bk.seller_id,
                    amount_cents=bk.total_agreed_cents,
                    currency="EUR",
                    subject_id=bk.booking_id,
                    summary=f"Cancelled booking {bk.booking_id} has no seller commission clawback entry.",
                )
            )

    # 7. missing_document_family (recurring monthly supplier with no document in current period)
    present_supplier_ids = {
        d.counterparty_id
        for d in audit.documents
        if d.issued_date.startswith(audit.period)
    }
    for sup in audit.suppliers:
        if sup.recurring_monthly and sup.supplier_id not in present_supplier_ids:
            est = sup.median_invoice_cents or 100_000
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-fam-{sup.supplier_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.MISSING_DOCUMENT_FAMILY,
                    severity=GapSeverity.MEDIUM,
                    counterparty_id=sup.supplier_id,
                    counterparty_name=sup.legal_name,
                    amount_cents=est,
                    currency="EUR",
                    subject_id=sup.supplier_id,
                    summary=(
                        f"Recurring monthly supplier {sup.legal_name} ({sup.category}) "
                        f"has no bill recorded in {audit.period}."
                    ),
                )
            )

    # 11. unlinked_credit_note
    for cn in audit.credit_notes:
        if not cn.referenced_invoice_id or cn.referenced_invoice_id not in docs_by_id:
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-cn-{cn.credit_note_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.UNLINKED_CREDIT_NOTE,
                    severity=GapSeverity.HIGH,
                    counterparty_id=cn.counterparty_id,
                    counterparty_name=cn.counterparty_id,
                    amount_cents=cn.gross_cents,
                    currency=cn.currency,
                    subject_id=cn.credit_note_id,
                    summary=f"Credit note {cn.credit_note_id} ({cn.gross_cents}c) is not linked to an invoice.",
                )
            )

    # 12. commission_payout_mismatch
    if (
        audit.commission_case is not None
        and audit.payroll_commission_paid_cents is not None
    ):
        diff = abs(
            audit.payroll_commission_paid_cents
            - audit.commission_case.total_payable_cents
        )
        if diff > 0:
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-commpay-{audit.commission_case.case_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.COMMISSION_PAYOUT_MISMATCH,
                    severity=GapSeverity.HIGH,
                    counterparty_id=audit.commission_case.case_id,
                    counterparty_name="Payroll Commission Line",
                    amount_cents=diff,
                    currency="EUR",
                    subject_id=audit.commission_case.case_id,
                    summary=(
                        f"Payroll commission paid ({audit.payroll_commission_paid_cents}c) differs "
                        f"from approved commission case ({audit.commission_case.total_payable_cents}c) by {diff}c."
                    ),
                )
            )

    # 13. reserve_floor_breach
    for currency, projected_cents, floor_cents in audit.reserve_breaches:
        shortfall = max(1, floor_cents - projected_cents)
        gaps.append(
            CompletenessGap(
                gap_id=f"gap-{audit.tenant_id}-rsv-{currency}",
                tenant_id=audit.tenant_id,
                period=audit.period,
                rule_id=GapRuleId.RESERVE_FLOOR_BREACH,
                severity=GapSeverity.CRITICAL,
                counterparty_id=f"TREASURY_{currency}",
                counterparty_name=f"{currency} Reserve Floor",
                amount_cents=shortfall,
                currency=currency,
                subject_id=f"pocket-{currency}",
                summary=(
                    f"{currency} projected balance ({projected_cents}c) breaches reserve floor "
                    f"({floor_cents}c) by {shortfall}c."
                ),
            )
        )

    # 14. payroll_missing_apd, 15. payroll_missing_fmy, 16. payroll_net_transfer_mismatch
    wf = audit.workforce_fusion
    if wf is not None:
        if wf.missing_apd:
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-apd-{wf.period}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.PAYROLL_MISSING_APD,
                    severity=GapSeverity.HIGH,
                    counterparty_id="EFKA_APD",
                    counterparty_name="Social Security Authority (APD)",
                    amount_cents=wf.gross_wages_cents // 4,
                    currency="EUR",
                    subject_id=f"payroll-{wf.period}",
                    summary=f"Payroll register for {wf.period} is missing companion APD social-security filing.",
                )
            )
        if wf.missing_fmy:
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-fmy-{wf.period}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.PAYROLL_MISSING_FMY,
                    severity=GapSeverity.HIGH,
                    counterparty_id="AADE_FMY",
                    counterparty_name="Tax Authority (FMY Withholding)",
                    amount_cents=wf.total_fmy_payable_cents or (wf.gross_wages_cents // 10),
                    currency="EUR",
                    subject_id=f"payroll-{wf.period}",
                    summary=f"Payroll register for {wf.period} is missing companion FMY withheld tax filing.",
                )
            )
        if wf.net_transfer_mismatch_cents != 0:
            diff = abs(wf.net_transfer_mismatch_cents)
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-wfnet-{wf.period}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.PAYROLL_NET_TRANSFER_MISMATCH,
                    severity=GapSeverity.HIGH,
                    counterparty_id="PAYROLL_BANK",
                    counterparty_name="Bank Payroll Batch",
                    amount_cents=diff,
                    currency="EUR",
                    subject_id=f"payroll-{wf.period}",
                    summary=f"Bank net salary transfers differ from payroll register net payable by {diff}c.",
                )
            )

    # 18. html_body_invoice_blocked
    for cand in audit.raw_candidates:
        if cand.source_kind == EvidenceSourceKind.HTML_BODY_TABLE and cand.doc_kind in (
            CandidateDocKind.SALES_INVOICE,
            CandidateDocKind.PURCHASE_INVOICE,
            CandidateDocKind.CREDIT_NOTE,
        ):
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-html-{cand.candidate_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.HTML_BODY_INVOICE_BLOCKED,
                    severity=GapSeverity.HIGH,
                    counterparty_id=cand.counterparty_tax_id or cand.counterparty_name,
                    counterparty_name=cand.counterparty_name,
                    amount_cents=cand.gross_cents,
                    currency=cand.currency,
                    subject_id=cand.candidate_id,
                    summary=(
                        f"Candidate {cand.candidate_id} from HTML email body was blocked "
                        f"from ledger invoice posting; formal PDF/XML invoice required."
                    ),
                )
            )

    # 19. unattributed_store_sale
    approved_or_suggested = {
        a.sale_id
        for a in audit.attributions
        if a.status in (AttributionStatus.APPROVED, AttributionStatus.SUGGESTED)
    }
    for sale in audit.sales_events:
        if sale.sale_id not in approved_or_suggested:
            gaps.append(
                CompletenessGap(
                    gap_id=f"gap-{audit.tenant_id}-unattr-{sale.sale_id}",
                    tenant_id=audit.tenant_id,
                    period=audit.period,
                    rule_id=GapRuleId.UNATTRIBUTED_STORE_SALE,
                    severity=GapSeverity.LOW,
                    counterparty_id=sale.store_id,
                    counterparty_name=f"Store {sale.store_id}",
                    amount_cents=sale.net_revenue_cents,
                    currency="EUR",
                    subject_id=sale.sale_id,
                    summary=f"Store sale {sale.sale_id} ({sale.net_revenue_cents}c) has no seller attribution.",
                )
            )

    # 21. stale_fx_quote_on_payout
    for payout_id in audit.stale_fx_payout_ids:
        gaps.append(
            CompletenessGap(
                gap_id=f"gap-{audit.tenant_id}-fx-{payout_id}",
                tenant_id=audit.tenant_id,
                period=audit.period,
                rule_id=GapRuleId.STALE_FX_QUOTE_ON_PAYOUT,
                severity=GapSeverity.HIGH,
                counterparty_id=payout_id,
                counterparty_name="FX Treasury Desk",
                amount_cents=50_000,
                currency="USD",
                subject_id=payout_id,
                summary=f"Cross-currency payout {payout_id} references an expired FX quote lock.",
            )
        )

    # 22. self_approval_attempt_detected
    for attempt_id in audit.self_approval_attempt_ids:
        gaps.append(
            CompletenessGap(
                gap_id=f"gap-{audit.tenant_id}-4eyes-{attempt_id}",
                tenant_id=audit.tenant_id,
                period=audit.period,
                rule_id=GapRuleId.SELF_APPROVAL_ATTEMPT_DETECTED,
                severity=GapSeverity.CRITICAL,
                counterparty_id=attempt_id,
                counterparty_name="Internal Governance Guard",
                amount_cents=100_000,
                currency="EUR",
                subject_id=attempt_id,
                summary=f"Four-eyes violation blocked on {attempt_id}: submitter attempted self-approval.",
            )
        )

    # 23. inter_store_imbalance
    if audit.inter_store_net_imbalance_cents != 0:
        diff = abs(audit.inter_store_net_imbalance_cents)
        gaps.append(
            CompletenessGap(
                gap_id=f"gap-{audit.tenant_id}-interstore-{audit.period}",
                tenant_id=audit.tenant_id,
                period=audit.period,
                rule_id=GapRuleId.INTER_STORE_IMBALANCE,
                severity=GapSeverity.HIGH,
                counterparty_id="FRANCHISE_CLEARING",
                counterparty_name="Inter-Store Clearing Account",
                amount_cents=diff,
                currency="EUR",
                subject_id=f"clearing-{audit.period}",
                summary=f"Inter-store franchise clearing entries fail to net to zero by {diff}c.",
            )
        )

    return tuple(sorted(gaps, key=lambda g: (g.rule_id.value, g.gap_id)))
