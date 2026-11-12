"""HTTP API v2 routes for the Kerdon + Archon Complete Superset capabilities."""
from __future__ import annotations

import base64
from dataclasses import asdict
import hashlib
from typing import Any
from urllib.parse import parse_qs

import kerdon as kd

from .http_utils import ValidationError, json_reply
from .persistence import MultiTenantStore, get_store

_SUPERSET_RUNTIME: dict[str, dict[str, Any]] = {}


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


def reset_superset_runtime(tenant_id: str | None = None) -> None:
    """Reset per-tenant superset runtime state (used by POST /tenants/{id}/reset)."""
    if tenant_id is None:
        _SUPERSET_RUNTIME.clear()
    else:
        _SUPERSET_RUNTIME.pop(tenant_id, None)


def get_tenant_superset_bundle(
    tid: str, state: kd.TenantMiniErpState
) -> dict[str, Any]:
    """Return or initialize the per-tenant Kerdon + Archon superset state."""
    if tid not in _SUPERSET_RUNTIME:
        unpaid_docs = [
            d.document_id
            for d in state.crm.documents.values()
            if d.outstanding_cents > 0
        ]
        first_doc_id = (
            unpaid_docs[0]
            if unpaid_docs
            else next(iter(state.crm.documents.keys()), "doc-inv-2026-101")
        )
        first_cust_id = next(iter(state.crm.customers.keys()), "cust-olympic-fleet")
        interim_rev = kd.SettlementRevisionInput(
            revision_id=f"rev-{tid}-202610-interim",
            tenant_id=tid,
            period="2026-10",
            principal_name="Vodafone / Nova Mobility Principal",
            authority_rank=kd.AuthoritySourceRank.INTERIM_SNAPSHOT,
            captured_date="2026-10-27",
            reward_net_cents=1_680_000,
            weighted_attainment_pct=96.4,
            tnps_score=68,
            source_sha256=hashlib.sha256(f"{tid}:interim:2026-10-27".encode("utf-8")).hexdigest(),
            tnps_note_conflict=False,
        )
        official_rev = kd.SettlementRevisionInput(
            revision_id=f"rev-{tid}-202610-official",
            tenant_id=tid,
            period="2026-10",
            principal_name="Vodafone / Nova Mobility Principal",
            authority_rank=kd.AuthoritySourceRank.OFFICIAL_SETTLEMENT,
            captured_date="2026-10-31",
            reward_net_cents=1_850_000,
            weighted_attainment_pct=104.2,
            tnps_score=74,
            source_sha256=hashlib.sha256(f"{tid}:official:2026-10-31".encode("utf-8")).hexdigest(),
            tnps_note_conflict=True,
        )
        supersession = kd.reconcile_settlement_revisions((interim_rev, official_rev))

        rem1 = kd.classify_inbound_remittance(
            remittance_id=f"rem-{tid}-001",
            tenant_id=tid,
            document_id=first_doc_id,
            amount_cents=50_000,
            value_date="2026-10-18",
            email_sha256=hashlib.sha256(b"eml-original-remittance-001").hexdigest(),
            transfer_reference="SEPA-TRF-20261018-8821",
            existing_remittances=(),
        )
        rem2 = kd.classify_inbound_remittance(
            remittance_id=f"rem-{tid}-002-dup",
            tenant_id=tid,
            document_id=first_doc_id,
            amount_cents=50_000,
            value_date="2026-10-19",
            email_sha256=hashlib.sha256(b"eml-forwarded-copy-002").hexdigest(),
            transfer_reference="SEPA-TRF-20261018-8821",
            existing_remittances=(rem1,),
        )
        rem3 = kd.classify_inbound_remittance(
            remittance_id=f"rem-{tid}-003-unverified",
            tenant_id=tid,
            document_id=first_doc_id,
            amount_cents=25_000,
            value_date="2026-10-22",
            email_sha256=hashlib.sha256(b"eml-missing-ref-003").hexdigest(),
            transfer_reference="",
            existing_remittances=(rem1, rem2),
        )

        invite_default = kd.create_workspace_invite(
            tenant_id=tid,
            email=f"accountant@{state.tenant.slug}.gr",
            role=kd.Role.ACCOUNTANT,
            invited_by="act-sofia-marinou",
            now_epoch=1762000000,
        )

        _SUPERSET_RUNTIME[tid] = {
            "revisions": [interim_rev, official_rev],
            "supersession": supersession,
            "seller_disputes": [],
            "remittances": [rem1, rem2, rem3],
            "attestations": [],
            "dispute_holds": [],
            "invites": [invite_default],
            "subscription_plan": "standard",
            "subscription_price_eur": 49,
            "portfolio_mode": "DEMO_SEED",
            "admission_ledger": kd.AdmissionBudgetLedger(max_tokens_budget=250_000),
            "send_ledger": kd.DurableSendLedger(),
            "default_doc_id": first_doc_id,
            "default_cust_id": first_cust_id,
        }
    return _SUPERSET_RUNTIME[tid]


