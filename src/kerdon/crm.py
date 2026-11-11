"""M3: Commercial CRM for Customers, Bookings, Suppliers, Credit Notes, and Register."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib

from .tenancy import Direction

SIGNED_LINK_TTL_SECONDS = 300


class BookingStatus(str, Enum):
    """Lifecycle status of a customer booking or commercial order."""

    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Customer:
    """Accounts Receivable (AR) counterparty record."""

    customer_id: str
    tenant_id: str
    legal_name: str
    tax_id: str
    email: str
    payment_terms_days: int = 30
    credit_limit_cents: int = 5_000_000


@dataclass(frozen=True)
class Supplier:
    """Accounts Payable (AP) vendor record with historical median tracking."""

    supplier_id: str
    tenant_id: str
    legal_name: str
    tax_id: str
    iban: str
    category: str
    historical_invoice_cents: tuple[int, ...] = ()
    recurring_monthly: bool = False

    @property
    def median_invoice_cents(self) -> int:
        if not self.historical_invoice_cents:
            return 0
        ordered = sorted(self.historical_invoice_cents)
        mid = len(ordered) // 2
        if len(ordered) % 2 == 1:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) // 2


@dataclass(frozen=True)
class ClientBooking:
    """Customer reservation or order tracking advance deposits and unpaid balance."""

    booking_id: str
    tenant_id: str
    customer_id: str
    store_id: str
    seller_id: str
    total_agreed_cents: int
    advance_deposit_cents: int
    invoiced_cents: int
    delivery_date: str
    status: BookingStatus = BookingStatus.CONFIRMED

    @property
    def remaining_balance_cents(self) -> int:
        return max(0, self.total_agreed_cents - self.advance_deposit_cents)

    @property
    def has_uninvoiced_deposit(self) -> bool:
        return self.advance_deposit_cents > self.invoiced_cents and self.status != BookingStatus.CANCELLED


@dataclass(frozen=True)
class CreditNote:
    """Sales or purchase credit note that reduces open AR/AP and invalidates stale payouts."""

    credit_note_id: str
    tenant_id: str
    direction: Direction
    counterparty_id: str
    net_cents: int
    vat_cents: int
    gross_cents: int
    currency: str
    issued_date: str
    source_sha256: str
    referenced_invoice_id: str = ""


@dataclass(frozen=True)
class SignedDownloadLink:
    """Short-lived content-addressed download link (300s TTL) to original evidence bytes."""

    document_id: str
    source_sha256: str
    issued_at_epoch: int
    expires_at_epoch: int
    url: str

    def is_valid_at(self, now_epoch: int) -> bool:
        return self.issued_at_epoch <= now_epoch < self.expires_at_epoch


@dataclass(frozen=True)
class DocumentRegisterEntry:
    """Authoritative entry in the tenant's Commercial Document Register."""

    document_id: str
    tenant_id: str
    direction: Direction
    counterparty_id: str
    counterparty_name: str
    counterparty_tax_id: str
    doc_type: str
    net_cents: int
    vat_cents: int
    gross_cents: int
    paid_cents: int
    currency: str
    issued_date: str
    due_date: str
    source_sha256: str
    einvoice_mark: str = ""
    store_id: str = ""

    @property
    def outstanding_cents(self) -> int:
        return max(0, self.gross_cents - self.paid_cents)


@dataclass
class CommercialRegistry:
    """Tenant-scoped CRM and Document Register."""

    tenant_id: str
    customers: dict[str, Customer] = field(default_factory=dict)
    suppliers: dict[str, Supplier] = field(default_factory=dict)
    bookings: dict[str, ClientBooking] = field(default_factory=dict)
    credit_notes: dict[str, CreditNote] = field(default_factory=dict)
    documents: dict[str, DocumentRegisterEntry] = field(default_factory=dict)

    def upsert_customer(self, customer: Customer) -> None:
        self._check_tenant(customer.tenant_id)
        self.customers[customer.customer_id] = customer

    def upsert_supplier(self, supplier: Supplier) -> None:
        self._check_tenant(supplier.tenant_id)
        self.suppliers[supplier.supplier_id] = supplier

    def upsert_booking(self, booking: ClientBooking) -> None:
        self._check_tenant(booking.tenant_id)
        self.bookings[booking.booking_id] = booking

    def register_credit_note(self, credit_note: CreditNote) -> None:
        self._check_tenant(credit_note.tenant_id)
        self.credit_notes[credit_note.credit_note_id] = credit_note

    def register_document(self, entry: DocumentRegisterEntry) -> None:
        self._check_tenant(entry.tenant_id)
        self.documents[entry.document_id] = entry

    def mint_signed_download_link(
        self, document_id: str, now_epoch: int, signing_secret: str = "kerdon-msp- local"
    ) -> SignedDownloadLink:
        doc = self.documents.get(document_id)
        if doc is None:
            raise KeyError(f"Unknown document_id: {document_id}")
        expires_at = now_epoch + SIGNED_LINK_TTL_SECONDS
        sig = hashlib.sha256(
            f"{self.tenant_id}:{doc.document_id}:{doc.source_sha256}:{expires_at}:{signing_secret}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        url = (
            f"https://files.kerdon.ai/v1/tenants/{self.tenant_id}/docs/{doc.document_id}"
            f"?sha256={doc.source_sha256[:16]}&expires={expires_at}&sig={sig}"
        )
        return SignedDownloadLink(
            document_id=doc.document_id,
            source_sha256=doc.source_sha256,
            issued_at_epoch=now_epoch,
            expires_at_epoch=expires_at,
            url=url,
        )

    def _check_tenant(self, candidate_tenant_id: str) -> None:
        if candidate_tenant_id != self.tenant_id:
            raise ValueError(
                f"Entity tenant {candidate_tenant_id} != registry {self.tenant_id}"
            )
