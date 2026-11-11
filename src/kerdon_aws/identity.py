"""Production JWT Identity Authorizer and Server-Managed Subject Membership Registry.

Enforces fail-closed identity verification outside explicit demo mode:
- Extracts verified claims from AWS API Gateway HTTP API v2 JWT Authorizer
  (`event.requestContext.authorizer.jwt.claims`) or HMAC-SHA256 signed Bearer
  tokens (`Authorization: Bearer <token>`).
- Maps authenticated `sub` to server-managed `(role, allowed_tenant_ids, seller_id)`
  bindings stored in `SubjectMembershipRegistry` (never trusting client role headers
  or unverified client claims).
"""
from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, field
import hashlib
import hmac
import json
import os
import time
from typing import Any

import kerdon as kd

from .http_utils import ValidationError


class AuthenticationError(PermissionError):
    """Raised (HTTP 401) when a request lacks verified credentials outside demo mode."""


@dataclass(frozen=True)
class OrganizationMember:
    """Collaborator membership record scoped to a single organization (`tenant_id`)."""

    tenant_id: str
    sub: str
    actor_id: str
    email: str
    display_name: str
    role: str
    seller_id: str | None = None
    invited_by: str = "system"
    status: str = "ACTIVE"


@dataclass(frozen=True)
class OrganizationInvitation:
    """Scoped invitation granting a specific role in a specific organization (`tenant_id`)."""

    invite_id: str
    invite_token: str
    tenant_id: str
    email: str
    target_sub: str
    display_name: str
    role: str
    seller_id: str | None
    invited_by: str
    status: str = "PENDING"


@dataclass(frozen=True)
class SubjectMembership:
    """Server-managed binding from an identity provider subject (`sub`) to per-org RBAC scope."""

    sub: str
    actor_id: str
    display_name: str
    role: kd.Role
    allowed_tenant_ids: frozenset[str]
    seller_id: str | None = None
    email: str = ""
    org_roles: dict[str, kd.Role] = field(default_factory=dict)
    org_seller_ids: dict[str, str] = field(default_factory=dict)
    default_tenant_id: str = ""

    def role_for_tenant(self, tenant_id: str | None) -> kd.Role:
        if tenant_id and tenant_id in self.org_roles:
            return self.org_roles[tenant_id]
        return self.role

    def seller_for_tenant(self, tenant_id: str | None) -> str | None:
        if tenant_id and tenant_id in self.org_seller_ids:
            return self.org_seller_ids[tenant_id]
        return self.seller_id

    def to_actor(self, active_tenant_id: str | None = None) -> kd.Actor:
        return kd.Actor(
            actor_id=self.actor_id,
            display_name=self.display_name,
            role=self.role_for_tenant(active_tenant_id),
            allowed_tenant_ids=self.allowed_tenant_ids,
            seller_id=self.seller_for_tenant(active_tenant_id),
        )


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * ((4 - len(segment) % 4) % 4)
    return base64.urlsafe_b64decode((segment + padding).encode("ascii"))


def mint_hs256_jwt(
    claims: dict[str, Any],
    *,
    secret: str | None = None,
    ttl_seconds: int = 3600,
    now_epoch: int | None = None,
) -> str:
    """Mint a signed HS256 JWT for staging/integration verification."""
    signing_key = (
        secret
        or os.environ.get("KERDON_JWT_SECRET")
        or "kerdon-staging-jwt-hmac-key-v1"
    ).encode("utf-8")
    issued = int(now_epoch if now_epoch is not None else time.time())
    payload = {
        "iat": issued,
        "exp": issued + ttl_seconds,
        "iss": os.environ.get("KERDON_JWT_ISSUER", "https://auth.kerdon.ai"),
        **claims,
    }
    header_b64 = _b64url_encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8")
    )
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(signing_key, signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(sig)}"


