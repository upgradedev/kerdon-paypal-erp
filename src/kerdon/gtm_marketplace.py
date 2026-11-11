"""Go-To-Market (GTM), AWS Marketplace SaaS Metering, and Opening Trial-Balance Cutover.

Pure hexagonal domain module (zero cloud/LLM/network/clock SDK imports).
Computes deterministic AWS Marketplace SaaS usage metering batches, validates and
posts balanced opening trial-balance cutovers into the double-entry ledger, and
evaluates 6-pillar commercial Go-To-Market readiness.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from typing import Any
import uuid

from .docgen import build_cfo_board_pack
from .fiscal import summarize_vat_and_einvoice
from .ledger import AccountCode, FinancialEvent, LedgerLine, UnbalancedEntryError
from .mydata_schema import resolve_organization_fiscal_profile
from .query import build_fact_sheet

_MARKETPLACE_NAMESPACE = uuid.UUID("c8e1838a-74b9-4d40-9e3c-174f7f5a3019")

MARKETPLACE_DIMENSIONS: tuple[dict[str, Any], ...] = (
    {
        "dimension": "managed_client_tenants",
        "unit": "Tenants/Month",
        "included_in_msp_hub": 25,
        "overage_price_eur": 39,
        "description": "Active downstream client organizations managed under the MSP Hub.",
    },
    {
        "dimension": "autonomous_period_closes",
        "unit": "Closes",
        "included_in_msp_hub": 50,
        "overage_price_eur": 9,
        "description": "8-stage Strands + Bedrock monthly closes with Merkle-sealed Board Packs.",
    },
    {
        "dimension": "governed_payouts_verified",
        "unit": "Payouts",
        "included_in_msp_hub": 250,
        "overage_price_eur": 1,
        "description": "Four-Eyes & Changed-Evidence-verified disbursements with Braille receipts.",
    },
)


@dataclass(frozen=True)
class MarketplaceEntitlement:
    """Resolved AWS Marketplace SaaS customer entitlement contract."""

    customer_identifier: str
    customer_aws_account_id: str
    product_code: str
    plan_code: str
    max_managed_tenants: int
    provider_mode: str
    resolved_date: str


@dataclass(frozen=True)
class MarketplaceMeteringRecord:
    """Single deterministic usage record ready for AWS Marketplace BatchMeterUsage."""

    usage_record_id: str
    customer_identifier: str
    product_code: str
    dimension: str
    quantity: int
    period: str
    idempotency_token: str


@dataclass(frozen=True)
class OpeningBalanceImportReceipt:
    """Receipt emitted when an accountant imports a balanced opening trial balance."""

    event_id: str
    tenant_id: str
    as_of_date: str
    line_count: int
    total_debit_cents: int
    total_credit_cents: int
    merkle_root_sha256: str


def resolve_account_code(raw_code: str) -> AccountCode:
    """Resolve an AccountCode by enum value ('1000_CASH') or enum name ('CASH_1000') or prefix ('1000')."""
    cleaned = str(raw_code or "").strip().upper()
    for member in AccountCode:
        if cleaned in (member.value.upper(), member.name.upper()) or member.value.startswith(f"{cleaned}_"):
            return member
    raise ValueError(f"Unsupported chart-of-accounts code: {raw_code!r}")


def import_opening_trial_balance(
    state: Any,
    rows: list[dict[str, Any]],
    *,
    as_of_date: str = "2026-10-01",
    description: str = "Opening Trial Balance Cutover (ERP Onboarding)",
) -> OpeningBalanceImportReceipt:
    """Validate and post a balanced opening trial balance into the tenant's General Ledger."""
    parsed_date = date.fromisoformat(str(as_of_date).strip()).isoformat()
    if not isinstance(rows, list) or len(rows) < 2:
        raise ValueError("Opening trial balance requires at least 2 ledger lines")

    ledger_lines: list[LedgerLine] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"Opening balance row {idx} must be an object")
        acct = resolve_account_code(str(row.get("account") or ""))
        debit = int(row.get("debit_cents") or 0)
        credit = int(row.get("credit_cents") or 0)
        memo = str(row.get("memo") or description)[:120]
        cp_id = str(row.get("counterparty_id") or "").strip()
        ledger_lines.append(
            LedgerLine(
                account=acct,
                debit_cents=debit,
                credit_cents=credit,
                counterparty_id=cp_id,
                memo=memo,
            )
        )

    total_debit = sum(line.debit_cents for line in ledger_lines)
    total_credit = sum(line.credit_cents for line in ledger_lines)
    if total_debit <= 0 or total_debit != total_credit:
        raise UnbalancedEntryError(
            f"Opening trial balance is unbalanced: debits={total_debit}c vs credits={total_credit}c"
        )

    tid = state.tenant.tenant_id
    period = parsed_date[:7]
    digest_seed = f"{tid}:{parsed_date}:{total_debit}:" + "|".join(
        f"{l.account.value}:{l.debit_cents}:{l.credit_cents}" for l in ledger_lines
    )
    source_sha = hashlib.sha256(digest_seed.encode("utf-8")).hexdigest()
    event_id = f"ev-opening-{state.tenant.slug}-{parsed_date}-{source_sha[:8]}"

    if not any(ev.event_id == event_id for ev in state.ledger.events):
        state.ledger.post(
            FinancialEvent(
                event_id=event_id,
                tenant_id=tid,
                period=period,
                posted_date=parsed_date,
                description=description,
                source_document_id=f"opening-tb-{parsed_date}",
                source_sha256=source_sha,
                lines=tuple(ledger_lines),
            )
        )

    active_period = state.board_pack.period or "2026-10"
    prev_period = "2026-09"
    pnl = state.ledger.summarize_period(active_period)
    mom = state.ledger.compute_mom_trend(active_period, prev_period)
    state.vat_summary = summarize_vat_and_einvoice(
        tenant_id=tid,
        period=active_period,
        documents=tuple(state.crm.documents.values()),
    )
    state.board_pack = build_cfo_board_pack(
        tenant_id=tid,
        period=active_period,
        pnl=pnl,
        mom_trend=mom,
        vat_summary=state.vat_summary,
        commission_case=state.commission_case,
        digest=state.digest,
        document_sha256s=(source_sha, state.board_pack.handoff_packet.merkle_root_sha256),
    )
    state.fact_sheet = build_fact_sheet(
        tenant_name=state.tenant.display_name,
        pnl=pnl,
        mom_trend=mom,
        vat_summary=state.vat_summary,
        commission_case=state.commission_case,
        gaps=state.gaps,
    )
    return OpeningBalanceImportReceipt(
        event_id=event_id,
        tenant_id=tid,
        as_of_date=parsed_date,
        line_count=len(ledger_lines),
        total_debit_cents=total_debit,
        total_credit_cents=total_credit,
        merkle_root_sha256=state.board_pack.handoff_packet.merkle_root_sha256,
    )


