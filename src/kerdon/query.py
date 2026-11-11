"""M7: Grounded Natural-Language Query Engine over Deterministic Fact Sheets."""
from __future__ import annotations

from dataclasses import dataclass

from .commissions import MonthlyCommissionCase
from .completeness import CompletenessGap
from .docgen import format_eur
from .fiscal import VatPeriodSummary
from .ledger import MomTrend, PeriodSummary


@dataclass(frozen=True)
class FactSheet:
    """Immutable deterministic fact sheet grounding every natural-language answer."""

    tenant_id: str
    tenant_name: str
    period: str
    revenue_cents: int
    ebitda_cents: int
    net_income_cents: int
    workforce_cost_cents: int
    cash_balance_cents: int
    ar_balance_cents: int
    ap_balance_cents: int
    net_vat_payable_cents: int
    seller_commission_payable_cents: int
    ebitda_mom_delta_bps: int
    open_gap_count: int
    top_gap_summaries: tuple[str, ...]


@dataclass(frozen=True)
class GroundedQueryAnswer:
    """Answer citing exact deterministic facts and provenance metrics."""

    tenant_id: str
    period: str
    question: str
    answer_text: str
    cited_metrics: dict[str, int | str]
    source: str = "deterministic-factsheet"
    refused_out_of_scope: bool = False


def build_fact_sheet(
    *,
    tenant_name: str,
    pnl: PeriodSummary,
    mom_trend: MomTrend,
    vat_summary: VatPeriodSummary,
    commission_case: MonthlyCommissionCase | None,
    gaps: tuple[CompletenessGap, ...],
) -> FactSheet:
    """Construct the fixed deterministic fact sheet for a tenant and period."""
    comm_cents = (
        commission_case.total_payable_cents if commission_case is not None else 0
    )
    top_gaps = tuple(g.summary for g in gaps[:5])
    return FactSheet(
        tenant_id=pnl.tenant_id,
        tenant_name=tenant_name,
        period=pnl.period,
        revenue_cents=pnl.revenue_cents,
        ebitda_cents=pnl.ebitda_cents,
        net_income_cents=pnl.net_income_cents,
        workforce_cost_cents=pnl.workforce_cost_cents,
        cash_balance_cents=pnl.cash_balance_cents,
        ar_balance_cents=pnl.ar_balance_cents,
        ap_balance_cents=pnl.ap_balance_cents,
        net_vat_payable_cents=vat_summary.net_vat_payable_cents,
        seller_commission_payable_cents=comm_cents,
        ebitda_mom_delta_bps=mom_trend.ebitda_delta_bps,
        open_gap_count=len(gaps),
        top_gap_summaries=top_gaps,
    )


def answer_grounded_query(
    question: str, fact_sheet: FactSheet, narrator_override: str = ""
) -> GroundedQueryAnswer:
    """Answer a finance question strictly from the deterministic FactSheet."""
    q_low = question.lower().strip()
    out_of_scope_tokens = ("bitcoin", "crypto", "weather", "lottery", "election")
    if any(tok in q_low for tok in out_of_scope_tokens):
        return GroundedQueryAnswer(
            tenant_id=fact_sheet.tenant_id,
            period=fact_sheet.period,
            question=question,
            answer_text=(
                f"Refused: '{question}' is outside the deterministic FactSheet scope "
                f"for {fact_sheet.tenant_name} ({fact_sheet.period}). Ask about revenue, "
                f"EBITDA, cash, AR, AP, 3-doc workforce cost, VAT, seller commissions, or completeness gaps."
            ),
            cited_metrics={"period": fact_sheet.period},
            source="deterministic-factsheet-guard",
            refused_out_of_scope=True,
        )
    cited: dict[str, int | str] = {
        "period": fact_sheet.period,
        "revenue_cents": fact_sheet.revenue_cents,
        "ebitda_cents": fact_sheet.ebitda_cents,
        "cash_balance_cents": fact_sheet.cash_balance_cents,
        "open_gap_count": fact_sheet.open_gap_count,
    }

    if "commission" in q_low or "seller" in q_low or "bonus" in q_low:
        cited["seller_commission_payable_cents"] = (
            fact_sheet.seller_commission_payable_cents
        )
        base_answer = (
            f"For {fact_sheet.tenant_name} in {fact_sheet.period}, approved seller "
            f"commissions total {format_eur(fact_sheet.seller_commission_payable_cents)} "
            f"alongside workforce cost of {format_eur(fact_sheet.workforce_cost_cents)}."
        )
    elif "vat" in q_low or "tax" in q_low or "einvoice" in q_low:
        cited["net_vat_payable_cents"] = fact_sheet.net_vat_payable_cents
        base_answer = (
            f"For {fact_sheet.tenant_name} in {fact_sheet.period}, net VAT payable is "
            f"{format_eur(fact_sheet.net_vat_payable_cents)} across revenue of "
            f"{format_eur(fact_sheet.revenue_cents)}."
        )
    elif "gap" in q_low or "missing" in q_low or "anomaly" in q_low:
        top_txt = "; ".join(fact_sheet.top_gap_summaries[:2]) or "No open gaps."
        base_answer = (
            f"{fact_sheet.tenant_name} has {fact_sheet.open_gap_count} open completeness "
            f"or anomaly items in {fact_sheet.period}. Top items: {top_txt}"
        )
    elif "payroll" in q_low or "workforce" in q_low or "salary" in q_low:
        cited["workforce_cost_cents"] = fact_sheet.workforce_cost_cents
        base_answer = (
            f"True 3-document fused employer workforce cost for {fact_sheet.tenant_name} "
            f"in {fact_sheet.period} is {format_eur(fact_sheet.workforce_cost_cents)}."
        )
    elif "paypal" in q_low or "checkout" in q_low or "dispute" in q_low or "fee" in q_low:
        cited["ar_balance_cents"] = fact_sheet.ar_balance_cents
        cited["seller_commission_payable_cents"] = fact_sheet.seller_commission_payable_cents
        base_answer = (
            f"PayPal Agentic Commerce for {fact_sheet.tenant_name} ({fact_sheet.period}): "
            f"PayPal Orders v2 captures post balanced 3-line GL entries (1000_CASH + 6200_OPEX_FEES = 1100_AR), "
            f"PayPal Customer Disputes v1 assemble autonomous ERP evidence defense packets and hold seller "
            f"commissions ({format_eur(fact_sheet.seller_commission_payable_cents)} payable), and "
            f"open AR is {format_eur(fact_sheet.ar_balance_cents)} with cash at {format_eur(fact_sheet.cash_balance_cents)}."
        )
    else:
        base_answer = (
            f"{fact_sheet.tenant_name} ({fact_sheet.period}): revenue is "
            f"{format_eur(fact_sheet.revenue_cents)}, EBITDA is "
            f"{format_eur(fact_sheet.ebitda_cents)} ({fact_sheet.ebitda_mom_delta_bps} bps MoM), "
            f"cash balance is {format_eur(fact_sheet.cash_balance_cents)}, AR is "
            f"{format_eur(fact_sheet.ar_balance_cents)}, AP is "
            f"{format_eur(fact_sheet.ap_balance_cents)}, and {fact_sheet.open_gap_count} "
            f"completeness gaps remain open."
        )

    final_text = narrator_override.strip() or base_answer
    source = "strands-bedrock-grounded" if narrator_override.strip() else "deterministic-factsheet"
    return GroundedQueryAnswer(
        tenant_id=fact_sheet.tenant_id,
        period=fact_sheet.period,
        question=question,
        answer_text=final_text,
        cited_metrics=cited,
        source=source,
    )
