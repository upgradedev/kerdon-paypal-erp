"""Kerdon Superset Domain: Authority Supersession, Plan Diff Simulator, Seller Privacy & Disputes, Event Allocations, Counterparty Drill-Down, and Invite/Subscription Governance."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum, Enum
import hashlib
from typing import Any

from .auth import Role
from .commissions import (
    AttributionStatus,
    ClawbackEvent,
    CommissionPlanVersion,
    SellerStatement,
    evaluate_seller_statement,
)
from .demo_fixtures import TenantMiniErpState


class QuantityState(str, Enum):
    """Truthful quantity classification preventing silent zero distortion (kerdon-api)."""

    KNOWN = "known"
    LEGACY_AMBIGUOUS = "legacy_ambiguous"
    INVALID = "invalid"


@dataclass(frozen=True)
class TypedQuantity:
    """Explicit quantity wrapper separating verified zero from missing/ambiguous legacy zero."""

    state: QuantityState
    value: int | None
    legacy_raw_value: int | None = None


def parse_typed_quantity(raw: Any, *, zero_is_verified: bool = False) -> TypedQuantity:
    """Parse raw integer quantity without silently treating ambiguous 0 as verified 0."""
    if raw is None or isinstance(raw, bool):
        return TypedQuantity(state=QuantityState.LEGACY_AMBIGUOUS, value=None, legacy_raw_value=None)
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return TypedQuantity(state=QuantityState.INVALID, value=None, legacy_raw_value=None)
    if val < 0:
        return TypedQuantity(state=QuantityState.INVALID, value=None, legacy_raw_value=val)
    if val == 0 and not zero_is_verified:
        return TypedQuantity(state=QuantityState.LEGACY_AMBIGUOUS, value=None, legacy_raw_value=0)
    return TypedQuantity(state=QuantityState.KNOWN, value=val, legacy_raw_value=val)


class AuthoritySourceRank(IntEnum):
    """Authority hierarchy for commission and settlement facts (WS2)."""

    INFERENCE = 10
    EXERCISE = 20
    INTERIM_SNAPSHOT = 30
    CORRECTED_REPORT = 40
    OFFICIAL_SETTLEMENT = 50


@dataclass(frozen=True)
class SettlementRevisionInput:
    """Candidate settlement snapshot or official settlement report for a period."""

    revision_id: str
    tenant_id: str
    period: str
    principal_name: str
    authority_rank: AuthoritySourceRank
    captured_date: str
    reward_net_cents: int
    weighted_attainment_pct: float | None
    tnps_score: int | None
    source_sha256: str
    tnps_note_conflict: bool = False


@dataclass(frozen=True)
class FactConflict:
    """Surfaced contradiction between settlement sources requiring human review."""

    conflict_id: str
    code: str
    severity: str
    field_name: str
    winning_revision_id: str
    superseded_revision_id: str
    winning_value: str
    conflicting_value: str
    explanation: str


@dataclass(frozen=True)
class SupersessionResult:
    """Authoritative resolution of interim vs official settlement revisions."""

    period: str
    principal_name: str
    winning_revision: SettlementRevisionInput
    superseded_revision_ids: tuple[str, ...]
    conflicts: tuple[FactConflict, ...]
    finality_status: str


def reconcile_settlement_revisions(
    revisions: tuple[SettlementRevisionInput, ...]
) -> SupersessionResult:
    """Rank settlement revisions by authority, supersede interim snapshots, and emit FactConflicts."""
    if not revisions:
        raise ValueError("revisions cannot be empty")
    ordered = sorted(
        revisions,
        key=lambda r: (int(r.authority_rank), r.captured_date, r.revision_id),
        reverse=True,
    )
    winner = ordered[0]
    superseded = tuple(r.revision_id for r in ordered[1:])
    conflicts: list[FactConflict] = []

    if winner.tnps_note_conflict or winner.tnps_score is None:
        conflicts.append(
            FactConflict(
                conflict_id=f"conf-tnps-{winner.revision_id}",
                code="TNPS_SOURCE_NOTE_CONFLICT",
                severity="warning",
                field_name="tnps_score",
                winning_revision_id=winner.revision_id,
                superseded_revision_id=superseded[0] if superseded else winner.revision_id,
                winning_value=str(winner.tnps_score) if winner.tnps_score is not None else "missing_not_zero",
                conflicting_value="0_or_note_override",
                explanation="Missing or note-overridden tNPS is preserved as non-zero unknown rather than 0.",
            )
        )

    for older in ordered[1:]:
        if older.reward_net_cents != winner.reward_net_cents:
            conflicts.append(
                FactConflict(
                    conflict_id=f"conf-reward-{winner.revision_id}-{older.revision_id}",
                    code="INTERIM_SUPERSEDED_BY_OFFICIAL",
                    severity="info",
                    field_name="reward_net_cents",
                    winning_revision_id=winner.revision_id,
                    superseded_revision_id=older.revision_id,
                    winning_value=str(winner.reward_net_cents),
                    conflicting_value=str(older.reward_net_cents),
                    explanation=(
                        f"{winner.authority_rank.name} ({winner.captured_date}) supersedes "
                        f"{older.authority_rank.name} ({older.captured_date})."
                    ),
                )
            )
        if (
            older.tnps_score is not None
            and winner.tnps_score is not None
            and older.tnps_score != winner.tnps_score
        ):
            conflicts.append(
                FactConflict(
                    conflict_id=f"conf-tnps-delta-{winner.revision_id}-{older.revision_id}",
                    code="TNPS_REVISION_CONFLICT",
                    severity="warning",
                    field_name="tnps_score",
                    winning_revision_id=winner.revision_id,
                    superseded_revision_id=older.revision_id,
                    winning_value=str(winner.tnps_score),
                    conflicting_value=str(older.tnps_score),
                    explanation="Interim and official settlement reports disagree on store tNPS score.",
                )
            )

    finality = (
        "official"
        if winner.authority_rank >= AuthoritySourceRank.OFFICIAL_SETTLEMENT
        else "interim_or_derived"
    )
    return SupersessionResult(
        period=winner.period,
        principal_name=winner.principal_name,
        winning_revision=winner,
        superseded_revision_ids=superseded,
        conflicts=tuple(conflicts),
        finality_status=finality,
    )


@dataclass(frozen=True)
class CaseBlocker:
    """Explicit readiness blocker preventing fabricated seller splits."""

    code: str
    severity: str
    action: str
    message: str


def evaluate_truthful_commission_blockers(
    state: TenantMiniErpState,
    *,
    has_store_targets: bool = True,
    has_published_plan: bool = True,
) -> tuple[CaseBlocker, ...]:
    """Build truthful commission blockers without fabricated equal-split fallbacks."""
    blockers: list[CaseBlocker] = []
    if not has_store_targets:
        blockers.append(
            CaseBlocker(
                code="STORE_TARGETS_MISSING",
                severity="blocker",
                action="add_store_targets",
                message="Store targets and attainment metrics are not yet configured for this period.",
            )
        )
    if not state.settlements:
        blockers.append(
            CaseBlocker(
                code="OFFICIAL_SETTLEMENT_MISSING",
                severity="blocker",
                action="capture_official_settlement",
                message="No official bank or payment settlement has been recorded for the period.",
            )
        )
    approved_attrs = [
        a for a in state.attributions if a.status == AttributionStatus.APPROVED
    ]
    if not approved_attrs:
        blockers.append(
            CaseBlocker(
                code="SELLER_SALES_SOURCE_UNAVAILABLE",
                severity="blocker",
                action="connect_seller_sales_source",
                message="Sales data is only available at the store level. Equal-split attribution is prohibited.",
            )
        )
    elif len(approved_attrs) < len(state.sales_events):
        blockers.append(
            CaseBlocker(
                code="UNATTRIBUTED_STORE_SALES_PENDING",
                severity="warning",
                action="attribute_remaining_sales",
                message="Store sales events exist without an approved seller attribution.",
            )
        )
    if not has_published_plan:
        blockers.append(
            CaseBlocker(
                code="SELLER_COMMISSION_PLAN_MISSING",
                severity="blocker",
                action="configure_seller_commission_plan",
                message="No seller commission plan has been published for this period.",
            )
        )
    return tuple(blockers)


@dataclass(frozen=True)
class SellerPlanDiffRow:
    """Per-seller comparison between baseline and candidate commission plan versions."""

    seller_id: str
    approved_sales_cents: int
    baseline_net_cents: int
    candidate_net_cents: int
    delta_cents: int
    baseline_gate_passed: bool
    candidate_gate_passed: bool


@dataclass(frozen=True)
class PlanDiffComparison:
    """What-If simulation comparing two CommissionPlanVersion configurations."""

    tenant_id: str
    period: str
    baseline_plan_id: str
    baseline_version: int
    baseline_mode: str
    candidate_plan_id: str
    candidate_version: int
    candidate_mode: str
    baseline_total_cents: int
    candidate_total_cents: int
    total_delta_cents: int
    seller_rows: tuple[SellerPlanDiffRow, ...]


def simulate_plan_version_diff(
    state: TenantMiniErpState,
    candidate_plan: CommissionPlanVersion,
    *,
    clawbacks: tuple[ClawbackEvent, ...] = (),
) -> PlanDiffComparison:
    """Simulate a candidate CommissionPlanVersion against the active plan across all sellers."""
    rows: list[SellerPlanDiffRow] = []
    for base_st in state.commission_case.statements:
        cand_st = evaluate_seller_statement(
            seller_id=base_st.seller_id,
            period=base_st.period,
            plan=candidate_plan,
            sales_events=state.sales_events,
            attributions=state.attributions,
            clawbacks=clawbacks,
            tnps_score=base_st.tnps_score,
            compliance_bps=base_st.compliance_bps,
        )
        rows.append(
            SellerPlanDiffRow(
                seller_id=base_st.seller_id,
                approved_sales_cents=base_st.approved_sales_cents,
                baseline_net_cents=base_st.net_payable_commission_cents,
                candidate_net_cents=cand_st.net_payable_commission_cents,
                delta_cents=cand_st.net_payable_commission_cents - base_st.net_payable_commission_cents,
                baseline_gate_passed=base_st.gate_passed,
                candidate_gate_passed=cand_st.gate_passed,
            )
        )
    base_tot = sum(r.baseline_net_cents for r in rows)
    cand_tot = sum(r.candidate_net_cents for r in rows)
    return PlanDiffComparison(
        tenant_id=state.tenant.tenant_id,
        period=state.commission_case.period,
        baseline_plan_id=state.commission_plan.plan_id,
        baseline_version=state.commission_plan.version,
        baseline_mode=state.commission_plan.mode.value,
        candidate_plan_id=candidate_plan.plan_id,
        candidate_version=candidate_plan.version,
        candidate_mode=candidate_plan.mode.value,
        baseline_total_cents=base_tot,
        candidate_total_cents=cand_tot,
        total_delta_cents=cand_tot - base_tot,
        seller_rows=tuple(rows),
    )


@dataclass(frozen=True)
class SellerDisputeNote:
    """Immutable dispute or comment submitted by a seller on their own commission statement."""

    dispute_id: str
    tenant_id: str
    seller_id: str
    period: str
    sale_or_line_ref: str
    reason_text: str
    status: str
    created_at_epoch: int


@dataclass(frozen=True)
class SellerPrivateStatementView:
    """Privacy-isolated view for a single seller (redacts all other employees and payroll)."""

    tenant_id: str
    seller_id: str
    period: str
    statement: SellerStatement
    own_sales_events: tuple[Any, ...]
    disputes: tuple[SellerDisputeNote, ...]
    redacted_other_sellers_count: int
    payroll_register_redacted: bool


def build_seller_private_statement(
    state: TenantMiniErpState,
    seller_id: str,
    disputes: tuple[SellerDisputeNote, ...] = (),
) -> SellerPrivateStatementView:
    """Return strictly one seller's statement and sales events, redacting all other staff."""
    matching = [s for s in state.commission_case.statements if s.seller_id == seller_id]
    if not matching:
        raise KeyError(f"Seller statement not found for seller_id={seller_id}")
    target_st = matching[0]
    own_sales = tuple(
        s for s in state.sales_events if s.sale_id in set(target_st.attributed_sale_ids)
    )
    own_disputes = tuple(
        d
        for d in disputes
        if d.tenant_id == state.tenant.tenant_id and d.seller_id == seller_id
    )
    other_count = max(0, len(state.commission_case.statements) - 1)
    return SellerPrivateStatementView(
        tenant_id=state.tenant.tenant_id,
        seller_id=seller_id,
        period=target_st.period,
        statement=target_st,
        own_sales_events=own_sales,
        disputes=own_disputes,
        redacted_other_sellers_count=other_count,
        payroll_register_redacted=True,
    )


