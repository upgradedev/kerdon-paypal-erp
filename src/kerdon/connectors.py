"""Pluggable Payment (PayPal / Stripe / Bank IBAN) & Tax Authority (AADE myDATA / PEPPOL) Connectors.

Pure domain module with zero cloud, network, LLM, or clock SDK imports (STANDARDS A5).
All monetary math, fee splits, commission clawbacks, and XML payload figures run in integer cents.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
from typing import Any

from .commissions import ClawbackEvent, MonthlyCommissionCase, SelfApprovalError, evaluate_seller_statement
from .crm import DocumentRegisterEntry
from .docgen import seal_aletheia_receipt
from .erp_services import AllocationSlice, SettlementRecord, get_erp_extensions, refresh_derived_period_state
from .ledger import AccountCode, FinancialEvent, LedgerLine
from .mydata_schema import (
    build_payroll_17_1_mydata_payload,
    build_rich_aade_mydata_payload,
    map_vat_rate_to_mydata_category,
    resolve_organization_fiscal_profile,
)
from .paypal_schema import (
    PAYPAL_AGENTIC_TOOLS,
    build_default_paypal_seed_bundle,
    build_paypal_dispute_evidence_packet,
    build_paypal_invoice_v2_payload,
    verify_paypal_webhook_signature,
)
from .tenancy import Direction


class PaymentConnectorKind(str, Enum):
    """Supported pluggable payment & commerce connectors per tenant."""
    NONE, BANK_IBAN, PAYPAL, STRIPE = "NONE", "BANK_IBAN", "PAYPAL", "STRIPE"


class TaxConnectorKind(str, Enum):
    """Supported pluggable statutory e-invoicing / tax authority connectors per tenant."""
    NONE, AADE_MYDATA, PEPPOL_EU = "NONE", "AADE_MYDATA", "PEPPOL_EU"


@dataclass(frozen=True)
class TenantConnectorConfig:
    """Per-tenant connector plugin configuration."""

    tenant_id: str
    payment_connector: PaymentConnectorKind = PaymentConnectorKind.BANK_IBAN
    tax_connector: TaxConnectorKind = TaxConnectorKind.AADE_MYDATA
    paypal_merchant_email: str = "merchant-sb@kerdon-synth.eu"
    paypal_fee_rate_bps: int = 290
    paypal_fixed_fee_cents: int = 35
    aade_issuer_branch: int = 0
    auto_transmit_mydata: bool = False
    version: int = 1


@dataclass(frozen=True)
class MyDataTransmissionRecord:
    """Statutory Greek IAPR (AADE myDATA v1.0.8 / v1.0.9) transmission & classification record."""

    document_id: str
    tenant_id: str
    invoice_type: str
    series: str
    aa: str
    invoice_uid: str
    invoice_mark: str
    authentication_code: str
    qr_url: str
    vat_category: int
    classification_type: str
    classification_category: str
    net_cents: int
    vat_cents: int
    gross_cents: int
    status: str
    cancellation_mark: str = ""
    xml_sha256: str = ""
    xml_preview: str = ""
    provider_mode: str = "aade-mydata-sandbox"
    payment_method_code: int = 5
    withheld_tax_cents: int = 0
    payable_cents: int = 0
    correlated_mark: str = ""
    transmission_role: str = "ISSUER_SEND_INVOICES"
    lines_count: int = 1
    b2b_cash_limit_violation: bool = False
    xsd_valid: bool = True
    xsd_checks_passed: int = 16
    xsd_checks_total: int = 16


@dataclass(frozen=True)
class PayPalOrderSettlementRecord:
    """PayPal Orders v2 / Invoicing v2 checkout & capture record linked to GL."""

    order_id: str
    paypal_invoice_id: str
    capture_id: str
    tenant_id: str
    document_id: str
    counterparty_id: str
    gross_cents: int
    paypal_fee_cents: int
    net_settled_cents: int
    currency: str
    status: str
    approval_url: str
    journal_event_id: str
    captured_date: str
    provider_mode: str = "paypal-sandbox"


@dataclass(frozen=True)
class PayPalDisputeRecord:
    """PayPal Customer Dispute / Chargeback record linked to seller commission clawbacks & evidence defense."""

    dispute_id: str
    tenant_id: str
    document_id: str
    seller_id: str
    disputed_amount_cents: int
    clawback_commission_cents: int
    reason_code: str
    status: str
    clawback_id: str
    created_date: str
    evidence_defense_packet: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PayPalBatchPayoutRecord:
    """Governed Four-Eyes PayPal Batch Payout record (`v1/payments/payouts`)."""

    payout_batch_id: str
    sender_batch_id: str
    tenant_id: str
    approval_id: str
    recipient_email: str
    amount_cents: int
    currency: str
    status: str
    approver_id: str
    executor_id: str
    braille_receipt: str
    provider_mode: str = "paypal-sandbox"


@dataclass
class TenantConnectorState:
    """In-memory per-tenant state for pluggable payment and tax connectors."""

    config: TenantConnectorConfig
    mydata_records: dict[str, MyDataTransmissionRecord] = field(default_factory=dict)
    paypal_orders: dict[str, PayPalOrderSettlementRecord] = field(default_factory=dict)
    paypal_disputes: dict[str, PayPalDisputeRecord] = field(default_factory=dict)
    paypal_payouts: dict[str, PayPalBatchPayoutRecord] = field(default_factory=dict)
    processed_webhook_event_ids: set[str] = field(default_factory=set)
    pending_paypal_orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    paypal_subscriptions: dict[str, dict[str, Any]] = field(default_factory=dict)
    paypal_webhooks: dict[str, dict[str, Any]] = field(default_factory=dict)
    paypal_identities: dict[str, dict[str, Any]] = field(default_factory=dict)
    paypal_trackers: dict[str, dict[str, Any]] = field(default_factory=dict)


_CONNECTOR_STATES: dict[str, TenantConnectorState] = {}


def reset_connector_states() -> None:
    """Reset all in-memory connector states (invoked on workspace reset)."""
    _CONNECTOR_STATES.clear()


def _dict_to_mydata_record(payload: dict[str, Any]) -> MyDataTransmissionRecord:
    return MyDataTransmissionRecord(
        document_id=payload["document_id"],
        tenant_id=payload["tenant_id"],
        invoice_type=payload["invoice_type"],
        series=payload["series"],
        aa=payload["aa"],
        invoice_uid=payload["invoice_uid"],
        invoice_mark=payload["invoice_mark"],
        authentication_code=payload["authentication_code"],
        qr_url=payload["qr_url"],
        vat_category=payload["vat_category"],
        classification_type=payload["classification_type"],
        classification_category=payload["classification_category"],
        net_cents=payload["net_cents"],
        vat_cents=payload["vat_cents"],
        gross_cents=payload["gross_cents"],
        status=payload["status"],
        cancellation_mark=payload.get("cancellation_mark", ""),
        xml_sha256=payload.get("xml_sha256", ""),
        xml_preview=payload.get("xml_preview", ""),
        provider_mode=payload.get("provider_mode", "aade-mydata-sandbox"),
        payment_method_code=int(payload.get("payment_method_code", 5)),
        withheld_tax_cents=int(payload.get("withheld_tax_cents", 0)),
        payable_cents=int(payload.get("payable_cents", payload["gross_cents"])),
        correlated_mark=str(payload.get("correlated_mark", "")),
        transmission_role=str(payload.get("transmission_role", "ISSUER_SEND_INVOICES")),
        lines_count=int(payload.get("lines_count", 1)),
        b2b_cash_limit_violation=bool(payload.get("b2b_cash_limit_violation", False)),
        xsd_valid=bool(payload.get("xsd_valid", True)),
        xsd_checks_passed=int(payload.get("xsd_checks_passed", 16)),
        xsd_checks_total=int(payload.get("xsd_checks_total", 16)),
    )


def get_connector_state(state: Any) -> TenantConnectorState:
    """Return or initialize the `TenantConnectorState` for `state.tenant.tenant_id`."""
    tid = state.tenant.tenant_id
    profile = resolve_organization_fiscal_profile(state)
    is_gr = bool(profile.get("is_greek_organization", True))
    if tid not in _CONNECTOR_STATES:
        default_tax = (
            TaxConnectorKind.AADE_MYDATA
            if is_gr
            else (
                TaxConnectorKind.PEPPOL_EU
                if profile.get("country_code") in ("CY", "DE")
                else TaxConnectorKind.NONE
            )
        )
        cfg = TenantConnectorConfig(
            tenant_id=tid,
            payment_connector=PaymentConnectorKind.PAYPAL,
            tax_connector=default_tax,
            paypal_merchant_email=f"treasury@{state.tenant.slug}.eu",
        )
        conn_state = TenantConnectorState(config=cfg)
        pp_seed = build_default_paypal_seed_bundle(state)
        for o_seed in pp_seed.get("orders") or ([pp_seed["order"]] if pp_seed.get("order") else []):
            conn_state.paypal_orders[o_seed["order_id"]] = PayPalOrderSettlementRecord(**o_seed)
        if pp_seed.get("subscription"):
            conn_state.paypal_subscriptions[pp_seed["subscription"]["subscription_id"]] = dict(pp_seed["subscription"])
        if pp_seed.get("dispute"):
            conn_state.paypal_disputes[pp_seed["dispute"]["dispute_id"]] = PayPalDisputeRecord(**pp_seed["dispute"])
        if pp_seed.get("payout"):
            conn_state.paypal_payouts[pp_seed["payout"]["payout_batch_id"]] = PayPalBatchPayoutRecord(**pp_seed["payout"])
        if is_gr:
            for idx, doc in enumerate(state.crm.documents.values(), start=101):
                if doc.einvoice_mark:
                    rec = build_aade_mydata_record(
                        state,
                        doc.document_id,
                        series="A" if doc.direction == Direction.SALES_REVENUE else "P",
                        aa=str(idx),
                        existing_mark=doc.einvoice_mark,
                    )
                    conn_state.mydata_records[doc.document_id] = rec
            payroll_payload = build_payroll_17_1_mydata_payload(state)
            conn_state.mydata_records[payroll_payload["document_id"]] = _dict_to_mydata_record(
                payroll_payload
            )
        _CONNECTOR_STATES[tid] = conn_state
    return _CONNECTOR_STATES[tid]


def configure_tenant_connectors(
    state: Any,
    *,
    payment_connector: str | None = None,
    tax_connector: str | None = None,
    paypal_merchant_email: str | None = None,
    paypal_fee_rate_bps: int | None = None,
    paypal_fixed_fee_cents: int | None = None,
    auto_transmit_mydata: bool | None = None,
) -> TenantConnectorConfig:
    """Update a tenant's active payment and tax authority connector plugins."""
    cs = get_connector_state(state)
    curr = cs.config
    pay_kind = (
        PaymentConnectorKind(payment_connector.strip().upper())
        if payment_connector
        else curr.payment_connector
    )
    tax_kind = (
        TaxConnectorKind(tax_connector.strip().upper())
        if tax_connector
        else curr.tax_connector
    )
    fee_bps = int(paypal_fee_rate_bps) if paypal_fee_rate_bps is not None else curr.paypal_fee_rate_bps
    fixed_fee = int(paypal_fixed_fee_cents) if paypal_fixed_fee_cents is not None else curr.paypal_fixed_fee_cents
    if fee_bps < 0 or fee_bps > 2500 or fixed_fee < 0:
        raise ValueError("Invalid PayPal fee parameters")
    new_cfg = TenantConnectorConfig(
        tenant_id=curr.tenant_id,
        payment_connector=pay_kind,
        tax_connector=tax_kind,
        paypal_merchant_email=str(paypal_merchant_email or curr.paypal_merchant_email).strip(),
        paypal_fee_rate_bps=fee_bps,
        paypal_fixed_fee_cents=fixed_fee,
        aade_issuer_branch=curr.aade_issuer_branch,
        auto_transmit_mydata=bool(auto_transmit_mydata) if auto_transmit_mydata is not None else curr.auto_transmit_mydata,
        version=curr.version + 1,
    )
    cs.config = new_cfg
    return new_cfg