def build_superset_summary_payload(
    tid: str, state: kd.TenantMiniErpState
) -> dict[str, Any]:
    """Build complete serializable dictionary of all Kerdon + Archon superset state for /full-state."""
    rt = get_tenant_superset_bundle(tid, state)
    allocations = kd.allocate_payments_to_invoices(state)
    counterparty_rollups = kd.rollup_completeness_by_counterparty(state)
    blockers = kd.evaluate_truthful_commission_blockers(state)

    cand_plan = kd.CommissionPlanVersion(
        plan_id=f"{state.commission_plan.plan_id}-retro-v2",
        version=state.commission_plan.version + 1,
        tenant_id=tid,
        effective_from_period="2026-01",
        effective_to_period=None,
        mode=kd.TierMode.RETROACTIVE,
        tiers=state.commission_plan.tiers,
        gate=state.commission_plan.gate,
        floor_cents=state.commission_plan.floor_cents,
        cap_cents=state.commission_plan.cap_cents,
    )
    plan_diff = kd.simulate_plan_version_diff(state, cand_plan)

    first_seller_id = (
        state.commission_case.statements[0].seller_id
        if state.commission_case.statements
        else "sel-nikos-papadakis"
    )
    private_view = kd.build_seller_private_statement(
        state, first_seller_id, tuple(rt["seller_disputes"])
    )

    doc_id = rt["default_doc_id"]
    graph_report = kd.run_six_reader_strands_graph(
        state,
        doc_id,
        remittances=tuple(rt["remittances"]),
        dispute_holds=tuple(rt["dispute_holds"]),
    )
    gate_verdict = kd.verify_outbound_draft_release_gate(graph_report)
    portfolio_240 = kd.build_240_record_portfolio(tid)
    plan_code = rt["subscription_plan"]

    return {
        "authority_supersession": asdict(rt["supersession"]),
        "typed_quantity_examples": {
            "verified_positive": asdict(kd.parse_typed_quantity(42)),
            "legacy_zero_ambiguous": asdict(kd.parse_typed_quantity(0, zero_is_verified=False)),
            "verified_zero": asdict(kd.parse_typed_quantity(0, zero_is_verified=True)),
        },
        "truthful_blockers": [asdict(b) for b in blockers],
        "plan_diff_simulation": asdict(plan_diff),
        "seller_private_view": asdict(private_view),
        "seller_disputes": [asdict(d) for d in rt["seller_disputes"]],
        "payment_allocations": [asdict(a) for a in allocations],
        "counterparty_completeness": [asdict(c) for c in counterparty_rollups],
        "six_reader_graph": asdict(graph_report),
        "release_gate_verdict": asdict(gate_verdict),
        "remittances": [asdict(r) for r in rt["remittances"]],
        "identity_attestations": [asdict(a) for a in rt["attestations"]],
        "client_dispute_holds": [asdict(d) for d in rt["dispute_holds"]],
        "invites": [asdict(i) for i in rt["invites"]],
        "subscription": {
            "plan_code": plan_code,
            "monthly_price_eur": rt["subscription_price_eur"],
            "entitlements": list(kd.resolve_plan_entitlements(plan_code)),
        },
        "portfolio": {
            "active_mode": rt["portfolio_mode"],
            "full_240_summary": asdict(portfolio_240),
        },
        "admission_budget": {
            "max_tokens_budget": rt["admission_ledger"].max_tokens_budget,
            "reserved_tokens_total": rt["admission_ledger"].reserved_tokens_total,
            "call_count": rt["admission_ledger"].call_count,
        },
        "send_ledger": {
            "sent_count": len(rt["send_ledger"].sent_records),
            "records": list(rt["send_ledger"].sent_records.values()),
        },
    }


