"""Pure-Python stdlib PDF 1.4 renderer for Kerdon outbound documents (zero third-party deps)."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .docgen import OutboundDraft, OutboundLineItem, build_line_item, format_eur
from .tenancy import Tenant


def _pdf_escape(text: str) -> str:
    """Fold text to safe ASCII/Latin-1 and escape PDF string literals."""
    folded = (text or "").encode("latin-1", "replace").decode("latin-1")
    return (
        folded.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", " ")
        .replace("\n", " ")
    )


@dataclass(frozen=True)
class RenderedPdfArtifact:
    """Deterministic downloadable PDF artifact with SHA-256 provenance."""

    draft_id: str
    reference_code: str
    filename: str
    content_type: str
    pdf_bytes: bytes
    sha256: str
    size_bytes: int


def next_tenant_document_reference(
    tenant_slug: str, doc_type_prefix: str, period: str, sequence_index: int
) -> str:
    """Compute sequential per-tenant document reference (e.g., INV-AEGEAN-202610-0001)."""
    clean_slug = (tenant_slug or "tenant").split("-")[0].upper()[:8]
    clean_period = (period or "2026-10").replace("-", "")
    seq = max(1, int(sequence_index))
    return f"{doc_type_prefix.upper()}-{clean_slug}-{clean_period}-{seq:04d}"


def render_outbound_draft_pdf(
    draft: OutboundDraft,
    tenant: Tenant,
    *,
    sequence_index: int = 1,
    discount_cents: int = 0,
    line_items: tuple[OutboundLineItem, ...] | None = None,
) -> RenderedPdfArtifact:
    """Render an already-computed OutboundDraft into valid PDF 1.4 bytes without external libs."""
    ref_code = next_tenant_document_reference(
        tenant.slug, draft.doc_type.value[:3], draft.period, sequence_index
    )
    vat_rate = (
        round((draft.vat_cents * 100) / draft.net_cents)
        if draft.net_cents > 0 and draft.vat_cents > 0
        else 0
    )
    items = line_items or (
        build_line_item(draft.subject or draft.doc_type.value, 1, draft.net_cents, vat_rate),
    )

    lines_cmd: list[str] = [
        "BT",
        "/F1 16 Tf",
        "50 790 Td",
        f"({_pdf_escape(tenant.display_name)} - Kerdon Autonomous Mini-ERP) Tj",
        "/F1 12 Tf",
        "0 -22 Td",
        f"(Document Type: {_pdf_escape(draft.doc_type.value)}   |   Reference: {_pdf_escape(ref_code)}) Tj",
        "/F2 10 Tf",
        "0 -18 Td",
        f"(Issuer Legal Name: {_pdf_escape(tenant.fiscal_identity.legal_name)}   |   Tax ID: {_pdf_escape(tenant.fiscal_identity.tax_id)}) Tj",
        "0 -15 Td",
        f"(Counterparty: {_pdf_escape(draft.recipient_name)} ({_pdf_escape(draft.recipient_id)})   |   Period: {_pdf_escape(draft.period)}) Tj",
        "0 -22 Td",
        "(--------------------------------------------------------------------------------------------------------------) Tj",
        "/F1 10 Tf",
        "0 -16 Td",
        "(Description                                      Qty      Unit Price     Discount     VAT %        Gross) Tj",
        "/F2 10 Tf",
        "0 -14 Td",
        "(--------------------------------------------------------------------------------------------------------------) Tj",
    ]

    for item in items:
        desc = _pdf_escape(item.description[:42]).ljust(44)
        qty_str = f"{item.quantity}".rjust(6)
        unit_str = format_eur(item.unit_price_cents).rjust(14)
        disc_str = format_eur(discount_cents).rjust(12)
        vat_str = f"{item.vat_rate_pct}%".rjust(8)
        gross_str = format_eur(item.gross_cents).rjust(13)
        row_txt = f"{desc} {qty_str} {unit_str} {disc_str} {vat_str} {gross_str}"
        lines_cmd.extend(["0 -15 Td", f"({_pdf_escape(row_txt)}) Tj"])

    net_after_disc = max(0, draft.net_cents - max(0, discount_cents))
    gross_after_disc = max(0, draft.gross_cents - max(0, discount_cents))

    lines_cmd.extend(
        [
            "0 -16 Td",
            "(--------------------------------------------------------------------------------------------------------------) Tj",
            "/F1 10 Tf",
            "0 -16 Td",
            f"(Subtotal Net: {_pdf_escape(format_eur(net_after_disc))}   |   Discount: {_pdf_escape(format_eur(discount_cents))}   |   VAT: {_pdf_escape(format_eur(draft.vat_cents))}   |   TOTAL GROSS: {_pdf_escape(format_eur(gross_after_disc))}) Tj",
            "/F2 9 Tf",
            "0 -24 Td",
            f"(Subject: {_pdf_escape(draft.subject)}) Tj",
        ]
    )

    prose = draft.covering_prose or ""
    chunk_size = 92
    for idx in range(0, max(1, len(prose)), chunk_size):
        segment = prose[idx : idx + chunk_size]
        lines_cmd.extend(["0 -13 Td", f"({_pdf_escape(segment)}) Tj"])

    body_fingerprint = hashlib.sha256(
        f"{tenant.tenant_id}|{ref_code}|{gross_after_disc}|{draft.source_gap_id or ''}".encode(
            "utf-8"
        )
    ).hexdigest()
    lines_cmd.extend(
        [
            "0 -24 Td",
            f"(Deterministic Audit Seal SHA-256: {body_fingerprint}) Tj",
            "0 -13 Td",
            "(Status: HUMAN-GATED DRAFT - Generated by Kerdon MSP Hexagonal Engine) Tj",
            "ET",
        ]
    )

    stream_content = "\n".join(lines_cmd).encode("latin-1", "replace")

    objects: list[bytes] = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>\nendobj\n"
        ),
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        (
            f"6 0 obj\n<< /Length {len(stream_content)} >>\nstream\n".encode("ascii")
            + stream_content
            + b"\nendstream\nendobj\n"
        ),
    ]

    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    body_parts: list[bytes] = [header]
    offsets: list[int] = []
    cursor = len(header)
    for obj in objects:
        offsets.append(cursor)
        body_parts.append(obj)
        cursor += len(obj)

    xref_lines = [f"xref\n0 {len(objects) + 1}\n", "0000000000 65535 f \n"]
    for off in offsets:
        xref_lines.append(f"{off:010d} 00000 n \n")
    xref_bytes = "".join(xref_lines).encode("ascii")
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{cursor}\n%%EOF\n".encode(
            "ascii"
        )
    )
    pdf_bytes = b"".join(body_parts) + xref_bytes + trailer
    sha256_hex = hashlib.sha256(pdf_bytes).hexdigest()
    filename = f"{ref_code.lower()}.pdf"
    return RenderedPdfArtifact(
        draft_id=draft.draft_id,
        reference_code=ref_code,
        filename=filename,
        content_type="application/pdf",
        pdf_bytes=pdf_bytes,
        sha256=sha256_hex,
        size_bytes=len(pdf_bytes),
    )
