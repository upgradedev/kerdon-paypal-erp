"""Extended PayPal Agentic Commerce HTTP Sub-Route Handlers (`src/kerdon_aws/paypal_routes.py`).

Handles `order-status`, `subscription`, `webhooks/register`, `disputes/sync`, `tracker`,
`oauth/start`, `oauth/callback`, `payout-sync`, and `agent` (`Strands @tool` orchestrator)
with deterministic DynamoDB journal replay (`_replay_provider_receipt`).
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any
import uuid

import kerdon as kd
from kerdon.connectors import (
    apply_paypal_capture_to_ledger,
    execute_governed_paypal_payout,
    get_connector_state,
)

from .http_utils import ValidationError, json_reply
from .paypal_agent_tools import run_paypal_commerce_agent_workflow
from .paypal_live_client import PayPalConnectorPlugin


def _handle_webhook(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    store: Any,
    pp_plugin: PayPalConnectorPlugin,
    listener_url: str,
    event: dict[str, Any],
    is_replay: bool,
) -> dict[str, Any]:
    resource = body.get("resource")
    event_type = str(body.get("event_type") or "").strip().upper()
    event_id = str(body.get("id") or "").strip()
    if is_replay or not pp_plugin.is_live_configured:
        event_id = event_id or str(body.get("event_id") or body.get("transmission_id") or "").strip()
    if not event_id or not event_type or not isinstance(resource, dict) or not resource:
        raise ValidationError("PayPal webhook requires id, event_type, and resource")

    cs = get_connector_state(state)
    if event_id in cs.processed_webhook_event_ids:
        raise kd.DuplicateIdempotencyError(f"PayPal webhook '{event_id}' has already been processed")

    replay_receipt = body.get("_replay_provider_receipt")
    if is_replay and isinstance(replay_receipt, dict):
        verification = replay_receipt
    elif is_replay or not pp_plugin.is_live_configured:
        if not is_replay and (body.get("simulation") is not True or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")):
            raise ValidationError("PayPal webhook simulation is available only in the offline demo")
        verification = kd.verify_paypal_webhook_signature(
            raw_body=json.dumps(resource, sort_keys=True),
            transmission_id=str(body.get("transmission_id") or ""),
            transmission_time=str(body.get("transmission_time") or ""),
            webhook_id=str(body.get("webhook_id") or ""),
            transmission_sig=str(body.get("transmission_sig") or ""),
        )
        verification["provider_mode"] = "paypal-sandbox-simulated"
    else:
        headers = {
            str(key).lower(): str(value).strip()
            for key, value in (event.get("headers") or {}).items()
            if value is not None
        }
        metadata = {
            field: headers.get("paypal-" + field.replace("_", "-"), "")
            for field in ("transmission_id", "transmission_time", "cert_url", "auth_algo", "transmission_sig")
        }
        raw = event.get("body")
        if not all(metadata.values()) or not isinstance(raw, str):
            raise ValidationError("PayPal webhook requires the signed request body and all PayPal transmission headers")
        registered = pp_plugin.find_registered_webhook(webhook_url=listener_url)
        if not registered:
            raise kd.PermissionDeniedError("PayPal webhook listener is not registered")
        raw_body = base64.b64decode(raw) if event.get("isBase64Encoded") else raw.encode("utf-8")
        verification = pp_plugin.verify_webhook_via_api(
            **metadata, webhook_id=registered["webhook_id"], webhook_event=raw_body
        )

    if verification.get("verification_status") != "SUCCESS":
        raise kd.PermissionDeniedError("PayPal webhook signature verification failed")
    body["_replay_provider_receipt"] = verification
    cs.processed_webhook_event_ids.add(event_id)
    resource_id = str(resource.get("id") or "").strip()
    if event_type == "CHECKOUT.ORDER.APPROVED" and resource_id in cs.pending_paypal_orders:
        cs.pending_paypal_orders[resource_id]["status"] = "APPROVED"
    elif event_type == "BILLING.SUBSCRIPTION.ACTIVATED" and resource_id in cs.paypal_subscriptions:
        cs.paypal_subscriptions[resource_id]["status"] = "ACTIVE"
    store.persist_audit_record(
        tid, "PAYPAL_WEBHOOK_VERIFIED", event_id,
        {"event_id": event_id, "event_type": event_type, "verification": verification},
    )
    return json_reply(200, {
        "webhook_event_id": event_id, "webhook_event_type": event_type,
        "verification": verification, "routed": True,
    })


def _restore_agent_tools_on_replay(
    state: kd.TenantMiniErpState, actor: kd.Actor, replay_res: dict[str, Any]
) -> None:
    cs = get_connector_state(state)
    for item in replay_res.get("executed_tools") or []:
        if not isinstance(item, dict):
            continue
        tname = str(item.get("tool") or "")
        res = item.get("result") or {}
        if not isinstance(res, dict):
            continue
        if tname == "paypal_create_checkout_order_v2" and res.get("order_id"):
            cs.pending_paypal_orders[str(res["order_id"])] = res
        elif tname == "paypal_provision_subscription_plan_v1" and res.get("subscription_id"):
            cs.paypal_subscriptions[str(res["subscription_id"])] = res
        elif tname == "paypal_register_or_list_webhook_v1" and res.get("webhook_id"):
            cs.paypal_webhooks[str(res["webhook_id"])] = res
        elif tname == "paypal_inspect_or_capture_order_v2" and res.get("captured") and isinstance(res.get("order"), dict):
            ord_d = res["order"]
            oid = str(ord_d.get("order_id") or "")
            doc_id = str(ord_d.get("document_id") or "")
            if oid and doc_id in state.crm.documents and oid not in cs.paypal_orders:
                apply_paypal_capture_to_ledger(
                    state,
                    document_id=doc_id,
                    order_id=oid,
                    paypal_invoice_id=str(ord_d.get("paypal_invoice_id") or f"PPINV-{oid[-8:]}"),
                    capture_id=str(ord_d.get("capture_id") or f"PPCAP-{oid[-8:]}"),
                    gross_cents=int(ord_d.get("gross_cents") or 0),
                    fee_cents=ord_d.get("paypal_fee_cents"),
                    captured_date=str(ord_d.get("captured_date") or "2026-10-29"),
                    approval_url=str(ord_d.get("approval_url") or ""),
                    provider_mode=str(ord_d.get("provider_mode") or "paypal-sandbox-live"),
                )
                cs.pending_paypal_orders.pop(oid, None)
        elif tname == "paypal_diagnose_or_execute_payout_v1" and res.get("executed") and isinstance(res.get("payout"), dict):
            pay_d = res["payout"]
            ap_id = str(pay_d.get("approval_id") or "")
            if ap_id in state.treasury.approvals and state.treasury.approvals[ap_id].state.value == "VALID":
                execute_governed_paypal_payout(
                    state,
                    approval_id=ap_id,
                    executor_id=str(pay_d.get("executor_id") or actor.actor_id),
                    recipient_email=str(pay_d.get("recipient_email") or "seller-payout-sb@kerdon-synth.eu"),
                    payout_batch_id=str(pay_d.get("payout_batch_id") or ""),
                    batch_status=str(pay_d.get("status") or "SUCCESS"),
                    provider_mode=str(pay_d.get("provider_mode") or "paypal-sandbox-live"),
                )


def handle_extended_paypal_post(
    *,
    tid: str,
    sub: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
    writer: kd.Writer,
    store: Any,
    pp_plugin: PayPalConnectorPlugin,
    public_origin: str,
    is_replay: bool,
    event: dict[str, Any] | None = None,
    webhook_listener_url: str = "",
) -> dict[str, Any] | None:
    """Dispatch extended PayPal Developer Platform sub-routes."""
    cs = get_connector_state(state)

    if sub == "connectors/paypal/webhook":
        return _handle_webhook(
            tid, state, body, store, pp_plugin, webhook_listener_url, event or {}, is_replay
        )

    if sub == "connectors/paypal/order-status":
        oid = str(body.get("order_id") or "").strip()
        if not oid:
            raise ValidationError("order_id is required")

        def _sync_order() -> dict[str, Any]:
            if is_replay and isinstance(body.get("_replay_provider_receipt"), dict):
                info = dict(body["_replay_provider_receipt"])
            else:
                info = pp_plugin.get_order(oid)
                body["_replay_provider_receipt"] = info
            if oid in cs.pending_paypal_orders and info.get("status"):
                cs.pending_paypal_orders[oid]["status"] = str(info["status"]).upper()
            return info

        info_res = writer.execute(
            tid, kd.Capability.ISSUE_DOCS, approval_token=f"pp-ord-st-{oid}", mutation_fn=_sync_order
        )
        return json_reply(200, {"order_id": oid, "order_status": info_res})

    if sub == "connectors/paypal/subscription":
        tier_name = str(body.get("tier_name") or "Kerdon Autonomous Mini-ERP Pro").strip()
        price_cents = int(body.get("monthly_price_cents") or 14_900)
        currency = str(body.get("currency") or "EUR").upper().strip()

        def _create_sub() -> dict[str, Any]:
            if is_replay and isinstance(body.get("_replay_provider_receipt"), dict):
                sub_res = dict(body["_replay_provider_receipt"])
            else:
                sub_res = pp_plugin.create_subscription_bundle(
                    tenant_id=tid,
                    tier_name=tier_name,
                    monthly_price_cents=price_cents,
                    currency=currency,
                    unique_nonce=uuid.uuid4().hex[:8],
                )
                body["_replay_provider_receipt"] = sub_res
            cs.paypal_subscriptions[str(sub_res["subscription_id"])] = sub_res
            return sub_res

        try:
            sub_out = writer.execute(
                tid, kd.Capability.ISSUE_DOCS, approval_token=f"pp-sub-{tid}", mutation_fn=_create_sub
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        store.persist_audit_record(tid, "PAYPAL_SUBSCRIPTION_PROVISIONED", sub_out["subscription_id"], sub_out)
        return json_reply(201, {"subscription": sub_out})

    if sub == "connectors/paypal/webhooks/register":
        wh_url = str(body.get("webhook_url") or f"{public_origin}/erp/connectors/paypal/webhook").strip()

        def _reg_wh() -> dict[str, Any]:
            if is_replay and isinstance(body.get("_replay_provider_receipt"), dict):
                wh_res = dict(body["_replay_provider_receipt"])
            else:
                wh_res = pp_plugin.list_or_register_webhook(webhook_url=wh_url)
                body["_replay_provider_receipt"] = wh_res
            if wh_res.get("webhook_id"):
                cs.paypal_webhooks[str(wh_res["webhook_id"])] = wh_res
            return wh_res

        wh_out = writer.execute(
            tid, kd.Capability.ISSUE_DOCS, approval_token=f"pp-wh-reg-{tid}", mutation_fn=_reg_wh
        )
        store.persist_audit_record(tid, "PAYPAL_WEBHOOK_REGISTERED", str(wh_out.get("webhook_id") or tid), wh_out)
        return json_reply(201, {"webhook": wh_out})

    if sub == "connectors/paypal/disputes/sync":
        kd.require_capability(actor, kd.Capability.ISSUE_DOCS, tid)
        res = pp_plugin.list_disputes()
        return json_reply(
            200,
            {
                "live_disputes": res.get("items") or [],
                "count": len(res.get("items") or []),
                "provider_mode": res.get("provider_mode"),
                "debug_id": res.get("debug_id", ""),
            },
        )

    if sub == "connectors/paypal/tracker":
        cap_id = str(body.get("capture_id") or "").strip()
        trk_no = str(body.get("tracking_number") or "").strip()
        carrier = str(body.get("carrier") or "DHL").strip()
        if not cap_id or not trk_no:
            raise ValidationError("capture_id and tracking_number are required")

        def _reg_trk() -> dict[str, Any]:
            if is_replay and isinstance(body.get("_replay_provider_receipt"), dict):
                tr_res = dict(body["_replay_provider_receipt"])
            else:
                tr_res = pp_plugin.register_shipment_tracker(
                    capture_id=cap_id, tracking_number=trk_no, carrier=carrier
                )
                body["_replay_provider_receipt"] = tr_res
            cs.paypal_trackers[cap_id] = tr_res
            return tr_res

        try:
            tr_out = writer.execute(
                tid, kd.Capability.ISSUE_DOCS, approval_token=f"pp-trk-{cap_id}", mutation_fn=_reg_trk
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        store.persist_audit_record(tid, "PAYPAL_SHIPMENT_TRACKED", cap_id, tr_out)
        return json_reply(201, {"tracker": tr_out})

    if sub == "connectors/paypal/oauth/start":
        kd.require_capability(actor, kd.Capability.ISSUE_DOCS, tid)
        redir = str(body.get("redirect_uri") or f"{public_origin}/erp/connectors/paypal/oauth/callback").strip()
        return json_reply(
            200,
            pp_plugin.build_oidc_authorize_url(redirect_uri=redir, state_nonce=f"ppoidc:{tid}"),
        )

    if sub == "connectors/paypal/oauth/callback":
        code = str(body.get("code") or "").strip()
        if not code:
            raise ValidationError("OIDC authorization code is required")
        redir = str(body.get("redirect_uri") or f"{public_origin}/erp/connectors/paypal/oauth/callback").strip()

        def _bind_oidc() -> dict[str, Any]:
            if is_replay and isinstance(body.get("_replay_provider_receipt"), dict):
                ident = dict(body["_replay_provider_receipt"])
            else:
                ident = pp_plugin.exchange_oidc_code_for_identity(code=code, redirect_uri=redir)
                body["_replay_provider_receipt"] = ident
            key = str(ident.get("payer_id") or ident.get("email") or "merchant-oidc")
            cs.paypal_identities[key] = ident
            return ident

        ident_out = writer.execute(
            tid, kd.Capability.ISSUE_DOCS, approval_token=f"pp-oidc-{tid}", mutation_fn=_bind_oidc
        )
        store.persist_audit_record(tid, "PAYPAL_OIDC_IDENTITY_LINKED", str(ident_out.get("payer_id") or tid), ident_out)
        return json_reply(200, {"identity": ident_out})

    if sub == "connectors/paypal/payout-sync":
        batch_id = str(body.get("payout_batch_id") or "").strip()
        if not batch_id:
            raise ValidationError("payout_batch_id is required")
        res = (
            body["_replay_provider_receipt"]
            if (is_replay and isinstance(body.get("_replay_provider_receipt"), dict))
            else pp_plugin.get_payout_batch(batch_id)
        )
        body["_replay_provider_receipt"] = res
        return json_reply(200, {"payout_batch": res})

    if sub == "connectors/paypal/agent":
        goal = str(
            body.get("goal")
            or "Inspect Sandbox status, create Checkout Order v2, and provision Subscription Plan v1"
        ).strip()
        require_live = bool(body.get("require_live", False))

        def _run_agent() -> dict[str, Any]:
            if is_replay and isinstance(body.get("_replay_provider_receipt"), dict):
                saved = dict(body["_replay_provider_receipt"])
                _restore_agent_tools_on_replay(state, actor, saved)
                return saved
            out = run_paypal_commerce_agent_workflow(
                tid=tid,
                state=state,
                actor=actor,
                pp_plugin=pp_plugin,
                goal=goal,
                public_origin=public_origin,
                require_live=require_live,
                llm_mode=body.get("llm_mode"),
            )
            body["_replay_provider_receipt"] = out
            return out

        try:
            agent_out = writer.execute(
                tid, kd.Capability.ISSUE_DOCS, approval_token=f"pp-agent-{tid}", mutation_fn=_run_agent
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        store.persist_audit_record(tid, "PAYPAL_AGENT_WORKFLOW", tid, agent_out)
        return json_reply(200, agent_out)

    return None
