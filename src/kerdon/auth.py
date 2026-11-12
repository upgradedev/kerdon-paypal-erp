"""M1: Stateless capability RBAC and Least-Privilege Reader/Evaluator/Writer roles."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, TypeVar

T = TypeVar("T")


class Capability(str, Enum):
    """Fine-grained capabilities enforced across the Mini-ERP surface."""

    VIEW_PNL = "view_pnl"
    VIEW_PAYROLL = "view_payroll"
    MANAGE_COMMISSIONS = "manage_commissions"
    APPROVE_COMMISSIONS = "approve_commissions"
    ISSUE_DOCS = "issue_docs"
    APPROVE_PAYOUTS = "approve_payouts"
    EXECUTE_PAYOUTS = "execute_payouts"
    VIEW_OWN_SALES = "view_own_sales"
    ONBOARD_TENANT = "onboard_tenant"


class Role(str, Enum):
    """Standard MSP and client roles mapped deterministically to capabilities."""

    MSP_FINOPS_DIRECTOR = "MSP_FINOPS_DIRECTOR"
    CLIENT_OWNER = "CLIENT_OWNER"
    STORE_MANAGER = "STORE_MANAGER"
    ACCOUNTANT = "ACCOUNTANT"
    SELLER = "SELLER"
    PUBLIC_AUDITOR = "PUBLIC_AUDITOR"


ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.MSP_FINOPS_DIRECTOR: frozenset(Capability),
    Role.CLIENT_OWNER: frozenset(
        {
            Capability.VIEW_PNL,
            Capability.VIEW_PAYROLL,
            Capability.MANAGE_COMMISSIONS,
            Capability.APPROVE_COMMISSIONS,
            Capability.ISSUE_DOCS,
            Capability.APPROVE_PAYOUTS,
            Capability.EXECUTE_PAYOUTS,
            Capability.VIEW_OWN_SALES,
        }
    ),
    Role.STORE_MANAGER: frozenset(
        {
            Capability.VIEW_PNL,
            Capability.MANAGE_COMMISSIONS,
            Capability.ISSUE_DOCS,
            Capability.VIEW_OWN_SALES,
        }
    ),
    Role.ACCOUNTANT: frozenset(
        {
            Capability.VIEW_PNL,
            Capability.VIEW_PAYROLL,
            Capability.ISSUE_DOCS,
        }
    ),
    Role.SELLER: frozenset({Capability.VIEW_OWN_SALES}),
    Role.PUBLIC_AUDITOR: frozenset({Capability.VIEW_PNL}),
}


class PermissionDeniedError(PermissionError):
    """Raised when an actor or execution port lacks the required capability."""


@dataclass(frozen=True)
class Actor:
    """Stateless authenticated principal scoped to an MSP hub or tenant subset."""

    actor_id: str
    display_name: str
    role: Role
    allowed_tenant_ids: frozenset[str]
    seller_id: str | None = None

    @property
    def capabilities(self) -> frozenset[Capability]:
        return ROLE_CAPABILITIES.get(self.role, frozenset())

    def can_access_tenant(self, tenant_id: str) -> bool:
        if "*" in self.allowed_tenant_ids:
            return True
        return tenant_id in self.allowed_tenant_ids

    def has_capability(self, capability: Capability, tenant_id: str | None = None) -> bool:
        if tenant_id is not None and not self.can_access_tenant(tenant_id):
            return False
        return capability in self.capabilities


def require_capability(
    actor: Actor, capability: Capability, tenant_id: str | None = None
) -> None:
    """Enforce that the actor holds the given capability for the target tenant."""
    if not actor.has_capability(capability, tenant_id):
        scope_msg = f" on tenant {tenant_id}" if tenant_id else ""
        raise PermissionDeniedError(
            f"Actor {actor.actor_id} ({actor.role.value}) lacks {capability.value}{scope_msg}"
        )


@dataclass(frozen=True)
class Reader:
    """Least-privilege read-only identity. Structurally lacks execute()."""

    actor: Actor

    def read(
        self,
        tenant_id: str,
        query_fn: Callable[[], T],
        capability: Capability = Capability.VIEW_PNL,
    ) -> T:
        require_capability(self.actor, capability, tenant_id)
        return query_fn()


@dataclass(frozen=True)
class Evaluator:
    """Least-privilege evaluation identity for completeness and commission scoring.

    Structurally lacks execute() so evaluation can never disburse funds or mutate state.
    """

    actor: Actor

    def evaluate(self, tenant_id: str, eval_fn: Callable[[], T]) -> T:
        require_capability(self.actor, Capability.VIEW_PNL, tenant_id)
        return eval_fn()


@dataclass(frozen=True)
class Writer:
    """Governed mutation identity. Only Writer exposes execute()."""

    actor: Actor

    def execute(
        self,
        tenant_id: str,
        required_capability: Capability,
        approval_token: str,
        mutation_fn: Callable[[], T],
    ) -> T:
        require_capability(self.actor, required_capability, tenant_id)
        if not approval_token or not approval_token.strip():
            raise PermissionDeniedError(
                "Governed Writer execution requires a non-empty approval_token"
            )
        return mutation_fn()
