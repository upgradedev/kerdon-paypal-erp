"""Commercial Go-To-Market, Accrual Basis Full-State, Invoice/Booking Creation, Compounding Memory & CSV Export routes."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
import hashlib
import os
import time
from typing import Any
from urllib.parse import parse_qs

import kerdon as kd
from kerdon.erp_services import get_erp_extensions, parse_and_compute_lines

from .bedrock_adapter import record_agentcore_memory_event
from .connectors_adapter import ExternalProviderError, _resolve_plugins
from .http_utils import ValidationError, json_reply
from .persistence import MultiTenantStore
from .superset_routes import build_superset_summary_payload


def _query_param(event: dict[str, Any], key: str, default: str = "") -> str:
    qsp = event.get("queryStringParameters")
    if isinstance(qsp, dict) and key in qsp and qsp[key] is not None:
        return str(qsp[key]).strip()
    raw_qs = str(event.get("rawQueryString") or "").strip()
    if raw_qs:
        parsed = parse_qs(raw_qs)
        if key in parsed and parsed[key]:
            return str(parsed[key][0]).strip()
    return default


def handle_get_full_state(
    tid: str,
    state: kd.TenantMiniErpState,
    store: MultiTenantStore,
    event: dict[str, Any],
    reader: kd.Reader,
    *,
    head_only: bool = False,
) -> dict[str, Any]:
    """Return full 8-module tenant state + Accounting/Business basis P&L + Fleet summary."""
    basis = _query_param(event, "basis", "accounting").lower()
    if basis not in ("accounting", "business"):
        basis = "accounting"

    def _build_payload() -> dict[str, Any]:
        acc_pnl = kd.summarize_period_by_basis(state, "2026-10", "accounting")
        bus_pnl = kd.summarize_period_by_basis(state, "2026-10", "business")
        active_pnl = bus_pnl if basis == "business" else acc_pnl

        fleet_summary = []
        for t in store.workspace.catalog.tenants.values():
            if not reader.actor.has_capability(kd.Capability.VIEW_PNL, t.tenant_id):
                continue
            st = store.workspace.tenant_states[t.tenant_id]
            t_pnl = kd.summarize_period_by_basis(st, "2026-10", basis)
            fleet_summary.append(
                {
                    "tenant_id": t.tenant_id,
                    "slug": t.slug,
                    "display_name": t.display_name,
                    "legal_name": t.fiscal_identity.legal_name,
                    "tax_id": t.fiscal_identity.tax_id,
                    "tier": t.tier.value,
                    "inbox_address": t.inbox_address,
                    "revenue_cents": t_pnl.revenue_cents,
                    "ebitda_cents": t_pnl.ebitda_cents,
                    "cash_balance_cents": t_pnl.cash_balance_cents,
                    "ar_balance_cents": t_pnl.ar_balance_cents,
                    "ap_balance_cents": t_pnl.ap_balance_cents,
                    "workforce_cost_cents": st.workforce_fusion.true_employer_cost_cents,
                    "vat_net_payable_cents": st.vat_summary.net_vat_payable_cents,
                    "commission_payable_cents": st.commission_case.total_payable_cents,
                    "open_gap_count": len(st.gaps),
                    "merkle_root_sha256": st.board_pack.handoff_packet.merkle_root_sha256,
                }
            )

        attributed_ids = {
            a.sale_id
            for a in state.attributions
            if a.status == kd.AttributionStatus.APPROVED
        }
        unattributed_sales = [
            asdict(s)
            for s in state.sales_events
            if s.sale_id not in attributed_ids
        ]

        can_view_payroll = reader.actor.has_capability(kd.Capability.VIEW_PAYROLL, tid)
        can_view_treasury = reader.actor.has_capability(
            kd.Capability.APPROVE_PAYOUTS, tid
        ) or reader.actor.has_capability(kd.Capability.EXECUTE_PAYOUTS, tid)

        return {
            "tenant": asdict(state.tenant),
            "basis": basis,
            "pnl": asdict(active_pnl),
            "accounting_pnl": asdict(acc_pnl),
            "business_pnl": asdict(bus_pnl),
            "accrual_delta_cents": bus_pnl.revenue_cents - acc_pnl.revenue_cents,
            "mom_trend": asdict(state.board_pack.mom_trend),
            "workforce_fusion": asdict(state.workforce_fusion) if can_view_payroll else {"redacted": True},
            "vat_summary": asdict(state.vat_summary),
            "open_gap_count": len(state.gaps),
            "fleet_summary": fleet_summary,
            "stores": [
                asdict(s)
                for s in store.workspace.catalog.stores.values()
                if s.tenant_id == tid
            ],
            "sellers": [
                asdict(s)
                for s in store.workspace.catalog.sellers.values()
                if s.tenant_id == tid
            ],
            "inbox": {
                "inbox_address": state.tenant.inbox_address,
                "blob_count": len(state.inbox.blobs_by_sha256),
                "blobs": [
                    {
                        "blob_sha256": b.sha256,
                        "mime_type": b.mime_type,
                        "size_bytes": len(b.raw_bytes),
                        "edge_count": len(b.source_edges),
                    }
                    for b in state.inbox.blobs_by_sha256.values()
                ],
                "candidates": [
                    asdict(c) for c in state.inbox.candidates_by_id.values()
                ],
            },
            "crm": {
                "customers": [asdict(c) for c in state.crm.customers.values()],
                "suppliers": [asdict(s) for s in state.crm.suppliers.values()],
                "bookings": [asdict(b) for b in state.crm.bookings.values()],
                "documents": [asdict(d) for d in state.crm.documents.values()],
                "credit_notes": [
                    asdict(cn) for cn in state.crm.credit_notes.values()
                ],
            },
            "ledger_events": [asdict(ev) for ev in state.ledger.events],
            "commissions": {
                "plan": asdict(state.commission_plan),
                "case": asdict(state.commission_case),
                "total_payable_cents": state.commission_case.total_payable_cents,
                "settlements": [asdict(s) for s in state.settlements],
                "sales_events": [asdict(s) for s in state.sales_events],
                "attributions": [asdict(a) for a in state.attributions],
                "unattributed_sales": unattributed_sales,
            },
            "completeness": {
                "rule_count": len(kd.GapRuleId),
                "gaps": [asdict(g) for g in state.gaps],
                "reasonings": [asdict(r) for r in state.reasonings],
                "digest": asdict(state.digest),
            },
            "docgen": {
                "board_pack": asdict(state.board_pack),
                "outbound_drafts": [asdict(d) for d in state.outbound_drafts],
                "fact_sheet": asdict(state.fact_sheet),
            },
            "treasury": {
                "pockets": {
                    k: asdict(v) for k, v in state.treasury.pockets.items()
                },
                "approvals": {
                    k: asdict(v) for k, v in state.treasury.approvals.items()
                },
                "receipts": {
                    k: asdict(v) for k, v in state.treasury.receipts.items()
                },
            } if can_view_treasury else {"pockets": {}, "approvals": {}, "receipts": {}, "redacted": True},
            "gtm": {
                "plans": [asdict(p) for p in kd.PUBLISHED_PLANS],
                "economics": asdict(kd.compute_msp_gtm_economics(35)),
            },
            "superset": build_superset_summary_payload(tid, state),
        }

    payload = reader.read(tid, _build_payload)
    return json_reply(200, payload, head_only=head_only)


def handle_get_export_csv(
    tid: str,
    state: kd.TenantMiniErpState,
    reader: kd.Reader,
    *,
    head_only: bool = False,
) -> dict[str, Any]:
    """Export Merkle-sealed Xero / myDATA / Galaxy ERP journal CSV."""
    csv_text = reader.read(tid, lambda: kd.export_journal_csv(state))
    merkle = state.board_pack.handoff_packet.merkle_root_sha256
    rows = [r for r in csv_text.strip().splitlines() if r]
    return json_reply(
        200,
        {
            "tenant_id": tid,
            "period": "2026-10",
            "format": "XERO_MYDATA_DOUBLE_ENTRY_CSV_V1",
            "merkle_root_sha256": merkle,
            "row_count": max(0, len(rows) - 1),
            "filename": f"kerdon-journal-{state.tenant.slug}-2026-10.csv",
            "csv": csv_text,
        },
        head_only=head_only,
    )


def handle_get_gtm_pricing(
    event: dict[str, Any],
    *,
    head_only: bool = False,
) -> dict[str, Any]:
    """Return commercial subscription tiers, MSP unit economics, and $10M ARR ladder."""
    raw_tenants = _query_param(event, "tenants", "35")
    try:
        managed_tenants = int(raw_tenants)
    except ValueError:
        managed_tenants = 35
    econ = kd.compute_msp_gtm_economics(managed_tenants)
    return json_reply(
        200,
        {
            "plans": [asdict(p) for p in kd.PUBLISHED_PLANS],
            "economics": asdict(econ),
            "build_vs_buy": [
                {
                    "subsystem": "Agentic orchestration & state graph",
                    "decision": "BUY / USE",
                    "vendor_service": "AWS Strands Agents SDK + AWS Step Functions",
                    "reason": "Managed retry, IAM isolation, and CloudWatch trace observability",
                },
                {
                    "subsystem": "Multimodal document OCR & narrative synthesis",
                    "decision": "BUY / USE",
                    "vendor_service": "Amazon Bedrock (eu.amazon.nova-pro-v1:0)",
                    "reason": "Native Greek/English PDF & receipt extraction without GPU hosting",
                },
                {
                    "subsystem": "Cross-period tenant mapping memory",
                    "decision": "BUY + CUSTOM FLYWHEEL",
                    "vendor_service": "Amazon Bedrock AgentCore Memory + TenantMappingMemory",
                    "reason": "Persists Run-1 operator attribution & vendor rules for unattended Run-2 close",
                },
                {
                    "subsystem": "Double-entry ledger, 3-doc payroll fusion, 24 completeness rules, seller commissions & changed-evidence invalidation",
                    "decision": "BUILD (Hexagonal Core)",
                    "vendor_service": "src/kerdon/ (100% deterministic integer cents)",
                    "reason": "LLMs cannot be trusted with statutory VAT rates, APD/FMY payroll reconciliation, tiered commission clawbacks, or stale-payout locks",
                },
            ],
            "token_economics": {
                "run_1_cold_start_tokens": 18_400,
                "run_2_compounding_memory_tokens": 3_980,
                "token_reduction_pct": 78.4,
                "bedrock_nova_pro_cost_per_close_usd": 0.019,
                "admission_reservation_formula": "2 * utf8_bytes + 4096",
            },
            "first_principles_idiot_index": {
                "manual_controller_cost_per_tenant_eur": 504.00,
                "aws_serverless_and_bedrock_cost_per_tenant_eur": 0.14,
                "idiot_index_ratio": 3600,
                "deleted_legacy_steps": [
                    "1. Manual portal login & file upload -> deleted via docs@<slug>.kerdon.ai inbox capture",
                    "2. Single-document net bank payroll posting -> deleted via 3-doc Payroll+APD+FMY fusion",
                    "3. Manual monthly seller commission spreadsheets -> deleted via effective-dated CommissionPlanVersion engine",
                    "4. Manual supplier/customer chaser email drafting -> deleted via Detect-Reason-Fix docgen + %PDF-1.4 renderer",
                    "5. Stale manual payment batch release -> deleted via SHA-256 Changed-Evidence Approval Invalidation & 6-Reader Strands Release Gate",
                ],
            },
        },
        head_only=head_only,
    )


def handle_post_invoice(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
    store: MultiTenantStore,
    now_ts: int,
) -> dict[str, Any]:
    """Issue a new Sales Invoice or register a Purchase Bill and post to the Double-Entry Ledger."""
    direction_raw = str(body.get("direction") or "SALES_REVENUE").upper().strip()
    try:
        direction = kd.Direction(direction_raw)
    except ValueError as exc:
        raise ValidationError(f"Invalid direction: {direction_raw}") from exc

    cp_id = str(body.get("counterparty_id") or "").strip()
    raw_lines = body.get("lines")
    net_cents = body.get("net_cents")
    vat_rate_pct = body.get("vat_rate_pct", 24)
    description = str(body.get("description") or "Commercial service invoice").strip()
    if not cp_id:
        raise ValidationError("counterparty_id and positive integer net_cents are required")
    if direction not in (kd.Direction.SALES_REVENUE, kd.Direction.PURCHASE_EXPENSE):
        raise ValidationError("Invoices must be sales or purchases")
    default_acct = (
        "4000_SALES_REVENUE"
        if direction == kd.Direction.SALES_REVENUE
        else "5000_COST_OF_GOODS_SOLD"
    )
    try:
        parsed_lines, net_cents, vat_cents, gross_cents = parse_and_compute_lines(
            raw_lines if isinstance(raw_lines, list) else None,
            fallback_net_cents=net_cents,
            fallback_vat_rate_pct=vat_rate_pct,
            fallback_description=description,
            default_account_code=default_acct,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    kd.require_capability(actor, kd.Capability.ISSUE_DOCS, tid)
    registry = state.crm.customers if direction == kd.Direction.SALES_REVENUE else state.crm.suppliers
    if cp_id not in registry:
        raise ValidationError("Counterparty must belong to this tenant and direction")
    try:
        issued_date = date.fromisoformat(str(body.get("issued_date", "2026-10-31"))).isoformat()
        due_date = date.fromisoformat(str(body.get("due_date", "2026-11-30"))).isoformat()
    except ValueError as exc:
        raise ValidationError("Invoice dates must be ISO calendar dates") from exc
    if due_date < issued_date:
        raise ValidationError("Due date must not precede invoice date")
    period = issued_date[:7]
    doc_id = str(body.get("document_id") or f"doc-{state.tenant.slug}-live-{now_ts}").strip()
    body.setdefault("document_id", doc_id)
    if doc_id in state.crm.documents or any(e.event_id == f"ev-{doc_id}" for e in state.ledger.events):
        raise kd.DuplicateIdempotencyError("Document already exists; not posted twice")
    doc_sha = hashlib.sha256(f"{tid}:{doc_id}:{cp_id}:{gross_cents}:{now_ts}".encode("utf-8")).hexdigest()

    entry = kd.DocumentRegisterEntry(
        document_id=doc_id,
        tenant_id=tid,
        direction=direction,
        counterparty_id=cp_id,
        counterparty_name=str(body.get("counterparty_name") or cp_id),
        counterparty_tax_id=str(body.get("counterparty_tax_id") or "998877665"),
        doc_type=str(body.get("invoice_number") or f"INV-{now_ts % 100000}"),
        net_cents=net_cents,
        vat_cents=vat_cents,
        gross_cents=gross_cents,
        paid_cents=0,
        currency="EUR",
        issued_date=issued_date,
        due_date=due_date,
        source_sha256=doc_sha,
        einvoice_mark=f"MARK-{now_ts % 1000000}",
        store_id=f"str-{state.tenant.slug}-01",
    )

    def _apply_invoice() -> kd.DocumentRegisterEntry:
        state.crm.register_document(entry)
        ext = get_erp_extensions(state)
        ext.document_lines[doc_id] = parsed_lines
        ext.document_status[doc_id] = "OPEN"
        dmeta = {
            k: body[k]
            for k in ("invoice_type", "series", "aa", "payment_method_code", "withheld_tax_pct", "vat_exemption_category", "correlated_mark", "measurement_unit")
            if body.get(k) not in (None, "")
        }
        if dmeta:
            ext.party_metadata[f"__DOC_META__:{doc_id}"] = dmeta
        if direction == kd.Direction.SALES_REVENUE:
            lines = (
                kd.LedgerLine(account=kd.AccountCode.AR_1100, debit_cents=gross_cents, counterparty_id=cp_id),
                kd.LedgerLine(account=kd.AccountCode.REVENUE_SALES_4000, credit_cents=net_cents, counterparty_id=cp_id),
                *((kd.LedgerLine(account=kd.AccountCode.VAT_OUTPUT_2400, credit_cents=vat_cents, counterparty_id=cp_id),) if vat_cents else ()),
            )
        else:
            lines = (
                kd.LedgerLine(account=kd.AccountCode.COGS_5000, debit_cents=net_cents, counterparty_id=cp_id),
                *((kd.LedgerLine(account=kd.AccountCode.VAT_INPUT_1400, debit_cents=vat_cents, counterparty_id=cp_id),) if vat_cents else ()),
                kd.LedgerLine(account=kd.AccountCode.AP_2000, credit_cents=gross_cents, counterparty_id=cp_id),
            )
        state.ledger.post(
            kd.FinancialEvent(
                event_id=f"ev-{doc_id}",
                tenant_id=tid,
                period=period,
                posted_date=issued_date,
                description=description,
                source_document_id=doc_id,
                source_sha256=doc_sha,
                lines=lines,
            )
        )
        pnl = state.ledger.summarize_period(period)
        mom = state.ledger.compute_mom_trend(period, date.fromordinal(date.fromisoformat(issued_date).replace(day=1).toordinal()-1).isoformat()[:7])
        state.vat_summary = kd.summarize_vat_and_einvoice(
            tenant_id=tid,
            period=period,
            documents=tuple(state.crm.documents.values()),
        )
        state.board_pack = kd.build_cfo_board_pack(
            tenant_id=tid,
            period=period,
            pnl=pnl,
            mom_trend=mom,
            vat_summary=state.vat_summary,
            commission_case=state.commission_case,
            digest=state.digest,
            document_sha256s=(doc_sha, state.board_pack.handoff_packet.merkle_root_sha256),
        )
        state.fact_sheet = kd.build_fact_sheet(
            tenant_name=state.tenant.display_name,
            pnl=pnl,
            mom_trend=mom,
            vat_summary=state.vat_summary,
            commission_case=state.commission_case,
            gaps=state.gaps,
        )
        if kd.resolve_organization_fiscal_profile(state).get("is_greek_organization", True):
            mrec = kd.build_aade_mydata_record(
                state,
                doc_id,
                series=str(body.get("series") or ("A" if direction == kd.Direction.SALES_REVENUE else "P")),
                aa=str(body.get("aa") or str(100 + len(state.crm.documents))),
            )
            kd.stamp_mydata_transmission(state, mrec)
        return state.crm.documents[doc_id]

    writer = kd.Writer(actor)
    created = writer.execute(
        tid,
        kd.Capability.ISSUE_DOCS,
        approval_token=f"inv-{doc_id}",
        mutation_fn=_apply_invoice,
    )
    aletheia = kd.seal_aletheia_receipt(
        tenant_id=tid,
        subject_id=created.document_id,
        approver_id=actor.actor_id,
        amount_cents=created.gross_cents,
        currency="EUR",
        evidence_hashes=(doc_sha,),
    )
    store.persist_audit_record(tid, "INVOICE_ISSUED", created.document_id, asdict(created))
    cs = kd.get_connector_state(state)
    return json_reply(
        201,
        {
            "document": asdict(created),
            "lines": [asdict(l) for l in parsed_lines],
            "mydata_record": asdict(cs.mydata_records[doc_id]) if doc_id in cs.mydata_records else None,
            "pnl": asdict(state.board_pack.pnl),
            "vat_summary": asdict(state.vat_summary),
            "aletheia_receipt": asdict(aletheia),
        },
    )


def handle_post_booking(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
    store: MultiTenantStore,
    now_ts: int,
) -> dict[str, Any]:
    """Create a confirmed ClientBooking and update Business (Accrual) Basis P&L."""
    cust_id = str(body.get("customer_id") or f"cus-{state.tenant.slug}-01").strip()
    agreed_cents = body.get("total_agreed_cents")
    invoiced_cents = int(body.get("invoiced_cents") or 0)
    if not isinstance(agreed_cents, int) or isinstance(agreed_cents, bool) or agreed_cents <= 0:
        raise ValidationError("total_agreed_cents must be a positive integer")
    booking_id = str(body.get("booking_id") or f"bkg-{state.tenant.slug}-live-{now_ts}").strip()
    body.setdefault("booking_id", booking_id)

    booking = kd.ClientBooking(
        booking_id=booking_id,
        tenant_id=tid,
        customer_id=cust_id,
        store_id=f"str-{state.tenant.slug}-01",
        seller_id=f"slr-{state.tenant.slug}-01",
        total_agreed_cents=agreed_cents,
        advance_deposit_cents=agreed_cents // 4,
        invoiced_cents=invoiced_cents,
        delivery_date="2026-10-29",
    )
    writer = kd.Writer(actor)
    writer.execute(
        tid,
        kd.Capability.ISSUE_DOCS,
        approval_token=f"bkg-{booking_id}",
        mutation_fn=lambda: state.crm.upsert_booking(booking),
    )
    acc_pnl = kd.summarize_period_by_basis(state, "2026-10", "accounting")
    bus_pnl = kd.summarize_period_by_basis(state, "2026-10", "business")
    store.persist_audit_record(tid, "BOOKING_CREATED", booking_id, asdict(booking))
    return json_reply(
        201,
        {
            "booking": asdict(booking),
            "accounting_pnl": asdict(acc_pnl),
            "business_pnl": asdict(bus_pnl),
            "accrual_delta_cents": bus_pnl.revenue_cents - acc_pnl.revenue_cents,
        },
    )


def handle_post_learn_memory(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
    store: MultiTenantStore,
    *,
    is_replay: bool = False,
) -> dict[str, Any]:
    """Execute Run 1 -> Run 2 Compounding Memory Flywheel and recompute commissions + ledger."""
    product_family = str(body.get("product_family") or "Hardware Accessory Pack").strip()
    target_seller_id = str(body.get("target_seller_id") or f"slr-{state.tenant.slug}-02").strip()
    writer = kd.Writer(actor)
    comp = writer.execute(
        tid,
        kd.Capability.APPROVE_COMMISSIONS,
        approval_token=f"mem-{tid}-{target_seller_id}",
        mutation_fn=lambda: kd.apply_learned_attribution_and_recompute(
            state,
            product_family=product_family,
            target_seller_id=target_seller_id,
            approved_by=actor.actor_id,
        ),
    )
    aletheia = kd.seal_aletheia_receipt(
        tenant_id=tid,
        subject_id=comp.rule_applied.rule_id,
        approver_id=actor.actor_id,
        amount_cents=comp.run_2_commission_payable_cents,
        currency="EUR",
        evidence_hashes=(state.board_pack.handoff_packet.merkle_root_sha256,),
    )
    mem_status = "replay-skipped" if is_replay else record_agentcore_memory_event(
        tenant_id=tid,
        session_id=f"flywheel-{tid}-{state.board_pack.period}",
        event_summary=(
            f"Learned attribution rule {comp.rule_applied.rule_id}: "
            f"{product_family} -> {target_seller_id} "
            f"(Run1={comp.run_1_commission_payable_cents}c -> Run2={comp.run_2_commission_payable_cents}c)"
        ),
    )
    store.persist_audit_record(tid, "COMPOUNDING_MEMORY_LEARNED", comp.rule_applied.rule_id, asdict(comp))
    return json_reply(
        200,
        {
            "compounding_comparison": asdict(comp),
            "commission_case": asdict(state.commission_case),
            "aletheia_receipt": asdict(aletheia),
            "agentcore_memory_status": mem_status,
        },
    )


def handle_get_gtm_readiness(
    tid: str,
    state: kd.TenantMiniErpState,
    store: MultiTenantStore,
    reader: kd.Reader,
    *,
    head_only: bool = False,
) -> dict[str, Any]:
    """Return 6-pillar Go-To-Market & AWS Marketplace SaaS production readiness report."""
    pp_plugin, aade_plugin = _resolve_plugins(tid)
    auth_mode = os.environ.get("KERDON_AUTH_MODE", "demo").strip().lower()
    agentcore_id = os.environ.get("AGENTCORE_MEMORY_ID", "").strip()
    mp_code = os.environ.get("AWS_MARKETPLACE_PRODUCT_CODE", "").strip()
    report = reader.read(
        tid,
        lambda: kd.evaluate_gtm_readiness(
            state,
            managed_tenant_count=len(store.workspace.catalog.tenants),
            auth_mode=auth_mode,
            agentcore_memory_configured=bool(agentcore_id),
            marketplace_product_code=mp_code,
            runtime_modes={
                "paypal": pp_plugin.mode_label,
                "aade_mydata": aade_plugin.mode_label,
            },
        ),
    )
    report["economics"] = asdict(kd.compute_msp_gtm_economics(max(35, len(store.workspace.catalog.tenants))))
    return json_reply(200, report, head_only=head_only)


def handle_post_opening_balance(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
    store: MultiTenantStore,
) -> dict[str, Any]:
    """Import a balanced opening trial balance into the tenant's double-entry ledger."""
    rows = body.get("rows")
    if not isinstance(rows, list) or len(rows) < 2:
        raise ValidationError("rows must be a list of at least 2 opening ledger lines")
    as_of = str(body.get("as_of_date") or "2026-10-01").strip()
    desc = str(body.get("description") or "Opening Trial Balance Cutover (ERP Onboarding)").strip()
    writer = kd.Writer(actor)
    try:
        receipt = writer.execute(
            tid,
            kd.Capability.ISSUE_DOCS,
            approval_token=f"opening-tb-{tid}-{as_of}",
            mutation_fn=lambda: kd.import_opening_trial_balance(
                state, rows, as_of_date=as_of, description=desc
            ),
        )
    except kd.UnbalancedEntryError:
        raise
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    store.persist_audit_record(tid, "OPENING_TRIAL_BALANCE_IMPORTED", receipt.event_id, asdict(receipt))
    return json_reply(201, {"opening_balance_receipt": asdict(receipt), "pnl": asdict(state.board_pack.pnl)})


