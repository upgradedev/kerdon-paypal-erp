"""M8: Agentic Multi-Currency Treasury, Reserve Floors, and Changed-Evidence Invalidation."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
import hashlib
import uuid

IDEMPOTENCY_NAMESPACE = uuid.UUID("7b3c9e50-6b4a-4e2a-9a3f-1c4d5e6f7a8b")
IDEMPOTENCY_WINDOW_SECONDS = 7 * 86_400


class ApprovalState(str, Enum):
    """Lifecycle state of a content-addressed supplier or commission payout approval."""

    VALID = "VALID"
    INVALIDATED = "INVALIDATED"
    EXECUTED = "EXECUTED"


class ReserveFloorBreachError(ValueError):
    """Raised when a payout would drop a currency pocket below its reserve floor."""


class StaleApprovalInvalidatedError(RuntimeError):
    """Raised (HTTP 409) when executing an approval invalidated by changed evidence."""


class DuplicateIdempotencyError(RuntimeError):
    """Raised when the same payout idempotency key is re-submitted within 7 days."""


class ExpiredFxQuoteError(ValueError):
    """Raised when a cross-currency payout uses an expired FX quote lock."""


@dataclass(frozen=True)
class FxQuote:
    """Locked foreign-exchange rate between two currencies (`rate_scaled` in 1e6 units)."""

    quote_id: str
    sell_currency: str
    buy_currency: str
    rate_micros: int
    issued_at_epoch: int
    expires_at_epoch: int

    def is_valid_at(self, now_epoch: int) -> bool:
        return self.issued_at_epoch <= now_epoch < self.expires_at_epoch

    def convert_to_sell_cents(self, buy_amount_cents: int) -> int:
        if self.sell_currency == self.buy_currency:
            return buy_amount_cents
        return int(
            (
                Decimal(buy_amount_cents)
                * Decimal(1_000_000)
                / Decimal(self.rate_micros)
            ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )


@dataclass
class CurrencyPocket:
    """Tenant cash pocket in a single currency (EUR, USD, GBP) with a reserve floor."""

    currency: str
    balance_cents: int
    reserve_floor_cents: int

    @property
    def available_above_floor_cents(self) -> int:
        return max(0, self.balance_cents - self.reserve_floor_cents)


@dataclass
class PayoutApproval:
    """Content-addressed human approval bound to counterparty, beneficiary, and evidence SHA-256."""

    approval_id: str
    tenant_id: str
    counterparty_id: str
    invoice_or_case_id: str
    amount_cents: int
    currency: str
    evidence_sha256: str
    approver_id: str
    created_at_epoch: int
    state: ApprovalState = ApprovalState.VALID
    invalidation_reason: str = ""
    recipient_account: str = ""
    preparer_id: str = ""

    @property
    def binding_digest(self) -> str:
        payload = (
            f"{self.tenant_id}:{self.counterparty_id}:{self.invoice_or_case_id}:"
            f"{self.amount_cents}:{self.currency}:{self.evidence_sha256}"
        )
        if self.recipient_account:
            payload = f"{payload}:{self.recipient_account}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PayoutExecutionReceipt:
    """Immutable receipt emitted when a governed payout executes."""

    payout_id: str
    approval_id: str
    tenant_id: str
    counterparty_id: str
    amount_cents: int
    currency: str
    debited_pocket_currency: str
    debited_cents: int
    remaining_balance_cents: int
    idempotency_key: str
    executed_at_epoch: int
    binding_digest: str


def compute_idempotency_key(
    tenant_id: str,
    counterparty_id: str,
    invoice_or_case_id: str,
    amount_cents: int,
    currency: str,
    day_bucket: int,
) -> str:
    """Compute deterministic UUIDv5 idempotency key for a payout instruction."""
    seed = (
        f"{tenant_id}:{counterparty_id}:{invoice_or_case_id}:"
        f"{amount_cents}:{currency}:{day_bucket}"
    )
    return str(uuid.uuid5(IDEMPOTENCY_NAMESPACE, seed))


@dataclass
class TreasuryEngine:
    """Multi-currency treasury with reserve floor guard and changed-evidence invalidation."""

    tenant_id: str
    pockets: dict[str, CurrencyPocket] = field(default_factory=dict)
    approvals: dict[str, PayoutApproval] = field(default_factory=dict)
    receipts: dict[str, PayoutExecutionReceipt] = field(default_factory=dict)
    idempotency_ledger: dict[str, tuple[str, int]] = field(default_factory=dict)

    def configure_pocket(
        self, currency: str, balance_cents: int, reserve_floor_cents: int
    ) -> CurrencyPocket:
        ccy = currency.upper().strip()
        pocket = CurrencyPocket(
            currency=ccy,
            balance_cents=balance_cents,
            reserve_floor_cents=reserve_floor_cents,
        )
        self.pockets[ccy] = pocket
        return pocket

    def create_approval(
        self,
        *,
        approval_id: str,
        counterparty_id: str,
        invoice_or_case_id: str,
        amount_cents: int,
        currency: str,
        evidence_sha256: str,
        approver_id: str,
        now_epoch: int,
        recipient_account: str = "",
        preparer_id: str = "",
    ) -> PayoutApproval:
        if amount_cents <= 0:
            raise ValueError("amount_cents must be positive")
        clean_sha = str(evidence_sha256 or "").strip()
        if not clean_sha:
            raise ValueError("evidence_sha256 is required for payout approval")
        clean_prep = str(preparer_id or "").strip()
        clean_appr = str(approver_id or "").strip()
        approval = PayoutApproval(
            approval_id=approval_id,
            tenant_id=self.tenant_id,
            counterparty_id=counterparty_id,
            invoice_or_case_id=invoice_or_case_id,
            amount_cents=amount_cents,
            currency=currency.upper().strip(),
            evidence_sha256=clean_sha,
            approver_id=clean_appr,
            created_at_epoch=now_epoch,
            state=ApprovalState.VALID,
            recipient_account=str(recipient_account or "").strip(),
            preparer_id=clean_prep,
        )
        self.approvals[approval_id] = approval
        return approval

    def notify_changed_evidence(
        self,
        *,
        counterparty_id: str,
        new_evidence_sha256: str,
        reason: str,
        invoice_or_case_id: str | None = None,
    ) -> tuple[str, ...]:
        """Invalidate pending approvals affected by new evidence (credit note/deposit/revision).

        Selective invalidation: only VALID approvals matching the counterparty (and
        optional invoice_or_case_id) whose bound evidence_sha256 differs from the
        new evidence flip to INVALIDATED. Unaffected counterparties stay VALID.
        """
        invalidated_ids: list[str] = []
        for approval in self.approvals.values():
            if approval.state != ApprovalState.VALID:
                continue
            if approval.counterparty_id != counterparty_id:
                continue
            if (
                invoice_or_case_id is not None
                and approval.invoice_or_case_id != invoice_or_case_id
            ):
                continue
            if approval.evidence_sha256 != new_evidence_sha256:
                approval.state = ApprovalState.INVALIDATED
                approval.invalidation_reason = (
                    f"STALE_APPROVAL_INVALIDATED: {reason} "
                    f"(old={approval.evidence_sha256[:10]}, new={new_evidence_sha256[:10]})"
                )
                invalidated_ids.append(approval.approval_id)
        return tuple(sorted(invalidated_ids))

    def validate_payout_preflight(
        self,
        *,
        approval_id: str,
        now_epoch: int,
        funding_currency: str | None = None,
        fx_quote: FxQuote | None = None,
        executor_id: str | None = None,
        recipient_account: str | None = None,
    ) -> tuple[PayoutApproval, CurrencyPocket, str, int, str, str]:
        """Validate freshness, Four-Eyes, beneficiary, FX, 7-day idempotency, and reserve floor without mutating state."""
        approval = self.approvals.get(approval_id)
        if approval is None:
            raise KeyError(f"Unknown approval_id: {approval_id}")

        if approval.state == ApprovalState.INVALIDATED:
            raise StaleApprovalInvalidatedError(approval.invalidation_reason)
        if approval.state == ApprovalState.EXECUTED:
            raise DuplicateIdempotencyError(
                f"Approval {approval_id} has already been executed"
            )

        if executor_id:
            clean_exec = executor_id.strip()
            if clean_exec and approval.preparer_id and clean_exec == approval.preparer_id:
                raise PermissionError(
                    f"Four-Eyes violation: executor {clean_exec} cannot execute payout prepared by {clean_exec}"
                )

        if recipient_account and approval.recipient_account:
            if recipient_account.strip().lower() != approval.recipient_account.strip().lower():
                raise ValueError(
                    f"Beneficiary account '{recipient_account}' does not match bound approval recipient '{approval.recipient_account}'"
                )

        day_bucket = now_epoch // IDEMPOTENCY_WINDOW_SECONDS
        idem_key = compute_idempotency_key(
            self.tenant_id,
            approval.counterparty_id,
            approval.invoice_or_case_id,
            approval.amount_cents,
            approval.currency,
            day_bucket,
        )
        rolling_key = compute_idempotency_key(
            self.tenant_id,
            approval.counterparty_id,
            approval.invoice_or_case_id,
            approval.amount_cents,
            approval.currency,
            0,
        )
        prior = self.idempotency_ledger.get(idem_key) or self.idempotency_ledger.get(rolling_key)
        if prior is not None and abs(now_epoch - prior[1]) < IDEMPOTENCY_WINDOW_SECONDS:
            raise DuplicateIdempotencyError(
                f"Duplicate payout blocked by 7-day idempotency lock {idem_key} (prior {prior[0]})"
            )

        debit_ccy = (funding_currency or approval.currency).upper().strip()
        if debit_ccy != approval.currency:
            if fx_quote is None:
                raise ValueError(
                    f"Cross-currency payout ({debit_ccy} -> {approval.currency}) requires fx_quote"
                )
            if not fx_quote.is_valid_at(now_epoch):
                raise ExpiredFxQuoteError(
                    f"FX quote {fx_quote.quote_id} expired at {fx_quote.expires_at_epoch} (now={now_epoch})"
                )
            debit_cents = fx_quote.convert_to_sell_cents(approval.amount_cents)
        else:
            debit_cents = approval.amount_cents

        pocket = self.pockets.get(debit_ccy)
        if pocket is None:
            raise KeyError(f"Unknown currency pocket: {debit_ccy}")

        projected_balance = pocket.balance_cents - debit_cents
        if projected_balance < pocket.reserve_floor_cents:
            raise ReserveFloorBreachError(
                f"Payout of {debit_cents}c in {debit_ccy} would leave {projected_balance}c, "
                f"breaching reserve floor {pocket.reserve_floor_cents}c"
            )
        return approval, pocket, debit_ccy, debit_cents, idem_key, rolling_key

    def execute_payout(
        self,
        *,
        approval_id: str,
        now_epoch: int,
        funding_currency: str | None = None,
        fx_quote: FxQuote | None = None,
        executor_id: str | None = None,
        recipient_account: str | None = None,
    ) -> PayoutExecutionReceipt:
        """Execute a governed payout after verifying approval freshness, Four-Eyes, beneficiary, FX, idempotency, and floor."""
        approval, pocket, debit_ccy, debit_cents, idem_key, rolling_key = self.validate_payout_preflight(
            approval_id=approval_id,
            now_epoch=now_epoch,
            funding_currency=funding_currency,
            fx_quote=fx_quote,
            executor_id=executor_id,
            recipient_account=recipient_account,
        )
        pocket.balance_cents = pocket.balance_cents - debit_cents
        approval.state = ApprovalState.EXECUTED
        payout_id = f"pay-{approval.approval_id}"
        receipt = PayoutExecutionReceipt(
            payout_id=payout_id,
            approval_id=approval.approval_id,
            tenant_id=self.tenant_id,
            counterparty_id=approval.counterparty_id,
            amount_cents=approval.amount_cents,
            currency=approval.currency,
            debited_pocket_currency=debit_ccy,
            debited_cents=debit_cents,
            remaining_balance_cents=pocket.balance_cents,
            idempotency_key=idem_key,
            executed_at_epoch=now_epoch,
            binding_digest=approval.binding_digest,
        )
        self.receipts[payout_id] = receipt
        self.idempotency_ledger[idem_key] = (payout_id, now_epoch)
        self.idempotency_ledger[rolling_key] = (payout_id, now_epoch)
        return receipt
