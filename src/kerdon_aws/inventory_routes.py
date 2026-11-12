"""HTTP API v2 routes for M9 SKU Inventory, Stock Movements, COGS & Reorder POs (`inventory_routes.py`)."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import kerdon as kd

from .http_utils import ValidationError, json_reply
from .persistence import get_store

_INVENTORY_RUNTIME: dict[str, kd.InventorySummarySnapshot] = {}


def reset_inventory_runtime(tenant_id: str | None = None) -> None:
    """Reset per-tenant inventory runtime state (used by POST /tenants/{id}/reset)."""
    if tenant_id is None:
        _INVENTORY_RUNTIME.clear()
    else:
        _INVENTORY_RUNTIME.pop(tenant_id, None)


def get_tenant_inventory(
    tid: str, state: kd.TenantMiniErpState
) -> kd.InventorySummarySnapshot:
    """Return or initialize the per-tenant SKU inventory and alerts snapshot."""
    if tid not in _INVENTORY_RUNTIME:
        _INVENTORY_RUNTIME[tid] = kd.build_default_inventory_snapshot(
            tid, state.tenant.slug
        )
    return _INVENTORY_RUNTIME[tid]


def handle_get_inventory(
    tid: str,
    state: kd.TenantMiniErpState,
    reader: kd.Reader,
    *,
    head_only: bool = False,
) -> dict[str, Any]:
    """GET `/tenants/{id}/inventory`: return SKUs, movements, COGS, alerts, and auto-drafted POs."""
    snap = get_tenant_inventory(tid, state)
    snap_dict = reader.read(tid, lambda: asdict(snap))
    payload = {
        **snap_dict,
        "total_inventory_valuation_cents": snap_dict["total_valuation_cents"],
        "total_cogs_cents": snap_dict["period_cogs_cents"],
        "low_stock_alert_count": snap_dict["low_stock_count"],
        "reorder_purchase_orders": snap_dict["purchase_order_drafts"],
        "inventory": {
            **snap_dict,
            "sku_items": snap_dict["skus"],
            "total_stock_valuation_cents": snap_dict["total_valuation_cents"],
            "draft_purchase_orders": snap_dict["purchase_order_drafts"],
        },
    }
    return json_reply(200, payload, head_only=head_only)


def handle_post_inventory_movement(
    tid: str,
    state: kd.TenantMiniErpState,
    body: dict[str, Any],
    actor: kd.Actor,
) -> dict[str, Any]:
    """POST `/tenants/{id}/inventory/movement`: record GOODS_RECEIPT or SALE_DISPATCH with COGS."""
    sku_code = str(body.get("sku_code") or "SKU-ONT-WIFI6-PRO").strip()
    kind_raw = str(
        body.get("kind") or body.get("movement_kind") or "GOODS_RECEIPT"
    ).strip().upper()
    try:
        kind = kd.StockMovementKind(kind_raw)
    except ValueError as exc:
        raise ValidationError(f"Unsupported stock movement kind: {kind_raw}") from exc

    qty = body.get("qty", body.get("quantity", 10))
    if not isinstance(qty, int) or qty <= 0:
        raise ValidationError("qty must be a positive integer")

    linked_doc = str(body.get("linked_document_id") or "").strip()
    note = str(body.get("note") or "").strip()
    snap = get_tenant_inventory(tid, state)
    writer = kd.Writer(actor)

    def _mutate() -> kd.InventorySummarySnapshot:
        try:
            updated = kd.apply_stock_movement(
                snap,
                sku_code=sku_code,
                kind=kind,
                qty=qty,
                linked_document_id=linked_doc,
                note=note,
            )
        except (ValueError, KeyError) as exc:
            raise ValidationError(str(exc)) from exc
        _INVENTORY_RUNTIME[tid] = updated
        return updated

    updated_snap = writer.execute(
        tid,
        kd.Capability.ISSUE_DOCS,
        approval_token=f"inv-mv-{sku_code}-{kind.value}",
        mutation_fn=_mutate,
    )
    last_mv = updated_snap.movements[-1]
    updated_sku = next(
        (s for s in updated_snap.skus if s.sku_code == sku_code),
        updated_snap.skus[0],
    )
    get_store().persist_audit_record(
        tid,
        "INVENTORY_MOVEMENT_RECORDED",
        last_mv.movement_id,
        asdict(last_mv),
    )
    snap_dict = asdict(updated_snap)
    mv_dict = asdict(last_mv)
    sale_price_cents = int(
        body.get("unit_sale_price_cents") or updated_sku.unit_list_price_cents
    )
    return json_reply(
        200,
        {
            **snap_dict,
            "inventory": {
                **snap_dict,
                "sku_items": snap_dict["skus"],
                "total_stock_valuation_cents": snap_dict["total_valuation_cents"],
                "draft_purchase_orders": snap_dict["purchase_order_drafts"],
            },
            "updated_sku": {
                **asdict(updated_sku),
                "stock_valuation_cents": updated_sku.valuation_cents,
            },
            "movement": {
                **mv_dict,
                "cogs_cents": last_mv.cogs_posted_cents,
                "revenue_cents": (
                    qty * sale_price_cents
                    if kind == kd.StockMovementKind.SALE_DISPATCH
                    else 0
                ),
            },
        },
    )
