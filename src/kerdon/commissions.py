"""M5: Sales Performance, Principal Settlements, and Deterministic Seller Commissions."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum


class AttributionStatus(str, Enum):
    """Lifecycle state of attributing a store sale to a seller."""

    UNATTRIBUTED = "UNATTRIBUTED"
    SUGGESTED = "SUGGESTED"
    APPROVED = "APPROVED"


class TierMode(str, Enum):
    """How commission tiers apply across cumulative monthly sales volume."""

    PROGRESSIVE = "PROGRESSIVE"
    RETROACTIVE = "RETROACTIVE"


class CommissionCaseStatus(str, Enum):
    """Governance state of a monthly seller commission calculation case."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"


class SelfApprovalError(PermissionError):
    """Raised when the same actor attempts to both submit and approve a case."""


@dataclass(frozen=True)
class PrincipalSettlement:
    """Non-posting principal commission statement requiring an invoice and bank receipt."""

    settlement_id: str
    tenant_id: str
    period: str
    principal_name: str
    principal_tax_id: str
    agreed_net_cents: int
    vat_cents: int
    gross_cents: int
    source_sha256: str
    linked_sales_invoice_id: str = ""
    linked_bank_receipt_id: str = ""

    @property
    def is_invoiced(self) -> bool:
        return bool(self.linked_sales_invoice_id.strip())

    @property
    def is_collected(self) -> bool:
        return bool(self.linked_bank_receipt_id.strip())


@dataclass(frozen=True)
class SalesEvent:
    """Commercial sale event at a store location before or during seller attribution."""

    sale_id: str
    tenant_id: str
    store_id: str
    period: str
    occurred_date: str
    net_revenue_cents: int
    product_family: str
    source_sha256: str


@dataclass(frozen=True)
class SalesAttribution:
    """Append-only record binding a SalesEvent to a SellerProfile."""

    attribution_id: str
    sale_id: str
    tenant_id: str
    seller_id: str
    status: AttributionStatus
    share_bps: int = 10_000
    evidence_note: str = ""

    def __post_init__(self) -> None:
        if not (0 <= self.share_bps <= 10_000):
            raise ValueError("share_bps must be between 0 and 10000")


@dataclass(frozen=True)
class CommissionTier:
    """Single bracket in a commission plan (rate_bps is basis points, e.g. 500 = 5.00%)."""

    lower_bound_cents: int
    upper_bound_cents: int | None
    rate_bps: int


@dataclass(frozen=True)
class CommissionGate:
    """Eligibility gate that a seller must clear to earn tier commission."""

    min_tnps_score: int = 0
    min_compliance_bps: int = 0


@dataclass(frozen=True)
class ClawbackEvent:
    """Deduction for a cancelled or refunded commissioned sale within the clawback window."""

    clawback_id: str
    tenant_id: str
    seller_id: str
    period: str
    original_sale_id: str
    clawback_commission_cents: int
    reason: str


@dataclass(frozen=True)
class CommissionPlanVersion:
    """Effective-dated deterministic commission plan configuration."""

    plan_id: str
    version: int
    tenant_id: str
    effective_from_period: str
    effective_to_period: str | None
    mode: TierMode
    tiers: tuple[CommissionTier, ...]
    gate: CommissionGate = CommissionGate()
    floor_cents: int = 0
    cap_cents: int | None = None

    def is_effective_for(self, period: str) -> bool:
        if period < self.effective_from_period:
            return False
        if self.effective_to_period is not None and period > self.effective_to_period:
            return False
        return True


@dataclass(frozen=True)
class SellerStatement:
    """Auditable breakdown of a single seller's monthly commission calculation."""

    seller_id: str
    period: str
    plan_id: str
    plan_version: int
    approved_sales_cents: int
    tnps_score: int
    compliance_bps: int
    gate_passed: bool
    gross_tier_commission_cents: int
    clawback_deduction_cents: int
    net_payable_commission_cents: int
    attributed_sale_ids: tuple[str, ...]


@dataclass(frozen=True)
class MonthlyCommissionCase:
    """Four-eyes governed monthly commission run for a store or tenant."""

    case_id: str
    tenant_id: str
    period: str
    plan_id: str
    plan_version: int
    statements: tuple[SellerStatement, ...]
    status: CommissionCaseStatus
    submitted_by: str = ""
    approved_by: str = ""

    @property
    def total_payable_cents(self) -> int:
        return sum(st.net_payable_commission_cents for st in self.statements)


