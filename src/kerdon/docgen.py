"""M7: Autonomous Outbound Document Engine, Digest, Board Pack, and Aletheia Receipts."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
import hashlib

from .commissions import MonthlyCommissionCase
from .completeness import CompletenessGap
from .fiscal import VatPeriodSummary
from .ledger import MomTrend, PeriodSummary
from .reasoning import GapReasoning


class OutboundDocType(str, Enum):
    """Human-gated outbound commercial and governance documents."""

    INVOICE = "INVOICE"
    QUOTE = "QUOTE"
    PAYMENT_REMINDER = "PAYMENT_REMINDER"
    DOCUMENT_REQUEST = "DOCUMENT_REQUEST"
    PROACTIVE_DIGEST = "PROACTIVE_DIGEST"
    BOARD_PACK = "BOARD_PACK"


@dataclass(frozen=True)
class OutboundLineItem:
    """Deterministic line item inside an outbound invoice or quote."""

    description: str
    quantity: int
    unit_price_cents: int
    vat_rate_pct: int
    net_cents: int
    vat_cents: int
    gross_cents: int


@dataclass(frozen=True)
class OutboundDraft:
    """Human-gated outbound document draft whose monetary totals are 100% deterministic."""

    draft_id: str
    tenant_id: str
    period: str
    doc_type: OutboundDocType
    recipient_name: str
    recipient_id: str
    net_cents: int
    vat_cents: int
    gross_cents: int
    currency: str
    subject: str
    covering_prose: str
    source_gap_id: str
    content_sha256: str
    requires_human_approval: bool = True


@dataclass(frozen=True)
class DigestItem:
    """Single prioritized finding inside a Proactive Month-End Digest."""

    gap_id: str
    rule_id: str
    severity: str
    counterparty_name: str
    amount_cents: int
    confidence_bps: int
    priority_score: int
    likely_cause: str
    suggested_action: str
    recommended_doc_type: str


@dataclass(frozen=True)
class ProactiveDigest:
    """Ranked digest of open completeness and anomaly findings (`confidence_bps * |amount|`)."""

    digest_id: str
    tenant_id: str
    period: str
    items: tuple[DigestItem, ...]
    total_at_risk_cents: int
    digest_sha256: str


@dataclass(frozen=True)
class AccountantHandoffPacket:
    """Tamper-evident month-end accountant handoff bundle with Merkle root."""

    packet_id: str
    tenant_id: str
    period: str
    event_count: int
    document_count: int
    open_gap_count: int
    net_vat_payable_cents: int
    total_commission_payable_cents: int
    merkle_root_sha256: str


@dataclass(frozen=True)
class BoardPack:
    """Executive CFO Board Pack combining P&L, MoM Trends, VAT, Commissions, and Handoff."""

    pack_id: str
    tenant_id: str
    period: str
    pnl: PeriodSummary
    mom_trend: MomTrend
    vat_summary: VatPeriodSummary
    commission_total_cents: int
    digest: ProactiveDigest
    handoff_packet: AccountantHandoffPacket
    executive_narrative: str


@dataclass(frozen=True)
class AletheiaMerkleReceipt:
    """Spoken and ASCII Braille Merkle-sealed approval receipt (`Volcan`/`Aletheia`)."""

    receipt_id: str
    tenant_id: str
    subject_id: str
    approver_id: str
    amount_cents: int
    currency: str
    merkle_root_sha256: str
    spoken_transcript: str
    braille_ascii: str
    braille_grade1_ascii: str = ""


_BRAILLE_MAP: dict[str, str] = {
    "0": "⠴",
    "1": "⠂",
    "2": "⠆",
    "3": "⠒",
    "4": "⠲",
    "5": "⠢",
    "6": "⠖",
    "7": "⠶",
    "8": "⠦",
    "9": "⠔",
    "a": "⠁",
    "b": "⠃",
    "c": "⠉",
    "d": "⠙",
    "e": "⠑",
    "f": "⠋",
    "g": "⠛",
    "h": "⠓",
    "i": "⠊",
    "j": "⠚",
    "k": "⠅",
    "l": "⠇",
    "m": "⠍",
    "n": "⠝",
    "o": "⠕",
    "p": "⠏",
    "q": "⠟",
    "r": "⠗",
    "s": "⠎",
    "t": "⠞",
    "u": "⠥",
    "v": "⠧",
    "w": "⠺",
    "x": "⠭",
    "y": "⠽",
    "z": "⠵",
    ".": "⠲",
    "-": "⠤",
    "_": "⠤",
    ":": "⠒",
    " ": "⠀",
}


def format_eur(cents: int) -> str:
    """Format integer cents into deterministic EUR string (`123456 -> 'EUR 1,234.56'`)."""
    sign = "-" if cents < 0 else ""
    abs_val = abs(cents)
    whole = abs_val // 100
    frac = abs_val % 100
    return f"{sign}EUR {whole:,}.{frac:02d}"


def build_line_item(
    description: str, quantity: int, unit_price_cents: int, vat_rate_pct: int = 24
) -> OutboundLineItem:
    """Compute a line item's net, VAT, and gross cents deterministically."""
    if quantity <= 0 or unit_price_cents < 0:
        raise ValueError("quantity must be > 0 and unit_price_cents >= 0")
    net = quantity * unit_price_cents
    vat = int(
        (Decimal(net) * Decimal(vat_rate_pct) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return OutboundLineItem(
        description=description,
        quantity=quantity,
        unit_price_cents=unit_price_cents,
        vat_rate_pct=vat_rate_pct,
        net_cents=net,
        vat_cents=vat,
        gross_cents=net + vat,
    )


def draft_corrective_document(
    gap: CompletenessGap,
    reasoning: GapReasoning,
    *,
    vat_rate_pct: int = 24,
    custom_prose: str = "",
) -> OutboundDraft:
    """Auto-draft a human-gated outbound corrective document from a gap and reasoning."""
    try:
        doc_type = OutboundDocType(reasoning.recommended_doc_type)
    except ValueError:
        doc_type = OutboundDocType.DOCUMENT_REQUEST

    if doc_type in (OutboundDocType.INVOICE, OutboundDocType.QUOTE):
        gross = gap.amount_cents
        net = int(
            (Decimal(gross) * Decimal(100) / Decimal(100 + vat_rate_pct)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        vat = gross - net
    else:
        net = gap.amount_cents
        vat = 0
        gross = gap.amount_cents

    subject = (
        f"[{doc_type.value}] {gap.counterparty_name} - {format_eur(gross)} "
        f"({gap.period}, ref {gap.subject_id})"
    )
    prose = custom_prose.strip() or (
        f"Automated draft for {gap.counterparty_name} ({gap.period}): "
        f"{gap.summary} Root cause: {reasoning.likely_cause} "
        f"Requested action: {reasoning.suggested_action} "
        f"Deterministic amount: {format_eur(gross)}."
    )
    digest = hashlib.sha256(
        f"{gap.tenant_id}:{gap.gap_id}:{doc_type.value}:{net}:{vat}:{gross}".encode(
            "utf-8"
        )
    ).hexdigest()

    return OutboundDraft(
        draft_id=f"drf-{gap.gap_id}",
        tenant_id=gap.tenant_id,
        period=gap.period,
        doc_type=doc_type,
        recipient_name=gap.counterparty_name,
        recipient_id=gap.counterparty_id,
        net_cents=net,
        vat_cents=vat,
        gross_cents=gross,
        currency=gap.currency,
        subject=subject,
        covering_prose=prose,
        source_gap_id=gap.gap_id,
        content_sha256=digest,
        requires_human_approval=True,
    )


def build_proactive_digest(
    tenant_id: str,
    period: str,
    gaps: tuple[CompletenessGap, ...],
    reasonings: tuple[GapReasoning, ...],
) -> ProactiveDigest:
    """Rank completeness gaps by `confidence_bps * abs(amount_cents)` descending."""
    reason_by_id = {r.gap_id: r for r in reasonings}
    items: list[DigestItem] = []
    for gap in gaps:
        r = reason_by_id.get(gap.gap_id)
        conf = r.confidence_bps if r is not None else 8500
        score = conf * abs(gap.amount_cents)
        items.append(
            DigestItem(
                gap_id=gap.gap_id,
                rule_id=gap.rule_id.value,
                severity=gap.severity.value,
                counterparty_name=gap.counterparty_name,
                amount_cents=gap.amount_cents,
                confidence_bps=conf,
                priority_score=score,
                likely_cause=r.likely_cause if r is not None else gap.summary,
                suggested_action=r.suggested_action if r is not None else "Review item",
                recommended_doc_type=(
                    r.recommended_doc_type if r is not None else "DOCUMENT_REQUEST"
                ),
            )
        )
    ranked = tuple(
        sorted(items, key=lambda it: (-it.priority_score, it.gap_id))
    )
    total_risk = sum(abs(it.amount_cents) for it in ranked)
    payload = "|".join(f"{it.gap_id}:{it.priority_score}" for it in ranked)
    digest_sha = hashlib.sha256(
        f"{tenant_id}:{period}:{total_risk}:{payload}".encode("utf-8")
    ).hexdigest()
    return ProactiveDigest(
        digest_id=f"dig-{tenant_id}-{period}",
        tenant_id=tenant_id,
        period=period,
        items=ranked,
        total_at_risk_cents=total_risk,
        digest_sha256=digest_sha,
    )


def _merkle_root(leaves: list[str]) -> str:
    if not leaves:
        return hashlib.sha256(b"empty").hexdigest()
    layer = [hashlib.sha256(leaf.encode("utf-8")).hexdigest() for leaf in sorted(leaves)]
    while len(layer) > 1:
        next_layer: list[str] = []
        for idx in range(0, len(layer), 2):
            left = layer[idx]
            right = layer[idx + 1] if idx + 1 < len(layer) else left
            combined = hashlib.sha256(f"{left}:{right}".encode("utf-8")).hexdigest()
            next_layer.append(combined)
        layer = next_layer
    return layer[0]


def build_cfo_board_pack(
    *,
    tenant_id: str,
    period: str,
    pnl: PeriodSummary,
    mom_trend: MomTrend,
    vat_summary: VatPeriodSummary,
    commission_case: MonthlyCommissionCase | None,
    digest: ProactiveDigest,
    document_sha256s: tuple[str, ...],
    narrative_override: str = "",
) -> BoardPack:
    """Assemble the deterministic Month-End CFO Board Pack and Accountant Handoff Packet."""
    comm_cents = (
        commission_case.total_payable_cents if commission_case is not None else 0
    )
    leaves = [
        f"pnl:{pnl.revenue_cents}:{pnl.ebitda_cents}:{pnl.net_income_cents}",
        f"vat:{vat_summary.net_vat_payable_cents}",
        f"comm:{comm_cents}",
        f"digest:{digest.digest_sha256}",
        *document_sha256s,
    ]
    merkle = _merkle_root(leaves)
    handoff = AccountantHandoffPacket(
        packet_id=f"hnd-{tenant_id}-{period}",
        tenant_id=tenant_id,
        period=period,
        event_count=pnl.event_count,
        document_count=len(document_sha256s),
        open_gap_count=len(digest.items),
        net_vat_payable_cents=vat_summary.net_vat_payable_cents,
        total_commission_payable_cents=comm_cents,
        merkle_root_sha256=merkle,
    )
    narrative = narrative_override.strip() or (
        f"Period {period} closed with revenue {format_eur(pnl.revenue_cents)}, "
        f"EBITDA {format_eur(pnl.ebitda_cents)} (MoM delta {mom_trend.ebitda_delta_bps} bps), "
        f"workforce cost {format_eur(pnl.workforce_cost_cents)}, "
        f"approved seller commissions {format_eur(comm_cents)}, "
        f"and {len(digest.items)} prioritized completeness items totaling "
        f"{format_eur(digest.total_at_risk_cents)}."
    )
    return BoardPack(
        pack_id=f"pack-{tenant_id}-{period}",
        tenant_id=tenant_id,
        period=period,
        pnl=pnl,
        mom_trend=mom_trend,
        vat_summary=vat_summary,
        commission_total_cents=comm_cents,
        digest=digest,
        handoff_packet=handoff,
        executive_narrative=narrative,
    )


def seal_aletheia_receipt(
    *,
    tenant_id: str,
    subject_id: str,
    approver_id: str,
    amount_cents: int,
    currency: str,
    evidence_hashes: tuple[str, ...],
) -> AletheiaMerkleReceipt:
    """Create a Spoken and ASCII Braille Merkle-sealed approval receipt (`Volcan`/`Aletheia`)."""
    leaves = [
        f"{tenant_id}:{subject_id}:{approver_id}:{amount_cents}:{currency}",
        *evidence_hashes,
    ]
    root = _merkle_root(leaves)
    short_hash = root[:8]
    whole = abs(amount_cents) // 100
    frac = abs(amount_cents) % 100
    spoken = (
        f"Aletheia Merkle receipt sealed for {subject_id}. "
        f"Approved by {approver_id} for {currency} {whole}.{frac:02d}. "
        f"Verification prefix {' '.join(short_hash.upper())}."
    )
    braille_token = f"{short_hash}:{currency.upper()}:{whole}.{frac:02d}:{approver_id}"
    braille = "".join(_BRAILLE_MAP.get(ch.lower(), "⠿") for ch in braille_token)
    return AletheiaMerkleReceipt(
        receipt_id=f"rcpt-{subject_id}-{short_hash}",
        tenant_id=tenant_id,
        subject_id=subject_id,
        approver_id=approver_id,
        amount_cents=amount_cents,
        currency=currency,
        merkle_root_sha256=root,
        spoken_transcript=spoken,
        braille_ascii=braille,
        braille_grade1_ascii=braille_token.upper(),
    )