def _cents_to_decimal_str(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    abs_c = abs(int(cents))
    return f"{sign}{abs_c // 100}.{abs_c % 100:02d}"


def _mydata_vat_category(net_cents: int, vat_cents: int) -> int:
    """Map effective VAT rate to official Greek IAPR (AADE myDATA) vatCategory code."""
    return map_vat_rate_to_mydata_category(net_cents, vat_cents)


def build_aade_mydata_record(
    state: Any,
    document_id: str,
    *,
    series: str = "A",
    aa: str = "101",
    existing_mark: str = "",
    provider_mode: str = "aade-mydata-sandbox",
) -> MyDataTransmissionRecord:
    """Build deterministic AADE myDATA v1.0.8 / v1.0.9 XML (`InvoicesDoc`) and classification metadata."""
    payload = build_rich_aade_mydata_payload(
        state,
        document_id,
        series=series,
        aa=aa,
        existing_mark=existing_mark,
        provider_mode=provider_mode,
    )
    return _dict_to_mydata_record(payload)


def stamp_mydata_transmission(
    state: Any,
    rec: MyDataTransmissionRecord,
) -> MyDataTransmissionRecord:
    """Persist a transmitted AADE myDATA MARK onto the ERP document register and VAT summary."""
    cs = get_connector_state(state)
    if cs.config.tax_connector == TaxConnectorKind.NONE:
        raise ValueError("Tax authority connector is set to NONE for this tenant")
    if rec.document_id in state.crm.documents:
        doc = state.crm.documents[rec.document_id]
        state.crm.documents[doc.document_id] = DocumentRegisterEntry(
            **{**asdict(doc), "einvoice_mark": rec.invoice_mark}
        )
        refresh_derived_period_state(state, doc.issued_date[:7], rec.xml_sha256)
    cs.mydata_records[rec.document_id] = rec
    return rec


def cancel_mydata_mark(
    state: Any,
    document_id: str,
    *,
    reason: str = "Document reversal / cancellation",
    provider_mode: str = "aade-mydata-sandbox",
) -> MyDataTransmissionRecord:
    """Cancel a previously issued AADE myDATA MARK (`CancelInvoice`)."""
    cs = get_connector_state(state)
    existing = cs.mydata_records.get(document_id)
    if existing is None:
        raise KeyError(f"Document {document_id} has no transmitted myDATA MARK to cancel")
    cancel_digits = int(hashlib.sha256(f"CANCEL:{existing.invoice_mark}:{reason}".encode("utf-8")).hexdigest()[:11], 16) % 100_000_000_000
    cancel_mark = f"MARK-9{cancel_digits:011d}"
    cancelled = MyDataTransmissionRecord(
        **{
            **asdict(existing),
            "status": "CANCELLED",
            "cancellation_mark": cancel_mark,
            "provider_mode": provider_mode,
        }
    )
    cs.mydata_records[document_id] = cancelled
    return cancelled


def reconcile_mydata_register(state: Any) -> dict[str, Any]:
    """Reconcile ERP DocumentRegister against AADE myDATA transmitted MARKs (parametric by country)."""
    cs = get_connector_state(state)
    profile = resolve_organization_fiscal_profile(state)
    is_gr = bool(profile.get("is_greek_organization", True))
    transmitted = []
    untransmitted = []
    cancelled = []
    for doc in state.crm.documents.values():
        rec = cs.mydata_records.get(doc.document_id)
        if rec and rec.status == "CANCELLED":
            cancelled.append(doc.document_id)
        elif rec or doc.einvoice_mark:
            transmitted.append(doc.document_id)
        else:
            untransmitted.append(doc.document_id)
    records_list = [asdict(r) for r in cs.mydata_records.values()] if is_gr else []
    return {
        "tax_connector": cs.config.tax_connector.value,
        "aade_mydata_enabled": is_gr,
        "country_code": profile["country_code"],
        "fiscal_regime_code": profile["fiscal_regime_code"],
        "einvoice_standard": profile["einvoice_standard"],
        "total_documents": len(state.crm.documents),
        "transmitted_count": len(transmitted) if is_gr else 0,
        "pending_transmission_count": len(untransmitted) if is_gr else 0,
        "cancelled_count": len(cancelled) if is_gr else 0,
        "pending_document_ids": untransmitted if is_gr else [],
        "xsd_100pct_conformant": all(r.get("xsd_valid", True) for r in records_list),
        "records": records_list,
    }


def compute_paypal_fee_cents(
    gross_cents: int, *, rate_bps: int = 290, fixed_cents: int = 35
) -> int:
    """Compute deterministic integer-cent PayPal commercial processing fee."""
    if gross_cents <= 0:
        return 0
    return ((gross_cents * rate_bps) + 5_000) // 10_000 + fixed_cents


def build_paypal_order_payload(state: Any, document_id: str) -> dict[str, Any]:
    """Build official PayPal Orders v2 (`POST /v2/checkout/orders`) request payload."""
    if document_id not in state.crm.documents:
        raise KeyError(f"Unknown document_id: {document_id}")
    doc: DocumentRegisterEntry = state.crm.documents[document_id]
    remaining_cents = max(0, doc.gross_cents - doc.paid_cents)
    if remaining_cents <= 0:
        raise ValueError(f"Document {document_id} is already paid in full")
    ratio_net = (doc.net_cents * remaining_cents) // doc.gross_cents if doc.gross_cents > 0 else remaining_cents
    ratio_vat = remaining_cents - ratio_net
    return {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": doc.document_id,
                "custom_id": f"{state.tenant.tenant_id}:{doc.document_id}",
                "description": f"{doc.doc_type} {doc.document_id} - {doc.counterparty_name}",
                "amount": {
                    "currency_code": doc.currency,
                    "value": _cents_to_decimal_str(remaining_cents),
                    "breakdown": {
                        "item_total": {
                            "currency_code": doc.currency,
                            "value": _cents_to_decimal_str(ratio_net),
                        },
                        "tax_total": {
                            "currency_code": doc.currency,
                            "value": _cents_to_decimal_str(ratio_vat),
                        },
                    },
                },
            }
        ],
    }


