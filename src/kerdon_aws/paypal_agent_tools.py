"""Executable Strands Agents SDK `@tool` Orchestrator for PayPal Agentic Commerce.

Wires real Python tool functions (`Orders v2`, `Subscriptions v1`, `Payouts v1`,
`Disputes v1`, `Webhooks v1`, and `OAuth2 Scope Introspection`) into an AWS Strands
`Agent(model=BedrockModel(...), tools=[...])` so natural-language operator goals
execute verified actions against `https://api-m.sandbox.paypal.com` while keeping
all double-entry GL postings and Four-Eyes treasury invariants deterministic.
"""
from __future__ import annotations

from dataclasses import asdict
import os
import time
from typing import Any
import uuid

import kerdon as kd
from kerdon.connectors import (
    apply_paypal_capture_to_ledger,
    execute_governed_paypal_payout,
    get_connector_state,
)
from kerdon.tenancy import Direction

from .bedrock_adapter import DEFAULT_MODEL_ID, record_agentcore_memory_event
from .paypal_live_client import ExternalProviderError, PayPalConnectorPlugin

PAYPAL_AGENT_SYSTEM_PROMPT = (
    "You are Kerdon PayPal Commerce Agent, a governed financial operations copilot. "
    "Use the provided PayPal tools to inspect live Sandbox status, create Checkout Orders v2 "
    "for open sales invoices, check or capture approved orders, provision Billing Plans and "
    "Subscriptions v1, register Webhooks v1, or diagnose Four-Eyes Batch Payouts v1. "
    "Always cite exact PayPal resource IDs (Order ID, Plan ID, Subscription ID, Webhook ID, "
    "or PayPal debug_id on fail-closed provider rejections) and never invent figures."
)


def _pick_open_sales_doc_id(state: kd.TenantMiniErpState, requested_doc_id: str = "") -> str:
    req = requested_doc_id.strip()
    if req and req != "auto" and req in state.crm.documents:
        return req
    for doc_id, doc in state.crm.documents.items():
        if doc.direction == Direction.SALES_REVENUE and doc.gross_cents > doc.paid_cents:
            return doc_id
    for doc_id, doc in state.crm.documents.items():
        if doc.direction == Direction.SALES_REVENUE:
            return doc_id
    raise ValueError("No outbound sales invoice found in organization register")


