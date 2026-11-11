"""M1: Multi-tenant MSP/Franchise hierarchy and fiscal identity classification."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib


class Direction(str, Enum):
    """Fiscal direction of a commercial document relative to the tenant."""

    SALES_REVENUE = "SALES_REVENUE"
    PURCHASE_EXPENSE = "PURCHASE_EXPENSE"
    PRINCIPAL_SETTLEMENT = "PRINCIPAL_SETTLEMENT"
    INTERNAL_TRANSFER = "INTERNAL_TRANSFER"
    UNKNOWN = "UNKNOWN"


class TenantTier(str, Enum):
    """Position of a node inside the MSP and franchise hierarchy."""

    MSP_HUB = "MSP_HUB"
    CLIENT_HQ = "CLIENT_HQ"
    FRANCHISE_STORE = "FRANCHISE_STORE"


@dataclass(frozen=True)
class FiscalIdentity:
    """Authoritative fiscal identity of a client tenant for sign classification."""

    tenant_id: str
    legal_name: str
    tax_id: str
    country_code: str = "GR"
    aliases: tuple[str, ...] = ()

    def matches_tax_id(self, candidate_tax_id: str) -> bool:
        norm_self = _normalize_tax_id(self.tax_id)
        norm_cand = _normalize_tax_id(candidate_tax_id)
        return bool(norm_self and norm_self == norm_cand)

    def matches_name(self, candidate_name: str) -> bool:
        target = _normalize_name(candidate_name)
        if not target:
            return False
        names = (self.legal_name, *self.aliases)
        return any(_normalize_name(n) == target for n in names)


@dataclass(frozen=True)
class Tenant:
    """A managed client organization or child franchise store location."""

    tenant_id: str
    slug: str
    display_name: str
    tier: TenantTier
    fiscal_identity: FiscalIdentity
    msp_hub_id: str
    parent_tenant_id: str | None = None
    default_currency: str = "EUR"
    inbox_address: str = ""

    def __post_init__(self) -> None:
        if not self.inbox_address:
            object.__setattr__(
                self, "inbox_address", f"docs@{self.slug}.kerdon.ai"
            )


@dataclass(frozen=True)
class StoreLocation:
    """Physical or logical store location inside a franchise or multi-store SMB."""

    store_id: str
    tenant_id: str
    parent_tenant_id: str
    name: str
    city: str
    monthly_target_cents: int


@dataclass(frozen=True)
class SalesTeam:
    """Sales team attached to a store location."""

    team_id: str
    tenant_id: str
    store_id: str
    name: str
    lead_seller_id: str
    monthly_target_cents: int


@dataclass(frozen=True)
class SellerProfile:
    """Individual salesperson eligible for sales attribution and commission cases."""

    seller_id: str
    tenant_id: str
    store_id: str
    team_id: str
    full_name: str
    employee_code: str
    active: bool = True


@dataclass(frozen=True)
class DirectionClassification:
    """Result of classifying a document's issuer and recipient against tenant identity."""

    direction: Direction
    counterparty_name: str
    counterparty_tax_id: str
    reason: str


def _normalize_tax_id(raw: str) -> str:
    return "".join(ch for ch in raw.upper().strip() if ch.isalnum())


def _normalize_name(raw: str) -> str:
    return " ".join(raw.upper().strip().split())