def verify_hs256_jwt(
    token: str,
    *,
    secret: str | None = None,
    now_epoch: int | None = None,
) -> dict[str, Any]:
    """Verify an HS256 Bearer JWT and return its validated claims dictionary."""
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise AuthenticationError("Malformed JWT bearer token")
    header_b64, payload_b64, sig_b64 = parts
    try:
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        provided_sig = _b64url_decode(sig_b64)
    except Exception as exc:
        raise AuthenticationError("Invalid JWT base64 or JSON encoding") from exc

    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise AuthenticationError("Unsupported JWT signing algorithm")
    if not isinstance(payload, dict):
        raise AuthenticationError("Invalid JWT claims payload")

    signing_key = (
        secret
        or os.environ.get("KERDON_JWT_SECRET")
        or "kerdon-staging-jwt-hmac-key-v1"
    ).encode("utf-8")
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(signing_key, signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise AuthenticationError("JWT signature verification failed")

    now_ts = int(now_epoch if now_epoch is not None else time.time())
    exp = payload.get("exp")
    if exp is not None:
        if not isinstance(exp, (int, float)) or int(exp) <= now_ts:
            raise AuthenticationError("JWT token has expired")
    return payload


def _catalog_tenant_id(slug: str, tax_id: str) -> str:
    digest = hashlib.sha256(
        f"msp-hellas-finops-01:{slug}:{tax_id}".encode("utf-8")
    ).hexdigest()[:10]
    return f"tnt-{slug}-{digest}"


def default_subject_memberships() -> dict[str, SubjectMembership]:
    """Server-side authoritative subject-to-tenant/role/seller directory."""
    aegean_tids = frozenset(
        {"tnt-aegean-mobility", _catalog_tenant_id("aegean-mobility", "EL998877665")}
    )
    attica_tids = frozenset(
        {"tnt-attica-grid-solar", _catalog_tenant_id("attica-grid-solar", "EL997766554")}
    )
    items = (
        SubjectMembership(
            sub="usr-sofia-marinou",
            actor_id="act-sofia-marinou",
            display_name="Sofia Marinou (MSP FinOps Director)",
            role=kd.Role.MSP_FINOPS_DIRECTOR,
            allowed_tenant_ids=frozenset({"*"}),
            email="sofia.marinou@kerdon.ai",
        ),
        SubjectMembership(
            sub="usr-nikos-controller",
            actor_id="act-nikos-controller",
            display_name="Nikos Papadakis (MSP Senior Controller)",
            role=kd.Role.MSP_FINOPS_DIRECTOR,
            allowed_tenant_ids=frozenset({"*"}),
            email="nikos.controller@kerdon.ai",
        ),
        SubjectMembership(
            sub="usr-nikos-alexiou",
            actor_id="act-nikos-alexiou",
            display_name="Nikos Alexiou (MSP Treasury Controller)",
            role=kd.Role.MSP_FINOPS_DIRECTOR,
            allowed_tenant_ids=frozenset({"*"}),
            email="nikos.alexiou@kerdon.ai",
        ),
        SubjectMembership(
            sub="usr-aegean-owner",
            actor_id="act-aegean-owner",
            display_name="Nikos Vrettos (Aegean Mobility Owner)",
            role=kd.Role.CLIENT_OWNER,
            allowed_tenant_ids=aegean_tids,
            email="owner@aegean-mobility.gr",
        ),
        SubjectMembership(
            sub="usr-aegean-accountant",
            actor_id="act-aegean-accountant",
            display_name="Elena Kostopoulou (Aegean Accountant)",
            role=kd.Role.ACCOUNTANT,
            allowed_tenant_ids=aegean_tids,
            email="accountant@aegean-mobility.gr",
        ),
        SubjectMembership(
            sub="usr-aegean-manager",
            actor_id="act-aegean-manager",
            display_name="Dimitris Petrou (Aegean Store Manager)",
            role=kd.Role.STORE_MANAGER,
            allowed_tenant_ids=aegean_tids,
            email="manager@aegean-mobility.gr",
        ),
        SubjectMembership(
            sub="usr-seller-01",
            actor_id="act-seller-01",
            display_name="Kostas Nikolaou (Aegean Seller 01)",
            role=kd.Role.SELLER,
            allowed_tenant_ids=aegean_tids,
            seller_id="slr-aegean-mobility-01",
            email="kostas.nikolaou@aegean-mobility.gr",
        ),
        SubjectMembership(
            sub="usr-hellenic-owner",
            actor_id="act-hellenic-owner",
            display_name="Maria Georgiou (Attica Solar Owner)",
            role=kd.Role.CLIENT_OWNER,
            allowed_tenant_ids=attica_tids,
            email="owner@attica-solar.gr",
        ),
    )
    return {m.sub: m for m in items}


@dataclass
class SubjectMembershipRegistry:
    """Server-side identity directory mapping verified JWT `sub` claims to per-org `Actor`."""

    memberships: dict[str, SubjectMembership] = field(
        default_factory=default_subject_memberships
    )
    org_members: dict[str, dict[str, OrganizationMember]] = field(default_factory=dict)
    org_invites: dict[str, dict[str, OrganizationInvitation]] = field(default_factory=dict)

    def register(self, membership: SubjectMembership) -> SubjectMembership:
        self.memberships[membership.sub] = membership
        for tid in membership.allowed_tenant_ids:
            if tid == "*":
                continue
            r = membership.role_for_tenant(tid)
            s = membership.seller_for_tenant(tid)
            self.org_members.setdefault(tid, {})[membership.sub] = OrganizationMember(
                tenant_id=tid,
                sub=membership.sub,
                actor_id=membership.actor_id,
                email=membership.email or f"{membership.sub}@kerdon-synth.eu",
                display_name=membership.display_name,
                role=r.value,
                seller_id=s,
            )
        return membership

    def lookup(self, sub: str) -> SubjectMembership:
        clean_sub = str(sub or "").strip()
        if not clean_sub or clean_sub not in self.memberships:
            raise kd.PermissionDeniedError(
                f"Authenticated subject '{clean_sub}' has no server-managed tenant membership"
            )
        return self.memberships[clean_sub]

    def find_by_actor_id(self, actor_id: str) -> SubjectMembership | None:
        for m in self.memberships.values():
            if m.actor_id == actor_id or m.sub == actor_id:
                return m
        return None

    def grant_organization_access(
        self,
        sub: str,
        *,
        tenant_id: str,
        role: kd.Role,
        email: str = "",
        display_name: str = "",
        seller_id: str | None = None,
        invited_by: str = "system",
    ) -> SubjectMembership:
        """Bind `sub` to `tenant_id` with a specific per-organization `role`."""
        clean_sub = str(sub or "").strip()
        if not clean_sub or not tenant_id:
            raise ValidationError("sub and tenant_id are required")
        existing = self.memberships.get(clean_sub)
        actor_id = existing.actor_id if existing else (clean_sub if clean_sub.startswith("act-") else f"act-{clean_sub}")
        disp = display_name.strip() or (existing.display_name if existing else clean_sub)
        mail = email.strip() or (existing.email if existing else f"{clean_sub}@kerdon-synth.eu")
        allowed = set(existing.allowed_tenant_ids) if existing else set()
        allowed.add(tenant_id)
        org_roles = dict(existing.org_roles) if existing else {}
        org_roles[tenant_id] = role
        org_sellers = dict(existing.org_seller_ids) if existing else {}
        if seller_id:
            org_sellers[tenant_id] = seller_id
        default_tid = existing.default_tenant_id if (existing and existing.default_tenant_id) else tenant_id
        primary_role = existing.role if existing else role
        updated = SubjectMembership(
            sub=clean_sub,
            actor_id=actor_id,
            display_name=disp,
            role=primary_role,
            allowed_tenant_ids=frozenset(allowed),
            seller_id=seller_id or (existing.seller_id if existing else None),
            email=mail,
            org_roles=org_roles,
            org_seller_ids=org_sellers,
            default_tenant_id=default_tid,
        )
        self.memberships[clean_sub] = updated
        self.org_members.setdefault(tenant_id, {})[clean_sub] = OrganizationMember(
            tenant_id=tenant_id,
            sub=clean_sub,
            actor_id=actor_id,
            email=mail,
            display_name=disp,
            role=role.value,
            seller_id=seller_id,
            invited_by=invited_by,
        )
        return updated

    def revoke_organization_access(self, sub: str, *, tenant_id: str) -> None:
        """Remove `sub`'s access to `tenant_id` without affecting other organizations."""
        clean_sub = str(sub or "").strip()
        existing = self.memberships.get(clean_sub)
        if existing is not None:
            allowed = set(existing.allowed_tenant_ids) - {tenant_id}
            org_roles = {k: v for k, v in existing.org_roles.items() if k != tenant_id}
            org_sellers = {k: v for k, v in existing.org_seller_ids.items() if k != tenant_id}
            default_tid = next(iter(sorted(allowed)), "") if existing.default_tenant_id == tenant_id else existing.default_tenant_id
            self.memberships[clean_sub] = SubjectMembership(
                sub=existing.sub,
                actor_id=existing.actor_id,
                display_name=existing.display_name,
                role=existing.role,
                allowed_tenant_ids=frozenset(allowed),
                seller_id=existing.seller_id,
                email=existing.email,
                org_roles=org_roles,
                org_seller_ids=org_sellers,
                default_tenant_id=default_tid,
            )
        if tenant_id in self.org_members:
            self.org_members[tenant_id].pop(clean_sub, None)

    def create_organization_invite(
        self,
        *,
        tenant_id: str,
        email: str,
        role: kd.Role,
        invited_by: str,
        target_sub: str = "",
        display_name: str = "",
        seller_id: str | None = None,
        auto_accept: bool = False,
    ) -> OrganizationInvitation:
        """Create a collaborator invitation scoped strictly to `tenant_id`."""
        clean_mail = str(email or "").strip().lower()
        if not clean_mail or "@" not in clean_mail:
            raise ValidationError("A valid collaborator email is required")
        derived_sub = str(target_sub or f"usr-{clean_mail.split('@')[0]}").strip()
        disp = str(display_name or clean_mail.split("@")[0]).strip()
        seed = f"{tenant_id}:{clean_mail}:{role.value}:{len(self.org_invites.get(tenant_id, {}))}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        inv_id = f"inv-{digest[:10]}"
        token = f"invtok-{digest[:24]}"
        status = "ACCEPTED" if auto_accept else "PENDING"
        inv = OrganizationInvitation(
            invite_id=inv_id,
            invite_token=token,
            tenant_id=tenant_id,
            email=clean_mail,
            target_sub=derived_sub,
            display_name=disp,
            role=role.value,
            seller_id=seller_id,
            invited_by=invited_by,
            status=status,
        )
        self.org_invites.setdefault(tenant_id, {})[inv_id] = inv
        if auto_accept:
            self.grant_organization_access(
                derived_sub,
                tenant_id=tenant_id,
                role=role,
                email=clean_mail,
                display_name=disp,
                seller_id=seller_id,
                invited_by=invited_by,
            )
        return inv

    def accept_organization_invite(
        self,
        invite_token: str,
        *,
        sub: str,
        email: str = "",
        display_name: str = "",
    ) -> tuple[OrganizationInvitation, SubjectMembership]:
        """Accept an invitation token and bind `sub` only to the invited organization."""
        tok = str(invite_token or "").strip()
        for tid, inv_map in self.org_invites.items():
            for inv_id, inv in list(inv_map.items()):
                if inv.invite_token == tok or inv.invite_id == tok:
                    if inv.status == "REVOKED":
                        raise kd.PermissionDeniedError("Invitation has been revoked")
                    target_sub = str(sub or inv.target_sub).strip()
                    role_enum = kd.Role(inv.role)
                    membership = self.grant_organization_access(
                        target_sub,
                        tenant_id=tid,
                        role=role_enum,
                        email=email or inv.email,
                        display_name=display_name or inv.display_name,
                        seller_id=inv.seller_id,
                        invited_by=inv.invited_by,
                    )
                    accepted = OrganizationInvitation(
                        **{**asdict(inv), "target_sub": target_sub, "status": "ACCEPTED"}
                    )
                    inv_map[inv_id] = accepted
                    return accepted, membership
        raise KeyError("Unknown or expired organization invite_token")

    def list_organization_access(self, tenant_id: str) -> dict[str, Any]:
        """Return members and invitations for `tenant_id`."""
        members = dict(self.org_members.get(tenant_id, {}))
        for m in self.memberships.values():
            if tenant_id in m.allowed_tenant_ids and m.sub not in members:
                members[m.sub] = OrganizationMember(
                    tenant_id=tenant_id,
                    sub=m.sub,
                    actor_id=m.actor_id,
                    email=m.email or f"{m.sub}@kerdon-synth.eu",
                    display_name=m.display_name,
                    role=m.role_for_tenant(tenant_id).value,
                    seller_id=m.seller_for_tenant(tenant_id),
                )
        invites = list(self.org_invites.get(tenant_id, {}).values())
        return {
            "tenant_id": tenant_id,
            "members": [asdict(x) for x in members.values()],
            "invites": [asdict(i) for i in invites],
        }


PUBLIC_UNAUTHENTICATED_PATHS = frozenset(
    {"/", "/cockpit", "/workspace", "/health", "/DEPLOYED_SHA", "/erp/connectors/paypal/oauth/callback"}
)
BOOTSTRAP_AUTHENTICATED_PATHS = frozenset(
    {
        "/organizations",
        "/erp/organizations",
        "/organizations/invites/accept",
        "/erp/invites/accept",
    }
)


def is_strict_auth_mode(event: dict[str, Any] | None = None) -> bool:
    """Return True when production/strict fail-closed identity verification is active."""
    env_mode = os.environ.get("KERDON_AUTH_MODE", "demo").strip().lower()
    if env_mode in ("strict", "production", "jwt", "cognito"):
        return True
    if isinstance(event, dict):
        ev_mode = str(event.get("auth_mode") or "").strip().lower()
        if ev_mode in ("strict", "production", "jwt"):
            return True
        headers = {
            str(k).lower(): str(v)
            for k, v in (event.get("headers") or {}).items()
            if v is not None
        }
        if headers.get("x-kerdon-auth-mode", "").strip().lower() in (
            "strict",
            "production",
            "jwt",
        ):
            return True
    return False


def extract_verified_jwt_claims(
    event: dict[str, Any], *, now_epoch: int | None = None
) -> dict[str, Any] | None:
    """Extract verified JWT claims from API Gateway authorizer context or Bearer header."""
    req_ctx = event.get("requestContext")
    if isinstance(req_ctx, dict):
        authorizer = req_ctx.get("authorizer")
        if isinstance(authorizer, dict):
            jwt_ctx = authorizer.get("jwt")
            if isinstance(jwt_ctx, dict) and isinstance(jwt_ctx.get("claims"), dict):
                return dict(jwt_ctx["claims"])

    headers = {
        str(k).lower(): str(v)
        for k, v in (event.get("headers") or {}).items()
        if v is not None
    }
    auth_hdr = headers.get("authorization", "").strip()
    if auth_hdr.lower().startswith("bearer "):
        raw_token = auth_hdr[7:].strip()
        if not raw_token:
            raise AuthenticationError("Empty Bearer token in Authorization header")
        return verify_hs256_jwt(raw_token, now_epoch=now_epoch)
    return None


def resolve_authenticated_actor(
    event: dict[str, Any],
    registry: SubjectMembershipRegistry,
    default_director: kd.Actor,
    *,
    path: str = "",
) -> kd.Actor:
    """Resolve the caller's `kd.Actor` from verified JWT claims or explicit demo headers.

    Outside explicit demo mode (`is_strict_auth_mode(event) == True`):
    - Client role/actor headers (`x-kerdon-role`, `x-kerdon-actor`) are NEVER trusted.
    - Non-public routes fail closed with `AuthenticationError` (HTTP 401) when no
      verified JWT is present, and `PermissionDeniedError` (HTTP 403) when the JWT
      `sub` has no server-side membership in `registry`.
    """
    claims = extract_verified_jwt_claims(event)
    if claims is not None:
        sub = str(
            claims.get("sub")
            or claims.get("username")
            or claims.get("cognito:username")
            or ""
        ).strip()
        if not sub:
            raise AuthenticationError("Verified JWT is missing required 'sub' claim")
        if sub not in registry.memberships and path in BOOTSTRAP_AUTHENTICATED_PATHS:
            return kd.Actor(
                actor_id=sub if sub.startswith("act-") else f"act-{sub}",
                display_name=str(claims.get("name") or claims.get("email") or sub),
                role=kd.Role.CLIENT_OWNER,
                allowed_tenant_ids=frozenset(),
            )
        membership = registry.lookup(sub)
        jwt_tid = str(
            claims.get("tenant_id")
            or claims.get("org_id")
            or claims.get("active_tenant_id")
            or ""
        ).strip() or None
        return membership.to_actor(active_tenant_id=jwt_tid)

    if not event.get("_internal_journal_replay") and is_strict_auth_mode(event):
        if path in PUBLIC_UNAUTHENTICATED_PATHS or path.startswith("/assets/"):
            return kd.Actor(
                actor_id="anonymous-public",
                display_name="Anonymous Public Viewer",
                role=kd.Role.PUBLIC_AUDITOR,
                allowed_tenant_ids=frozenset(),
            )
        raise AuthenticationError(
            "Authentication required: verified JWT authorizer or Bearer token missing (fail-closed outside demo mode)"
        )

    # Explicit demo/test mode fallback: honor test headers only when not in strict mode
    headers = {
        str(k).lower(): str(v)
        for k, v in (event.get("headers") or {}).items()
        if v is not None
    }
    role_hdr = headers.get("x-kerdon-role", "").upper().strip()
    actor_id = headers.get("x-kerdon-actor", default_director.actor_id).strip()
    tenants_hdr = headers.get("x-kerdon-tenants", "").strip()
    seller_hdr = headers.get("x-kerdon-seller-id", "").strip() or None
    allowed_tids = (
        frozenset(t.strip() for t in tenants_hdr.split(",") if t.strip())
        if tenants_hdr
        else frozenset({"*"})
    )
    if role_hdr:
        try:
            role = kd.Role(role_hdr)
        except ValueError as exc:
            raise ValidationError(f"Unknown role header: {role_hdr}") from exc
        if role == kd.Role.SELLER and seller_hdr is None:
            seller_hdr = "slr-aegean-mobility-01"
        return kd.Actor(
            actor_id=actor_id,
            display_name=actor_id,
            role=role,
            allowed_tenant_ids=allowed_tids,
            seller_id=seller_hdr,
        )
    if tenants_hdr:
        return kd.Actor(
            actor_id=actor_id,
            display_name=default_director.display_name,
            role=default_director.role,
            allowed_tenant_ids=allowed_tids,
            seller_id=seller_hdr,
        )
    return default_director


def bind_actor_to_organization(
    actor: kd.Actor,
    tenant_id: str,
    registry: SubjectMembershipRegistry,
) -> kd.Actor:
    """Resolve the caller's per-organization role and seller_id for `tenant_id`."""
    membership = registry.find_by_actor_id(actor.actor_id)
    if membership is None or tenant_id not in membership.org_roles:
        return actor
    return membership.to_actor(active_tenant_id=tenant_id)


def resolve_active_tenant_id(
    event: dict[str, Any],
    actor: kd.Actor,
    store: Any,
) -> str:
    """Resolve the active `tenant_id` from verified JWT claims, validated context header, or default membership."""
    claims = extract_verified_jwt_claims(event) or {}
    headers = {
        str(k).lower(): str(v)
        for k, v in (event.get("headers") or {}).items()
        if v is not None
    }
    requested_tid = (
        str(
            claims.get("tenant_id")
            or claims.get("org_id")
            or claims.get("active_tenant_id")
            or headers.get("x-active-tenant")
            or headers.get("x-organization-id")
            or ""
        ).strip()
    )
    catalog_tenants = store.workspace.catalog.tenants
    if requested_tid:
        # Resolve canonical tenant_id if slug/prefix was passed
        canonical = requested_tid
        if canonical not in catalog_tenants:
            for cid, t in catalog_tenants.items():
                if cid.startswith(requested_tid) or t.slug == requested_tid:
                    canonical = cid
                    break
        if not (actor.can_access_tenant(canonical) or actor.can_access_tenant(requested_tid)):
            raise kd.PermissionDeniedError(
                f"Actor '{actor.actor_id}' is not authorized for organization '{requested_tid}'"
            )
        return canonical

    membership = store.identity_registry.find_by_actor_id(actor.actor_id)
    if membership and membership.default_tenant_id:
        dtid = membership.default_tenant_id
        if dtid in catalog_tenants and actor.can_access_tenant(dtid):
            return dtid

    for cid in catalog_tenants:
        if actor.can_access_tenant(cid):
            return cid

    raise kd.PermissionDeniedError(
        f"Actor '{actor.actor_id}' has no accessible organization"
    )


def resolve_jwt_tenant_route(
    path: str,
    event: dict[str, Any],
    actor: kd.Actor,
    store: Any,
) -> tuple[str, kd.Actor]:
    """Rewrite tenant-agnostic `/erp/*` routes using JWT-bound tenant resolution and per-org RBAC."""
    if path == "/erp/organizations":
        return "/organizations", actor
    if path == "/erp/invites/accept":
        return "/organizations/invites/accept", actor
    req_method = str(((event.get("requestContext") or {}).get("http") or {}).get("method") or event.get("httpMethod") or "GET").upper()
    if path == "/erp/connectors/paypal/oauth/callback" and req_method in ("GET", "HEAD"):
        return path, actor
    if path.startswith("/erp/"):
        subpath = path[len("/erp/") :].lstrip("/")
        if subpath:
            tid = resolve_active_tenant_id(event, actor, store)
            scoped_actor = bind_actor_to_organization(
                actor, tid, store.identity_registry
            )
            return f"/tenants/{tid}/{subpath}", scoped_actor
    if path.startswith("/tenants/"):
        parts = path.strip("/").split("/")
        if len(parts) >= 3:
            tid = parts[1]
            return path, bind_actor_to_organization(
                actor, tid, store.identity_registry
            )
    return path, actor
