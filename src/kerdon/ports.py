"""Hexagonal architecture ports (Protocols) for Kerdon Mini-ERP (M1-M8).

Pure domain interfaces with zero cloud or LLM SDK imports (STANDARDS A5).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .completeness import CompletenessGap
from .demo_fixtures import TenantMiniErpState
from .docgen import OutboundDraft, ProactiveDigest
from .query import FactSheet, GroundedQueryAnswer
from .reasoning import GapReasoning


@runtime_checkable
class WorkspaceRepositoryPort(Protocol):
    """Port for multi-tenant Mini-ERP workspace persistence and retrieval."""

    def get_tenant_state(self, tenant_id: str) -> TenantMiniErpState:
        """Return the state object for `tenant_id`."""
        ...

    def save_snapshot(self, tenant_id: str) -> dict[str, Any]:
        """Persist a deterministic snapshot for `tenant_id`."""
        ...


@runtime_checkable
class EvidenceBlobStorePort(Protocol):
    """Port for content-addressed evidence storage (`sha256` -> immutable bytes)."""

    def put_evidence_blob(
        self,
        tenant_id: str,
        sha256_hex: str,
        raw_bytes: bytes,
        mime_type: str = "application/octet-stream",
    ) -> str:
        """Store raw evidence bytes and return an addressable URI."""
        ...


@runtime_checkable
class MultimodalSynthesizerPort(Protocol):
    """Port for multimodal candidate extraction, gap reasoning, and prose narration.

    Implementations may never invent or alter monetary cents; all financial
    numbers are supplied by the deterministic domain engine.
    """

    def run_eight_stage_close(
        self,
        *,
        tenant_id: str,
        period: str,
        gaps: list[CompletenessGap],
        drafts: list[OutboundDraft],
        digest: ProactiveDigest,
        fact_sheet: FactSheet,
        question: str | None = None,
        require_live: bool = False,
    ) -> dict[str, Any]:
        """Execute the 8-stage evaluation and narration workflow."""
        ...

    def diagnose_gaps(
        self,
        gaps: list[CompletenessGap],
        *,
        tenant_id: str = "tenant-athens-hq",
        require_live: bool = False,
    ) -> tuple[list[GapReasoning], str]:
        """Return `(diagnoses, source)` for completeness gaps."""
        ...

    def answer_query(
        self,
        question: str,
        fact_sheet: FactSheet,
        *,
        require_live: bool = False,
    ) -> GroundedQueryAnswer:
        """Answer a natural-language question strictly from `fact_sheet`."""
        ...


@runtime_checkable
class PaymentConnectorPort(Protocol):
    """Pluggable payment & commerce connector port (`NONE`, `PAYPAL`, `STRIPE`, `BANK_IBAN`)."""

    connector_id: str

    def create_order_or_invoice(
        self,
        *,
        tenant_id: str,
        document_id: str,
        amount_cents: int,
        currency: str,
        payer_email: str,
        description: str,
    ) -> dict[str, Any]:
        """Create an external payable order/invoice or local payment instruction."""
        ...

    def capture_order(
        self,
        *,
        tenant_id: str,
        order_id: str,
        document_id: str,
        gross_cents: int,
        currency: str,
    ) -> dict[str, Any]:
        """Capture an order and return gross_cents, fee_cents, net_cents, and provider_tx_id."""
        ...

    def execute_batch_payout(
        self,
        *,
        tenant_id: str,
        sender_batch_id: str,
        items: list[dict[str, Any]],
        currency: str,
    ) -> dict[str, Any]:
        """Execute a governed batch payout for seller commissions or supplier approvals."""
        ...


@runtime_checkable
class TaxAuthorityConnectorPort(Protocol):
    """Pluggable statutory e-invoicing / tax authority port (`NONE`, `AADE_MYDATA`, `PEPPOL_EU`)."""

    connector_id: str

    def transmit_document(
        self,
        *,
        tenant_id: str,
        document_id: str,
        xml_payload: str,
    ) -> dict[str, Any]:
        """Transmit an invoice or credit note and return uid, mark, and verification metadata."""
        ...

    def cancel_document_mark(
        self,
        *,
        tenant_id: str,
        invoice_mark: str,
        reason: str,
    ) -> dict[str, Any]:
        """Cancel a previously issued statutory mark upon document reversal."""
        ...


@runtime_checkable
class UnitOfWorkPort(Protocol):
    """Port for atomic transactional Unit of Work with automatic state rollback and Transactional Outbox."""

    def stage_entity(
        self,
        entity_kind: str,
        entity_id: str,
        payload: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> None:
        """Stage a versioned entity write inside the active transaction."""
        ...

    def stage_outbox(
        self,
        event_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Stage a Transactional Outbox event committed atomically with entity writes."""
        ...

    def commit(self) -> Any:
        """Atomically commit all staged entity writes and outbox events, or roll back on error."""
        ...