def build_marketplace_metering_batch(
    workspace: Any,
    *,
    product_code: str,
    customer_identifier: str,
    period: str = "2026-10",
) -> tuple[MarketplaceMeteringRecord, ...]:
    """Compute measured usage quantities across managed tenants for AWS Marketplace metering."""
    clean_prod = str(product_code or "kerdon-msp-saas").strip()
    clean_cust = str(customer_identifier or "cust-msp-partner-001").strip()
    tenant_count = len(workspace.catalog.tenants)
    close_count = sum(1 for st in workspace.tenant_states.values() if st.board_pack is not None)
    payout_count = sum(len(st.treasury.receipts) for st in workspace.tenant_states.values())

    quantities = (
        ("managed_client_tenants", max(1, tenant_count)),
        ("autonomous_period_closes", max(1, close_count)),
        ("governed_payouts_verified", max(1, payout_count)),
    )
    records: list[MarketplaceMeteringRecord] = []
    for dim, qty in quantities:
        tok = str(uuid.uuid5(_MARKETPLACE_NAMESPACE, f"{clean_prod}:{clean_cust}:{period}:{dim}:{qty}"))
        records.append(
            MarketplaceMeteringRecord(
                usage_record_id=f"mtr-{dim[:12]}-{tok[:8]}",
                customer_identifier=clean_cust,
                product_code=clean_prod,
                dimension=dim,
                quantity=qty,
                period=period,
                idempotency_token=tok,
            )
        )
    return tuple(records)