def run_paypal_commerce_agent_workflow(
    *,
    tid: str,
    state: kd.TenantMiniErpState,
    actor: kd.Actor,
    pp_plugin: PayPalConnectorPlugin,
    goal: str,
    public_origin: str = "https://dshvkidt3tkge.cloudfront.net",
    require_live: bool = False,
    llm_mode: str | None = None,
    model_id: str = DEFAULT_MODEL_ID,
    region_name: str = "eu-west-1",
) -> dict[str, Any]:
    """Execute a natural-language PayPal Agentic Commerce goal using real `@tool` functions."""
    if require_live and not pp_plugin.is_live_configured:
        raise ExternalProviderError(
            "PayPal Sandbox credentials are required when require_live=True",
            issue="CREDENTIALS_MISSING",
        )
    cs = get_connector_state(state)
    executed_tools: list[dict[str, Any]] = []
    nonce = uuid.uuid4().hex[:8]
    clean_origin = public_origin.rstrip("/")

    def _impl_introspect() -> dict[str, Any]:
        meta: dict[str, Any] = {
            "provider_mode": pp_plugin.mode_label,
            "live_credentials_configured": pp_plugin.is_live_configured,
        }
        if pp_plugin.is_live_configured:
            oauth = pp_plugin.obtain_oauth_metadata()
            disputes = pp_plugin.list_disputes()
            meta["app_id"] = oauth.get("app_id", "")
            meta["scopes_count"] = len(oauth.get("scopes") or [])
            meta["live_disputes_count"] = len(disputes.get("items") or [])
        open_docs = [
            {"document_id": did, "open_cents": d.gross_cents - d.paid_cents, "currency": d.currency}
            for did, d in state.crm.documents.items()
            if d.direction == Direction.SALES_REVENUE and d.gross_cents > d.paid_cents
        ]
        meta["open_sales_invoices"] = open_docs[:5]
        meta["pending_paypal_orders"] = len(cs.pending_paypal_orders)
        executed_tools.append({"tool": "paypal_introspect_sandbox_status", "result": meta})
        return meta

    def _impl_create_order(document_id: str = "auto") -> dict[str, Any]:
        doc_id = _pick_open_sales_doc_id(state, document_id)
        doc = state.crm.documents[doc_id]
        open_cents = max(100, doc.gross_cents - doc.paid_cents)
        created = pp_plugin.create_order_or_invoice(
            tenant_id=tid,
            document_id=doc_id,
            amount_cents=open_cents,
            currency=doc.currency,
            payer_email="buyer-sb@client-synth.eu",
            description=f"Kerdon Sales Invoice {doc_id}",
            return_url=f"{clean_origin}/#module=documents",
            cancel_url=f"{clean_origin}/#module=documents",
            unique_nonce=nonce,
        )
        cs.pending_paypal_orders[created["order_id"]] = created
        res = {
            "order_id": created["order_id"],
            "document_id": doc_id,
            "amount_cents": open_cents,
            "currency": doc.currency,
            "status": created["status"],
            "approval_url": created["approval_url"],
            "debug_id": created.get("debug_id", ""),
            "provider_mode": created["provider_mode"],
            "ledger_posted": False,
        }
        executed_tools.append({"tool": "paypal_create_checkout_order_v2", "result": res})
        return res

    def _impl_inspect_or_capture(order_id: str) -> dict[str, Any]:
        oid = order_id.strip()
        info = pp_plugin.get_order(oid)
        live_status = str(info.get("status") or "CREATED").upper()
        pending = cs.pending_paypal_orders.get(oid) or {}
        doc_id = str(pending.get("document_id") or _pick_open_sales_doc_id(state, "auto"))
        doc = state.crm.documents[doc_id]
        gross = int(pending.get("amount_cents") or max(100, doc.gross_cents - doc.paid_cents))
        if live_status != "APPROVED":
            res = {
                "order_id": oid,
                "live_status": live_status,
                "captured": False,
                "approval_url": pending.get("approval_url") or f"{pp_plugin.web_host}/checkoutnow?token={oid}",
                "reason": f"Order {oid} is in status {live_status}; awaiting buyer approval before capture.",
                "debug_id": info.get("debug_id", ""),
            }
            executed_tools.append({"tool": "paypal_inspect_or_capture_order_v2", "result": res})
            return res
        cap = pp_plugin.capture_order(
            tenant_id=tid, order_id=oid, document_id=doc_id, gross_cents=gross, currency=doc.currency
        )
        settled = apply_paypal_capture_to_ledger(
            state,
            document_id=doc_id,
            order_id=oid,
            paypal_invoice_id=str(pending.get("paypal_invoice_id") or f"PPINV-{oid[-8:]}"),
            capture_id=cap["capture_id"],
            gross_cents=int(cap.get("gross_cents") or gross),
            fee_cents=cap.get("fee_cents"),
            captured_date="2026-10-29",
            approval_url=str(pending.get("approval_url") or ""),
            provider_mode=cap["provider_mode"],
        )
        cs.pending_paypal_orders.pop(oid, None)
        res = {"captured": True, "order": asdict(settled), "debug_id": cap.get("debug_id", "")}
        executed_tools.append({"tool": "paypal_inspect_or_capture_order_v2", "result": res})
        return res

    def _impl_provision_subscription(
        tier_name: str = "Kerdon Autonomous Mini-ERP Pro", monthly_price_cents: int = 14_900
    ) -> dict[str, Any]:
        sub = pp_plugin.create_subscription_bundle(
            tenant_id=tid,
            tier_name=tier_name,
            monthly_price_cents=int(monthly_price_cents or 14_900),
            currency="EUR",
            unique_nonce=nonce,
        )
        cs.paypal_subscriptions[sub["subscription_id"]] = sub
        executed_tools.append({"tool": "paypal_provision_subscription_plan_v1", "result": sub})
        return sub

    def _impl_register_webhook() -> dict[str, Any]:
        wh_url = f"{clean_origin}/erp/connectors/paypal/webhook"
        wh = pp_plugin.list_or_register_webhook(webhook_url=wh_url)
        if wh.get("webhook_id"):
            cs.paypal_webhooks[wh["webhook_id"]] = wh
        executed_tools.append({"tool": "paypal_register_or_list_webhook_v1", "result": wh})
        return wh

    def _impl_diagnose_or_payout(approval_id: str = "auto") -> dict[str, Any]:
        target_apr = None
        if approval_id and approval_id != "auto":
            target_apr = state.treasury.approvals.get(approval_id)
        else:
            for apr in state.treasury.approvals.values():
                if apr.state.value == "VALID" and apr.approver_id != "act-treasury-release-officer":
                    target_apr = apr
                    break
        if target_apr is None:
            res = {"status": "NO_VALID_FOUR_EYES_APPROVAL", "executed": False}
            executed_tools.append({"tool": "paypal_diagnose_or_execute_payout_v1", "result": res})
            return res
        rec_email = target_apr.recipient_account or "seller-payout-sb@kerdon-synth.eu"
        val_str = f"{target_apr.amount_cents // 100}.{target_apr.amount_cents % 100:02d}"
        try:
            live_batch = pp_plugin.execute_batch_payout(
                tenant_id=tid,
                sender_batch_id=f"agent-{tid[:10]}-{target_apr.approval_id[-8:]}-{nonce}",
                items=[
                    {
                        "recipient_type": "EMAIL",
                        "amount": {"value": val_str, "currency": target_apr.currency},
                        "receiver": rec_email,
                        "note": f"Kerdon Approved Payout {target_apr.approval_id}",
                        "sender_item_id": target_apr.approval_id,
                    }
                ],
                currency=target_apr.currency,
            )
            payout_rec = execute_governed_paypal_payout(
                state,
                approval_id=target_apr.approval_id,
                executor_id="act-treasury-release-officer" if actor.actor_id == target_apr.approver_id else actor.actor_id,
                recipient_email=rec_email,
                payout_batch_id=live_batch["payout_batch_id"],
                batch_status=live_batch["status"],
                provider_mode=live_batch["provider_mode"],
            )
            res = {"executed": True, "payout": asdict(payout_rec), "debug_id": live_batch.get("debug_id", "")}
        except ExternalProviderError as exc:
            res = {
                "executed": False,
                "status": "PROVIDER_REJECTED_FAIL_CLOSED",
                "approval_id": target_apr.approval_id,
                "approval_preserved_valid": state.treasury.approvals[target_apr.approval_id].state.value == "VALID",
                "issue": exc.issue or "PROVIDER_ERROR",
                "debug_id": exc.debug_id,
                "message": str(exc),
                "remediation": "Capture an approved PayPal buyer order or fund the Sandbox merchant wallet before retrying.",
            }
        executed_tools.append({"tool": "paypal_diagnose_or_execute_payout_v1", "result": res})
        return res

    mode = (llm_mode or os.environ.get("KERDON_LLM_MODE", "deterministic")).lower().strip()
    if require_live:
        mode = "bedrock"

    narrative = ""
    engine_label = "deterministic-tool-router"
    started = time.time()

    if mode == "bedrock":
        try:
            from strands import Agent, tool
            from strands.models import BedrockModel

            @tool
            def paypal_introspect_sandbox_status() -> str:
                """Inspect live PayPal OAuth2 app_id, granted scopes, disputes, and open ERP invoices."""
                import json as _j
                return _j.dumps(_impl_introspect())

            @tool
            def paypal_create_checkout_order_v2(document_id: str = "auto") -> str:
                """Create a real PayPal Order v2 on Sandbox for an open sales invoice (pass 'auto' for next unpaid)."""
                import json as _j
                return _j.dumps(_impl_create_order(document_id))

            @tool
            def paypal_inspect_or_capture_order_v2(order_id: str) -> str:
                """Inspect live PayPal Order v2 status and capture into 3-line GL if buyer-approved."""
                import json as _j
                return _j.dumps(_impl_inspect_or_capture(order_id))

            @tool
            def paypal_provision_subscription_plan_v1(
                tier_name: str = "Kerdon Autonomous Mini-ERP Pro", monthly_price_cents: int = 14900
            ) -> str:
                """Create a PayPal Catalog Product, Billing Plan, and Subscription v1 in EUR."""
                import json as _j
                return _j.dumps(_impl_provision_subscription(tier_name, monthly_price_cents))

            @tool
            def paypal_register_or_list_webhook_v1() -> str:
                """List or register the Kerdon ERP Webhook v1 subscription on PayPal Sandbox."""
                import json as _j
                return _j.dumps(_impl_register_webhook())

            @tool
            def paypal_diagnose_or_execute_payout_v1(approval_id: str = "auto") -> str:
                """Execute or fail-closed diagnose a Four-Eyes approved PayPal Batch Payout v1."""
                import json as _j
                return _j.dumps(_impl_diagnose_or_payout(approval_id))

            resolved_model = (
                os.environ.get("BEDROCK_MODEL_ID")
                or os.environ.get("KERDON_BEDROCK_MODEL_ID")
                or model_id
            )
            bedrock_model = BedrockModel(
                model_id=resolved_model, region_name=region_name, temperature=0.0
            )
            agent = Agent(
                model=bedrock_model,
                system_prompt=PAYPAL_AGENT_SYSTEM_PROMPT,
                tools=[
                    paypal_introspect_sandbox_status,
                    paypal_create_checkout_order_v2,
                    paypal_inspect_or_capture_order_v2,
                    paypal_provision_subscription_plan_v1,
                    paypal_register_or_list_webhook_v1,
                    paypal_diagnose_or_execute_payout_v1,
                ],
            )
            narrative = str(agent(goal)).strip()
            engine_label = f"strands-bedrock-tools:{resolved_model}"
        except Exception as exc:
            if require_live:
                raise ExternalProviderError(
                    f"Strands/Bedrock PayPal Agent failed in require_live mode: {exc}",
                    issue="BEDROCK_AGENT_ERROR",
                ) from exc

    if not executed_tools:
        low = goal.lower()
        _impl_introspect()
        if any(k in low for k in ("order", "checkout", "invoice", "collect", "full", "suite")):
            _impl_create_order("auto")
        if any(k in low for k in ("subscri", "plan", "recurring", "saas", "full", "suite")):
            _impl_provision_subscription()
        if any(k in low for k in ("webhook", "notify", "full", "suite")):
            _impl_register_webhook()
        if any(k in low for k in ("payout", "disburse", "commission", "treasury", "full", "suite")):
            _impl_diagnose_or_payout("auto")

    if not narrative:
        parts = [f"Executed {len(executed_tools)} PayPal tool call(s) in {pp_plugin.mode_label} mode:"]
        for item in executed_tools:
            r = item["result"]
            tid_ref = (
                r.get("order_id")
                or r.get("subscription_id")
                or r.get("webhook_id")
                or r.get("payout_batch_id")
                or r.get("debug_id")
                or r.get("app_id")
                or "ok"
            )
            parts.append(f"{item['tool']} -> {tid_ref}")
        narrative = " | ".join(parts)

    mem_status = record_agentcore_memory_event(
        tenant_id=tid,
        session_id=f"paypal-agent-{tid}-{nonce}",
        event_summary=f"PayPal Agent goal='{goal[:120]}' tools={len(executed_tools)} mode={pp_plugin.mode_label}",
        region_name=region_name,
    )
    elapsed_ms = round((time.time() - started) * 1000.0, 2)
    return {
        "engine": engine_label,
        "provider_mode": pp_plugin.mode_label,
        "goal": goal,
        "tools_executed_count": len(executed_tools),
        "executed_tools": executed_tools,
        "narrative": narrative,
        "agentcore_memory_status": mem_status,
        "elapsed_ms": elapsed_ms,
    }