def handle_get_draft_pdf(
    tid: str,
    draft_id: str,
    state: kd.TenantMiniErpState,
    event: dict[str, Any],
    reader: kd.Reader,
    *,
    head_only: bool = False,
) -> dict[str, Any]:
    """Render and return a downloadable PDF 1.4 artifact for an outbound draft or register document (A3)."""
    def _render() -> kd.RenderedPdfArtifact:
        disc_raw = _query_param(event, "discount_cents", "0")
        try:
            disc_cents = max(0, int(disc_raw))
        except ValueError:
            disc_cents = 0
        return kd.resolve_and_render_tenant_pdf(state, draft_id, discount_cents=disc_cents)

    artifact = reader.read(tid, _render)
    fmt = _query_param(event, "format", "").lower()
    hdrs = event.get("headers") or {}
    accept_hdr = str(hdrs.get("accept") or hdrs.get("Accept") or "").lower()
    wants_binary = fmt == "binary" or (
        fmt != "json" and ("text/html" in accept_hdr or "application/pdf" in accept_hdr)
    )
    if wants_binary:
        return {
            "statusCode": 200,
            "headers": {
                "content-type": "application/pdf",
                "content-disposition": f'attachment; filename="{artifact.filename}"',
                "x-kerdon-pdf-sha256": artifact.sha256,
            },
            "body": "" if head_only else base64.b64encode(artifact.pdf_bytes).decode("ascii"),
            "isBase64Encoded": True,
        }
    return json_reply(
        200,
        {
            "tenant_id": tid,
            "draft_id": artifact.draft_id,
            "reference_code": artifact.reference_code,
            "filename": artifact.filename,
            "content_type": artifact.content_type,
            "size_bytes": artifact.size_bytes,
            "sha256": artifact.sha256,
            "pdf_header": artifact.pdf_bytes[:8].decode("latin-1", "replace"),
            "pdf_base64": base64.b64encode(artifact.pdf_bytes).decode("ascii"),
        },
        head_only=head_only,
    )


def handle_post_send_draft(
    tid: str,
    draft_id: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
    now_epoch: int,
) -> dict[str, Any]:
    """Dispatch an outbound draft through AdmissionBudgetLedger and DurableSendLedger (B5)."""
    kd.require_capability(actor, kd.Capability.ISSUE_DOCS, tid)
    rt = get_tenant_superset_bundle(tid, state)
    matching = [d for d in state.outbound_drafts if d.draft_id == draft_id]
    if not matching:
        raise KeyError(f"Unknown draft_id: {draft_id}")
    target_draft = matching[0]

    reserved_tokens = rt["admission_ledger"].reserve(target_draft.covering_prose)
    try:
        send_rec = rt["send_ledger"].record_send(
            tenant_id=tid,
            draft_id=target_draft.draft_id,
            recipient=str(body.get("recipient") or target_draft.recipient_name),
            content_sha256=target_draft.content_sha256,
            now_epoch=now_epoch,
        )
    except kd.DuplicateSendBlockedError as exc:
        return json_reply(409, {"error": str(exc), "code": "DUPLICATE_SEND_BLOCKED"})

    get_store().persist_audit_record(
        tid, "OUTBOUND_SEND_DISPATCHED", target_draft.draft_id, send_rec
    )
    return json_reply(
        200,
        {
            "status": "DISPATCHED",
            "send_record": send_rec,
            "reserved_tokens": reserved_tokens,
            "admission_budget": {
                "reserved_tokens_total": rt["admission_ledger"].reserved_tokens_total,
                "call_count": rt["admission_ledger"].call_count,
            },
        },
    )