def evaluate_gtm_readiness(
    state: Any,
    *,
    managed_tenant_count: int,
    auth_mode: str,
    agentcore_memory_configured: bool,
    marketplace_product_code: str,
    runtime_modes: dict[str, str],
) -> dict[str, Any]:
    """Build a transparent 6-pillar Go-To-Market & AWS Marketplace readiness report."""
    fiscal_prof = resolve_organization_fiscal_profile(state)
    has_opening = any(ev.event_id.startswith("ev-opening-") for ev in state.ledger.events)
    pillars = [
        {
            "pillar_id": "AWS_AI_AND_AGENTCORE",
            "title": "AWS Strands + Bedrock Nova Pro + AgentCore Memory",
            "status": "READY_LIVE" if agentcore_memory_configured else "PARTIAL_CONFIG",
            "evidence": (
                "Live ConverseStream on eu.amazon.nova-pro-v1:0 + provisioned AWS::BedrockAgentCore::Memory write/read-back"
                if agentcore_memory_configured
                else "Bedrock Nova Pro active; set AGENTCORE_MEMORY_ID for persistent AgentCore Memory"
            ),
        },
        {
            "pillar_id": "COUNTRY_PARAMETRIC_FISCAL",
            "title": "Statutory Tax & E-Invoicing Engine (GR myDATA / EU Peppol / INTL)",
            "status": "READY_LIVE",
            "evidence": (
                f"Active country={fiscal_prof['country_code']} ({fiscal_prof['tax_authority']}), "
                f"aade_mydata_enabled={fiscal_prof['aade_mydata_enabled']}"
            ),
        },
        {
            "pillar_id": "IDENTITY_AND_TENANT_ISOLATION",
            "title": "Multi-Tenant RBAC, Four-Eyes & Cognito JWT Cutover",
            "status": "STRICT_JWT_ACTIVE" if auth_mode == "strict" else "DEMO_HEADER_MODE_STRICT_READY",
            "evidence": (
                f"Current AuthMode={auth_mode}; Reader/Evaluator/Writer IAM roles isolated across "
                f"{managed_tenant_count} workspace tenants; flip AuthMode=strict for fail-closed JWT"
            ),
        },
        {
            "pillar_id": "AWS_MARKETPLACE_SAAS",
            "title": "AWS Marketplace SaaS Contract & Usage Metering",
            "status": "LIVE_PRODUCT_CODE" if marketplace_product_code else "METER_READY_AWAITING_LISTING_CODE",
            "evidence": (
                f"ProductCode={marketplace_product_code}"
                if marketplace_product_code
                else "ResolveCustomer + BatchMeterUsage adapter wired; attach AWS_MARKETPLACE_PRODUCT_CODE on listing approval"
            ),
        },
        {
            "pillar_id": "EXTERNAL_PAYMENT_TAX_CHANNELS",
            "title": "Live Payment & Tax Authority Connectors",
            "status": (
                "LIVE_CREDENTIALS_ACTIVE"
                if any("live" in str(v) for v in runtime_modes.values())
                else "PREVIEW_AWAITING_TENANT_KEYS"
            ),
            "evidence": f"paypal={runtime_modes.get('paypal', 'unknown')}, aade_mydata={runtime_modes.get('aade_mydata', 'unknown')}",
        },
        {
            "pillar_id": "CUSTOMER_CUTOVER_AND_HANDOFF",
            "title": "Opening Trial-Balance Import & Xero/SoftOne/myDATA Handoff",
            "status": "CUTOVER_VERIFIED" if has_opening else "READY_FOR_OPENING_IMPORT",
            "evidence": (
                "Opening trial balance posted + Merkle-sealed CSV/XML/PDF Board Pack ready"
                if has_opening
                else "Use POST /erp/onboarding/opening-balance + GET /tenants/{id}/export/journal-csv"
            ),
        },
    ]
    return {
        "tenant_id": state.tenant.tenant_id,
        "organization_name": state.tenant.display_name,
        "country_code": fiscal_prof["country_code"],
        "pillars": pillars,
        "marketplace_dimensions": list(MARKETPLACE_DIMENSIONS),
        "rollout_plan_30_60_90": [
            {
                "window": "Days 1-30 (Design Partner MSP Cohort)",
                "milestone": "Onboard 5 APN Managed Service Providers (100-175 downstream SMB client tenants) with AuthMode=strict + Cognito OIDC and inbound SES -> S3 -> EvaluatorFunction intake.",
                "kpi_target": "Cut monthly client close preparation from 7.0h to <= 1.2h per tenant [ESTIMATE]",
            },
            {
                "window": "Days 31-60 (AWS Marketplace SaaS Listing)",
                "milestone": "Publish Kerdon MSP Hub on AWS Marketplace (SaaS Contract + BatchMeterUsage overage dimensions) with Private Offers for 25+ tenant MSP fleets.",
                "kpi_target": "15 paying MSP partners (~EUR 26,800 MRR / EUR 321,600 ARR) [ESTIMATE]",
            },
            {
                "window": "Days 61-90 (Statutory & ERP Ecosystem Scale)",
                "milestone": "Activate certified YPAES provider bridge for Greek myDATA, Peppol BIS 3.0 Access Point for EU clients, and automated Xero HQ / SoftOne journal push.",
                "kpi_target": "50 MSP partners / 1,750 downstream tenants (~EUR 1.07M ARR run-rate toward $10M ARR ladder) [ESTIMATE]",
            },
        ],
    }