def apply_paypal_capture_to_ledger(
    state: Any,
    *,
    document_id: str,
    order_id: str,
    paypal_invoice_id: str,
    capture_id: str,
    gross_cents: int,
    fee_cents: int | None = None,
    captured_date: str = "2026-10-29",
    approval_url: str = "",
    provider_mode: str = "paypal-sandbox",
) -> PayPalOrderSettlementRecord:
    """Record a captured PayPal Order/Invoice and post a 3-line balanced GL entry."""
    cs = get_connector_state(state)
    if cs.config.payment_connector != PaymentConnectorKind.PAYPAL:
        raise ValueError(
            f"PayPal connector is not active for tenant (current={cs.config.payment_connector.value})"
        )
    if order_id in cs.paypal_orders:
        return cs.paypal_orders[order_id]
    for existing_rec in cs.paypal_orders.values():
        if capture_id and existing_rec.capture_id == capture_id:
            return existing_rec
    if document_id not in state.crm.documents:
        raise KeyError(f"Unknown document_id: {document_id}")
    doc: DocumentRegisterEntry = state.crm.documents[document_id]
    if doc.direction != Direction.SALES_REVENUE:
        raise ValueError("PayPal customer checkout capture requires a SALES_REVENUE document")
    remaining = doc.gross_cents - doc.paid_cents
    if gross_cents <= 0 or gross_cents > remaining:
        raise ValueError(
            f"Capture gross_cents ({gross_cents}) must be between 1 and remaining unpaid ({remaining})"
        )
    actual_fee = (
        int(fee_cents)
        if fee_cents is not None
        else compute_paypal_fee_cents(
            gross_cents,
            rate_bps=cs.config.paypal_fee_rate_bps,
            fixed_cents=cs.config.paypal_fixed_fee_cents,
        )
    )
    if actual_fee < 0 or actual_fee >= gross_cents:
        raise ValueError("PayPal fee cannot exceed gross captured amount")
    net_settled = gross_cents - actual_fee
    period = captured_date[:7]
    sha = hashlib.sha256(
        f"PAYPAL_CAPTURE:{state.tenant.tenant_id}:{order_id}:{capture_id}:{gross_cents}:{actual_fee}".encode("utf-8")
    ).hexdigest()

    lines = [
        LedgerLine(
            account=AccountCode.CASH_1000,
            debit_cents=net_settled,
            counterparty_id=doc.counterparty_id,
            store_id=doc.store_id,
            memo=f"PayPal capture {capture_id} net settlement",
        ),
        LedgerLine(
            account=AccountCode.AR_1100,
            credit_cents=gross_cents,
            counterparty_id=doc.counterparty_id,
            store_id=doc.store_id,
            memo=f"PayPal checkout clearing for {document_id}",
        ),
    ]
    if actual_fee > 0:
        lines.insert(
            1,
            LedgerLine(
                account=AccountCode.OPEX_GENERAL_6200,
                debit_cents=actual_fee,
                counterparty_id="PAYPAL_MERCHANT_FEES",
                store_id=doc.store_id,
                memo=f"PayPal merchant processing fee on {order_id}",
            ),
        )
    ev_id = f"ev-pp-cap-{order_id.lower()}"
    state.ledger.post(
        FinancialEvent(
            event_id=ev_id,
            tenant_id=state.tenant.tenant_id,
            period=period,
            posted_date=captured_date,
            description=f"PayPal Order {order_id} captured for {document_id}",
            source_document_id=document_id,
            source_sha256=sha,
            lines=tuple(lines),
        )
    )
    state.crm.documents[document_id] = DocumentRegisterEntry(
        **{**asdict(doc), "paid_cents": doc.paid_cents + gross_cents}
    )
    ext = get_erp_extensions(state)
    ext.settlements[order_id] = SettlementRecord(
        settlement_id=order_id,
        tenant_id=state.tenant.tenant_id,
        kind="receipt",
        counterparty_id=doc.counterparty_id,
        bank_account_id="bnk-paypal-merchant",
        posted_date=captured_date,
        currency=doc.currency,
        gross_cash_cents=net_settled,
        fee_cents=actual_fee,
        allocated_total_cents=gross_cents,
        unapplied_advance_cents=0,
        allocations=(AllocationSlice(document_id=document_id, allocated_cents=gross_cents),),
        ledger_event_id=ev_id,
        bank_execution_status="PAYPAL_CAPTURED",
        external_transfer_id=capture_id,
    )
    refresh_derived_period_state(state, period, sha)
    rec = PayPalOrderSettlementRecord(
        order_id=order_id,
        paypal_invoice_id=paypal_invoice_id,
        capture_id=capture_id,
        tenant_id=state.tenant.tenant_id,
        document_id=document_id,
        counterparty_id=doc.counterparty_id,
        gross_cents=gross_cents,
        paypal_fee_cents=actual_fee,
        net_settled_cents=net_settled,
        currency=doc.currency,
        status="COMPLETED",
        approval_url=approval_url or f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}",
        journal_event_id=ev_id,
        captured_date=captured_date,
        provider_mode=provider_mode,
    )
    cs.paypal_orders[order_id] = rec
    return rec


