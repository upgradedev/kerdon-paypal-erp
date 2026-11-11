"""Least-Privilege HTTP API v2 and Step Functions handlers for Kerdon MSP."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import os
import time
from typing import Any

import kerdon as kd
from kerdon.erp_services import reset_erp_extensions

from .bedrock_adapter import answer_query_with_bedrock, run_eight_stage_erp_workflow
from .connectors_adapter import ExternalProviderError, reset_connector_runtime_secrets
from .gtm_routes import (
    handle_get_export_csv,
    handle_get_full_state,
    handle_get_gtm_pricing,
    handle_get_gtm_readiness,
    handle_post_booking,
    handle_post_invoice,
    handle_post_learn_memory,
    handle_post_marketplace_meter_usage,
    handle_post_marketplace_resolve_customer,
    handle_post_opening_balance,
)
from .http_utils import PayloadTooLargeError, ValidationError, extract_http_route, html_reply, json_reply, parse_json_body
from .identity import (
    AuthenticationError,
    SubjectMembershipRegistry,
    is_strict_auth_mode,
    resolve_authenticated_actor,
    resolve_jwt_tenant_route,
)
from .inventory_routes import handle_get_inventory, handle_post_inventory_movement, reset_inventory_runtime
from .persistence import MultiTenantStore, PersistenceError, VersionConflictError, get_store
from .sandbox_provider import reset_sandbox_runtime
from .superset_routes import (
    handle_get_draft_pdf,
    handle_get_evidence_bundle,
    handle_get_seller_private_statement,
    handle_post_attest_remittance,
    handle_post_classify_remittance,
    handle_post_dispute_hold,
    handle_post_invite,
    handle_post_portfolio_mode,
    handle_post_seller_dispute,
    handle_post_send_draft,
    handle_post_simulate_commission_plan,
    handle_post_strands_gate_verify,
    handle_post_subscription_switch,
    handle_post_supersede_settlement,
    reset_superset_runtime,
)
from .workspace_routes import workspace_post_response, workspace_response, workspace_root_post_response


def _deployed_sha() -> str:
    return os.environ.get("DEPLOYED_SHA", "local-dev")


def _now_epoch(event: dict[str, Any], body: dict[str, Any] | None = None) -> int:
    raw = (body or {}).get("now_epoch", event.get("now_epoch", int(time.time())))
    if isinstance(raw, bool):
        raise ValidationError("now_epoch must be an integer")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError("now_epoch must be an integer") from exc


def _resolve_actor(event: dict[str, Any], store: MultiTenantStore, *, path: str = "") -> kd.Actor:
    return resolve_authenticated_actor(event, store.identity_registry, store.workspace.director, path=path)


def lambda_reader(event: dict[str, Any], context: Any = None, *, store: MultiTenantStore | None = None) -> dict[str, Any]:
    """Least-Privilege Reader Lambda entrypoint. Refuses all POST mutations (A7)."""
    return dispatch_http_event(event, role_mode="reader", store=store)


def lambda_evaluator(event: dict[str, Any], context: Any = None, *, store: MultiTenantStore | None = None) -> dict[str, Any]:
    """Least-Privilege Evaluator Lambda entrypoint for Strands/Bedrock evaluation (A7)."""
    return dispatch_http_event(event, role_mode="evaluator", store=store)


def lambda_writer(event: dict[str, Any], context: Any = None, *, store: MultiTenantStore | None = None) -> dict[str, Any]:
    """Governed Writer Lambda entrypoint for approved state mutations and Step Functions."""
    active_store = store or get_store()
    if isinstance(event, dict) and event.get("action") == "month_end_close":
        tid = str(event.get("tenant_id") or active_store.workspace.default_tenant_id)
        state = active_store.get_tenant_state(tid)
        wf_res = run_eight_stage_erp_workflow(state)
        active_store.persist_audit_record(tid, "MONTH_END_CLOSE", wf_res.period, asdict(wf_res))
        return {
            "status": "SUCCEEDED",
            "tenant_id": tid,
            "period": wf_res.period,
            "source": wf_res.source,
            "merkle_root_sha256": state.board_pack.handoff_packet.merkle_root_sha256,
        }
    return dispatch_http_event(event, role_mode="writer", store=active_store)


def dispatch_http_event(
    event: dict[str, Any],
    *,
    role_mode: str = "all",
    store: MultiTenantStore | None = None,
) -> dict[str, Any]:
    """Unified HTTP API v2 router enforcing role_mode separation and Trap T6 guards."""
    active_store = store or get_store()
    method, path = extract_http_route(event)
    head_only = method == "HEAD"

    if method == "OPTIONS":
        return json_reply(200, {"status": "ok"})

    if role_mode == "reader" and method not in ("GET", "HEAD"):
        return json_reply(
            403,
            {"error": "Reader identity cannot execute state mutations (Least Privilege A7)", "role_mode": role_mode},
        )
    _eval_suffixes = (
        "/evaluate",
        "/query",
        "/commissions/simulate",
        "/commissions/plan-diff",
        "/strands-gate/verify",
        "/ai/extract-document",
    )
    if role_mode == "evaluator":
        if not (method == "POST" and any(path.endswith(s) for s in _eval_suffixes)):
            return json_reply(
                403,
                {"error": "Evaluator identity is restricted to non-mutating evaluation routes (Least Privilege A7)", "role_mode": role_mode},
            )
    if role_mode == "writer":
        if method != "POST" or any(path.endswith(s) for s in _eval_suffixes):
            return json_reply(
                403,
                {"error": "Writer identity is restricted to governed state-mutation POST routes (Least Privilege A7)", "role_mode": role_mode},
            )

    def _replay_journal_mutation(replay_path: str, replay_body: dict[str, Any], replay_role: str) -> None:
        actor_hdr = str(replay_body.get("_journal_actor_id") or active_store.workspace.director.actor_id)
        replay_ev = {
            "version": "2.0",
            "rawPath": replay_path,
            "_internal_journal_replay": True,
            "headers": {"x-kerdon-role": replay_role, "x-kerdon-actor": actor_hdr},
            "requestContext": {"http": {"method": "POST", "path": replay_path}},
        }
        replay_actor = _resolve_actor(replay_ev, active_store)
        _handle_post(replay_path, body=replay_body, actor=replay_actor, store=active_store, event=replay_ev)

    def _reset_local_workspace() -> None:
        active_store.workspace = kd.build_default_msp_workspace()
        active_store.identity_registry = SubjectMembershipRegistry()
        reset_superset_runtime()
        reset_inventory_runtime()
        reset_erp_extensions()
        reset_sandbox_runtime()
        reset_connector_runtime_secrets()
        kd.reset_connector_states()

    try:
        active_store.sync_from_dynamodb(_replay_journal_mutation, _reset_local_workspace)
        actor = _resolve_actor(event, active_store, path=path)
        path, actor = resolve_jwt_tenant_route(path, event, actor, active_store)
        if method in ("GET", "HEAD"):
            return _handle_get_or_head(path, head_only=head_only, actor=actor, store=active_store, event=event)
        if method == "POST":
            body = parse_json_body(event)
            resp = _handle_post(path, body=body, actor=actor, store=active_store, event=event)
            if resp.get("statusCode") in (200, 201):
                if path.endswith("/reset"):
                    active_store.write_journal_reset()
                elif not any(
                    path.endswith(s)
                    for s in (
                        *_eval_suffixes,
                        "/connectors/verify",
                        "/connectors/paypal/oauth/start",
                        "/connectors/paypal/disputes/sync",
                    )
                ):
                    body.setdefault("_journal_actor_id", actor.actor_id)
                    active_store.append_journal_mutation(path, body, actor.role.value)
            return resp
        return json_reply(405, {"error": f"Method {method} not allowed"})
    except PayloadTooLargeError as exc:
        return json_reply(413, {"error": str(exc)})
    except ValidationError as exc:
        return json_reply(400, {"error": str(exc)})
    except AuthenticationError as exc:
        return json_reply(401, {"error": str(exc)})
    except (kd.PermissionDeniedError, kd.SelfApprovalError, PermissionError) as exc:
        return json_reply(403, {"error": str(exc)})
    except (kd.StaleApprovalInvalidatedError, kd.DuplicateIdempotencyError, VersionConflictError) as exc:
        return json_reply(409, {"error": str(exc)})
    except (kd.ReserveFloorBreachError, kd.ExpiredFxQuoteError, kd.UnbalancedEntryError, kd.HtmlBodyPostingError) as exc:
        return json_reply(422, {"error": str(exc)})
    except ExternalProviderError as exc:
        return json_reply(
            502,
            {
                "error": str(exc),
                "provider_issue": getattr(exc, "issue", ""),
                "paypal_debug_id": getattr(exc, "debug_id", ""),
                "upstream_status": getattr(exc, "http_status", 502),
            },
        )
    except PersistenceError as exc:
        return json_reply(503, {"error": str(exc)})
    except KeyError as exc:
        return json_reply(404, {"error": str(exc)})
    except RuntimeError as exc:
        return json_reply(502, {"error": str(exc)})


def _handle_get_or_head(
    path: str,
    *,
    head_only: bool,
    actor: kd.Actor,
    store: MultiTenantStore,
    event: dict[str, Any],
) -> dict[str, Any]:
    sha = _deployed_sha()
    response = workspace_response(path, actor, store, event, head_only)
    if response is not None:
        return response
    if path == "/health":
        return json_reply(
            200,
            {
                "status": "ok",
                "service": "kerdon-msp",
                "deployed_sha": sha,
                "tenant_count": len(store.workspace.catalog.tenants),
                "completeness_rules": len(kd.GapRuleId),
            },
            head_only=head_only,
        )
    if path == "/DEPLOYED_SHA":
        return json_reply(200, {"deployed_sha": sha, "service": "kerdon-msp"}, head_only=head_only)
    if path == "/gtm/pricing":
        return handle_get_gtm_pricing(event, head_only=head_only)
    if path == "/gtm/readiness":
        def_tid = store.workspace.default_tenant_id
        return handle_get_gtm_readiness(def_tid, store.get_tenant_state(def_tid), store, kd.Reader(actor), head_only=head_only)

    reader = kd.Reader(actor)
    if path == "/tenants":
        visible = [
            {
                "tenant_id": t.tenant_id,
                "slug": t.slug,
                "display_name": t.display_name,
                "tier": t.tier.value,
                "tax_id": t.fiscal_identity.tax_id,
                "inbox_address": t.inbox_address,
            }
            for t in store.workspace.catalog.tenants.values()
            if actor.has_capability(kd.Capability.VIEW_PNL, t.tenant_id)
            or actor.has_capability(kd.Capability.VIEW_OWN_SALES, t.tenant_id)
        ]
        if not visible:
            raise kd.PermissionDeniedError(f"Actor {actor.actor_id} has no readable tenant memberships")
        return json_reply(200, {"tenants": visible}, head_only=head_only)

    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "tenants":
        tid = parts[1]
        state = store.get_tenant_state(tid)
        sub = "/".join(parts[2:])

        if sub in ("", "overview"):
            can_payroll = actor.has_capability(kd.Capability.VIEW_PAYROLL, tid)
            payload = reader.read(
                tid,
                lambda: {
                    "tenant": asdict(state.tenant),
                    "pnl": asdict(state.board_pack.pnl),
                    "mom_trend": asdict(state.board_pack.mom_trend),
                    "workforce_fusion": {
                        "true_employer_cost_cents": state.workforce_fusion.true_employer_cost_cents,
                        "gross_wages_cents": state.workforce_fusion.gross_wages_cents,
                        "employer_social_security_cents": state.workforce_fusion.employer_social_security_cents,
                        "total_apd_payable_cents": state.workforce_fusion.total_apd_payable_cents,
                        "total_fmy_payable_cents": state.workforce_fusion.total_fmy_payable_cents,
                        "net_salary_payable_cents": state.workforce_fusion.net_salary_payable_cents,
                    } if can_payroll else {"redacted": True},
                    "vat_summary": asdict(state.vat_summary),
                    "open_gap_count": len(state.gaps),
                },
            )
            return json_reply(200, payload, head_only=head_only)

        if sub == "full-state":
            return handle_get_full_state(tid, state, store, event, reader, head_only=head_only)
        if sub == "gtm/readiness":
            return handle_get_gtm_readiness(tid, state, store, reader, head_only=head_only)
        if sub == "export/journal-csv":
            return handle_get_export_csv(tid, state, reader, head_only=head_only)
        if sub == "ledger":
            payload = reader.read(
                tid,
                lambda: {
                    "tenant_id": tid,
                    "pnl": asdict(state.board_pack.pnl),
                    "events": [asdict(ev) for ev in state.ledger.events],
                },
            )
            return json_reply(200, payload, head_only=head_only)

        if sub == "commissions":
            payload = reader.read(
                tid,
                lambda: {
                    "tenant_id": tid,
                    "commission_case": asdict(state.commission_case),
                    "total_payable_cents": state.commission_case.total_payable_cents,
                    "settlements": [asdict(s) for s in state.settlements],
                },
            )
            return json_reply(200, payload, head_only=head_only)

        if sub == "completeness":
            payload = reader.read(
                tid,
                lambda: {
                    "tenant_id": tid,
                    "rule_count": len(kd.GapRuleId),
                    "gaps": [asdict(g) for g in state.gaps],
                    "reasonings": [asdict(r) for r in state.reasonings],
                    "digest": asdict(state.digest),
                },
            )
            return json_reply(200, payload, head_only=head_only)

        if sub == "board-pack":
            payload = reader.read(
                tid,
                lambda: {
                    "tenant_id": tid,
                    "board_pack": asdict(state.board_pack),
                    "outbound_drafts": [asdict(d) for d in state.outbound_drafts],
                },
            )
            return json_reply(200, payload, head_only=head_only)

        if sub == "treasury":
            if not (
                actor.has_capability(kd.Capability.APPROVE_PAYOUTS, tid)
                or actor.has_capability(kd.Capability.EXECUTE_PAYOUTS, tid)
            ):
                raise kd.PermissionDeniedError(
                    f"Actor {actor.actor_id} ({actor.role.value}) lacks treasury inspection capability"
                )
            payload = reader.read(
                tid,
                lambda: {
                    "tenant_id": tid,
                    "pockets": {k: asdict(v) for k, v in state.treasury.pockets.items()},
                    "approvals": {k: asdict(v) for k, v in state.treasury.approvals.items()},
                    "receipts": {k: asdict(v) for k, v in state.treasury.receipts.items()},
                },
            )
            return json_reply(200, payload, head_only=head_only)

        if len(parts) == 5 and parts[2] == "documents" and parts[4] == "link":
            doc_id = parts[3]
            now_ts = _now_epoch(event)
            link = reader.read(tid, lambda: state.crm.mint_signed_download_link(doc_id, now_epoch=now_ts))
            return json_reply(200, asdict(link), head_only=head_only)

        if len(parts) == 5 and parts[2] == "docgen" and parts[4] == "pdf":
            return handle_get_draft_pdf(tid, parts[3], state, event, reader, head_only=head_only)
        if sub == "commissions/seller-statement":
            return handle_get_seller_private_statement(tid, state, event, reader, head_only=head_only)
        if sub == "evidence-bundle":
            return handle_get_evidence_bundle(tid, state, reader, head_only=head_only)
        if sub == "inventory":
            return handle_get_inventory(tid, state, reader, head_only=head_only)

    return json_reply(404, {"error": f"Unknown route: {path}"}, head_only=head_only)


def _handle_post(
    path: str,
    *,
    body: dict[str, Any],
    actor: kd.Actor,
    store: MultiTenantStore,
    event: dict[str, Any],
) -> dict[str, Any]:
    now_ts = _now_epoch(event, body)

    if path == "/tenants/onboard":
        slug = str(body.get("slug") or "").strip()
        display_name = str(body.get("display_name") or "").strip()
        legal_name = str(body.get("legal_name") or display_name).strip()
        tax_id = str(body.get("tax_id") or "").strip()
        if not slug or not display_name or not tax_id:
            raise ValidationError("slug, display_name, and tax_id are required")

        writer = kd.Writer(actor)
        tenant = writer.execute(
            store.workspace.default_tenant_id,
            kd.Capability.ONBOARD_TENANT,
            approval_token=f"onboard-{slug}",
            mutation_fn=lambda: store.workspace.catalog.onboard_tenant(
                slug=slug, display_name=display_name, legal_name=legal_name, tax_id=tax_id
            ),
        )
        use_empty = bool(body.get("empty_state")) or is_strict_auth_mode(event)
        if use_empty:
            store.workspace.tenant_states[tenant.tenant_id] = kd.build_empty_tenant_state(
                store.workspace.catalog, tenant
            )
        else:
            from kerdon.demo_fixtures import _build_tenant_state

            store.workspace.tenant_states[tenant.tenant_id] = _build_tenant_state(
                store.workspace.catalog, tenant, scale=50
            )
        store.persist_audit_record(tenant.tenant_id, "ONBOARD", tenant.tenant_id, asdict(tenant))
        return json_reply(201, {"tenant": asdict(tenant), "empty_state": use_empty})

    is_replay = bool(event.get("_internal_journal_replay"))
    if path == "/gtm/marketplace/resolve-customer":
        return handle_post_marketplace_resolve_customer(body, actor, store, is_replay=is_replay)
    if path == "/gtm/marketplace/meter-usage":
        return handle_post_marketplace_meter_usage(body, actor, store, is_replay=is_replay)

    root_resp = workspace_root_post_response(path, body, actor, store, event, now_ts)
    if root_resp is not None:
        return root_resp

    parts = [p for p in path.split("/") if p]
    if len(parts) < 3 or parts[0] != "tenants":
        return json_reply(404, {"error": f"Unknown POST route: {path}"})

    tid = parts[1]
    body_tid = str(body.get("tenant_id") or "").strip()
    if body_tid and body_tid != tid:
        raise kd.PermissionDeniedError(
            f"Cross-tenant isolation violation: URL tenant '{tid}' conflicts with body tenant '{body_tid}'"
        )
    state = store.get_tenant_state(tid)
    sub = "/".join(parts[2:])

    if sub == "reset":
        writer = kd.Writer(actor)
        writer.execute(
            tid,
            kd.Capability.ONBOARD_TENANT,
            approval_token=f"reset-{tid}",
            mutation_fn=lambda: (
                setattr(store, "workspace", kd.build_default_msp_workspace()),
                setattr(store, "identity_registry", SubjectMembershipRegistry()),
                reset_superset_runtime(),
                reset_inventory_runtime(),
                reset_erp_extensions(),
                reset_sandbox_runtime(),
                reset_connector_runtime_secrets(),
                kd.reset_connector_states(),
            ),
        )
        return json_reply(200, {"status": "reset", "tenant_id": tid})

    if sub == "evaluate":
        wf = kd.Evaluator(actor).evaluate(
            tid, lambda: run_eight_stage_erp_workflow(state, require_live=bool(body.get("require_live", False)))
        )
        return json_reply(200, asdict(wf))

    if sub == "query":
        question = str(body.get("question") or "").strip()
        if not question:
            raise ValidationError("question is required and must not be empty")
        ans = kd.Evaluator(actor).evaluate(tid, lambda: answer_query_with_bedrock(question, state.fact_sheet))
        return json_reply(200, asdict(ans))

    if sub == "commissions/simulate":
        sales_cents = body.get("sales_cents")
        if not isinstance(sales_cents, int) or isinstance(sales_cents, bool) or sales_cents < 0:
            raise ValidationError("sales_cents must be a non-negative integer")
        gross = kd.Evaluator(actor).evaluate(
            tid, lambda: kd.compute_tier_commission(sales_cents, state.commission_plan)
        )
        return json_reply(
            200,
            {
                "tenant_id": tid,
                "plan_id": state.commission_plan.plan_id,
                "sales_cents": sales_cents,
                "simulated_commission_cents": gross,
            },
        )

    writer = kd.Writer(actor)

    if sub == "ingest/email":
        msg_id = str(body.get("message_id") or f"msg-{now_ts}").strip()
        sender = str(body.get("sender") or "").strip()
        subject = str(body.get("subject") or "").strip()
        if not sender or not subject:
            raise ValidationError("sender and subject are required")
        filename = str(body.get("attachment_filename") or "invoice.pdf").strip()
        content_str = str(body.get("attachment_content") or f"PDF-{msg_id}").strip()
        raw_bytes = content_str.encode("utf-8")

        envelope = kd.RawEmailEnvelope(
            message_id=msg_id,
            tenant_id=tid,
            sender=sender,
            recipient=state.tenant.inbox_address,
            subject=subject,
            received_at_epoch=now_ts,
            attachments=(
                kd.AttachmentPayload(
                    attachment_id=f"att-{msg_id}",
                    filename=filename,
                    mime_type="application/pdf",
                    raw_bytes=raw_bytes,
                ),
            ),
        )
        hashes = writer.execute(
            tid, kd.Capability.ISSUE_DOCS, approval_token=f"ingest-{msg_id}", mutation_fn=lambda: state.inbox.ingest_email(envelope)
        )
        s3_key = None if is_replay else store.persist_evidence_blob(tid, hashes[0], raw_bytes, "application/pdf")
        cand_dict: dict[str, Any] | None = None
        try:
            draft_ext = kd.extract_erp_document_draft(state, f"{subject}\n{content_str}", preferred_module="purchases")
            doc_kind = kd.CandidateDocKind.SALES_INVOICE if draft_ext.direction == "SALES_REVENUE" else kd.CandidateDocKind.PURCHASE_INVOICE
            cand = kd.ExtractedCandidate(
                candidate_id=f"cand-{msg_id}",
                tenant_id=tid,
                doc_kind=doc_kind,
                source_kind=kd.EvidenceSourceKind.PDF_ATTACHMENT,
                counterparty_name=draft_ext.counterparty_name,
                counterparty_tax_id=draft_ext.counterparty_tax_id,
                net_cents=draft_ext.total_net_cents,
                vat_cents=draft_ext.total_vat_cents,
                gross_cents=draft_ext.total_gross_cents,
                currency=draft_ext.currency,
                issued_date=draft_ext.issued_date,
                due_date=draft_ext.due_date,
                provenance=kd.FieldProvenance(
                    message_id=msg_id,
                    attachment_id=f"att-{msg_id}",
                    source_sha256=hashes[0],
                    page=1,
                    raw_snippet=content_str[:120],
                ),
            )
            state.inbox.register_candidate(cand)
            cand_dict = asdict(cand)
        except ValueError:
            cand_dict = None
        return json_reply(
            201,
            {"tenant_id": tid, "message_id": msg_id, "blob_sha256": hashes[0], "s3_key": s3_key, "extracted_candidate": cand_dict},
        )

    if sub == "credit-notes":
        cn_id = str(body.get("credit_note_id") or "").strip()
        cp_id = str(body.get("counterparty_id") or "").strip()
        net_cents = body.get("net_cents")
        vat_cents = body.get("vat_cents")
        gross_cents = body.get("gross_cents")
        ref_inv = str(body.get("referenced_invoice_id") or "").strip()
        if (
            not cn_id
            or not cp_id
            or not isinstance(net_cents, int)
            or not isinstance(vat_cents, int)
            or not isinstance(gross_cents, int)
            or gross_cents <= 0
            or net_cents < 0
            or vat_cents < 0
            or net_cents + vat_cents != gross_cents
        ):
            raise ValidationError(
                "credit_note_id, counterparty_id, and balanced integer net_cents + vat_cents == gross_cents > 0 are required"
            )
        cn_sha = hashlib.sha256(f"{tid}:{cn_id}:{cp_id}:{gross_cents}".encode("utf-8")).hexdigest()
        issued_date = str(body.get("issued_date") or "2026-10-31")
        cn = kd.CreditNote(
            credit_note_id=cn_id,
            tenant_id=tid,
            direction=kd.Direction.PURCHASE_EXPENSE,
            counterparty_id=cp_id,
            net_cents=net_cents,
            vat_cents=vat_cents,
            gross_cents=gross_cents,
            currency=str(body.get("currency") or "EUR"),
            issued_date=issued_date,
            source_sha256=cn_sha,
            referenced_invoice_id=ref_inv,
        )

        def _apply_cn() -> tuple[str, ...]:
            state.crm.register_credit_note(cn)
            ev_id = f"ev-cn-{cn_id}"
            if not any(e.event_id == ev_id for e in state.ledger.events):
                lines = [
                    kd.LedgerLine(account=kd.AccountCode.AP_2000, debit_cents=gross_cents, counterparty_id=cp_id),
                    kd.LedgerLine(account=kd.AccountCode.OPEX_GENERAL_6200, credit_cents=net_cents, counterparty_id=cp_id),
                ]
                if vat_cents > 0:
                    lines.append(
                        kd.LedgerLine(account=kd.AccountCode.VAT_INPUT_1400, credit_cents=vat_cents, counterparty_id=cp_id)
                    )
                state.ledger.post(
                    kd.FinancialEvent(
                        event_id=ev_id,
                        tenant_id=tid,
                        period=issued_date[:7],
                        posted_date=issued_date,
                        description=f"Supplier credit note {cn_id}",
                        source_document_id=cn_id,
                        source_sha256=cn_sha,
                        lines=tuple(lines),
                    )
                )
            if ref_inv and ref_inv in state.crm.documents:
                orig_doc = state.crm.documents[ref_inv]
                new_paid = min(orig_doc.gross_cents, orig_doc.paid_cents + gross_cents)
                state.crm.documents[ref_inv] = kd.DocumentRegisterEntry(**{**asdict(orig_doc), "paid_cents": new_paid})
            pnl = state.ledger.summarize_period("2026-10")
            mom = state.ledger.compute_mom_trend("2026-10", "2026-09")
            state.board_pack = kd.build_cfo_board_pack(
                tenant_id=tid,
                period="2026-10",
                pnl=pnl,
                mom_trend=mom,
                vat_summary=state.vat_summary,
                commission_case=state.commission_case,
                digest=state.digest,
                document_sha256s=(cn_sha, state.board_pack.handoff_packet.merkle_root_sha256),
            )
            state.fact_sheet = kd.build_fact_sheet(
                tenant_name=state.tenant.display_name,
                pnl=pnl,
                mom_trend=mom,
                vat_summary=state.vat_summary,
                commission_case=state.commission_case,
                gaps=state.gaps,
            )
            return state.treasury.notify_changed_evidence(
                counterparty_id=cp_id,
                new_evidence_sha256=cn_sha,
                reason=f"Credit note {cn_id} ({kd.format_eur(gross_cents)}) arrived",
                invoice_or_case_id=ref_inv or None,
            )

        invalidated = writer.execute(
            tid, kd.Capability.APPROVE_PAYOUTS, approval_token=f"cn-{cn_id}", mutation_fn=_apply_cn
        )
        store.persist_audit_record(
            tid, "CREDIT_NOTE_INVALIDATION", cn_id, {"credit_note_id": cn_id, "invalidated_approval_ids": list(invalidated)}
        )
        for inv_ap_id in invalidated:
            store.persist_approval_state(inv_ap_id, tid, "INVALIDATED", cn_sha)
        return json_reply(200, {"credit_note": asdict(cn), "invalidated_approval_ids": list(invalidated)})

    if sub == "commissions/approve":
        approver_id = str(body.get("approver_id") or actor.actor_id).strip()
        submitted_by = str(body.get("submitted_by") or state.commission_case.submitted_by or "mgr-store-lead").strip()
        sub_case = kd.submit_commission_case(state.commission_case, submitted_by)
        approved = writer.execute(
            tid,
            kd.Capability.APPROVE_COMMISSIONS,
            approval_token=f"4eyes-{approver_id}",
            mutation_fn=lambda: kd.approve_commission_case(sub_case, approver_id),
        )
        state.commission_case = approved
        aletheia = kd.seal_aletheia_receipt(
            tenant_id=tid,
            subject_id=approved.case_id,
            approver_id=approver_id,
            amount_cents=approved.total_payable_cents,
            currency="EUR",
            evidence_hashes=(state.board_pack.handoff_packet.merkle_root_sha256,),
        )
        return json_reply(200, {"commission_case": asdict(approved), "aletheia_receipt": asdict(aletheia)})

    if sub == "treasury/approvals":
        ap_id = str(body.get("approval_id") or "").strip()
        cp_id = str(body.get("counterparty_id") or "").strip()
        inv_id = str(body.get("invoice_or_case_id") or "").strip()
        amt = body.get("amount_cents")
        ccy = str(body.get("currency") or "EUR").strip()
        ev_sha = str(body.get("evidence_sha256") or "").strip()
        if (
            not ap_id
            or not cp_id
            or not inv_id
            or not ev_sha
            or not isinstance(amt, int)
            or isinstance(amt, bool)
            or amt <= 0
        ):
            raise ValidationError(
                "approval_id, counterparty_id, invoice_or_case_id, evidence_sha256, and positive integer amount_cents are required"
            )
        if inv_id not in state.crm.documents and inv_id != state.commission_case.case_id:
            raise ValidationError(
                f"Payable '{inv_id}' does not exist in tenant document register or commission case"
            )
        recipient_acct = str(body.get("recipient_account") or body.get("recipient_email") or "").strip()
        prep_id = str(body.get("preparer_id") or actor.actor_id).strip()
        ap = writer.execute(
            tid,
            kd.Capability.APPROVE_PAYOUTS,
            approval_token=f"create-{ap_id}",
            mutation_fn=lambda: state.treasury.create_approval(
                approval_id=ap_id,
                counterparty_id=cp_id,
                invoice_or_case_id=inv_id,
                amount_cents=amt,
                currency=ccy,
                evidence_sha256=ev_sha,
                approver_id=actor.actor_id,
                now_epoch=now_ts,
                recipient_account=recipient_acct,
                preparer_id=prep_id,
            ),
        )
        return json_reply(201, {"approval": asdict(ap)})

    if sub == "treasury/execute":
        ap_id = str(body.get("approval_id") or "").strip()
        if not ap_id:
            raise ValidationError("approval_id is required")
        rcpt = writer.execute(
            tid,
            kd.Capability.EXECUTE_PAYOUTS,
            approval_token=ap_id,
            mutation_fn=lambda: state.treasury.execute_payout(
                approval_id=ap_id, now_epoch=now_ts, executor_id=actor.actor_id
            ),
        )
        aletheia = kd.seal_aletheia_receipt(
            tenant_id=tid,
            subject_id=rcpt.payout_id,
            approver_id=actor.actor_id,
            amount_cents=rcpt.amount_cents,
            currency=rcpt.currency,
            evidence_hashes=(rcpt.binding_digest,),
        )
        store.persist_audit_record(tid, "PAYOUT_EXECUTED", rcpt.payout_id, asdict(rcpt))
        store.persist_approval_state(ap_id, tid, "EXECUTED", rcpt.binding_digest)
        return json_reply(200, {"receipt": asdict(rcpt), "aletheia_receipt": asdict(aletheia)})

    if sub == "invoices":
        return handle_post_invoice(tid, state, body, actor, store, now_ts)
    if sub == "bookings":
        return handle_post_booking(tid, state, body, actor, store, now_ts)
    if sub == "onboarding/opening-balance":
        return handle_post_opening_balance(tid, state, body, actor, store)
    if sub == "memory/learn":
        return handle_post_learn_memory(tid, state, body, actor, store, is_replay=is_replay)
    if len(parts) == 5 and parts[2] == "docgen" and parts[4] == "send":
        return handle_post_send_draft(tid, parts[3], state, body, actor, now_ts)
    if sub == "commissions/plan-diff":
        return handle_post_simulate_commission_plan(tid, state, body, actor)
    if sub == "commissions/dispute":
        return handle_post_seller_dispute(tid, state, body, actor, now_ts)
    if sub == "commissions/supersede":
        return handle_post_supersede_settlement(tid, state, body, actor)
    if sub == "remittances/classify":
        return handle_post_classify_remittance(tid, state, body, actor)
    if sub == "remittances/attest":
        return handle_post_attest_remittance(tid, state, body, actor, now_ts)
    if sub == "disputes/hold":
        return handle_post_dispute_hold(tid, state, body, actor)
    if sub == "strands-gate/verify":
        return handle_post_strands_gate_verify(tid, state, body, actor)
    if sub == "portfolio/mode":
        return handle_post_portfolio_mode(tid, state, body, actor)
    if sub == "invites":
        return handle_post_invite(tid, state, body, actor, now_ts)
    if sub == "billing/subscription":
        return handle_post_subscription_switch(tid, state, body, actor)
    if sub == "inventory/movement":
        return handle_post_inventory_movement(tid, state, body, actor)

    erp_resp = workspace_post_response(tid, sub, state, body, actor, store, event, now_ts)
    if erp_resp is not None:
        return erp_resp
    return json_reply(404, {"error": f"Unknown tenant POST route: {path}"})