def handle_post_simulate_commission_plan(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
) -> dict[str, Any]:
    """Evaluate What-If CommissionPlanVersion diff (PROGRESSIVE vs RETROACTIVE, gates, caps)."""
    evaluator = kd.Evaluator(actor)
    mode_str = str(body.get("mode") or "RETROACTIVE").strip().upper()
    mode = kd.TierMode.RETROACTIVE if mode_str == "RETROACTIVE" else kd.TierMode.PROGRESSIVE
    min_tnps = int(body.get("min_tnps_score", state.commission_plan.gate.min_tnps_score))
    cap_raw = body.get("cap_cents", state.commission_plan.cap_cents)
    cap_cents = int(cap_raw) if cap_raw is not None else None
    rate_boost_bps = int(body.get("rate_boost_bps", 0))

    boosted_tiers = tuple(
        kd.CommissionTier(
            lower_bound_cents=t.lower_bound_cents,
            upper_bound_cents=t.upper_bound_cents,
            rate_bps=max(0, t.rate_bps + rate_boost_bps),
        )
        for t in state.commission_plan.tiers
    )
    cand_plan = kd.CommissionPlanVersion(
        plan_id=f"{state.commission_plan.plan_id}-sim",
        version=state.commission_plan.version + 1,
        tenant_id=tid,
        effective_from_period="2026-01",
        effective_to_period=None,
        mode=mode,
        tiers=boosted_tiers,
        gate=kd.CommissionGate(
            min_tnps_score=min_tnps,
            min_compliance_bps=state.commission_plan.gate.min_compliance_bps,
        ),
        floor_cents=state.commission_plan.floor_cents,
        cap_cents=cap_cents,
    )
    diff = evaluator.evaluate(tid, lambda: kd.simulate_plan_version_diff(state, cand_plan))
    return json_reply(200, {"simulation": asdict(diff)})


def handle_get_seller_private_statement(
    tid: str,
    state: kd.TenantMiniErpState,
    event: dict[str, Any],
    reader: kd.Reader,
    *,
    head_only: bool = False,
) -> dict[str, Any]:
    """Return privacy-isolated SellerPrivateStatementView for a single seller (A2)."""
    rt = get_tenant_superset_bundle(tid, state)
    default_seller = (
        state.commission_case.statements[0].seller_id
        if state.commission_case.statements
        else "sel-nikos-papadakis"
    )
    seller_id = _query_param(event, "seller_id", default_seller)
    kd.require_capability(reader.actor, kd.Capability.VIEW_OWN_SALES, tid)
    if (
        reader.actor.role == kd.Role.SELLER
        and reader.actor.seller_id
        and seller_id != reader.actor.seller_id
    ):
        raise kd.PermissionDeniedError(
            f"Seller {reader.actor.seller_id} cannot access statement for seller {seller_id}"
        )
    view = kd.build_seller_private_statement(
        state, seller_id, tuple(rt["seller_disputes"])
    )
    return json_reply(200, asdict(view), head_only=head_only)


def handle_post_seller_dispute(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
    now_epoch: int,
) -> dict[str, Any]:
    """Record a seller dispute comment on their commission statement (A2)."""
    kd.require_capability(actor, kd.Capability.VIEW_OWN_SALES, tid)
    rt = get_tenant_superset_bundle(tid, state)
    default_seller = (
        state.commission_case.statements[0].seller_id
        if state.commission_case.statements
        else "sel-nikos-papadakis"
    )
    seller_id = str(body.get("seller_id") or default_seller).strip()
    line_ref = str(body.get("sale_or_line_ref") or "sale-2026-10-01").strip()
    reason_text = str(
        body.get("reason_text")
        or "Customer settled invoice on 2026-10-28; requesting commission attribution review."
    ).strip()
    if not reason_text:
        raise ValidationError("reason_text is required")

    disp_id = f"disp-{len(rt['seller_disputes']) + 1:03d}"
    note = kd.SellerDisputeNote(
        dispute_id=disp_id,
        tenant_id=tid,
        seller_id=seller_id,
        period="2026-10",
        sale_or_line_ref=line_ref,
        reason_text=reason_text,
        status="DISPUTE_OPEN",
        created_at_epoch=now_epoch,
    )
    rt["seller_disputes"].append(note)
    view = kd.build_seller_private_statement(
        state, seller_id, tuple(rt["seller_disputes"])
    )
    return json_reply(
        200,
        {
            "status": "DISPUTE_RECORDED",
            "dispute": asdict(note),
            "seller_private_view": asdict(view),
        },
    )