def handle_post_marketplace_resolve_customer(
    body: dict[str, Any],
    actor: kd.Actor,
    store: MultiTenantStore,
    *,
    is_replay: bool = False,
) -> dict[str, Any]:
    """Resolve an AWS Marketplace SaaS x-amzn-marketplace-token into a Kerdon MSP entitlement."""
    if actor.role not in (kd.Role.MSP_FINOPS_DIRECTOR, kd.Role.CLIENT_OWNER):
        raise kd.PermissionDeniedError("Only MSP FinOps Director or Client Owner can resolve Marketplace contracts")
    reg_token = str(body.get("registration_token") or body.get("x_amzn_marketplace_token") or "").strip()
    if not reg_token:
        raise ValidationError("registration_token is required")
    require_live = bool(body.get("require_live", False))
    env_prod_code = os.environ.get("AWS_MARKETPLACE_PRODUCT_CODE", "").strip()
    replay_ent = body.get("_replay_marketplace_entitlement") if is_replay else None

    if isinstance(replay_ent, dict):
        ent = kd.MarketplaceEntitlement(**replay_ent)
    elif env_prod_code or require_live:
        try:
            import boto3

            mp_client = boto3.client("meteringmarketplace", region_name=os.environ.get("AWS_REGION", "us-east-1"))
            res = mp_client.resolve_customer(RegistrationToken=reg_token)
            cust_id = str(res.get("CustomerIdentifier") or "").strip()
            acct_id = str(res.get("CustomerAWSAccountId") or "").strip()
            prod_code = str(res.get("ProductCode") or env_prod_code).strip()
            if not cust_id or not prod_code:
                raise ExternalProviderError("AWS Marketplace ResolveCustomer returned incomplete customer metadata")
            ent = kd.MarketplaceEntitlement(
                customer_identifier=cust_id,
                customer_aws_account_id=acct_id or "unknown",
                product_code=prod_code,
                plan_code=str(body.get("plan_code") or "msp_hub"),
                max_managed_tenants=int(body.get("max_managed_tenants") or 35),
                provider_mode="aws-marketplace-live",
                resolved_date=date.today().isoformat(),
            )
        except ExternalProviderError:
            raise
        except Exception as exc:
            raise ExternalProviderError(f"AWS Marketplace ResolveCustomer failed: {exc}") from exc
        body["_replay_marketplace_entitlement"] = asdict(ent)
    else:
        tok_hash = hashlib.sha256(reg_token.encode("utf-8")).hexdigest()[:12]
        ent = kd.MarketplaceEntitlement(
            customer_identifier=f"mp-cust-{tok_hash}",
            customer_aws_account_id=str(body.get("customer_aws_account_id") or "308857099262"),
            product_code="kerdon-msp-saas-preview",
            plan_code=str(body.get("plan_code") or "msp_hub"),
            max_managed_tenants=int(body.get("max_managed_tenants") or 35),
            provider_mode="aws-marketplace-contract-preview",
            resolved_date="2026-10-31",
        )
        body["_replay_marketplace_entitlement"] = asdict(ent)

    tid = store.workspace.default_tenant_id
    store.persist_audit_record(tid, "AWS_MARKETPLACE_CUSTOMER_RESOLVED", ent.customer_identifier, asdict(ent))
    return json_reply(200, {"entitlement": asdict(ent)})


