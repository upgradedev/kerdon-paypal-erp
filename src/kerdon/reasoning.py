"""M6: Deterministic Gap Reasoner Floor for all 24 Completeness and Anomaly Rules."""
from __future__ import annotations

from dataclasses import dataclass

from .completeness import CompletenessGap, GapRuleId


@dataclass(frozen=True)
class GapReasoning:
    """Structured root-cause hypothesis and corrective action for a CompletenessGap."""

    gap_id: str
    rule_id: GapRuleId
    likely_cause: str
    suggested_action: str
    confidence_bps: int
    recommended_doc_type: str
    source: str = "deterministic-floor"


_RULE_PLAYBOOK: dict[GapRuleId, tuple[str, str, int, str]] = {
    GapRuleId.PAYMENT_WITHOUT_DOCUMENT: (
        "Bank debit cleared before the supplier emailed or uploaded the corresponding tax invoice.",
        "Dispatch an automated Supplier Document Request citing the exact bank debit date and amount.",
        9200,
        "DOCUMENT_REQUEST",
    ),
    GapRuleId.INVOICE_UNPAID: (
        "Customer or supplier invoice passed its contractual due date without a matched bank movement.",
        "Issue a polite Payment Reminder with invoice reference and outstanding balance.",
        9100,
        "PAYMENT_REMINDER",
    ),
    GapRuleId.AMOUNT_MISMATCH: (
        "Partial payment, bank wire fee deduction, or unrecorded credit note caused settlement variance.",
        "Request a remittance breakdown or credit note from the counterparty for the residual cents.",
        8800,
        "DOCUMENT_REQUEST",
    ),
    GapRuleId.SETTLEMENT_NOT_INVOICED: (
        "Principal sent the monthly commission settlement sheet, but our outbound commission invoice has not been issued.",
        "Auto-draft the outbound Sales Invoice matching the principal settlement net and VAT amounts.",
        9600,
        "INVOICE",
    ),
    GapRuleId.SETTLEMENT_UNRECEIVED: (
        "Outbound commission invoice was issued against the principal settlement, but funds have not arrived.",
        "Send a Payment Reminder to the principal treasury desk referencing the settlement ID.",
        8900,
        "PAYMENT_REMINDER",
    ),
    GapRuleId.UNINVOICED_CLIENT_DEPOSIT: (
        "Advance deposit was collected on a client booking without issuing the corresponding advance or final tax invoice.",
        "Draft the outbound customer invoice applying the recorded advance deposit.",
        9300,
        "INVOICE",
    ),
    GapRuleId.MISSING_DOCUMENT_FAMILY: (
        "Recurring monthly vendor bill (rent, utilities, or telecom) present in prior periods has not arrived this month.",
        "Send a proactive Supplier Document Request so month-endOPEX is not understated.",
        8600,
        "DOCUMENT_REQUEST",
    ),
    GapRuleId.DUPLICATE_PAYMENT: (
        "Two identical bank debits to the same vendor executed within a 7-day window.",
        "Freeze pending payouts to this vendor and send a refund or credit-offset demand.",
        9500,
        "DOCUMENT_REQUEST",
    ),
    GapRuleId.AMOUNT_OUTLIER: (
        "Invoice gross amount exceeds 5x the vendor's historical median bill.",
        "Hold payout approval and request itemized line-item verification from the supplier.",
        8700,
        "DOCUMENT_REQUEST",
    ),
    GapRuleId.VAT_INCONSISTENCY: (
        "Document net plus VAT does not equal gross or uses a non-statutory VAT rate outside 0/6/13/24%.",
        "Reject ledger posting and request a corrected tax invoice from the issuer.",
        9800,
        "DOCUMENT_REQUEST",
    ),
    GapRuleId.UNLINKED_CREDIT_NOTE: (
        "Credit note arrived without referencing a valid original invoice ID in the Document Register.",
        "Link the credit note to its parent invoice and invalidate any stale payout approval on that vendor.",
        9000,
        "DOCUMENT_REQUEST",
    ),
    GapRuleId.COMMISSION_PAYOUT_MISMATCH: (
        "Payroll commission bonus line differs from the Four-Eyes approved MonthlyCommissionCase total.",
        "Reconcile the SellerStatement delta before releasing the payroll bank batch.",
        9400,
        "PROACTIVE_DIGEST",
    ),
    GapRuleId.RESERVE_FLOOR_BREACH: (
        "Proposed disbursement or cash drawdown drops the currency pocket below its configured reserve floor.",
        "Block disbursement execution and stage a treasury funding transfer or installment schedule.",
        9900,
        "PROACTIVE_DIGEST",
    ),
    GapRuleId.PAYROLL_MISSING_APD: (
        "Monthly payroll register was ingested without the companion APD social-security return.",
        "Request the APD filing from the payroll bureau so employer contributions are booked.",
        9500,
        "DOCUMENT_REQUEST",
    ),
    GapRuleId.PAYROLL_MISSING_FMY: (
        "Monthly payroll register was ingested without the companion FMY withheld income-tax return.",
        "Request the FMY filing from the payroll bureau to complete 3-document workforce fusion.",
        9500,
        "DOCUMENT_REQUEST",
    ),
    GapRuleId.PAYROLL_NET_TRANSFER_MISMATCH: (
        "Executed bank salary transfers do not equal the payroll register net payable total.",
        "Inspect unpaid employee lines or off-cycle advances in the Month-End Digest.",
        9100,
        "PROACTIVE_DIGEST",
    ),
    GapRuleId.EINVOICE_MARK_MISSING: (
        "Domestic tax document was recorded without a statutory e-invoicing MARK/UID transmission token.",
        "Request or transmit the e-invoice MARK before locking the VAT return.",
        8900,
        "DOCUMENT_REQUEST",
    ),
    GapRuleId.HTML_BODY_INVOICE_BLOCKED: (
        "Counterparty sent figures inside an HTML email body table without an official PDF/XML tax invoice.",
        "Keep the HTML table as commission/sales evidence and request the official tax invoice attachment.",
        9700,
        "DOCUMENT_REQUEST",
    ),
    GapRuleId.UNATTRIBUTED_STORE_SALE: (
        "Store POS sale was recorded without an approved salesperson attribution.",
        "Prompt the Store Manager to confirm seller attribution before closing the monthly commission case.",
        8500,
        "PROACTIVE_DIGEST",
    ),
    GapRuleId.CLAWBACK_UNAPPLIED: (
        "Customer booking was cancelled after initial sale without recording a seller commission clawback.",
        "Apply the deterministic clawback adjustment to the seller's current MonthlyCommissionCase.",
        9300,
        "PROACTIVE_DIGEST",
    ),
    GapRuleId.STALE_FX_QUOTE_ON_PAYOUT: (
        "Cross-currency supplier payout references an FX rate lock whose TTL has expired.",
        "Refresh the FX quote lock and re-bind the payout approval digest.",
        9600,
        "PROACTIVE_DIGEST",
    ),
    GapRuleId.SELF_APPROVAL_ATTEMPT_DETECTED: (
        "Same actor attempted to both submit and approve a governed commission case or payout.",
        "Route the case to a second authorized MSP FinOps Director or Client Owner for Four-Eyes sign-off.",
        9900,
        "PROACTIVE_DIGEST",
    ),
    GapRuleId.INTER_STORE_IMBALANCE: (
        "Franchise inter-store clearing legs do not net to zero across parent and child locations.",
        "Generate balancing inter-store journal lines in the Month-End Digest.",
        9200,
        "PROACTIVE_DIGEST",
    ),
    GapRuleId.BOOKING_BALANCE_OVERDUE: (
        "Delivered customer booking still carries an unpaid balance past the agreed delivery date.",
        "Issue an outbound Payment Reminder or final balance Invoice to the customer.",
        9000,
        "PAYMENT_REMINDER",
    ),
}


def reason_over_gap(gap: CompletenessGap) -> GapReasoning:
    """Produce a deterministic root-cause hypothesis and corrective action for a gap."""
    cause, action, confidence_bps, doc_type = _RULE_PLAYBOOK[gap.rule_id]
    return GapReasoning(
        gap_id=gap.gap_id,
        rule_id=gap.rule_id,
        likely_cause=cause,
        suggested_action=action,
        confidence_bps=confidence_bps,
        recommended_doc_type=doc_type,
        source="deterministic-floor",
    )


def reason_over_all_gaps(
    gaps: tuple[CompletenessGap, ...]
) -> tuple[GapReasoning, ...]:
    """Run deterministic root-cause reasoning across a tuple of gaps."""
    return tuple(reason_over_gap(g) for g in gaps)