@dataclass(frozen=True)
class PaymentAllocation:
    """Event-linker allocation mapping partial or multi-invoice payments to documents."""

    allocation_id: str
    tenant_id: str
    document_id: str
    counterparty_id: str
    counterparty_name: str
    direction: str
    invoice_gross_cents: int
    credit_note_offset_cents: int
    allocated_paid_cents: int
    remaining_open_cents: int
    allocation_kind: str
    confidence_bps: int


def allocate_payments_to_invoices(
    state: TenantMiniErpState,
) -> tuple[PaymentAllocation, ...]:
    """Compute payment & credit-note allocations across all registered invoices."""
    credit_by_inv: dict[str, int] = {}
    for cn in state.crm.credit_notes.values():
        if cn.referenced_invoice_id:
            credit_by_inv[cn.referenced_invoice_id] = (
                credit_by_inv.get(cn.referenced_invoice_id, 0) + cn.gross_cents
            )

    allocations: list[PaymentAllocation] = []
    for doc in state.crm.documents.values():
        cn_offset = credit_by_inv.get(doc.document_id, 0)
        effective_due = max(0, doc.gross_cents - cn_offset)
        allocated = min(doc.paid_cents, effective_due)
        remaining = max(0, effective_due - allocated)
        if allocated == 0 and cn_offset == 0:
            kind = "UNPAID"
        elif remaining == 0 and cn_offset > 0:
            kind = "SETTLED_WITH_CREDIT_NOTE"
        elif remaining == 0:
            kind = "FULL_PAYMENT"
        else:
            kind = "PARTIAL_ALLOCATION"
        allocations.append(
            PaymentAllocation(
                allocation_id=f"alloc-{doc.document_id}",
                tenant_id=state.tenant.tenant_id,
                document_id=doc.document_id,
                counterparty_id=doc.counterparty_id,
                counterparty_name=doc.counterparty_name,
                direction=doc.direction.value,
                invoice_gross_cents=doc.gross_cents,
                credit_note_offset_cents=cn_offset,
                allocated_paid_cents=allocated,
                remaining_open_cents=remaining,
                allocation_kind=kind,
                confidence_bps=9800 if remaining == 0 else 9400,
            )
        )
    return tuple(allocations)


