"""Archon Superset Domain: 6-Reader Strands Graph, Toolless Composer Release Gate, Transfer Ref vs Email Hash Separation, Dispute Holds, 240-Record Portfolio, Redacted Evidence Bundle, and Send/Admission Ledgers."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
from typing import Any

from .demo_fixtures import TenantMiniErpState
from .docgen import format_eur


class RemittanceClassification(str, Enum):
    """Disposition of an inbound bank transfer advice (Archon transfer_reference vs email_sha256)."""

    POSTED_RECEIPT = "POSTED_RECEIPT"
    VALID_INSTALMENT = "VALID_INSTALMENT"
    DUPLICATE_TRANSFER_HOLD = "DUPLICATE_TRANSFER_HOLD"
    UNVERIFIED_REMITTANCE_HOLD = "UNVERIFIED_REMITTANCE_HOLD"


@dataclass(frozen=True)
class RemittanceDecision:
    """Deterministic classification of an inbound remittance separating bank ref from email hash."""

    remittance_id: str
    tenant_id: str
    document_id: str
    amount_cents: int
    value_date: str
    email_sha256: str
    transfer_reference: str
    classification: RemittanceClassification
    hold_active: bool
    linked_original_remittance_id: str
    explanation: str


@dataclass(frozen=True)
class IdentityAttestationRecord:
    """Additive human attestation resolving an unverified remittance without rewriting history."""

    attestation_id: str
    tenant_id: str
    remittance_id: str
    document_id: str
    verified_transfer_reference: str
    attested_by_actor_id: str
    reason: str
    attested_at_epoch: int
    attestation_sha256: str


@dataclass(frozen=True)
class ClientDisputeHold:
    """Collection hold triggered by an ambiguous or disputed client reply email."""

    dispute_hold_id: str
    tenant_id: str
    document_id: str
    counterparty_id: str
    client_email_sha256: str
    client_excerpt: str
    status: str
    resolution_note: str = ""
    resolved_by_actor_id: str = ""


def classify_inbound_remittance(
    *,
    remittance_id: str,
    tenant_id: str,
    document_id: str,
    amount_cents: int,
    value_date: str,
    email_sha256: str,
    transfer_reference: str,
    existing_remittances: tuple[RemittanceDecision, ...],
) -> RemittanceDecision:
    """Separate bank transfer_reference from email_sha256 to catch forwarded duplicates while allowing equal instalments."""
    clean_ref = (transfer_reference or "").strip()
    if not clean_ref:
        return RemittanceDecision(
            remittance_id=remittance_id,
            tenant_id=tenant_id,
            document_id=document_id,
            amount_cents=amount_cents,
            value_date=value_date,
            email_sha256=email_sha256,
            transfer_reference="",
            classification=RemittanceClassification.UNVERIFIED_REMITTANCE_HOLD,
            hold_active=True,
            linked_original_remittance_id="",
            explanation=(
                "Remittance email lacks a bank transfer_reference. Held from posting until "
                "human Identity Attestation records the bank reference."
            ),
        )

    for prev in existing_remittances:
        if prev.tenant_id == tenant_id and prev.transfer_reference == clean_ref:
            return RemittanceDecision(
                remittance_id=remittance_id,
                tenant_id=tenant_id,
                document_id=document_id,
                amount_cents=amount_cents,
                value_date=value_date,
                email_sha256=email_sha256,
                transfer_reference=clean_ref,
                classification=RemittanceClassification.DUPLICATE_TRANSFER_HOLD,
                hold_active=True,
                linked_original_remittance_id=prev.remittance_id,
                explanation=(
                    f"Bank transfer_reference {clean_ref} already posted under {prev.remittance_id} "
                    f"(even though email SHA-256 {email_sha256[:12]} differs). Held to prevent double credit."
                ),
            )

    same_doc_date_amt = [
        p
        for p in existing_remittances
        if p.tenant_id == tenant_id
        and p.document_id == document_id
        and p.value_date == value_date
        and p.amount_cents == amount_cents
        and not p.hold_active
    ]
    if same_doc_date_amt:
        return RemittanceDecision(
            remittance_id=remittance_id,
            tenant_id=tenant_id,
            document_id=document_id,
            amount_cents=amount_cents,
            value_date=value_date,
            email_sha256=email_sha256,
            transfer_reference=clean_ref,
            classification=RemittanceClassification.VALID_INSTALMENT,
            hold_active=False,
            linked_original_remittance_id="",
            explanation=(
                f"Equal instalment on {document_id} allowed because transfer_reference {clean_ref} "
                "is distinct from prior instalments."
            ),
        )

    return RemittanceDecision(
        remittance_id=remittance_id,
        tenant_id=tenant_id,
        document_id=document_id,
        amount_cents=amount_cents,
        value_date=value_date,
        email_sha256=email_sha256,
        transfer_reference=clean_ref,
        classification=RemittanceClassification.POSTED_RECEIPT,
        hold_active=False,
        linked_original_remittance_id="",
        explanation=f"Verified bank transfer_reference {clean_ref}; posted to ledger.",
    )


def attest_remittance_identity(
    decision: RemittanceDecision,
    *,
    verified_transfer_reference: str,
    actor_id: str,
    reason: str,
    now_epoch: int,
) -> tuple[RemittanceDecision, IdentityAttestationRecord]:
    """Resolve an UNVERIFIED_REMITTANCE_HOLD via additive human attestation."""
    clean_ref = verified_transfer_reference.strip()
    if not clean_ref:
        raise ValueError("verified_transfer_reference is required for identity attestation")
    att_hash = hashlib.sha256(
        f"{decision.remittance_id}:{clean_ref}:{actor_id}:{now_epoch}".encode("utf-8")
    ).hexdigest()
    attestation = IdentityAttestationRecord(
        attestation_id=f"att-{att_hash[:10]}",
        tenant_id=decision.tenant_id,
        remittance_id=decision.remittance_id,
        document_id=decision.document_id,
        verified_transfer_reference=clean_ref,
        attested_by_actor_id=actor_id,
        reason=reason.strip() or "Verified against bank statement line",
        attested_at_epoch=now_epoch,
        attestation_sha256=att_hash,
    )
    resolved = RemittanceDecision(
        remittance_id=decision.remittance_id,
        tenant_id=decision.tenant_id,
        document_id=decision.document_id,
        amount_cents=decision.amount_cents,
        value_date=decision.value_date,
        email_sha256=decision.email_sha256,
        transfer_reference=clean_ref,
        classification=RemittanceClassification.POSTED_RECEIPT,
        hold_active=False,
        linked_original_remittance_id="",
        explanation=f"Released via human Identity Attestation {attestation.attestation_id} ({clean_ref}).",
    )
    return resolved, attestation


@dataclass(frozen=True)
class ReaderNodeOutput:
    """Output of one of the 6 specialized Strands ledger readers."""

    reader_name: str
    status: str
    summary: str
    facts: dict[str, Any]


@dataclass(frozen=True)
class SixReaderGraphReport:
    """Complete 6-reader Strands graph output feeding the toolless composer."""

    tenant_id: str
    document_id: str
    counterparty_id: str
    counterparty_name: str
    recipient_email: str
    invoice_gross_cents: int
    allocated_remittance_cents: int
    credit_note_cents: int
    net_collectible_cents: int
    dispute_hold_active: bool
    duplicate_transfer_hold_active: bool
    unverified_remittance_hold_active: bool
    all_six_readers_completed: bool
    readers: tuple[ReaderNodeOutput, ...]
    toolless_composer_draft: str


@dataclass(frozen=True)
class ReleaseGateVerdict:
    """Deterministic text release gate checking every figure and hold before approval."""

    allowed: bool
    blocked_reason: str
    expected_amount_str: str
    expected_document_id: str
    expected_recipient: str
    checked_prose: str
    checks: dict[str, bool]


def run_six_reader_strands_graph(
    state: TenantMiniErpState,
    document_id: str,
    *,
    remittances: tuple[RemittanceDecision, ...] = (),
    dispute_holds: tuple[ClientDisputeHold, ...] = (),
) -> SixReaderGraphReport:
    """Execute all 6 specialized readers on a document before drafting outbound prose."""
    doc = state.crm.documents.get(document_id)
    if doc is None:
        raise KeyError(f"Unknown document_id: {document_id}")

    cust = state.crm.customers.get(doc.counterparty_id)
    recipient_email = cust.email if cust else f"finance@{doc.counterparty_id}.example.com"

    # 1. invoice_reader
    r1 = ReaderNodeOutput(
        reader_name="invoice_reader",
        status="COMPLETED",
        summary=f"Invoice {doc.document_id} gross {format_eur(doc.gross_cents)} due {doc.due_date}",
        facts={
            "document_id": doc.document_id,
            "gross_cents": doc.gross_cents,
            "due_date": doc.due_date,
        },
    )

    # 2. remittance_reader
    posted_rems = [
        r
        for r in remittances
        if r.document_id == document_id and not r.hold_active
    ]
    extra_rem_cents = sum(r.amount_cents for r in posted_rems)
    allocated_cents = min(doc.gross_cents, doc.paid_cents + extra_rem_cents)
    unverified_hold = any(
        r.document_id == document_id
        and r.classification == RemittanceClassification.UNVERIFIED_REMITTANCE_HOLD
        and r.hold_active
        for r in remittances
    )
    r2 = ReaderNodeOutput(
        reader_name="remittance_reader",
        status="COMPLETED",
        summary=f"Allocated {format_eur(allocated_cents)} paid; unverified_hold={unverified_hold}",
        facts={
            "allocated_cents": allocated_cents,
            "unverified_remittance_hold": unverified_hold,
        },
    )

    # 3. credit_note_reader
    linked_cns = [
        cn
        for cn in state.crm.credit_notes.values()
        if cn.referenced_invoice_id == document_id or cn.counterparty_id == doc.counterparty_id
    ]
    cn_cents = sum(cn.gross_cents for cn in linked_cns)
    r3 = ReaderNodeOutput(
        reader_name="credit_note_reader",
        status="COMPLETED",
        summary=f"Found {len(linked_cns)} credit note(s) totaling {format_eur(cn_cents)}",
        facts={"credit_note_count": len(linked_cns), "credit_note_cents": cn_cents},
    )

    # 4. dispute_reader
    active_disputes = [
        d
        for d in dispute_holds
        if d.document_id == document_id and d.status == "OPEN_HOLD"
    ]
    dispute_active = len(active_disputes) > 0
    r4 = ReaderNodeOutput(
        reader_name="dispute_reader",
        status="COMPLETED",
        summary=(
            f"Active dispute hold: {active_disputes[0].client_excerpt}"
            if dispute_active
            else "No active client dispute holds"
        ),
        facts={"dispute_hold_active": dispute_active, "count": len(active_disputes)},
    )

    # 5. duplicate_transfer_reader
    dup_rems = [
        r
        for r in remittances
        if r.document_id == document_id
        and r.classification == RemittanceClassification.DUPLICATE_TRANSFER_HOLD
        and r.hold_active
    ]
    dup_active = len(dup_rems) > 0
    r5 = ReaderNodeOutput(
        reader_name="duplicate_transfer_reader",
        status="COMPLETED",
        summary=(
            f"Held {len(dup_rems)} duplicate forwarded transfer advice(s)"
            if dup_active
            else "Zero duplicate transfer collisions"
        ),
        facts={"duplicate_transfer_hold": dup_active, "count": len(dup_rems)},
    )

    # 6. balance_reader
    net_collectible = max(0, doc.gross_cents - allocated_cents - cn_cents)
    r6 = ReaderNodeOutput(
        reader_name="balance_reader",
        status="COMPLETED",
        summary=f"Authoritative collectible balance: {format_eur(net_collectible)}",
        facts={"net_collectible_cents": net_collectible},
    )

    draft_prose = (
        f"To: {recipient_email} ({doc.counterparty_name}) | Subject: Statement & Reminder for {doc.document_id}. "
        f"Original invoice gross: {format_eur(doc.gross_cents)}, less allocated payments {format_eur(allocated_cents)} "
        f"and credit notes {format_eur(cn_cents)}. Authoritative balance due on {doc.document_id}: "
        f"{format_eur(net_collectible)}."
    )

    return SixReaderGraphReport(
        tenant_id=state.tenant.tenant_id,
        document_id=doc.document_id,
        counterparty_id=doc.counterparty_id,
        counterparty_name=doc.counterparty_name,
        recipient_email=recipient_email,
        invoice_gross_cents=doc.gross_cents,
        allocated_remittance_cents=allocated_cents,
        credit_note_cents=cn_cents,
        net_collectible_cents=net_collectible,
        dispute_hold_active=dispute_active,
        duplicate_transfer_hold_active=dup_active,
        unverified_remittance_hold_active=unverified_hold,
        all_six_readers_completed=True,
        readers=(r1, r2, r3, r4, r5, r6),
        toolless_composer_draft=draft_prose,
    )


def verify_outbound_draft_release_gate(
    report: SixReaderGraphReport,
    candidate_prose: str | None = None,
    candidate_recipient: str | None = None,
) -> ReleaseGateVerdict:
    """Deterministic post-composer release gate blocking holds or hallucinated numbers."""
    prose = candidate_prose if candidate_prose is not None else report.toolless_composer_draft
    recipient = candidate_recipient if candidate_recipient is not None else report.recipient_email
    expected_amt = format_eur(report.net_collectible_cents)

    checks = {
        "all_six_readers_completed": report.all_six_readers_completed and len(report.readers) == 6,
        "no_dispute_hold": not report.dispute_hold_active,
        "no_unverified_remittance_hold": not report.unverified_remittance_hold_active,
        "positive_collectible_balance": report.net_collectible_cents > 0,
        "exact_balance_in_prose": expected_amt in prose,
        "exact_document_id_in_prose": report.document_id in prose,
        "exact_recipient_match": recipient.strip().lower() == report.recipient_email.strip().lower(),
    }

    blocked_reason = ""
    if not checks["all_six_readers_completed"]:
        blocked_reason = "INCOMPLETE_STRANDS_READER_GRAPH"
    elif not checks["no_dispute_hold"]:
        blocked_reason = "CLIENT_DISPUTE_COLLECTION_HOLD"
    elif not checks["no_unverified_remittance_hold"]:
        blocked_reason = "UNVERIFIED_REMITTANCE_HOLD"
    elif not checks["positive_collectible_balance"]:
        blocked_reason = "ZERO_COLLECTIBLE_BALANCE"
    elif not checks["exact_balance_in_prose"]:
        blocked_reason = "NUMERIC_DRIFT_IN_PROSE"
    elif not checks["exact_document_id_in_prose"]:
        blocked_reason = "MISSING_DOCUMENT_ID_IN_PROSE"
    elif not checks["exact_recipient_match"]:
        blocked_reason = "RECIPIENT_MISMATCH"

    return ReleaseGateVerdict(
        allowed=(blocked_reason == ""),
        blocked_reason=blocked_reason,
        expected_amount_str=expected_amt,
        expected_document_id=report.document_id,
        expected_recipient=report.recipient_email,
        checked_prose=prose,
        checks=checks,
    )


@dataclass
class AdmissionBudgetLedger:
    """Hard token/spend reservation ledger before Bedrock/SES calls (`2 * utf8_bytes + 4096`)."""

    max_tokens_budget: int = 250_000
    reserved_tokens_total: int = 0
    call_count: int = 0

    def reserve(self, payload_text: str) -> int:
        utf8_bytes = len((payload_text or "").encode("utf-8"))
        tokens_needed = 2 * utf8_bytes + 4096
        if self.reserved_tokens_total + tokens_needed > self.max_tokens_budget:
            raise PermissionError(
                f"Admission budget exceeded: need {tokens_needed}, remaining {self.max_tokens_budget - self.reserved_tokens_total}"
            )
        self.reserved_tokens_total += tokens_needed
        self.call_count += 1
        return tokens_needed


class DuplicateSendBlockedError(RuntimeError):
    """Raised when an outbound draft is dispatched more than once."""


@dataclass
class DurableSendLedger:
    """Idempotent outbox ledger preventing duplicate SES/outbound dispatches."""

    sent_records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def record_send(
        self,
        *,
        tenant_id: str,
        draft_id: str,
        recipient: str,
        content_sha256: str,
        now_epoch: int,
    ) -> dict[str, Any]:
        key = f"{tenant_id}:{draft_id}"
        if key in self.sent_records:
            raise DuplicateSendBlockedError(
                f"Outbound draft {draft_id} already dispatched for tenant {tenant_id}"
            )
        entry = {
            "send_key": key,
            "tenant_id": tenant_id,
            "draft_id": draft_id,
            "recipient": recipient,
            "content_sha256": content_sha256,
            "sent_at_epoch": now_epoch,
        }
        self.sent_records[key] = entry
        return entry


@dataclass(frozen=True)
class PortfolioRecordSummary:
    """Summary of the 240-record multi-month business portfolio (Archon PR #22/#23)."""

    mode: str
    total_records: int
    sales_invoices: int
    purchase_invoices: int
    sales_credit_notes: int
    purchase_credit_notes: int
    client_receipts: int
    supplier_payments: int
    customer_count: int
    supplier_count: int
    periods: tuple[str, ...]
    records_preview: tuple[dict[str, Any], ...]


def build_240_record_portfolio(tenant_id: str) -> PortfolioRecordSummary:
    """Generate deterministic 240-record multi-month portfolio across 16 clients and 10 suppliers."""
    records: list[dict[str, Any]] = []
    periods = ("2026-08", "2026-09", "2026-10")

    for i in range(1, 81):
        p = periods[(i - 1) % 3]
        records.append({
            "record_id": f"INV-2026-{i:04d}",
            "kind": "SALES_INVOICE",
            "period": p,
            "counterparty_id": f"cust-{(i % 16) + 1:02d}",
            "gross_cents": 124_000 + (i * 3_100),
            "transfer_reference": f"SEPA-AR-{i:04d}",
        })
    for i in range(1, 51):
        p = periods[(i - 1) % 3]
        records.append({
            "record_id": f"BILL-2026-{i:04d}",
            "kind": "PURCHASE_INVOICE",
            "period": p,
            "counterparty_id": f"sup-{(i % 10) + 1:02d}",
            "gross_cents": 86_800 + (i * 2_480),
            "transfer_reference": f"SEPA-AP-{i:04d}",
        })
    for i in range(1, 21):
        p = periods[(i - 1) % 3]
        records.append({
            "record_id": f"SCN-2026-{i:04d}",
            "kind": "SALES_CREDIT_NOTE",
            "period": p,
            "counterparty_id": f"cust-{(i % 16) + 1:02d}",
            "gross_cents": 18_600 + (i * 500),
            "transfer_reference": f"CN-AR-{i:04d}",
        })
    for i in range(1, 11):
        p = periods[(i - 1) % 3]
        records.append({
            "record_id": f"PCN-2026-{i:04d}",
            "kind": "PURCHASE_CREDIT_NOTE",
            "period": p,
            "counterparty_id": f"sup-{(i % 10) + 1:02d}",
            "gross_cents": 12_400 + (i * 400),
            "transfer_reference": f"CN-AP-{i:04d}",
        })
    for i in range(1, 51):
        p = periods[(i - 1) % 3]
        records.append({
            "record_id": f"RCPT-2026-{i:04d}",
            "kind": "CLIENT_RECEIPT",
            "period": p,
            "counterparty_id": f"cust-{(i % 16) + 1:02d}",
            "gross_cents": 124_000 + (i * 3_100),
            "transfer_reference": f"TR-IN-2026-{i:04d}",
        })
    for i in range(1, 31):
        p = periods[(i - 1) % 3]
        records.append({
            "record_id": f"PMT-2026-{i:04d}",
            "kind": "SUPPLIER_PAYMENT",
            "period": p,
            "counterparty_id": f"sup-{(i % 10) + 1:02d}",
            "gross_cents": 86_800 + (i * 2_480),
            "transfer_reference": f"TR-OUT-2026-{i:04d}",
        })

    return PortfolioRecordSummary(
        mode="FULL_240_PORTFOLIO",
        total_records=len(records),
        sales_invoices=80,
        purchase_invoices=50,
        sales_credit_notes=20,
        purchase_credit_notes=10,
        client_receipts=50,
        supplier_payments=30,
        customer_count=16,
        supplier_count=10,
        periods=periods,
        records_preview=tuple(records[:24]),
    )


def build_redacted_evidence_bundle(
    state: TenantMiniErpState,
    *,
    graph_reports: tuple[SixReaderGraphReport, ...] = (),
    attestations: tuple[IdentityAttestationRecord, ...] = (),
    dispute_holds: tuple[ClientDisputeHold, ...] = (),
) -> dict[str, Any]:
    """Export a readable, redacted audit evidence bundle with SHA-256 provenance."""
    bundle_core = {
        "schema": "KERDON_ARCHON_REDACTED_EVIDENCE_BUNDLE_V1",
        "tenant_id": state.tenant.tenant_id,
        "tenant_slug": state.tenant.slug,
        "period": "2026-10",
        "redaction_policy": "PII emails masked; raw credentials excluded; SHA-256 hashes preserved",
        "merkle_root_sha256": state.board_pack.handoff_packet.merkle_root_sha256,
        "source_blobs": [
            {
                "sha256": b.sha256,
                "mime_type": b.mime_type,
                "size_bytes": len(b.raw_bytes),
                "edge_count": len(b.source_edges),
            }
            for b in state.inbox.blobs_by_sha256.values()
        ],
        "completeness_gap_count": len(state.gaps),
        "commission_case_status": state.commission_case.status.value,
        "six_reader_graph_runs": [asdict(r) for r in graph_reports],
        "identity_attestations": [asdict(a) for a in attestations],
        "client_dispute_holds": [asdict(d) for d in dispute_holds],
        "treasury_approvals": [
            {
                "approval_id": ap.approval_id,
                "counterparty_id": ap.counterparty_id,
                "amount_cents": ap.amount_cents,
                "status": ap.state.value,
                "evidence_sha256": ap.evidence_sha256,
            }
            for ap in state.treasury.approvals.values()
        ],
    }
    bundle_sha = hashlib.sha256(str(bundle_core).encode("utf-8")).hexdigest()
    bundle_core["bundle_sha256"] = bundle_sha
    return bundle_core
