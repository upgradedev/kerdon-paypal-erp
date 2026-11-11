"""M4: 3-Document Workforce/Payroll Fusion and Multi-Rate VAT / E-Invoicing Readiness."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from .crm import DocumentRegisterEntry
from .ledger import AccountCode, FinancialEvent, LedgerLine
from .tenancy import Direction

STATUTORY_VAT_RATES_PCT: frozenset[int] = frozenset({0, 6, 13, 24})


@dataclass(frozen=True)
class PayrollRegisterDoc:
    """Monthly payroll register listing gross wages, withholdings, and net pay."""

    document_id: str
    tenant_id: str
    period: str
    gross_wages_cents: int
    employee_social_security_cents: int
    withheld_tax_fmy_cents: int
    net_payable_cents: int
    commission_bonus_included_cents: int
    source_sha256: str


@dataclass(frozen=True)
class ApdSocialSecurityDoc:
    """APD monthly social security return covering employer and employee contributions."""

    document_id: str
    tenant_id: str
    period: str
    employer_contribution_cents: int
    employee_contribution_cents: int
    total_apd_cents: int
    source_sha256: str


@dataclass(frozen=True)
class FmyWithheldTaxDoc:
    """FMY monthly payroll withheld income tax filing."""

    document_id: str
    tenant_id: str
    period: str
    withheld_income_tax_cents: int
    stamp_duty_cents: int
    total_fmy_cents: int
    source_sha256: str


@dataclass(frozen=True)
class WorkforceCostFusion:
    """Fused 3-document employer workforce cost and balanced double-entry journal."""

    tenant_id: str
    period: str
    true_employer_cost_cents: int
    gross_wages_cents: int
    employer_social_security_cents: int
    net_salary_payable_cents: int
    total_apd_payable_cents: int
    total_fmy_payable_cents: int
    bank_net_transferred_cents: int
    missing_apd: bool
    missing_fmy: bool
    net_transfer_mismatch_cents: int
    journal_event: FinancialEvent


def fuse_workforce_cost(
    *,
    payroll: PayrollRegisterDoc,
    apd: ApdSocialSecurityDoc | None,
    fmy: FmyWithheldTaxDoc | None,
    bank_net_transferred_cents: int,
    posted_date: str,
) -> WorkforceCostFusion:
    """Fuse Payroll Register + APD + FMY into true employer cost and a balanced journal.

    Prevents P&L understatement when only net bank salary transfers or only the
    payroll register arrive without employer social-security contributions.
    """
    employer_ss = apd.employer_contribution_cents if apd is not None else 0
    employee_ss = (
        apd.employee_contribution_cents
        if apd is not None
        else payroll.employee_social_security_cents
    )
    total_apd = employer_ss + employee_ss

    stamp_duty = fmy.stamp_duty_cents if fmy is not None else 0
    withheld_tax = (
        fmy.withheld_income_tax_cents
        if fmy is not None
        else payroll.withheld_tax_fmy_cents
    )
    total_fmy = withheld_tax + stamp_duty

    expected_net = payroll.gross_wages_cents - employee_ss - withheld_tax
    if expected_net != payroll.net_payable_cents:
        # Respect the register's net payable and adjust employer cost so entry stays balanced
        net_payable = payroll.net_payable_cents
    else:
        net_payable = expected_net

    true_employer_cost = net_payable + total_apd + total_fmy
    lines: list[LedgerLine] = [
        LedgerLine(
            account=AccountCode.OPEX_WORKFORCE_6000,
            debit_cents=true_employer_cost,
            memo=f"Fused 3-doc workforce cost for {payroll.period}",
        ),
        LedgerLine(
            account=AccountCode.PAYROLL_PAYABLE_2500,
            credit_cents=net_payable,
            memo=f"Net wages payable for {payroll.period}",
        ),
    ]
    if total_apd > 0:
        lines.append(
            LedgerLine(
                account=AccountCode.SOCIAL_SECURITY_PAYABLE_2510,
                credit_cents=total_apd,
                memo=f"APD social security payable for {payroll.period}",
            )
        )
    if total_fmy > 0:
        lines.append(
            LedgerLine(
                account=AccountCode.WITHHELD_TAX_PAYABLE_2520,
                credit_cents=total_fmy,
                memo=f"FMY withheld tax payable for {payroll.period}",
            )
        )

    event = FinancialEvent(
        event_id=f"ev-workforce-{payroll.tenant_id}-{payroll.period}",
        tenant_id=payroll.tenant_id,
        period=payroll.period,
        posted_date=posted_date,
        description=f"3-Doc workforce cost fusion for {payroll.period}",
        source_document_id=payroll.document_id,
        source_sha256=payroll.source_sha256,
        lines=tuple(lines),
    )

    return WorkforceCostFusion(
        tenant_id=payroll.tenant_id,
        period=payroll.period,
        true_employer_cost_cents=true_employer_cost,
        gross_wages_cents=payroll.gross_wages_cents,
        employer_social_security_cents=employer_ss,
        net_salary_payable_cents=net_payable,
        total_apd_payable_cents=total_apd,
        total_fmy_payable_cents=total_fmy,
        bank_net_transferred_cents=bank_net_transferred_cents,
        missing_apd=apd is None,
        missing_fmy=fmy is None,
        net_transfer_mismatch_cents=bank_net_transferred_cents - net_payable,
        journal_event=event,
    )


@dataclass(frozen=True)
class VatValidationResult:
    """Outcome of checking a document's net, VAT, and gross cents against statutory rates."""

    is_valid: bool
    inferred_rate_pct: int | None
    reason: str