@dataclass(frozen=True)
class CounterpartyCompletenessRollup:
    """Aggregated completeness gaps, open balance, and dispute state per counterparty."""

    counterparty_id: str
    legal_name: str
    role: str
    document_count: int
    gross_invoiced_cents: int
    allocated_paid_cents: int
    credit_note_cents: int
    remaining_open_cents: int
    open_finding_count: int
    finding_exposure_cents: int
    finding_rule_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]


def rollup_completeness_by_counterparty(
    state: TenantMiniErpState,
) -> tuple[CounterpartyCompletenessRollup, ...]:
    """Aggregate completeness findings and open balances per Customer and per Supplier."""
    allocations = allocate_payments_to_invoices(state)
    alloc_by_cp: dict[str, list[PaymentAllocation]] = {}
    for al in allocations:
        alloc_by_cp.setdefault(al.counterparty_id, []).append(al)

    gaps_by_cp: dict[str, list[Any]] = {}
    for g in state.gaps:
        gaps_by_cp.setdefault(g.counterparty_id, []).append(g)

    rollups: list[CounterpartyCompletenessRollup] = []
    for cust in state.crm.customers.values():
        c_allocs = alloc_by_cp.get(cust.customer_id, [])
        c_gaps = gaps_by_cp.get(cust.customer_id, [])
        rollups.append(
            CounterpartyCompletenessRollup(
                counterparty_id=cust.customer_id,
                legal_name=cust.legal_name,
                role="CUSTOMER",
                document_count=len(c_allocs),
                gross_invoiced_cents=sum(a.invoice_gross_cents for a in c_allocs),
                allocated_paid_cents=sum(a.allocated_paid_cents for a in c_allocs),
                credit_note_cents=sum(a.credit_note_offset_cents for a in c_allocs),
                remaining_open_cents=sum(a.remaining_open_cents for a in c_allocs),
                open_finding_count=len(c_gaps),
                finding_exposure_cents=sum(g.amount_cents for g in c_gaps),
                finding_rule_ids=tuple(g.rule_id.value for g in c_gaps),
                finding_ids=tuple(g.gap_id for g in c_gaps),
            )
        )
    for sup in state.crm.suppliers.values():
        s_allocs = alloc_by_cp.get(sup.supplier_id, [])
        s_gaps = gaps_by_cp.get(sup.supplier_id, [])
        rollups.append(
            CounterpartyCompletenessRollup(
                counterparty_id=sup.supplier_id,
                legal_name=sup.legal_name,
                role="SUPPLIER",
                document_count=len(s_allocs),
                gross_invoiced_cents=sum(a.invoice_gross_cents for a in s_allocs),
                allocated_paid_cents=sum(a.allocated_paid_cents for a in s_allocs),
                credit_note_cents=sum(a.credit_note_offset_cents for a in s_allocs),
                remaining_open_cents=sum(a.remaining_open_cents for a in s_allocs),
                open_finding_count=len(s_gaps),
                finding_exposure_cents=sum(g.amount_cents for g in s_gaps),
                finding_rule_ids=tuple(g.rule_id.value for g in s_gaps),
                finding_ids=tuple(g.gap_id for g in s_gaps),
            )
        )
    return tuple(rollups)