def classify_fiscal_direction(
    identity: FiscalIdentity,
    *,
    issuer_tax_id: str,
    issuer_name: str,
    recipient_tax_id: str,
    recipient_name: str,
    is_principal_settlement: bool = False,
) -> DirectionClassification:
    """Classify whether a document is a sale, purchase, or principal settlement.

    Uses the tenant's authoritative tax_id and legal_name so the system never
    books a supplier bill as revenue or a customer invoice as an expense.
    """
    if is_principal_settlement:
        return DirectionClassification(
            direction=Direction.PRINCIPAL_SETTLEMENT,
            counterparty_name=issuer_name.strip(),
            counterparty_tax_id=_normalize_tax_id(issuer_tax_id),
            reason="Explicit principal commission settlement statement (non-posting).",
        )

    issuer_is_self = identity.matches_tax_id(issuer_tax_id) or identity.matches_name(
        issuer_name
    )
    recipient_is_self = identity.matches_tax_id(
        recipient_tax_id
    ) or identity.matches_name(recipient_name)

    if issuer_is_self and recipient_is_self:
        return DirectionClassification(
            direction=Direction.INTERNAL_TRANSFER,
            counterparty_name=identity.legal_name,
            counterparty_tax_id=_normalize_tax_id(identity.tax_id),
            reason="Both issuer and recipient match tenant fiscal identity.",
        )
    if issuer_is_self:
        return DirectionClassification(
            direction=Direction.SALES_REVENUE,
            counterparty_name=recipient_name.strip(),
            counterparty_tax_id=_normalize_tax_id(recipient_tax_id),
            reason="Issuer matches tenant fiscal identity; classified as outbound sale.",
        )
    if recipient_is_self:
        return DirectionClassification(
            direction=Direction.PURCHASE_EXPENSE,
            counterparty_name=issuer_name.strip(),
            counterparty_tax_id=_normalize_tax_id(issuer_tax_id),
            reason="Recipient matches tenant fiscal identity; classified as inbound purchase.",
        )
    return DirectionClassification(
        direction=Direction.UNKNOWN,
        counterparty_name=issuer_name.strip() or recipient_name.strip(),
        counterparty_tax_id=_normalize_tax_id(issuer_tax_id or recipient_tax_id),
        reason="Neither issuer nor recipient matched tenant fiscal identity.",
    )


@dataclass
class TenancyCatalog:
    """In-memory multi-tenant hierarchy registry for an MSP hub."""

    msp_hub_id: str
    tenants: dict[str, Tenant] = field(default_factory=dict)
    stores: dict[str, StoreLocation] = field(default_factory=dict)
    teams: dict[str, SalesTeam] = field(default_factory=dict)
    sellers: dict[str, SellerProfile] = field(default_factory=dict)

    def onboard_tenant(
        self,
        *,
        slug: str,
        display_name: str,
        legal_name: str,
        tax_id: str,
        country_code: str = "GR",
        parent_tenant_id: str | None = None,
        default_currency: str = "EUR",
        aliases: tuple[str, ...] = (),
    ) -> Tenant:
        clean_slug = slug.strip().lower().replace(" ", "-")
        if not clean_slug:
            raise ValueError("slug must not be empty")
        digest = hashlib.sha256(
            f"{self.msp_hub_id}:{clean_slug}:{_normalize_tax_id(tax_id)}".encode("utf-8")
        ).hexdigest()[:10]
        tenant_id = f"tnt-{clean_slug}-{digest}"
        tier = (
            TenantTier.FRANCHISE_STORE
            if parent_tenant_id is not None
            else TenantTier.CLIENT_HQ
        )
        identity = FiscalIdentity(
            tenant_id=tenant_id,
            legal_name=legal_name.strip(),
            tax_id=_normalize_tax_id(tax_id),
            country_code=country_code.upper().strip(),
            aliases=aliases,
        )
        tenant = Tenant(
            tenant_id=tenant_id,
            slug=clean_slug,
            display_name=display_name.strip(),
            tier=tier,
            fiscal_identity=identity,
            msp_hub_id=self.msp_hub_id,
            parent_tenant_id=parent_tenant_id,
            default_currency=default_currency.upper().strip(),
        )
        self.tenants[tenant_id] = tenant
        return tenant

    def register_store(self, store: StoreLocation) -> None:
        if store.tenant_id not in self.tenants:
            raise KeyError(f"Unknown tenant_id: {store.tenant_id}")
        self.stores[store.store_id] = store

    def register_team(self, team: SalesTeam) -> None:
        if team.store_id not in self.stores:
            raise KeyError(f"Unknown store_id: {team.store_id}")
        self.teams[team.team_id] = team

    def register_seller(self, seller: SellerProfile) -> None:
        if seller.team_id not in self.teams:
            raise KeyError(f"Unknown team_id: {seller.team_id}")
        self.sellers[seller.seller_id] = seller

    def child_stores_for(self, tenant_id: str) -> tuple[StoreLocation, ...]:
        return tuple(
            s
            for s in sorted(self.stores.values(), key=lambda item: item.store_id)
            if s.tenant_id == tenant_id or s.parent_tenant_id == tenant_id
        )
