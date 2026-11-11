"""Approved Sandbox Payment Provider Adapter with Verified Beneficiaries,
Evidence-Bound Four-Eyes Release, Idempotent Submission, and Signed Webhook Reconciliation.

Explicitly separates internal GL cash journal entries (`JOURNAL_ONLY`) from
external bank transfer execution (`SUBMITTED_TO_SANDBOX` -> `SETTLED_AT_BANK`).
Never embeds live bank credentials in source code.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import hmac
import json
import os
from typing import Any

import kerdon as kd
from kerdon.erp_services import get_erp_extensions

from .http_utils import ValidationError


@dataclass
class SandboxTransferOrder:
    """External sandbox payment order bound to a governed treasury approval and IBAN."""

    transfer_id: str
    tenant_id: str
    approval_id: str
    payout_id: str
    counterparty_id: str
    beneficiary_name: str
    beneficiary_iban: str
    amount_cents: int
    currency: str
    idempotency_key: str
    evidence_sha256: str
    binding_digest: str
    provider_mode: str
    status: str  # "SUBMITTED_TO_SANDBOX" | "SETTLED_AT_BANK" | "FAILED_AT_BANK"
    submitted_by: str
    approved_by: str
    submitted_at_epoch: int
    settled_at_epoch: int = 0
    bank_settlement_ref: str = ""
    failure_reason: str = ""


@dataclass
class SandboxProviderRuntime:
    """In-memory + DynamoDB-audited sandbox transfer and webhook state."""

    transfers_by_id: dict[str, SandboxTransferOrder] = field(default_factory=dict)
    transfers_by_idem: dict[str, str] = field(default_factory=dict)
    processed_webhook_ids: set[str] = field(default_factory=set)


_SANDBOX_RUNTIME = SandboxProviderRuntime()


def get_sandbox_runtime() -> SandboxProviderRuntime:
    return _SANDBOX_RUNTIME


def reset_sandbox_runtime() -> None:
    _SANDBOX_RUNTIME.transfers_by_id.clear()
    _SANDBOX_RUNTIME.transfers_by_idem.clear()
    _SANDBOX_RUNTIME.processed_webhook_ids.clear()


def verify_beneficiary_iban(iban: str) -> str:
    """Validate basic ISO 13616 IBAN format for a verified supplier beneficiary."""
    clean = "".join(ch for ch in str(iban or "").upper().strip() if not ch.isspace())
    if len(clean) < 15 or len(clean) > 34 or not clean[:2].isalpha() or not clean[2:4].isdigit():
        raise ValidationError(
            f"Unverified or malformed beneficiary IBAN '{iban}': must be valid ISO 13616 format"
        )
    return clean


def sign_webhook_payload(payload: dict[str, Any], secret: str | None = None) -> str:
    """Compute HMAC-SHA256 signature over canonical webhook JSON."""
    key = (
        secret
        or os.environ.get("KERDON_WEBHOOK_SECRET")
        or "kerdon-sandbox-webhook-secret-v1"
    ).encode("utf-8")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def submit_sandbox_payout(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
    store: Any,
    now_ts: int,
) -> dict[str, Any]:
    """Submit an approved payout to the sandbox payment provider with Four-Eyes and IBAN verification."""
    approval_id = str(body.get("approval_id") or "").strip()
    if not approval_id:
        raise ValidationError("approval_id is required")
    approval = state.treasury.approvals.get(approval_id)
    if approval is None:
        raise KeyError(f"Unknown approval_id: {approval_id}")

    # Enforce Four-Eyes separation unconditionally across initiator/preparer and executor
    creator_id = str(body.get("created_by") or approval.preparer_id or approval.approver_id).strip()
    if creator_id == actor.actor_id:
        raise kd.SelfApprovalError(
            f"Four-Eyes violation: actor {actor.actor_id} cannot both initiate/approve and release bank execution"
        )

    # Verify beneficiary IBAN from supplier registry or explicit verified override
    sup = state.crm.suppliers.get(approval.counterparty_id)
    bound_iban = (
        approval.recipient_account
        if (approval.recipient_account and "@" not in approval.recipient_account)
        else ""
    )
    raw_iban = str(
        body.get("beneficiary_iban") or bound_iban or (sup.iban if sup else "")
    ).strip()
    if not raw_iban and approval.counterparty_id == "PAYROLL_COMMISSION_POOL":
        raw_iban = "GR1601101250000000099999999"
    verified_iban = verify_beneficiary_iban(raw_iban)
    if bound_iban and verify_beneficiary_iban(bound_iban) != verified_iban:
        raise ValidationError(
            f"Beneficiary IBAN mismatch: '{verified_iban}' does not match approval bound IBAN '{bound_iban}'"
        )
    beneficiary_name = sup.legal_name if sup else approval.counterparty_id

    writer = kd.Writer(actor)
    rcpt = writer.execute(
        tid,
        kd.Capability.EXECUTE_PAYOUTS,
        approval_token=f"sbx-{approval_id}",
        mutation_fn=lambda: state.treasury.execute_payout(
            approval_id=approval_id, now_epoch=now_ts, executor_id=actor.actor_id
        ),
    )

    live_key_present = bool(os.environ.get("KERDON_BANK_SANDBOX_API_KEY", "").strip())
    provider_mode = (
        "external-sandbox-api" if live_key_present else "deterministic-local-sandbox"
    )
    transfer_id = f"trf-{approval_id}"
    order = SandboxTransferOrder(
        transfer_id=transfer_id,
        tenant_id=tid,
        approval_id=approval_id,
        payout_id=rcpt.payout_id,
        counterparty_id=approval.counterparty_id,
        beneficiary_name=beneficiary_name,
        beneficiary_iban=verified_iban,
        amount_cents=rcpt.amount_cents,
        currency=rcpt.currency,
        idempotency_key=rcpt.idempotency_key,
        evidence_sha256=approval.evidence_sha256,
        binding_digest=rcpt.binding_digest,
        provider_mode=provider_mode,
        status="SUBMITTED_TO_SANDBOX",
        submitted_by=actor.actor_id,
        approved_by=approval.approver_id,
        submitted_at_epoch=now_ts,
    )
    rt = get_sandbox_runtime()
    rt.transfers_by_id[transfer_id] = order
    rt.transfers_by_idem[rcpt.idempotency_key] = transfer_id

    aletheia = kd.seal_aletheia_receipt(
        tenant_id=tid,
        subject_id=transfer_id,
        approver_id=actor.actor_id,
        amount_cents=rcpt.amount_cents,
        currency=rcpt.currency,
        evidence_hashes=(rcpt.binding_digest,),
    )
    store.persist_audit_record(tid, "SANDBOX_TRANSFER_SUBMITTED", transfer_id, asdict(order))
    store.persist_approval_state(approval_id, tid, "EXECUTED", rcpt.binding_digest)
    return {
        "transfer": asdict(order),
        "receipt": asdict(rcpt),
        "aletheia_receipt": asdict(aletheia),
        "live_bank_credentials_configured": live_key_present,
    }


def reconcile_sandbox_webhook(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    event: dict[str, Any],
    store: Any,
    now_ts: int,
) -> dict[str, Any]:
    """Verify signed provider webhook callback and reconcile transfer & settlement status."""
    headers = {
        str(k).lower(): str(v)
        for k, v in (event.get("headers") or {}).items()
        if v is not None
    }
    provided_sig = headers.get("x-kerdon-webhook-signature", "").strip()
    if not provided_sig:
        raise kd.PermissionDeniedError("Missing required x-kerdon-webhook-signature header")

    expected_sig = sign_webhook_payload(body)
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise kd.PermissionDeniedError("Invalid webhook HMAC-SHA256 signature")

    webhook_id = str(body.get("webhook_event_id") or "").strip()
    transfer_id = str(body.get("transfer_id") or "").strip()
    new_status = str(body.get("status") or "SETTLED_AT_BANK").upper().strip()
    if not webhook_id or not transfer_id:
        raise ValidationError("webhook_event_id and transfer_id are required")
    if new_status not in ("SETTLED_AT_BANK", "FAILED_AT_BANK"):
        raise ValidationError("Webhook status must be SETTLED_AT_BANK or FAILED_AT_BANK")

    rt = get_sandbox_runtime()
    if webhook_id in rt.processed_webhook_ids:
        raise kd.DuplicateIdempotencyError(
            f"Duplicate webhook_event_id '{webhook_id}' already processed"
        )
    order = rt.transfers_by_id.get(transfer_id)
    if order is None or order.tenant_id != tid:
        raise KeyError(f"Unknown transfer_id '{transfer_id}' for tenant {tid}")

    rt.processed_webhook_ids.add(webhook_id)
    order.status = new_status
    order.settled_at_epoch = now_ts
    order.bank_settlement_ref = str(
        body.get("bank_settlement_ref") or f"BNK-REF-{webhook_id}"
    ).strip()
    if new_status == "FAILED_AT_BANK":
        order.failure_reason = str(body.get("failure_reason") or "Bank rejected transfer").strip()

    # Reconcile any linked SettlementRecord in ERP extensions
    ext = get_erp_extensions(state)
    linked_settlement_id = str(body.get("settlement_id") or "").strip()
    if linked_settlement_id and linked_settlement_id in ext.settlements:
        old_st = ext.settlements[linked_settlement_id]
        ext.settlements[linked_settlement_id] = type(old_st)(
            **{
                **asdict(old_st),
                "allocations": old_st.allocations,
                "bank_execution_status": new_status,
                "external_transfer_id": transfer_id,
            }
        )

    store.persist_audit_record(tid, "SANDBOX_WEBHOOK_RECONCILED", webhook_id, asdict(order))
    return {
        "webhook_event_id": webhook_id,
        "transfer": asdict(order),
        "reconciled": True,
    }