def _bps_mul(amount_cents: int, rate_bps: int) -> int:
    return int(
        (Decimal(amount_cents) * Decimal(rate_bps) / Decimal(10_000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def compute_tier_commission(
    sales_cents: int, plan: CommissionPlanVersion
) -> int:
    """Compute gross commission from tiers in deterministic integer cents."""
    if sales_cents <= 0 or not plan.tiers:
        return 0
    ordered = sorted(plan.tiers, key=lambda t: t.lower_bound_cents)
    if plan.mode == TierMode.RETROACTIVE:
        applicable_rate = 0
        for tier in ordered:
            if sales_cents > tier.lower_bound_cents:
                applicable_rate = tier.rate_bps
        return _bps_mul(sales_cents, applicable_rate)

    # PROGRESSIVE marginal bracket calculation
    total_commission = 0
    for tier in ordered:
        if sales_cents <= tier.lower_bound_cents:
            continue
        upper = (
            sales_cents
            if tier.upper_bound_cents is None
            else min(sales_cents, tier.upper_bound_cents)
        )
        taxable_slice = max(0, upper - tier.lower_bound_cents)
        total_commission += _bps_mul(taxable_slice, tier.rate_bps)
    return total_commission


def evaluate_seller_statement(
    *,
    seller_id: str,
    period: str,
    plan: CommissionPlanVersion,
    sales_events: tuple[SalesEvent, ...],
    attributions: tuple[SalesAttribution, ...],
    clawbacks: tuple[ClawbackEvent, ...],
    tnps_score: int,
    compliance_bps: int = 10_000,
) -> SellerStatement:
    """Compute a seller's statement from approved attributions only.

    Being on the payroll register never implies sales attribution; only
    APPROVED SalesAttribution records enter the commission base.
    """
    if not plan.is_effective_for(period):
        raise ValueError(
            f"Plan {plan.plan_id} v{plan.version} is not effective for period {period}"
        )
    sales_by_id = {s.sale_id: s for s in sales_events if s.period == period}
    approved_cents = 0
    matched_sale_ids: list[str] = []

    for attr in sorted(attributions, key=lambda a: a.attribution_id):
        if attr.seller_id != seller_id or attr.status != AttributionStatus.APPROVED:
            continue
        sale = sales_by_id.get(attr.sale_id)
        if sale is None:
            continue
        approved_cents += _bps_mul(sale.net_revenue_cents, attr.share_bps)
        matched_sale_ids.append(sale.sale_id)

    gate_passed = (
        tnps_score >= plan.gate.min_tnps_score
        and compliance_bps >= plan.gate.min_compliance_bps
    )
    gross_comm = (
        compute_tier_commission(approved_cents, plan) if gate_passed else 0
    )
    clawback_total = sum(
        cb.clawback_commission_cents
        for cb in clawbacks
        if cb.seller_id == seller_id and cb.period == period
    )
    after_clawback = max(plan.floor_cents, gross_comm - clawback_total)
    if plan.cap_cents is not None:
        net_payable = min(after_clawback, plan.cap_cents)
    else:
        net_payable = after_clawback

    return SellerStatement(
        seller_id=seller_id,
        period=period,
        plan_id=plan.plan_id,
        plan_version=plan.version,
        approved_sales_cents=approved_cents,
        tnps_score=tnps_score,
        compliance_bps=compliance_bps,
        gate_passed=gate_passed,
        gross_tier_commission_cents=gross_comm,
        clawback_deduction_cents=clawback_total,
        net_payable_commission_cents=net_payable,
        attributed_sale_ids=tuple(matched_sale_ids),
    )


def submit_commission_case(
    case: MonthlyCommissionCase, requester_id: str
) -> MonthlyCommissionCase:
    """Transition a commission case to SUBMITTED under a named requester."""
    if not requester_id.strip():
        raise ValueError("requester_id is required to submit a commission case")
    return MonthlyCommissionCase(
        case_id=case.case_id,
        tenant_id=case.tenant_id,
        period=case.period,
        plan_id=case.plan_id,
        plan_version=case.plan_version,
        statements=case.statements,
        status=CommissionCaseStatus.SUBMITTED,
        submitted_by=requester_id.strip(),
        approved_by="",
    )


def approve_commission_case(
    case: MonthlyCommissionCase, approver_id: str
) -> MonthlyCommissionCase:
    """Enforce Four-Eyes separation: approver_id must differ from submitted_by."""
    if case.status != CommissionCaseStatus.SUBMITTED:
        raise ValueError(
            f"Case {case.case_id} must be SUBMITTED before approval (got {case.status.value})"
        )
    clean_approver = approver_id.strip()
    if not clean_approver:
        raise ValueError("approver_id is required")
    if clean_approver == case.submitted_by:
        raise SelfApprovalError(
            f"Four-eyes violation on {case.case_id}: approver {clean_approver} == submitter"
        )
    return MonthlyCommissionCase(
        case_id=case.case_id,
        tenant_id=case.tenant_id,
        period=case.period,
        plan_id=case.plan_id,
        plan_version=case.plan_version,
        statements=case.statements,
        status=CommissionCaseStatus.APPROVED,
        submitted_by=case.submitted_by,
        approved_by=clean_approver,
    )


def reconcile_commission_to_payroll(
    case: MonthlyCommissionCase, payroll_commission_cents: int
) -> int:
    """Return signed difference (payroll_commission_cents - case.total_payable_cents)."""
    return payroll_commission_cents - case.total_payable_cents