@dataclass(frozen=True)
class WorkspaceInvite:
    """Invite-claim onboarding record for team members and external accountants (0014_invite_claim)."""

    invite_id: str
    tenant_id: str
    email: str
    role: Role
    invited_by: str
    status: str
    invite_token_sha256: str
    claimed_by_actor_id: str = ""


def create_workspace_invite(
    *,
    tenant_id: str,
    email: str,
    role: Role,
    invited_by: str,
    now_epoch: int,
) -> WorkspaceInvite:
    """Create a pending workspace invite with a deterministic SHA-256 claim token."""
    clean_email = email.strip().lower()
    if "@" not in clean_email:
        raise ValueError("Invite email must be a valid email address")
    token_hash = hashlib.sha256(
        f"{tenant_id}:{clean_email}:{role.value}:{now_epoch}".encode("utf-8")
    ).hexdigest()
    return WorkspaceInvite(
        invite_id=f"inv-{token_hash[:10]}",
        tenant_id=tenant_id,
        email=clean_email,
        role=role,
        invited_by=invited_by,
        status="PENDING",
        invite_token_sha256=token_hash,
    )


def claim_workspace_invite(
    invite: WorkspaceInvite, *, actor_id: str
) -> WorkspaceInvite:
    """Transition a PENDING workspace invite to CLAIMED."""
    if invite.status == "CLAIMED":
        return invite
    return replace(invite, status="CLAIMED", claimed_by_actor_id=actor_id)


PLAN_ENTITLEMENTS: dict[str, tuple[str, ...]] = {
    "entry": (
        "email_inbox_capture",
        "double_entry_ledger",
        "completeness_scan_24",
    ),
    "standard": (
        "email_inbox_capture",
        "double_entry_ledger",
        "completeness_scan_24",
        "seller_commissions_engine",
        "outbound_pdf_docgen",
        "grounded_cfo_query",
        "multi_currency_treasury",
    ),
    "pro": (
        "email_inbox_capture",
        "double_entry_ledger",
        "completeness_scan_24",
        "seller_commissions_engine",
        "outbound_pdf_docgen",
        "grounded_cfo_query",
        "multi_currency_treasury",
        "msp_fleet_control_plane",
        "compounding_agentcore_memory",
        "six_reader_strands_release_gate",
    ),
}


def resolve_plan_entitlements(plan_code: str) -> tuple[str, ...]:
    """Return active capability entitlements for a subscription plan code."""
    key = (plan_code or "standard").strip().lower()
    return PLAN_ENTITLEMENTS.get(key, PLAN_ENTITLEMENTS["standard"])