def handle_post_supersede_settlement(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
) -> dict[str, Any]:
    """Record a new settlement revision and run authority ranking + supersession (A1)."""
    kd.require_capability(actor, kd.Capability.ISSUE_DOCS, tid)
    rt = get_tenant_superset_bundle(tid, state)
    rank_name = str(body.get("authority_rank") or "OFFICIAL_SETTLEMENT").strip().upper()
    rank = getattr(kd.AuthoritySourceRank, rank_name, kd.AuthoritySourceRank.OFFICIAL_SETTLEMENT)
    reward_net_cents = int(body.get("reward_net_cents", 1_920_000))
    tnps_raw = body.get("tnps_score", 78)
    tnps_score = int(tnps_raw) if tnps_raw is not None else None
    new_rev = kd.SettlementRevisionInput(
        revision_id=f"rev-{tid}-{len(rt['revisions']) + 1:03d}",
        tenant_id=tid,
        period="2026-10",
        principal_name=str(body.get("principal_name") or "Vodafone / Nova Mobility Principal"),
        authority_rank=rank,
        captured_date=str(body.get("captured_date") or "2026-11-01"),
        reward_net_cents=reward_net_cents,
        weighted_attainment_pct=float(body.get("weighted_attainment_pct", 106.5)),
        tnps_score=tnps_score,
        source_sha256=hashlib.sha256(f"{tid}:{reward_net_cents}:{rank_name}".encode("utf-8")).hexdigest(),
        tnps_note_conflict=bool(body.get("tnps_note_conflict", False)),
    )
    rt["revisions"].append(new_rev)
    rt["supersession"] = kd.reconcile_settlement_revisions(tuple(rt["revisions"]))
    return json_reply(200, {"supersession": asdict(rt["supersession"])})


def handle_post_classify_remittance(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
) -> dict[str, Any]:
    """Classify an inbound remittance (duplicate ref hold vs equal instalment vs missing ref) (B2)."""
    kd.require_capability(actor, kd.Capability.ISSUE_DOCS, tid)
    rt = get_tenant_superset_bundle(tid, state)
    doc_id = str(body.get("document_id") or rt["default_doc_id"]).strip()
    amount_cents = int(body.get("amount_cents", 248_000))
    value_date = str(body.get("value_date") or "2026-10-25").strip()
    transfer_ref = str(body.get("transfer_reference") or "").strip()
    email_sha = str(
        body.get("email_sha256")
        or hashlib.sha256(f"{tid}:{doc_id}:{len(rt['remittances'])}".encode("utf-8")).hexdigest()
    )
    rem_id = f"rem-{tid}-{len(rt['remittances']) + 1:03d}"
    decision = kd.classify_inbound_remittance(
        remittance_id=rem_id,
        tenant_id=tid,
        document_id=doc_id,
        amount_cents=amount_cents,
        value_date=value_date,
        email_sha256=email_sha,
        transfer_reference=transfer_ref,
        existing_remittances=tuple(rt["remittances"]),
    )
    rt["remittances"].append(decision)
    return json_reply(
        200,
        {
            "decision": asdict(decision),
            "remittance_count": len(rt["remittances"]),
        },
    )


def handle_post_attest_remittance(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
    now_epoch: int,
) -> dict[str, Any]:
    """Resolve an UNVERIFIED_REMITTANCE_HOLD via additive human Identity Attestation (B2)."""
    kd.require_capability(actor, kd.Capability.ISSUE_DOCS, tid)
    rt = get_tenant_superset_bundle(tid, state)
    rem_id = str(body.get("remittance_id") or "").strip()
    verified_ref = str(body.get("verified_transfer_reference") or "SEPA-ATTESTED-20261022-9901").strip()
    reason = str(body.get("reason") or "Cross-checked with bank statement line #44").strip()

    target_idx = -1
    for idx, r in enumerate(rt["remittances"]):
        if r.remittance_id == rem_id or (
            not rem_id and r.classification == kd.RemittanceClassification.UNVERIFIED_REMITTANCE_HOLD
        ):
            target_idx = idx
            break
    if target_idx < 0:
        raise KeyError(f"Unverified remittance not found: {rem_id}")

    resolved_rem, attestation = kd.attest_remittance_identity(
        rt["remittances"][target_idx],
        verified_transfer_reference=verified_ref,
        actor_id=actor.actor_id,
        reason=reason,
        now_epoch=now_epoch,
    )
    rt["remittances"][target_idx] = resolved_rem
    rt["attestations"].append(attestation)
    return json_reply(
        200,
        {
            "status": "ATTESTED_AND_RELEASED",
            "remittance": asdict(resolved_rem),
            "attestation": asdict(attestation),
        },
    )