def apply_paypal_dispute_and_clawback(
    state: Any,
    *,
    dispute_id: str,
    document_id: str,
    seller_id: str | None = None,
    disputed_amount_cents: int,
    reason_code: str = "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
    created_date: str = "2026-10-30",
) -> PayPalDisputeRecord:
    """Process a PayPal Customer Dispute into a Seller Commission ClawbackEvent."""
    cs = get_connector_state(state)
    if disputed_amount_cents <= 0:
        raise ValueError("disputed_amount_cents must be positive")
    target_seller = seller_id or (
        state.commission_case.statements[0].seller_id
        if state.commission_case.statements
        else f"slr-{state.tenant.slug}-01"
    )
    clawback_cents = max(1_000, (disputed_amount_cents * 500) // 10_000)
    cb_id = f"cb-pp-{dispute_id.lower()}"
    cb_event = ClawbackEvent(
        clawback_id=cb_id,
        tenant_id=state.tenant.tenant_id,
        seller_id=target_seller,
        period=created_date[:7],
        original_sale_id=document_id,
        clawback_commission_cents=clawback_cents,
        reason=f"PayPal Dispute {dispute_id} ({reason_code})",
    )
    new_stmts = []
    for stmt in state.commission_case.statements:
        if stmt.seller_id == target_seller:
            updated_stmt = evaluate_seller_statement(
                seller_id=target_seller,
                period=state.commission_case.period,
                plan=state.commission_plan,
                sales_events=state.sales_events,
                attributions=state.attributions,
                clawbacks=(cb_event,),
                tnps_score=stmt.tnps_score,
            )
            new_stmts.append(updated_stmt)
        else:
            new_stmts.append(stmt)
    if new_stmts:
        state.commission_case = MonthlyCommissionCase(
            case_id=state.commission_case.case_id,
            tenant_id=state.commission_case.tenant_id,
            period=state.commission_case.period,
            plan_id=state.commission_case.plan_id,
            plan_version=state.commission_case.plan_version,
            statements=tuple(new_stmts),
            status=state.commission_case.status,
            submitted_by=state.commission_case.submitted_by,
            approved_by=state.commission_case.approved_by,
        )
    defense_packet = build_paypal_dispute_evidence_packet(
        state,
        dispute_id=dispute_id,
        document_id=document_id,
        disputed_amount_cents=disputed_amount_cents,
        reason_code=reason_code,
        seller_id=target_seller,
        clawback_id=cb_id,
        clawback_commission_cents=clawback_cents,
    )
    rec = PayPalDisputeRecord(
        dispute_id=dispute_id,
        tenant_id=state.tenant.tenant_id,
        document_id=document_id,
        seller_id=target_seller,
        disputed_amount_cents=disputed_amount_cents,
        clawback_commission_cents=clawback_cents,
        reason_code=reason_code,
        status="EVIDENCE_SUBMITTED_UNDER_REVIEW",
        clawback_id=cb_id,
        created_date=created_date,
        evidence_defense_packet=defense_packet,
    )
    cs.paypal_disputes[dispute_id] = rec
    return rec


def execute_governed_paypal_payout(
    state: Any,
    *,
    approval_id: str,
    executor_id: str,
    recipient_email: str,
    now_epoch: int = 1761950500,
    payout_batch_id: str = "",
    batch_status: str = "SUCCESS",
    provider_mode: str = "paypal-sandbox",
) -> PayPalBatchPayoutRecord:
    """Execute a Four-Eyes approved payout via PayPal Batch Payouts (`v1/payments/payouts`)."""
    cs = get_connector_state(state)
    if cs.config.payment_connector != PaymentConnectorKind.PAYPAL:
        raise ValueError(f"PayPal connector is not active (current={cs.config.payment_connector.value})")
    approval = state.treasury.approvals.get(approval_id)
    if approval is None:
        raise KeyError(f"Unknown approval_id: {approval_id}")
    if executor_id == approval.approver_id or (
        approval.preparer_id and executor_id == approval.preparer_id
    ):
        raise SelfApprovalError(
            f"Four-Eyes violation: executor {executor_id} cannot execute approval signed by {approval.approver_id}"
        )
    clean_email = str(recipient_email or "").strip().lower()
    if not clean_email or "@" not in clean_email:
        raise ValueError("Valid recipient_email is required for PayPal payout")
    if approval.recipient_account:
        if clean_email != approval.recipient_account.strip().lower():
            raise ValueError(
                f"recipient_email '{recipient_email}' does not match bound approval beneficiary '{approval.recipient_account}'"
            )
    elif approval.counterparty_id in state.crm.suppliers:
        sup = state.crm.suppliers[approval.counterparty_id]
        sup_email = getattr(sup, "email", "").strip().lower()
        if sup_email and clean_email != sup_email:
            raise ValueError(
                f"recipient_email '{recipient_email}' does not match registered supplier email '{sup_email}'"
            )
    else:
        allowed_domains = ("@kerdon-synth.eu", "@aegean-mobility.gr", "@kerdon.ai", "@paypal.com")
        if not any(clean_email.endswith(d) for d in allowed_domains):
            raise ValueError(
                f"Unverified recipient_email '{recipient_email}' is not registered in tenant payroll/commission beneficiary directory"
            )
    payout_exec = state.treasury.execute_payout(
        approval_id=approval_id,
        now_epoch=now_epoch,
        executor_id=executor_id,
        recipient_account=recipient_email,
    )
    aletheia = seal_aletheia_receipt(
        tenant_id=state.tenant.tenant_id,
        subject_id=approval.invoice_or_case_id,
        approver_id=approval.approver_id,
        amount_cents=payout_exec.amount_cents,
        currency=payout_exec.currency,
        evidence_hashes=(approval.evidence_sha256,),
    )
    batch_id = payout_batch_id or f"PPBATCH-{payout_exec.idempotency_key[:12].upper()}"
    rec = PayPalBatchPayoutRecord(
        payout_batch_id=batch_id,
        sender_batch_id=payout_exec.idempotency_key,
        tenant_id=state.tenant.tenant_id,
        approval_id=approval_id,
        recipient_email=recipient_email,
        amount_cents=payout_exec.amount_cents,
        currency=payout_exec.currency,
        status=batch_status,
        approver_id=approval.approver_id,
        executor_id=executor_id,
        braille_receipt=aletheia.braille_ascii,
        provider_mode=provider_mode,
    )
    cs.paypal_payouts[batch_id] = rec
    return rec


def summarize_tenant_connectors(state: Any) -> dict[str, Any]:
    """Return full serializable snapshot of pluggable payment and tax connectors."""
    cs = get_connector_state(state)
    fiscal_profile = resolve_organization_fiscal_profile(state)
    return {
        "config": asdict(cs.config),
        "fiscal_profile": fiscal_profile,
        "available_payment_connectors": [
            {"id": PaymentConnectorKind.NONE.value, "name": "No External Payment Processor (Journal Only)", "description": "Standalone ERP ledgering without third-party payment rails."},
            {"id": PaymentConnectorKind.BANK_IBAN.value, "name": "Direct Bank IBAN / SEPA XML", "description": "Standard bank wire & IBAN reconciliation without card/wallet fees."},
            {"id": PaymentConnectorKind.PAYPAL.value, "name": "PayPal Commerce & Payouts Plugin (Orders v2, Invoicing v2, Payouts, Disputes)", "description": "End-to-end PayPal checkout, auto-fee GL posting, dispute clawbacks & Four-Eyes batch payouts."},
            {"id": PaymentConnectorKind.STRIPE.value, "name": "Stripe Connect & Invoicing Plugin", "description": "Optional Stripe PaymentIntents and Connect payout adapter."},
        ],
        "available_tax_connectors": [
            {"id": TaxConnectorKind.NONE.value, "name": "Local Document Register Only", "description": "No live statutory tax authority transmission."},
            {"id": TaxConnectorKind.AADE_MYDATA.value, "name": "AADE myDATA REST v1.0.8 XML Connector (Greece)", "description": "Official IAPR InvoicesDoc XML, E3 income/expense classification, UID/MARK & QR."},
            {"id": TaxConnectorKind.PEPPOL_EU.value, "name": "PEPPOL BIS Billing 3.0 UBL Connector (EU)", "description": "European EN 16931 e-invoicing interchange."},
        ],
        "mydata": reconcile_mydata_register(state),
        "paypal": {
            "enabled": cs.config.payment_connector == PaymentConnectorKind.PAYPAL,
            "merchant_email": cs.config.paypal_merchant_email,
            "fee_rate_bps": cs.config.paypal_fee_rate_bps,
            "fixed_fee_cents": cs.config.paypal_fixed_fee_cents,
            "agentic_tools": list(PAYPAL_AGENTIC_TOOLS),
            "summary": {
                "orders_count": len(cs.paypal_orders),
                "total_gross_captured_cents": sum(o.gross_cents for o in cs.paypal_orders.values()),
                "total_paypal_fees_cents": sum(o.paypal_fee_cents for o in cs.paypal_orders.values()),
                "total_net_settled_cents": sum(o.net_settled_cents for o in cs.paypal_orders.values()),
                "disputes_count": len(cs.paypal_disputes),
                "total_disputed_cents": sum(d.disputed_amount_cents for d in cs.paypal_disputes.values()),
                "total_clawback_cents": sum(d.clawback_commission_cents for d in cs.paypal_disputes.values()),
                "payouts_count": len(cs.paypal_payouts),
                "total_payouts_cents": sum(p.amount_cents for p in cs.paypal_payouts.values()),
            },
            "orders": [asdict(o) for o in cs.paypal_orders.values()],
            "pending_orders": list(cs.pending_paypal_orders.values()),
            "subscriptions": list(cs.paypal_subscriptions.values()),
            "webhooks": list(cs.paypal_webhooks.values()),
            "identities": list(cs.paypal_identities.values()),
            "trackers": list(cs.paypal_trackers.values()),
            "disputes": [asdict(d) for d in cs.paypal_disputes.values()],
            "payouts": [asdict(p) for p in cs.paypal_payouts.values()],
        },
    }