def handle_post_marketplace_meter_usage(
    body: dict[str, Any],
    actor: kd.Actor,
    store: MultiTenantStore,
    *,
    is_replay: bool = False,
) -> dict[str, Any]:
    """Compute measured multi-tenant usage and submit BatchMeterUsage to AWS Marketplace."""
    if actor.role not in (kd.Role.MSP_FINOPS_DIRECTOR, kd.Role.CLIENT_OWNER):
        raise kd.PermissionDeniedError("Only MSP FinOps Director or Client Owner can meter Marketplace usage")
    cust_id = str(body.get("customer_identifier") or "mp-cust-partner-001").strip()
    period = str(body.get("period") or "2026-10").strip()
    require_live = bool(body.get("require_live", False))
    env_prod_code = os.environ.get("AWS_MARKETPLACE_PRODUCT_CODE", "").strip()
    prod_code = env_prod_code or str(body.get("product_code") or "kerdon-msp-saas-preview").strip()

    batch = kd.build_marketplace_metering_batch(
        store.workspace,
        product_code=prod_code,
        customer_identifier=cust_id,
        period=period,
    )
    provider_mode = "aws-marketplace-metering-preview"
    unprocessed_count = 0
    if not is_replay and (env_prod_code or require_live):
        if not env_prod_code and require_live:
            raise ExternalProviderError("AWS_MARKETPLACE_PRODUCT_CODE is not configured for live BatchMeterUsage")
        try:
            import boto3

            mp_client = boto3.client("meteringmarketplace", region_name=os.environ.get("AWS_REGION", "us-east-1"))
            ts = int(time.time())
            res = mp_client.batch_meter_usage(
                UsageRecords=[
                    {
                        "Timestamp": ts,
                        "CustomerIdentifier": r.customer_identifier,
                        "Dimension": r.dimension,
                        "Quantity": r.quantity,
                    }
                    for r in batch
                ],
                ProductCode=env_prod_code,
            )
            unprocessed_count = len(res.get("UnprocessedRecords") or [])
            provider_mode = "aws-marketplace-live"
        except Exception as exc:
            raise ExternalProviderError(f"AWS Marketplace BatchMeterUsage failed: {exc}") from exc

    payload = {
        "product_code": prod_code,
        "customer_identifier": cust_id,
        "period": period,
        "provider_mode": provider_mode,
        "unprocessed_count": unprocessed_count,
        "records": [asdict(r) for r in batch],
    }
    store.persist_audit_record(store.workspace.default_tenant_id, "AWS_MARKETPLACE_USAGE_METERED", cust_id, payload)
    return json_reply(200, payload)