def handle_post_dispute_hold(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
) -> dict[str, Any]:
    """Place or resolve a ClientDisputeHold on an invoice (What changes the decision) (B1, B2)."""
    kd.require_capability(actor, kd.Capability.ISSUE_DOCS, tid)
    rt = get_tenant_superset_bundle(tid, state)
    action = str(body.get("action") or "place_hold").strip().lower()
    doc_id = str(body.get("document_id") or rt["default_doc_id"]).strip()

    if action == "resolve":
        resolution_note = str(
            body.get("resolution_note") or "Confirmed delivery pod & credit note adjustment with client."
        ).strip()
        for idx, d in enumerate(rt["dispute_holds"]):
            if d.document_id == doc_id and d.status == "OPEN_HOLD":
                rt["dispute_holds"][idx] = kd.ClientDisputeHold(
                    dispute_hold_id=d.dispute_hold_id,
                    tenant_id=tid,
                    document_id=d.document_id,
                    counterparty_id=d.counterparty_id,
                    client_email_sha256=d.client_email_sha256,
                    client_excerpt=d.client_excerpt,
                    status="RESOLVED",
                    resolution_note=resolution_note,
                    resolved_by_actor_id=actor.actor_id,
                )
        graph_rep = kd.run_six_reader_strands_graph(
            state, doc_id, remittances=tuple(rt["remittances"]), dispute_holds=tuple(rt["dispute_holds"])
        )
        verdict = kd.verify_outbound_draft_release_gate(graph_rep)
        return json_reply(
            200,
            {
                "status": "DISPUTE_HOLD_RESOLVED",
                "six_reader_graph": asdict(graph_rep),
                "release_gate_verdict": asdict(verdict),
            },
        )

    excerpt = str(
        body.get("client_excerpt")
        or "We dispute 2 damaged units on this invoice; please pause collection until credit note is issued."
    ).strip()
    hold = kd.ClientDisputeHold(
        dispute_hold_id=f"dhold-{len(rt['dispute_holds']) + 1:03d}",
        tenant_id=tid,
        document_id=doc_id,
        counterparty_id=rt["default_cust_id"],
        client_email_sha256=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        client_excerpt=excerpt,
        status="OPEN_HOLD",
    )
    rt["dispute_holds"].append(hold)
    graph_rep = kd.run_six_reader_strands_graph(
        state, doc_id, remittances=tuple(rt["remittances"]), dispute_holds=tuple(rt["dispute_holds"])
    )
    verdict = kd.verify_outbound_draft_release_gate(graph_rep)
    return json_reply(
        200,
        {
            "status": "COLLECTION_HOLD_ACTIVE",
            "dispute_hold": asdict(hold),
            "six_reader_graph": asdict(graph_rep),
            "release_gate_verdict": asdict(verdict),
        },
    )


def handle_post_strands_gate_verify(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
) -> dict[str, Any]:
    """Run the 6-Reader Strands Graph and deterministic post-composer Release Gate (B1)."""
    evaluator = kd.Evaluator(actor)
    rt = get_tenant_superset_bundle(tid, state)
    doc_id = str(body.get("document_id") or rt["default_doc_id"]).strip()
    candidate_prose = body.get("candidate_prose")
    candidate_recipient = body.get("candidate_recipient")

    def _run() -> dict[str, Any]:
        rep = kd.run_six_reader_strands_graph(
            state,
            doc_id,
            remittances=tuple(rt["remittances"]),
            dispute_holds=tuple(rt["dispute_holds"]),
        )
        verdict = kd.verify_outbound_draft_release_gate(
            rep,
            candidate_prose=str(candidate_prose) if candidate_prose is not None else None,
            candidate_recipient=str(candidate_recipient) if candidate_recipient is not None else None,
        )
        return {
            "six_reader_graph": asdict(rep),
            "release_gate_verdict": asdict(verdict),
        }

    res = evaluator.evaluate(tid, _run)
    return json_reply(200, res)


