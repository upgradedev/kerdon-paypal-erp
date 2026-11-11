"""Tenant-authorized operational reads and governed ERP mutations for `/`."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
import hashlib
import re
from typing import Any
from urllib.parse import parse_qs, urlencode

import kerdon as kd
from kerdon.connectors import summarize_tenant_connectors
from kerdon.erp_services import (
    ErpDraftRecord,
    evaluate_targets_vs_actuals,
    get_erp_extensions,
    parse_and_compute_lines,
    post_direct_expense_bill,
    post_settlement_with_allocations,
    reverse_posted_document,
    upsert_party_record,
    upsert_sales_target,
)
from kerdon.operational import (
    dashboard_projection,
    due_date_aging_report,
    operational_records,
    party_statement,
    profitability_and_cash_forecast,
)

from .bedrock_adapter import extract_document_with_bedrock
from .connectors_adapter import enrich_connector_summary, handle_get_connectors, handle_post_connectors
from .http_utils import ValidationError, canonical_root_location, html_reply, json_reply, redirect_reply
from .identity import extract_verified_jwt_claims
from .sandbox_provider import reconcile_sandbox_webhook, submit_sandbox_payout
from .workspace_ui import render_workspace, serve_static_asset


def workspace_response(
    path: str, actor: kd.Actor, store: Any, event: dict[str, Any], head_only: bool = False
) -> dict[str, Any] | None:
    """Handle `GET /`, legacy `301` redirects, `GET /organizations`, `GET /erp/*`, and `GET /tenants/{id}/operations`."""
    if path.startswith("/assets/"):
        return serve_static_asset(path, head_only=head_only)
    if path == "/":
        return html_reply(200, render_workspace(store.workspace), head_only=head_only)
    if path in ("/workspace", "/cockpit"):
        return redirect_reply(canonical_root_location(event), status=301, head_only=head_only)
    if path == "/erp/connectors/paypal/oauth/callback":
        q_raw = parse_qs(event.get("rawQueryString") or "")
        qp = {k: str(v) for k, v in (event.get("queryStringParameters") or {}).items() if v is not None}
        code_v = qp.get("code") or (q_raw.get("code") or [""])[0]
        state_v = qp.get("state") or (q_raw.get("state") or [""])[0]
        qs_out = urlencode({"paypal_oidc_code": code_v, "paypal_oidc_state": state_v})
        return redirect_reply(f"/?{qs_out}#module=documents", status=302, head_only=head_only)
    if path in ("/bounded-contexts", "/erp/bounded-contexts", "/datasets", "/erp/datasets") or path.endswith(("/bounded-contexts", "/datasets")):
        return json_reply(
            200,
            {
                "bounded_contexts": kd.summarize_bounded_contexts(),
                "public_datasets": kd.list_public_datasets(),
            },
            head_only=head_only,
        )
    if path == "/organizations":
        membership = store.identity_registry.find_by_actor_id(actor.actor_id)
        orgs = []
        for t in store.workspace.catalog.tenants.values():
            if actor.can_access_tenant(t.tenant_id):
                role_val = (
                    membership.role_for_tenant(t.tenant_id).value
                    if membership
                    else actor.role.value
                )
                access = store.identity_registry.list_organization_access(t.tenant_id)
                orgs.append(
                    {
                        **asdict(t),
                        "role": role_val,
                        "members_count": len(access["members"]),
                    }
                )
        active_tid = orgs[0]["tenant_id"] if orgs else ""
        if membership and membership.default_tenant_id:
            if any(o["tenant_id"] == membership.default_tenant_id for o in orgs):
                active_tid = membership.default_tenant_id
        return json_reply(
            200,
            {
                "organizations": orgs,
                "tenants": orgs,
                "active_tenant_id": active_tid,
            },
            head_only=head_only,
        )
    parts = path.strip("/").split("/")
    if len(parts) == 3 and parts[0] == "tenants" and parts[2] == "connectors":
        return handle_get_connectors(parts[1], store.get_tenant_state(parts[1]), actor, event=event, head_only=head_only)
    if len(parts) == 3 and parts[0] == "tenants" and parts[2] == "members":
        tid = parts[1]
        _ = store.get_tenant_state(tid)
        return json_reply(200, kd.Reader(actor).read(tid, lambda: store.identity_registry.list_organization_access(tid)), head_only=head_only)
    if len(parts) != 3 or parts[0] != "tenants" or parts[2] != "operations":
        return None
    tid = parts[1]

    def project() -> dict[str, Any]:
        state = store.get_tenant_state(tid)
        ext = get_erp_extensions(state)
        q = parse_qs(event.get("rawQueryString") or "")
        q.update(
            {
                k: [str(v)]
                for k, v in (event.get("queryStringParameters") or {}).items()
                if v is not None
            }
        )
        latest = max(
            (e.posted_date for e in state.ledger.events),
            default=date.today().isoformat(),
        )
        start = q.get("start", [latest[:7] + "-01"])[0]
        end = q.get("end", [latest])[0]
        try:
            dashboard = dashboard_projection(state, start, end)
            statement = (
                party_statement(
                    state, q["party"][0], q.get("kind", [""])[0], start, end
                )
                if q.get("party")
                else None
            )
            aging = due_date_aging_report(state, end)
            profitability = profitability_and_cash_forecast(state, start, end)
            targets_summary = evaluate_targets_vs_actuals(state, start, end)
        except kd.HtmlBodyPostingError:
            raise
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return {
            "tenant": asdict(state.tenant),
            "dashboard": dashboard,
            "statement": statement,
            "aging": aging,
            "profitability": profitability,
            "targets_summary": targets_summary,
            "records": {
                m: operational_records(state, m)
                for m in (
                    "customers",
                    "suppliers",
                    "sales",
                    "purchases",
                    "expenses",
                    "payments",
                    "receipts",
                )
            },
            "drafts": [asdict(d) for d in ext.drafts.values()],
            "settlements": [asdict(s) for s in ext.settlements.values()],
            "bank_accounts": [asdict(b) for b in ext.bank_accounts.values()],
            "connectors": enrich_connector_summary(tid, summarize_tenant_connectors(state), event),
            "fiscal_profile": kd.resolve_organization_fiscal_profile(state),
            "organization_access": {
                **store.identity_registry.list_organization_access(tid),
                "caller_role": actor.role.value,
                "can_manage_members": actor.role
                in (kd.Role.CLIENT_OWNER, kd.Role.MSP_FINOPS_DIRECTOR),
            },
            "ledger": [asdict(e) for e in state.ledger.events],
            "trial_balance": kd.build_trial_balance(state),
            "bounded_contexts": kd.summarize_bounded_contexts(),
            "public_datasets": kd.list_public_datasets(),
            "dataset_coverage": kd.verify_erp_dataset_coverage(state),
            "evidence_inbox": {
                "envelopes": [
                    {
                        "message_id": e.message_id,
                        "sender": e.sender,
                        "recipient": e.recipient,
                        "subject": e.subject,
                        "parent_message_id": e.parent_message_id,
                        "received_at_epoch": e.received_at_epoch,
                        "attachments": [
                            {
                                "attachment_id": a.attachment_id,
                                "filename": a.filename,
                                "mime_type": a.mime_type,
                                "sha256": a.sha256,
                            }
                            for a in e.attachments
                        ],
                    }
                    for e in state.inbox.messages_by_id.values()
                ],
                "blobs_count": len(state.inbox.blobs_by_sha256),
                "edges_count": sum(
                    len(b.source_edges) for b in state.inbox.blobs_by_sha256.values()
                ),
            },
            "durability": "configured-unverified"
            if store.app_table_name
            else "in-memory",
            "capabilities": {
                "invoice_submission": actor.has_capability(
                    kd.Capability.ISSUE_DOCS, tid
                ),
                "party_write": actor.has_capability(kd.Capability.ISSUE_DOCS, tid),
                "expense_write": actor.has_capability(kd.Capability.ISSUE_DOCS, tid),
                "settlement_write": actor.has_capability(
                    kd.Capability.ISSUE_DOCS, tid
                ),
                "cash_write": bool(store.app_table_name)
                and actor.has_capability(kd.Capability.EXECUTE_PAYOUTS, tid),
                "durable_targets": actor.has_capability(
                    kd.Capability.MANAGE_COMMISSIONS, tid
                ),
            },
        }

    return json_reply(200, kd.Reader(actor).read(tid, project), head_only=head_only)


def workspace_post_response(
    tid: str,
    sub: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
    store: Any,
    event: dict[str, Any],
    now_ts: int,
) -> dict[str, Any] | None:
    """Handle governed ERP POST routes for parties, drafts, expenses, reversals, receipts, payments, targets, and sandbox provider."""
    writer = kd.Writer(actor)

    if sub == "datasets/import":
        ds_id = str(body.get("dataset_id") or "kerdon-universal-en-v1").strip()

        def _mutate_dataset() -> dict[str, Any]:
            with store.unit_of_work(tid, actor.actor_id) as uow:
                try:
                    res = kd.import_public_dataset_into_tenant(state, ds_id, now_ts=now_ts)
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc
                uow.stage_outbox("PUBLIC_DATASET_IMPORTED", ds_id, res)
                res["uow_receipt"] = asdict(uow.commit())
                return res

        imported = writer.execute(
            tid,
            kd.Capability.ISSUE_DOCS,
            approval_token=f"dataset-{ds_id}-{now_ts}",
            mutation_fn=_mutate_dataset,
        )
        return json_reply(201, {"imported": imported})

    if sub == "ai/extract-document":
        raw_text = str(body.get("raw_text") or body.get("text") or "").strip()
        if not raw_text:
            raise ValidationError("raw_text is required for AI document extraction")
        pref_mod = str(body.get("module") or body.get("preferred_module") or "purchases").strip().lower()
        src_kind = str(body.get("source_kind") or "PDF_ATTACHMENT").strip().upper()
        try:
            draft_obj = kd.Evaluator(actor).evaluate(
                tid,
                lambda: extract_document_with_bedrock(
                    state,
                    raw_text,
                    preferred_module=pref_mod,
                    source_kind=src_kind,
                    require_live=bool(body.get("require_live", False)),
                ),
            )
        except kd.HtmlBodyPostingError:
            raise
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        return json_reply(200, {"extracted_draft": asdict(draft_obj)})

    if sub == "parties":
        kind = str(body.get("kind") or "customer").strip().lower()
        party_id = str(body.get("party_id") or body.get("id") or "").strip()
        legal_name = str(body.get("legal_name") or "").strip()
        tax_id = str(body.get("tax_id") or "").strip()
        expected_ver = body.get("expected_version")
        if expected_ver is not None and (
            isinstance(expected_ver, bool) or not isinstance(expected_ver, int)
        ):
            raise ValidationError("expected_version must be an integer")
        idem_key = str(body.get("idempotency_key") or "").strip()
        if idem_key:
            store.claim_idempotency_key(tid, "PARTY", idem_key, body)

        def _mutate_party() -> tuple[dict[str, Any], dict[str, Any]]:
            with store.unit_of_work(tid, actor.actor_id) as uow:
                try:
                    rec = upsert_party_record(
                        state,
                        kind=kind,
                        party_id=party_id,
                        legal_name=legal_name,
                        tax_id=tax_id,
                        email=str(body.get("email") or ""),
                        phone=str(body.get("phone") or ""),
                        address=str(body.get("address") or ""),
                        payment_terms_days=int(body.get("payment_terms_days", 30)),
                        credit_limit_cents=int(body.get("credit_limit_cents", 5_000_000)),
                        iban=str(body.get("iban") or ""),
                        category=str(body.get("category") or "General Commercial"),
                        country_code=str(body.get("country_code") or state.tenant.fiscal_identity.country_code or "GR"),
                        doy=str(body.get("doy") or ""),
                        gemi_number=str(body.get("gemi_number") or ""),
                        branch_id=int(body.get("branch_id", 0)),
                        city=str(body.get("city") or ""),
                        postal_code=str(body.get("postal_code") or ""),
                    )
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc
                uow.stage_entity(
                    f"PARTY_{kind.upper()}",
                    rec["id"],
                    rec,
                    expected_version=expected_ver,
                )
                uow.stage_outbox("PARTY_UPSERTED", rec["id"], rec)
                uow_receipt = uow.commit()
                new_ver = store.entity_versions.get(
                    f"{tid}:PARTY_{kind.upper()}:{rec['id']}", 1
                )
                rec["version"] = new_ver
                get_erp_extensions(state).party_metadata[rec["id"]]["version"] = new_ver
                return rec, asdict(uow_receipt)

        created, receipt_dict = writer.execute(
            tid,
            kd.Capability.ISSUE_DOCS,
            approval_token=f"party-{kind}-{legal_name or party_id}",
            mutation_fn=_mutate_party,
        )
        return json_reply(201, {"party": created, "uow_receipt": receipt_dict})

    if sub == "drafts":
        draft_id = str(body.get("draft_id") or f"drf-{state.tenant.slug}-{now_ts}").strip()
        module = str(body.get("module") or "sales").strip().lower()
        action = str(body.get("action") or "save").strip().lower()
        expected_ver = body.get("expected_version")
        if expected_ver is not None and (
            isinstance(expected_ver, bool) or not isinstance(expected_ver, int)
        ):
            raise ValidationError("expected_version must be an integer")

        def _mutate_draft() -> dict[str, Any]:
            ext = get_erp_extensions(state)
            existing = ext.drafts.get(draft_id)
            if action == "approve":
                if existing is None:
                    raise KeyError(f"Unknown draft_id: {draft_id}")
                if existing.created_by == actor.actor_id:
                    raise kd.SelfApprovalError(
                        "Four-Eyes violation: draft creator cannot approve the same draft"
                    )
                updated = ErpDraftRecord(
                    **{
                        **asdict(existing),
                        "lines": existing.lines,
                        "status": "APPROVED",
                        "approved_by": actor.actor_id,
                    }
                )
            else:
                cp_id = str(body.get("counterparty_id") or (existing.counterparty_id if existing else "")).strip()
                inv_num = str(body.get("invoice_number") or (existing.invoice_number if existing else f"DRF-{now_ts % 10000}")).strip()
                issued_d = str(body.get("issued_date") or (existing.issued_date if existing else "2026-10-31")).strip()
                due_d = str(body.get("due_date") or (existing.due_date if existing else issued_d)).strip()
                desc = str(body.get("description") or (existing.description if existing else "Draft record")).strip()
                try:
                    lines_t, net_c, vat_c, gross_c = parse_and_compute_lines(
                        body.get("lines") if isinstance(body.get("lines"), list) else None,
                        fallback_net_cents=body.get("net_cents", existing.net_cents if existing else 10000),
                        fallback_vat_rate_pct=body.get("vat_rate_pct", 24),
                        fallback_description=desc,
                    )
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc
                updated = ErpDraftRecord(
                    draft_id=draft_id,
                    tenant_id=tid,
                    module=module,
                    counterparty_id=cp_id,
                    invoice_number=inv_num,
                    issued_date=issued_d,
                    due_date=due_d,
                    currency=str(body.get("currency") or "EUR"),
                    description=desc,
                    lines=lines_t,
                    net_cents=net_c,
                    vat_cents=vat_c,
                    gross_cents=gross_c,
                    status="DRAFT",
                    version=(existing.version + 1) if existing else 1,
                    created_by=existing.created_by if existing else actor.actor_id,
                    attachment_sha256=str(body.get("attachment_sha256") or ""),
                )
            new_ver = store.put_versioned_entity(
                tid,
                "ERP_DRAFT",
                draft_id,
                asdict(updated),
                expected_version=expected_ver,
            )
            final_rec = ErpDraftRecord(
                **{**asdict(updated), "lines": updated.lines, "version": new_ver}
            )
            ext.drafts[draft_id] = final_rec
            store.persist_audit_record(tid, "DRAFT_SAVED", draft_id, asdict(final_rec))
            return asdict(final_rec)

        saved = writer.execute(
            tid,
            kd.Capability.ISSUE_DOCS,
            approval_token=f"draft-{draft_id}-{action}",
            mutation_fn=_mutate_draft,
        )
        return json_reply(201 if action == "save" else 200, {"draft": saved})

    if sub == "expenses":
        doc_id = str(body.get("document_id") or f"exp-{state.tenant.slug}-{now_ts}").strip()
        sup_id = str(body.get("counterparty_id") or body.get("supplier_id") or "").strip()
        inv_num = str(body.get("invoice_number") or f"EXP-{now_ts % 100000}").strip()
        issued_d = str(body.get("issued_date") or "2026-10-31").strip()
        due_d = str(body.get("due_date") or issued_d).strip()
        desc = str(body.get("description") or "Operating expense bill").strip()
        acct_key = str(body.get("expense_account") or "6200_GENERAL_OPERATING_EXPENSE").strip()

        def _mutate_expense() -> dict[str, Any]:
            with store.unit_of_work(tid, actor.actor_id) as uow:
                try:
                    res = post_direct_expense_bill(
                        state,
                        document_id=doc_id,
                        supplier_id=sup_id,
                        invoice_number=inv_num,
                        issued_date=issued_d,
                        due_date=due_d,
                        description=desc,
                        expense_account_key=acct_key,
                        raw_lines=body.get("lines") if isinstance(body.get("lines"), list) else None,
                        fallback_net_cents=body.get("net_cents"),
                        fallback_vat_rate_pct=body.get("vat_rate_pct", 24),
                        now_ts=now_ts,
                    )
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc
                ext = get_erp_extensions(state)
                dmeta = {
                    k: body[k]
                    for k in ("invoice_type", "series", "aa", "payment_method_code", "withheld_tax_pct", "vat_exemption_category", "correlated_mark")
                    if body.get(k) not in (None, "")
                }
                if dmeta:
                    ext.party_metadata[f"__DOC_META__:{doc_id}"] = dmeta
                if kd.resolve_organization_fiscal_profile(state).get("is_greek_organization", True):
                    mrec = kd.build_aade_mydata_record(state, doc_id, series=str(body.get("series") or "P"), aa=str(body.get("aa") or "199"))
                    kd.stamp_mydata_transmission(state, mrec)
                    res["mydata_transmission"] = asdict(mrec)
                uow.stage_outbox("EXPENSE_POSTED", doc_id, res["document"])
                res["uow_receipt"] = asdict(uow.commit())
                return res

        posted = writer.execute(
            tid,
            kd.Capability.ISSUE_DOCS,
            approval_token=f"exp-{doc_id}",
            mutation_fn=_mutate_expense,
        )
        return json_reply(201, posted)

    if sub.startswith("invoices/") and sub.endswith("/reverse"):
        seg = sub.split("/")
        if len(seg) == 3 and seg[2] == "reverse":
            doc_id = seg[1]
            rev_date = str(body.get("reversal_date") or "2026-10-31").strip()
            reason = str(body.get("reason") or "Credit note / invoice reversal").strip()

            def _mutate_reverse() -> dict[str, Any]:
                with store.unit_of_work(tid, actor.actor_id) as uow:
                    try:
                        res = reverse_posted_document(
                            state,
                            document_id=doc_id,
                            reversal_date=rev_date,
                            reason=reason,
                            actor_id=actor.actor_id,
                        )
                    except ValueError as exc:
                        raise ValidationError(str(exc)) from exc
                    uow.stage_outbox("DOCUMENT_REVERSED", doc_id, res)
                    res["uow_receipt"] = asdict(uow.commit())
                    for inv_ap_id in res["invalidated_approval_ids"]:
                        store.persist_approval_state(
                            inv_ap_id, tid, "INVALIDATED", res["reversal_event"]["source_sha256"]
                        )
                    return res

            reversed_res = writer.execute(
                tid,
                kd.Capability.ISSUE_DOCS,
                approval_token=f"rev-{doc_id}",
                mutation_fn=_mutate_reverse,
            )
            return json_reply(200, reversed_res)

    if sub in ("receipts", "payments"):
        kind = "receipt" if sub == "receipts" else "payment"
        st_id = str(
            body.get("settlement_id")
            or body.get("document_id")
            or f"{kind[:3]}-{state.tenant.slug}-{now_ts}"
        ).strip()
        cp_id = str(body.get("counterparty_id") or "").strip()
        posted_d = str(body.get("posted_date") or body.get("issued_date") or "2026-10-31").strip()
        gross_c = body.get("gross_cash_cents", body.get("amount_cents", body.get("net_cents")))
        fee_c = body.get("fee_cents", 0)
        allocs = body.get("allocations")
        bank_id = str(body.get("bank_account_id") or "").strip()
        desc = str(body.get("description") or f"Posted {kind} {st_id}").strip()

        def _mutate_settlement() -> dict[str, Any]:
            with store.unit_of_work(tid, actor.actor_id) as uow:
                try:
                    rec = post_settlement_with_allocations(
                        state,
                        settlement_id=st_id,
                        kind=kind,
                        counterparty_id=cp_id,
                        posted_date=posted_d,
                        gross_cash_cents=gross_c,
                        fee_cents=fee_c,
                        allocations=allocs if isinstance(allocs, list) else None,
                        bank_account_id=bank_id,
                        description=desc,
                        now_ts=now_ts,
                    )
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc
                payload = asdict(rec)
                uow.stage_outbox(f"SETTLEMENT_{kind.upper()}", st_id, payload)
                payload["uow_receipt"] = asdict(uow.commit())
                return payload

        settled = writer.execute(
            tid,
            kd.Capability.ISSUE_DOCS,
            approval_token=f"stl-{st_id}",
            mutation_fn=_mutate_settlement,
        )
        return json_reply(201, {"settlement": settled})

    if sub == "targets":
        period = str(body.get("period") or "2026-10").strip()
        scope_kind = str(body.get("scope_kind") or "company").strip().lower()
        scope_id = str(body.get("scope_id") or tid).strip()
        target_cents = body.get("target_cents")
        expected_ver = body.get("expected_version")
        if expected_ver is not None and (
            isinstance(expected_ver, bool) or not isinstance(expected_ver, int)
        ):
            raise ValidationError("expected_version must be an integer")

        def _mutate_target() -> dict[str, Any]:
            try:
                rec = upsert_sales_target(
                    state,
                    period=period,
                    scope_kind=scope_kind,
                    scope_id=scope_id,
                    target_cents=target_cents,
                    updated_by=actor.actor_id,
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            new_ver = store.put_versioned_entity(
                tid,
                "SALES_TARGET",
                rec.target_id,
                asdict(rec),
                expected_version=expected_ver,
            )
            final_rec = type(rec)(**{**asdict(rec), "version": new_ver})
            get_erp_extensions(state).targets[rec.target_id] = final_rec
            out = asdict(final_rec)
            store.persist_audit_record(tid, "TARGET_SAVED", rec.target_id, out)
            return out

        saved_tgt = writer.execute(
            tid,
            kd.Capability.MANAGE_COMMISSIONS,
            approval_token=f"tgt-{period}-{scope_kind}-{scope_id}",
            mutation_fn=_mutate_target,
        )
        return json_reply(201, {"target": saved_tgt})

    if sub == "treasury/sandbox-submit":
        return json_reply(
            200, submit_sandbox_payout(tid, state, body, actor, store, now_ts)
        )

    if sub == "treasury/webhooks/sandbox":
        return json_reply(
            200, reconcile_sandbox_webhook(tid, state, body, event, store, now_ts)
        )

    if sub.startswith("connectors/"):
        return handle_post_connectors(tid, sub, state, body, actor, store, event=event, is_replay=bool(event.get("_internal_journal_replay")))

    if sub in ("members/invite", "members/invites"):
        if actor.role not in (kd.Role.CLIENT_OWNER, kd.Role.MSP_FINOPS_DIRECTOR):
            raise kd.PermissionDeniedError(
                "Only CLIENT_OWNER or MSP_FINOPS_DIRECTOR in this organization can invite collaborators"
            )
        email = str(body.get("email") or "").strip()
        role_raw = str(body.get("role") or "ACCOUNTANT").strip().upper()
        try:
            role_enum = kd.Role(role_raw)
        except ValueError as exc:
            raise ValidationError(f"Unsupported organization role: {role_raw}") from exc
        seller_id = str(body.get("seller_id") or "").strip() or None
        if role_enum == kd.Role.SELLER and not seller_id:
            seller_id = f"slr-{state.tenant.slug}-01"
        inv = writer.execute(
            tid,
            kd.Capability.APPROVE_PAYOUTS,
            approval_token=f"org-inv-{tid}-{email}",
            mutation_fn=lambda: store.identity_registry.create_organization_invite(
                tenant_id=tid,
                email=email,
                role=role_enum,
                invited_by=actor.actor_id,
                target_sub=str(body.get("target_sub") or body.get("sub") or ""),
                display_name=str(body.get("display_name") or ""),
                seller_id=seller_id,
                auto_accept=bool(body.get("auto_accept", False)),
            ),
        )
        store.persist_audit_record(tid, "ORG_COLLABORATOR_INVITED", inv.invite_id, asdict(inv))
        return json_reply(
            201,
            {
                "invitation": asdict(inv),
                "access": store.identity_registry.list_organization_access(tid),
            },
        )

    if sub == "members/remove":
        if actor.role not in (kd.Role.CLIENT_OWNER, kd.Role.MSP_FINOPS_DIRECTOR):
            raise kd.PermissionDeniedError(
                "Only CLIENT_OWNER or MSP_FINOPS_DIRECTOR in this organization can remove collaborators"
            )
        target_sub = str(body.get("sub") or body.get("target_sub") or "").strip()
        if not target_sub:
            raise ValidationError("sub is required to remove an organization member")
        writer.execute(
            tid,
            kd.Capability.APPROVE_PAYOUTS,
            approval_token=f"org-rm-{tid}-{target_sub}",
            mutation_fn=lambda: store.identity_registry.revoke_organization_access(
                target_sub, tenant_id=tid
            ),
        )
        store.persist_audit_record(
            tid, "ORG_COLLABORATOR_REMOVED", target_sub, {"removed_sub": target_sub}
        )
        return json_reply(
            200,
            {
                "removed_sub": target_sub,
                "access": store.identity_registry.list_organization_access(tid),
            },
        )

    return None


def workspace_root_post_response(
    path: str,
    body: dict[str, Any],
    actor: kd.Actor,
    store: Any,
    event: dict[str, Any],
    now_ts: int,
) -> dict[str, Any] | None:
    """Handle organization creation (`POST /organizations`) and invitation acceptance."""
    if path == "/organizations":
        if actor.actor_id == "anonymous-public":
            raise kd.PermissionDeniedError("Authenticated identity required to create an organization")
        display_name = str(body.get("display_name") or "").strip()
        tax_id = str(body.get("tax_id") or "").strip()
        if not display_name or not tax_id:
            raise ValidationError("display_name and tax_id are required to create an organization")
        raw_slug = str(body.get("slug") or "").strip()
        if not raw_slug:
            raw_slug = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-") or f"org-{now_ts}"
        legal_name = str(body.get("legal_name") or display_name).strip()
        try:
            tenant = store.workspace.catalog.onboard_tenant(
                slug=raw_slug,
                display_name=display_name,
                legal_name=legal_name,
                tax_id=tax_id,
                country_code=str(body.get("country_code") or "GR").upper().strip(),
            )
        except kd.HtmlBodyPostingError:
            raise
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        store.workspace.tenant_states[tenant.tenant_id] = kd.build_empty_tenant_state(
            store.workspace.catalog, tenant
        )
        claims = extract_verified_jwt_claims(event) or {}
        caller_sub = (
            str(claims.get("sub") or body.get("owner_sub") or "").strip()
            or (actor.actor_id[4:] if actor.actor_id.startswith("act-") else actor.actor_id)
        )
        body.setdefault("owner_sub", caller_sub)
        caller_email = str(
            body.get("owner_email") or claims.get("email") or f"{caller_sub}@kerdon-synth.eu"
        ).strip()
        caller_name = str(
            body.get("owner_name") or claims.get("name") or actor.display_name
        ).strip()
        membership = store.identity_registry.grant_organization_access(
            caller_sub,
            tenant_id=tenant.tenant_id,
            role=kd.Role.CLIENT_OWNER,
            email=caller_email,
            display_name=caller_name,
            invited_by="organization-founder",
        )
        store.persist_audit_record(
            tenant.tenant_id, "ORGANIZATION_CREATED", tenant.tenant_id, asdict(tenant)
        )
        return json_reply(
            201,
            {
                "organization": asdict(tenant),
                "owner_sub": membership.sub,
                "access": store.identity_registry.list_organization_access(tenant.tenant_id),
            },
        )

    if path == "/organizations/invites/accept":
        if actor.actor_id == "anonymous-public":
            raise kd.PermissionDeniedError("Authenticated identity required to accept an invitation")
        invite_token = str(body.get("invite_token") or body.get("invite_id") or "").strip()
        if not invite_token:
            raise ValidationError("invite_token is required")
        claims = extract_verified_jwt_claims(event) or {}
        caller_sub = (
            str(claims.get("sub") or body.get("sub") or "").strip()
            or (actor.actor_id[4:] if actor.actor_id.startswith("act-") else actor.actor_id)
        )
        body.setdefault("sub", caller_sub)
        accepted_inv, membership = store.identity_registry.accept_organization_invite(
            invite_token,
            sub=caller_sub,
            email=str(body.get("email") or claims.get("email") or ""),
            display_name=str(body.get("display_name") or claims.get("name") or ""),
        )
        store.persist_audit_record(
            accepted_inv.tenant_id,
            "ORG_INVITATION_ACCEPTED",
            accepted_inv.invite_id,
            asdict(accepted_inv),
        )
        return json_reply(
            200,
            {
                "invitation": asdict(accepted_inv),
                "tenant_id": accepted_inv.tenant_id,
                "role": accepted_inv.role,
                "allowed_tenant_ids": sorted(membership.allowed_tenant_ids),
            },
        )

    return None
