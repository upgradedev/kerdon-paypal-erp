"""M2: Omnichannel Evidence Inbox and Recursive Email/Attachment Graph."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib


class EvidenceSourceKind(str, Enum):
    """Physical representation of an ingested evidence artifact."""

    PDF_ATTACHMENT = "PDF_ATTACHMENT"
    XML_EINVOICE = "XML_EINVOICE"
    CSV_STATEMENT = "CSV_STATEMENT"
    HTML_BODY_TABLE = "HTML_BODY_TABLE"
    WEBHOOK_PAYLOAD = "WEBHOOK_PAYLOAD"


class CandidateDocKind(str, Enum):
    """Semantic financial document kind extracted from evidence."""

    SALES_INVOICE = "SALES_INVOICE"
    PURCHASE_INVOICE = "PURCHASE_INVOICE"
    CREDIT_NOTE = "CREDIT_NOTE"
    COMMISSION_SETTLEMENT = "COMMISSION_SETTLEMENT"
    PAYROLL_REGISTER = "PAYROLL_REGISTER"
    APD_FILING = "APD_FILING"
    FMY_FILING = "FMY_FILING"
    BANK_STATEMENT_LINE = "BANK_STATEMENT_LINE"
    SALES_TABLE_EVIDENCE = "SALES_TABLE_EVIDENCE"


class HtmlBodyPostingError(ValueError):
    """Raised when an HTML email body table is submitted for direct invoice posting."""


@dataclass(frozen=True)
class FieldProvenance:
    """Exact coordinates tracing a domain value back to immutable source bytes."""

    message_id: str
    attachment_id: str
    source_sha256: str
    page: int = 1
    cell: str = ""
    raw_snippet: str = ""


@dataclass(frozen=True)
class SourceEdge:
    """Records one arrival path of content-addressed bytes across messages."""

    message_id: str
    parent_message_id: str | None
    attachment_id: str
    filename: str
    received_at_epoch: int


@dataclass(frozen=True)
class AttachmentPayload:
    """An attachment or nested message inside an inbound email tree."""

    attachment_id: str
    filename: str
    mime_type: str
    raw_bytes: bytes
    nested_message: RawEmailEnvelope | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw_bytes).hexdigest()


@dataclass(frozen=True)
class RawEmailEnvelope:
    """Recursive inbound .eml/.msg message structure with optional nested messages."""

    message_id: str
    tenant_id: str
    sender: str
    recipient: str
    subject: str
    received_at_epoch: int
    html_body_tables: tuple[str, ...] = ()
    attachments: tuple[AttachmentPayload, ...] = ()
    parent_message_id: str | None = None


@dataclass(frozen=True)
class ExtractedCandidate:
    """Typed candidate document produced from an evidence artifact."""

    candidate_id: str
    tenant_id: str
    doc_kind: CandidateDocKind
    source_kind: EvidenceSourceKind
    counterparty_name: str
    counterparty_tax_id: str
    net_cents: int
    vat_cents: int
    gross_cents: int
    currency: str
    issued_date: str
    due_date: str
    provenance: FieldProvenance
    einvoice_mark: str = ""
    referenced_invoice_id: str = ""
    store_id: str = ""


@dataclass
class DeduplicatedBlob:
    """Content-addressed byte blob retaining every distinct arrival edge."""

    sha256: str
    raw_bytes: bytes
    mime_type: str
    source_edges: list[SourceEdge] = field(default_factory=list)


@dataclass
class EvidenceInbox:
    """Tenant-scoped omnichannel evidence store with recursive email unpacking."""

    tenant_id: str
    blobs_by_sha256: dict[str, DeduplicatedBlob] = field(default_factory=dict)
    messages_by_id: dict[str, RawEmailEnvelope] = field(default_factory=dict)
    candidates_by_id: dict[str, ExtractedCandidate] = field(default_factory=dict)
    sales_table_evidence: list[tuple[str, str, FieldProvenance]] = field(
        default_factory=list
    )

    def ingest_email(self, envelope: RawEmailEnvelope) -> tuple[str, ...]:
        """Recursively unpack an email and its nested .msg/.eml attachments."""
        if envelope.tenant_id != self.tenant_id:
            raise ValueError(
                f"Envelope tenant {envelope.tenant_id} != inbox {self.tenant_id}"
            )
        discovered_Hashes: list[str] = []
        self._unpack_recursive(envelope, parent_id=envelope.parent_message_id, out=discovered_Hashes)
        return tuple(discovered_Hashes)

    def _unpack_recursive(
        self,
        envelope: RawEmailEnvelope,
        *,
        parent_id: str | None,
        out: list[str],
    ) -> None:
        recorded = RawEmailEnvelope(
            message_id=envelope.message_id,
            tenant_id=envelope.tenant_id,
            sender=envelope.sender,
            recipient=envelope.recipient,
            subject=envelope.subject,
            received_at_epoch=envelope.received_at_epoch,
            html_body_tables=envelope.html_body_tables,
            attachments=envelope.attachments,
            parent_message_id=parent_id,
        )
        self.messages_by_id[recorded.message_id] = recorded

        for idx, html_table in enumerate(recorded.html_body_tables):
            table_sha = hashlib.sha256(html_table.encode("utf-8")).hexdigest()
            prov = FieldProvenance(
                message_id=recorded.message_id,
                attachment_id=f"html-table-{idx}",
                source_sha256=table_sha,
                page=1,
                cell=f"table[{idx}]",
                raw_snippet=html_table[:120],
            )
            self.sales_table_evidence.append((recorded.message_id, html_table, prov))

        for att in recorded.attachments:
            if att.nested_message is not None:
                self._unpack_recursive(
                    att.nested_message,
                    parent_id=recorded.message_id,
                    out=out,
                )
                continue
            digest = att.sha256
            edge = SourceEdge(
                message_id=recorded.message_id,
                parent_message_id=parent_id,
                attachment_id=att.attachment_id,
                filename=att.filename,
                received_at_epoch=recorded.received_at_epoch,
            )
            existing = self.blobs_by_sha256.get(digest)
            if existing is None:
                self.blobs_by_sha256[digest] = DeduplicatedBlob(
                    sha256=digest,
                    raw_bytes=att.raw_bytes,
                    mime_type=att.mime_type,
                    source_edges=[edge],
                )
            else:
                if edge not in existing.source_edges:
                    existing.source_edges.append(edge)
            out.append(digest)

    def register_candidate(self, candidate: ExtractedCandidate) -> ExtractedCandidate:
        """Validate and store an extracted document candidate.

        Enforces the structural guard that HTML email body tables can never post
        directly as a sales or purchase invoice.
        """
        if candidate.tenant_id != self.tenant_id:
            raise ValueError("Candidate tenant mismatch")
        guard_invoice_candidate(candidate)
        self.candidates_by_id[candidate.candidate_id] = candidate
        return candidate


def guard_invoice_candidate(candidate: ExtractedCandidate) -> None:
    """Reject any attempt to post an invoice from an HTML email body table."""
    if candidate.source_kind == EvidenceSourceKind.HTML_BODY_TABLE and candidate.doc_kind in (
        CandidateDocKind.SALES_INVOICE,
        CandidateDocKind.PURCHASE_INVOICE,
        CandidateDocKind.CREDIT_NOTE,
    ):
        raise HtmlBodyPostingError(
            f"Candidate {candidate.candidate_id} originates from HTML_BODY_TABLE "
            "and is barred from invoice posting; keep as sales/commission evidence only."
        )