def handle_post_portfolio_mode(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
) -> dict[str, Any]:
    """Switch between compact DEMO_SEED and 240-record FULL_240_PORTFOLIO (B3)."""
    kd.require_capability(actor, kd.Capability.ISSUE_DOCS, tid)
    rt = get_tenant_superset_bundle(tid, state)
    mode = str(body.get("mode") or "FULL_240_PORTFOLIO").strip().upper()
    if mode not in ("DEMO_SEED", "FULL_240_PORTFOLIO"):
        mode = "FULL_240_PORTFOLIO"
    rt["portfolio_mode"] = mode
    if mode == "FULL_240_PORTFOLIO":
        for ds_id in ("kerdon-hellenic-eu-v1", "kerdon-universal-en-v1", "kerdon-vision-multimodal-v1", "open-erp-peppol-iso20022-finqa-v1"):
            kd.import_public_dataset_into_tenant(state, ds_id)
    summary = kd.build_240_record_portfolio(tid)
    return json_reply(
        200,
        {
            "active_mode": mode,
            "total_records": summary.total_records,
            "portfolio": asdict(summary),
        },
    )


def handle_get_evidence_bundle(
    tid: str,
    state: kd.TenantMiniErpState,
    reader: kd.Reader,
    *,
    head_only: bool = False,
) -> dict[str, Any]:
    """Export redacted, readable audit evidence bundle (B4)."""
    rt = get_tenant_superset_bundle(tid, state)
    doc_id = rt["default_doc_id"]
    rep = kd.run_six_reader_strands_graph(
        state,
        doc_id,
        remittances=tuple(rt["remittances"]),
        dispute_holds=tuple(rt["dispute_holds"]),
    )
    bundle = reader.read(
        tid,
        lambda: kd.build_redacted_evidence_bundle(
            state,
            graph_reports=(rep,),
            attestations=tuple(rt["attestations"]),
            dispute_holds=tuple(rt["dispute_holds"]),
        ),
    )
    return json_reply(200, bundle, head_only=head_only)


def handle_post_invite(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
    now_epoch: int,
) -> dict[str, Any]:
    """Create or claim a workspace invite (0014_invite_claim) (A6)."""
    kd.require_capability(actor, kd.Capability.ISSUE_DOCS, tid)
    rt = get_tenant_superset_bundle(tid, state)
    action = str(body.get("action") or "create").strip().lower()
    if action == "claim":
        invite_id = str(body.get("invite_id") or "").strip()
        for idx, inv in enumerate(rt["invites"]):
            if inv.invite_id == invite_id or not invite_id:
                claimed = kd.claim_workspace_invite(inv, actor_id=actor.actor_id)
                rt["invites"][idx] = claimed
                return json_reply(200, {"status": "INVITE_CLAIMED", "invite": asdict(claimed)})
        raise KeyError(f"Unknown invite_id: {invite_id}")

    email = str(body.get("email") or f"controller@{state.tenant.slug}.gr").strip()
    role_str = str(body.get("role") or "STORE_MANAGER").strip().upper()
    role = getattr(kd.Role, role_str, kd.Role.STORE_MANAGER)
    inv = kd.create_workspace_invite(
        tenant_id=tid,
        email=email,
        role=role,
        invited_by=actor.actor_id,
        now_epoch=now_epoch,
    )
    rt["invites"].append(inv)
    return json_reply(
        200,
        {
            "status": "INVITE_CREATED",
            "invite": asdict(inv),
            "invites": [asdict(i) for i in rt["invites"]],
        },
    )


def handle_post_subscription_switch(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
) -> dict[str, Any]:
    """Switch tenant subscription plan (entry €29, standard €49, pro €79) and update entitlements (A6)."""
    kd.require_capability(actor, kd.Capability.ISSUE_DOCS, tid)
    rt = get_tenant_superset_bundle(tid, state)
    plan_code = str(body.get("plan_code") or "pro").strip().lower()
    if plan_code not in ("entry", "standard", "pro"):
        raise ValidationError("plan_code must be entry, standard, or pro")
    prices = {"entry": 29, "standard": 49, "pro": 79}
    rt["subscription_plan"] = plan_code
    rt["subscription_price_eur"] = prices[plan_code]
    entitlements = list(kd.resolve_plan_entitlements(plan_code))
    return json_reply(
        200,
        {
            "status": "SUBSCRIPTION_UPDATED",
            "tenant_id": tid,
            "plan_code": plan_code,
            "monthly_price_eur": prices[plan_code],
            "entitlements": entitlements,
        },
    )
