"""M4: Deterministic Double-Entry General Ledger, P&L, EBITDA, Cash, AR/AP, and MoM Trends."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AccountCode(str, Enum):
    """Standard chart of accounts for the Kerdon Mini-ERP double-entry ledger."""

    CASH_1000 = "1000_CASH"
    AR_1100 = "1100_ACCOUNTS_RECEIVABLE"
    VAT_INPUT_1400 = "1400_VAT_INPUT_RECEIVABLE"
    INTER_STORE_CLEAR_1900 = "1900_INTER_STORE_CLEARING"
    AP_2000 = "2000_ACCOUNTS_PAYABLE"
    CUSTOMER_DEPOSITS_2100 = "2100_CUSTOMER_ADVANCE_DEPOSITS"
    VAT_OUTPUT_2400 = "2400_VAT_OUTPUT_PAYABLE"
    PAYROLL_PAYABLE_2500 = "2500_NET_PAYROLL_PAYABLE"
    SOCIAL_SECURITY_PAYABLE_2510 = "2510_APD_SOCIAL_SECURITY_PAYABLE"
    WITHHELD_TAX_PAYABLE_2520 = "2520_FMY_WITHHELD_TAX_PAYABLE"
    REVENUE_SALES_4000 = "4000_SALES_REVENUE"
    REVENUE_COMMISSION_4100 = "4100_PRINCIPAL_COMMISSION_REVENUE"
    COGS_5000 = "5000_COST_OF_GOODS_SOLD"
    OPEX_WORKFORCE_6000 = "6000_WORKFORCE_EMPLOYER_COST"
    OPEX_COMMISSION_6050 = "6050_SELLER_COMMISSION_EXPENSE"
    OPEX_RENT_UTILITIES_6100 = "6100_RENT_AND_UTILITIES"
    OPEX_GENERAL_6200 = "6200_GENERAL_OPERATING_EXPENSE"
    DEPRECIATION_AMORTIZATION_6800 = "6800_DEPRECIATION_AMORTIZATION"
    INTEREST_AND_TAX_6900 = "6900_INTEREST_AND_INCOME_TAX"


class UnbalancedEntryError(ValueError):
    """Raised when a FinancialEvent violates the double-entry accounting invariant."""


@dataclass(frozen=True)
class LedgerLine:
    """Single debit or credit leg of a balanced FinancialEvent in integer cents."""

    account: AccountCode
    debit_cents: int = 0
    credit_cents: int = 0
    counterparty_id: str = ""
    store_id: str = ""
    memo: str = ""

    def __post_init__(self) -> None:
        if self.debit_cents < 0 or self.credit_cents < 0:
            raise UnbalancedEntryError("LedgerLine amounts must be non-negative cents")
        if (self.debit_cents == 0 and self.credit_cents == 0) or (
            self.debit_cents > 0 and self.credit_cents > 0
        ):
            raise UnbalancedEntryError(
                "LedgerLine must have either a positive debit_cents or credit_cents, not both"
            )


@dataclass(frozen=True)
class FinancialEvent:
    """Immutable balanced double-entry journal entry linked to source provenance."""

    event_id: str
    tenant_id: str
    period: str
    posted_date: str
    description: str
    source_document_id: str
    source_sha256: str
    lines: tuple[LedgerLine, ...]
    currency: str = "EUR"

    def __post_init__(self) -> None:
        if len(self.lines) < 2:
            raise UnbalancedEntryError(
                f"FinancialEvent {self.event_id} requires at least 2 ledger lines"
            )
        total_debit = sum(line.debit_cents for line in self.lines)
        total_credit = sum(line.credit_cents for line in self.lines)
        if total_debit <= 0 or total_debit != total_credit:
            raise UnbalancedEntryError(
                f"FinancialEvent {self.event_id} is unbalanced: "
                f"debit={total_debit} != credit={total_credit}"
            )

    @property
    def total_debit_cents(self) -> int:
        return sum(line.debit_cents for line in self.lines)


@dataclass(frozen=True)
class PeriodSummary:
    """Deterministic P&L, EBITDA, and Balance Sheet roll-up for a period."""

    tenant_id: str
    period: str
    revenue_cents: int
    cogs_cents: int
    gross_profit_cents: int
    workforce_cost_cents: int
    seller_commission_cents: int
    rent_utilities_cents: int
    general_opex_cents: int
    total_opex_cents: int
    ebitda_cents: int
    depreciation_cents: int
    interest_tax_cents: int
    net_income_cents: int
    cash_balance_cents: int
    ar_balance_cents: int
    ap_balance_cents: int
    vat_net_payable_cents: int
    event_count: int


@dataclass(frozen=True)
class MomTrend:
    """Month-over-Month deterministic variance between two accounting periods."""

    tenant_id: str
    current_period: str
    prior_period: str
    revenue_delta_cents: int
    revenue_delta_bps: int
    ebitda_delta_cents: int
    ebitda_delta_bps: int
    workforce_delta_cents: int
    cash_delta_cents: int


def _delta_bps(current: int, prior: int) -> int:
    if prior == 0:
        return 10_000 if current > 0 else (-10_000 if current < 0 else 0)
    return int(((current - prior) * 10_000) // abs(prior))


@dataclass
class GeneralLedger:
    """Tenant-scoped append-only double-entry ledger."""

    tenant_id: str
    events: list[FinancialEvent] = field(default_factory=list)

    def post(self, event: FinancialEvent) -> FinancialEvent:
        if event.tenant_id != self.tenant_id:
            raise ValueError(
                f"Event tenant {event.tenant_id} != ledger {self.tenant_id}"
            )
        self.events.append(event)
        return event

    def post_sales_invoice(
        self,
        *,
        event_id: str,
        period: str,
        posted_date: str,
        document_id: str,
        source_sha256: str,
        customer_id: str,
        net_cents: int,
        vat_cents: int,
        gross_cents: int,
        is_commission_revenue: bool = False,
        store_id: str = "",
    ) -> FinancialEvent:
        if net_cents + vat_cents != gross_cents:
            raise UnbalancedEntryError(
                f"Invoice {document_id} net ({net_cents}) + vat ({vat_cents}) != gross ({gross_cents})"
            )
        rev_account = (
            AccountCode.REVENUE_COMMISSION_4100
            if is_commission_revenue
            else AccountCode.REVENUE_SALES_4000
        )
        lines: list[LedgerLine] = [
            LedgerLine(
                account=AccountCode.AR_1100,
                debit_cents=gross_cents,
                counterparty_id=customer_id,
                store_id=store_id,
                memo=f"AR for {document_id}",
            ),
            LedgerLine(
                account=rev_account,
                credit_cents=net_cents,
                counterparty_id=customer_id,
                store_id=store_id,
                memo=f"Net revenue for {document_id}",
            ),
        ]
        if vat_cents > 0:
            lines.append(
                LedgerLine(
                    account=AccountCode.VAT_OUTPUT_2400,
                    credit_cents=vat_cents,
                    counterparty_id=customer_id,
                    store_id=store_id,
                    memo=f"Output VAT for {document_id}",
                )
            )
        event = FinancialEvent(
            event_id=event_id,
            tenant_id=self.tenant_id,
            period=period,
            posted_date=posted_date,
            description=f"Post sales invoice {document_id}",
            source_document_id=document_id,
            source_sha256=source_sha256,
            lines=tuple(lines),
        )
        return self.post(event)

    def post_purchase_invoice(
        self,
        *,
        event_id: str,
        period: str,
        posted_date: str,
        document_id: str,
        source_sha256: str,
        supplier_id: str,
        net_cents: int,
        vat_cents: int,
        gross_cents: int,
        expense_account: AccountCode = AccountCode.OPEX_GENERAL_6200,
        store_id: str = "",
    ) -> FinancialEvent:
        if net_cents + vat_cents != gross_cents:
            raise UnbalancedEntryError(
                f"Purchase {document_id} net ({net_cents}) + vat ({vat_cents}) != gross ({gross_cents})"
            )
        lines: list[LedgerLine] = [
            LedgerLine(
                account=expense_account,
                debit_cents=net_cents,
                counterparty_id=supplier_id,
                store_id=store_id,
                memo=f"Expense for {document_id}",
            ),
        ]
        if vat_cents > 0:
            lines.append(
                LedgerLine(
                    account=AccountCode.VAT_INPUT_1400,
                    debit_cents=vat_cents,
                    counterparty_id=supplier_id,
                    store_id=store_id,
                    memo=f"Input VAT for {document_id}",
                )
            )
        lines.append(
            LedgerLine(
                account=AccountCode.AP_2000,
                credit_cents=gross_cents,
                counterparty_id=supplier_id,
                store_id=store_id,
                memo=f"AP for {document_id}",
            )
        )
        event = FinancialEvent(
            event_id=event_id,
            tenant_id=self.tenant_id,
            period=period,
            posted_date=posted_date,
            description=f"Post purchase invoice {document_id}",
            source_document_id=document_id,
            source_sha256=source_sha256,
            lines=tuple(lines),
        )
        return self.post(event)

    def summarize_period(self, period: str | None = None) -> PeriodSummary:
        relevant = [
            ev for ev in self.events if period is None or ev.period == period
        ]
        net_by_acct: dict[AccountCode, int] = {acct: 0 for acct in AccountCode}
        for ev in relevant:
            for line in ev.lines:
                net_by_acct[line.account] += line.debit_cents - line.credit_cents

        def credit_normal(acct: AccountCode) -> int:
            return -net_by_acct[acct]

        def debit_normal(acct: AccountCode) -> int:
            return net_by_acct[acct]

        revenue = credit_normal(AccountCode.REVENUE_SALES_4000) + credit_normal(
            AccountCode.REVENUE_COMMISSION_4100
        )
        cogs = debit_normal(AccountCode.COGS_5000)
        gross_profit = revenue - cogs
        workforce = debit_normal(AccountCode.OPEX_WORKFORCE_6000)
        commissions = debit_normal(AccountCode.OPEX_COMMISSION_6050)
        rent_util = debit_normal(AccountCode.OPEX_RENT_UTILITIES_6100)
        general_opex = debit_normal(AccountCode.OPEX_GENERAL_6200)
        total_opex = workforce + commissions + rent_util + general_opex
        ebitda = gross_profit - total_opex
        depreciation = debit_normal(AccountCode.DEPRECIATION_AMORTIZATION_6800)
        interest_tax = debit_normal(AccountCode.INTEREST_AND_TAX_6900)
        net_income = ebitda - depreciation - interest_tax

        cash_bal = debit_normal(AccountCode.CASH_1000)
        ar_bal = debit_normal(AccountCode.AR_1100)
        ap_bal = credit_normal(AccountCode.AP_2000)
        vat_net = credit_normal(AccountCode.VAT_OUTPUT_2400) - debit_normal(
            AccountCode.VAT_INPUT_1400
        )

        return PeriodSummary(
            tenant_id=self.tenant_id,
            period=period or "ALL",
            revenue_cents=revenue,
            cogs_cents=cogs,
            gross_profit_cents=gross_profit,
            workforce_cost_cents=workforce,
            seller_commission_cents=commissions,
            rent_utilities_cents=rent_util,
            general_opex_cents=general_opex,
            total_opex_cents=total_opex,
            ebitda_cents=ebitda,
            depreciation_cents=depreciation,
            interest_tax_cents=interest_tax,
            net_income_cents=net_income,
            cash_balance_cents=cash_bal,
            ar_balance_cents=ar_bal,
            ap_balance_cents=ap_bal,
            vat_net_payable_cents=vat_net,
            event_count=len(relevant),
        )

    def compute_mom_trend(self, current_period: str, prior_period: str) -> MomTrend:
        curr = self.summarize_period(current_period)
        prev = self.summarize_period(prior_period)
        return MomTrend(
            tenant_id=self.tenant_id,
            current_period=current_period,
            prior_period=prior_period,
            revenue_delta_cents=curr.revenue_cents - prev.revenue_cents,
            revenue_delta_bps=_delta_bps(curr.revenue_cents, prev.revenue_cents),
            ebitda_delta_cents=curr.ebitda_cents - prev.ebitda_cents,
            ebitda_delta_bps=_delta_bps(curr.ebitda_cents, prev.ebitda_cents),
            workforce_delta_cents=curr.workforce_cost_cents - prev.workforce_cost_cents,
            cash_delta_cents=curr.cash_balance_cents - prev.cash_balance_cents,
        )