def validate_vat_breakdown(
    net_cents: int, vat_cents: int, gross_cents: int
) -> VatValidationResult:
    """Verify net + vat == gross and that VAT corresponds to a statutory rate (24/13/6/0%)."""
    if net_cents < 0 or vat_cents < 0 or gross_cents <= 0:
        return VatValidationResult(False, None, "Amounts must be positive cents")
    if net_cents + vat_cents != gross_cents:
        return VatValidationResult(
            False,
            None,
            f"net ({net_cents}) + vat ({vat_cents}) != gross ({gross_cents})",
        )
    if net_cents == 0:
        return VatValidationResult(False, None, "net_cents cannot be zero")

    net_dec = Decimal(net_cents)
    for rate in sorted(STATUTORY_VAT_RATES_PCT):
        expected_vat = int(
            (net_dec * Decimal(rate) / Decimal(100)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        if abs(expected_vat - vat_cents) <= 1:
            return VatValidationResult(
                True, rate, f"Matches statutory VAT rate {rate}%"
            )
    return VatValidationResult(
        False,
        None,
        f"VAT {vat_cents} on net {net_cents} does not match any statutory rate (0/6/13/24%)",
    )


@dataclass(frozen=True)
class VatPeriodSummary:
    """Multi-rate VAT and E-Invoicing MARK readiness summary for a period."""

    tenant_id: str
    period: str
    output_vat_by_rate_cents: dict[int, int]
    input_vat_by_rate_cents: dict[int, int]
    total_output_vat_cents: int
    total_input_vat_cents: int
    net_vat_payable_cents: int
    documents_missing_einvoice_mark: tuple[str, ...]


def summarize_vat_and_einvoice(
    tenant_id: str,
    period: str,
    documents: tuple[DocumentRegisterEntry, ...],
) -> VatPeriodSummary:
    """Aggregate output and input VAT by statutory rate and flag missing e-invoice MARKs."""
    output_by_rate: dict[int, int] = {0: 0, 6: 0, 13: 0, 24: 0}
    input_by_rate: dict[int, int] = {0: 0, 6: 0, 13: 0, 24: 0}
    missing_marks: list[str] = []

    for doc in documents:
        if not doc.issued_date.startswith(period):
            continue
        check = validate_vat_breakdown(doc.net_cents, doc.vat_cents, doc.gross_cents)
        bucket_rate = check.inferred_rate_pct if check.inferred_rate_pct is not None else 24
        if doc.direction == Direction.SALES_REVENUE:
            output_by_rate[bucket_rate] = output_by_rate.get(bucket_rate, 0) + doc.vat_cents
            if not doc.einvoice_mark.strip():
                missing_marks.append(doc.document_id)
        elif doc.direction == Direction.PURCHASE_EXPENSE:
            input_by_rate[bucket_rate] = input_by_rate.get(bucket_rate, 0) + doc.vat_cents
            if not doc.einvoice_mark.strip():
                missing_marks.append(doc.document_id)

    total_out = sum(output_by_rate.values())
    total_in = sum(input_by_rate.values())
    return VatPeriodSummary(
        tenant_id=tenant_id,
        period=period,
        output_vat_by_rate_cents=output_by_rate,
        input_vat_by_rate_cents=input_by_rate,
        total_output_vat_cents=total_out,
        total_input_vat_cents=total_in,
        net_vat_payable_cents=total_out - total_in,
        documents_missing_einvoice_mark=tuple(sorted(missing_marks)),
    )
