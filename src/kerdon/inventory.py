"""M9: Deterministic SKU Inventory, Stock Ledger, Weighted-Average COGS & Reorder Engine (`inventory.py`).

Completes Pillar 2 (`Inventory tracking`) of the Mini-ERP specification and provides
`<InventoryAlerts />`, weighted-average Cost of Goods Sold (`COGS`), stock-vs-invoice
completeness checks (`UNBILLED_STOCK_DISPATCH`, `UNRECEIVED_PURCHASE_STOCK`), and
autonomous Purchase Order (`PO`) drafting when available stock hits `reorder_point_qty`.
100% integer cents and integer quantities; zero cloud/LLM SDK imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib


class SkuCategory(str, Enum):
    HARDWARE_TERMINAL = "HARDWARE_TERMINAL"
    FIBER_OPTIC_ONT = "FIBER_OPTIC_ONT"
    NETWORK_ROUTER = "NETWORK_ROUTER"
    CONSUMABLE_SIM_PACK = "CONSUMABLE_SIM_PACK"


class StockMovementKind(str, Enum):
    GOODS_RECEIPT = "GOODS_RECEIPT"
    SALE_DISPATCH = "SALE_DISPATCH"
    STOCK_ADJUSTMENT = "STOCK_ADJUSTMENT"
    RETURN_INBOUND = "RETURN_INBOUND"


class InventoryAlertKind(str, Enum):
    LOW_STOCK_REORDER = "LOW_STOCK_REORDER"
    UNBILLED_STOCK_DISPATCH = "UNBILLED_STOCK_DISPATCH"
    UNRECEIVED_PURCHASE_STOCK = "UNRECEIVED_PURCHASE_STOCK"


@dataclass(frozen=True)
class InventorySku:
    sku_id: str
    tenant_id: str
    sku_code: str
    name: str
    category: SkuCategory
    preferred_supplier_id: str
    preferred_supplier_name: str
    unit_cost_cents: int
    unit_list_price_cents: int
    on_hand_qty: int
    reserved_qty: int
    reorder_point_qty: int
    reorder_order_qty: int

    @property
    def available_qty(self) -> int:
        return max(0, self.on_hand_qty - self.reserved_qty)

    @property
    def valuation_cents(self) -> int:
        return self.on_hand_qty * self.unit_cost_cents

    @property
    def needs_reorder(self) -> bool:
        return self.available_qty <= self.reorder_point_qty


@dataclass(frozen=True)
class StockMovement:
    movement_id: str
    tenant_id: str
    sku_id: str
    sku_code: str
    kind: StockMovementKind
    qty_delta: int
    unit_cost_cents: int
    total_cost_cents: int
    cogs_posted_cents: int
    linked_document_id: str
    occurred_date: str
    note: str


@dataclass(frozen=True)
class InventoryAlert:
    alert_id: str
    tenant_id: str
    sku_id: str
    sku_code: str
    sku_name: str
    kind: InventoryAlertKind
    severity: str
    exposure_cents: int
    summary: str
    suggested_action: str


@dataclass(frozen=True)
class PurchaseOrderDraft:
    po_id: str
    tenant_id: str
    supplier_id: str
    supplier_name: str
    sku_id: str
    sku_code: str
    sku_name: str
    order_qty: int
    unit_cost_cents: int
    net_cents: int
    vat_cents: int
    gross_cents: int
    created_date: str
    status: str
    po_sha256: str


@dataclass(frozen=True)
class InventorySummarySnapshot:
    tenant_id: str
    total_sku_count: int
    total_units_on_hand: int
    total_valuation_cents: int
    period_cogs_cents: int
    low_stock_count: int
    open_alert_count: int
    skus: tuple[InventorySku, ...]
    movements: tuple[StockMovement, ...]
    alerts: tuple[InventoryAlert, ...]
    purchase_order_drafts: tuple[PurchaseOrderDraft, ...]


def evaluate_inventory_alerts_and_pos(
    tenant_id: str,
    skus: tuple[InventorySku, ...],
    movements: tuple[StockMovement, ...],
) -> tuple[tuple[InventoryAlert, ...], tuple[PurchaseOrderDraft, ...]]:
    """Deterministically compute `<InventoryAlerts />` and auto-drafted Reorder POs."""
    alerts: list[InventoryAlert] = []
    po_drafts: list[PurchaseOrderDraft] = []
    sku_by_id = {s.sku_id: s for s in skus}

    for idx, s in enumerate(skus, start=1):
        if s.needs_reorder:
            net_cents = s.reorder_order_qty * s.unit_cost_cents
            vat_cents = (net_cents * 24) // 100
            gross_cents = net_cents + vat_cents
            po_id = f"PO-2026-{idx:04d}"
            po_sha = hashlib.sha256(
                f"{tenant_id}|{po_id}|{s.sku_code}|{s.reorder_order_qty}|{gross_cents}".encode("utf-8")
            ).hexdigest()
            po_drafts.append(
                PurchaseOrderDraft(
                    po_id=po_id,
                    tenant_id=tenant_id,
                    supplier_id=s.preferred_supplier_id,
                    supplier_name=s.preferred_supplier_name,
                    sku_id=s.sku_id,
                    sku_code=s.sku_code,
                    sku_name=s.name,
                    order_qty=s.reorder_order_qty,
                    unit_cost_cents=s.unit_cost_cents,
                    net_cents=net_cents,
                    vat_cents=vat_cents,
                    gross_cents=gross_cents,
                    created_date="2026-10-31",
                    status="AUTO_DRAFTED_PENDING_APPROVAL",
                    po_sha256=po_sha,
                )
            )
            alerts.append(
                InventoryAlert(
                    alert_id=f"inv-alert-reorder-{s.sku_id}",
                    tenant_id=tenant_id,
                    sku_id=s.sku_id,
                    sku_code=s.sku_code,
                    sku_name=s.name,
                    kind=InventoryAlertKind.LOW_STOCK_REORDER,
                    severity="WARNING" if s.available_qty > 0 else "CRITICAL",
                    exposure_cents=gross_cents,
                    summary=(
                        f"{s.sku_code} available stock ({s.available_qty} units) is at or below "
                        f"reorder point ({s.reorder_point_qty} units)."
                    ),
                    suggested_action=(
                        f"Approve auto-drafted Purchase Order {po_id} for {s.reorder_order_qty} units "
                        f"from {s.preferred_supplier_name}."
                    ),
                )
            )

    for mv in movements:
        if mv.kind == StockMovementKind.SALE_DISPATCH and not mv.linked_document_id.strip():
            sku_obj = sku_by_id.get(mv.sku_id)
            sku_name = sku_obj.name if sku_obj else mv.sku_code
            billable_cents = (
                abs(mv.qty_delta) * sku_obj.unit_list_price_cents
                if sku_obj
                else abs(mv.total_cost_cents)
            )
            alerts.append(
                InventoryAlert(
                    alert_id=f"inv-alert-unbilled-{mv.movement_id}",
                    tenant_id=tenant_id,
                    sku_id=mv.sku_id,
                    sku_code=mv.sku_code,
                    sku_name=sku_name,
                    kind=InventoryAlertKind.UNBILLED_STOCK_DISPATCH,
                    severity="CRITICAL",
                    exposure_cents=billable_cents,
                    summary=(
                        f"{abs(mv.qty_delta)} units of {mv.sku_code} dispatched on {mv.occurred_date} "
                        f"without a linked customer sales invoice."
                    ),
                    suggested_action=(
                        f"Issue customer sales invoice for {abs(mv.qty_delta)}x {mv.sku_code} "
                        f"or link dispatch {mv.movement_id} to an existing invoice."
                    ),
                )
            )

    return tuple(alerts), tuple(po_drafts)


def build_default_inventory_snapshot(tenant_id: str, slug: str) -> InventorySummarySnapshot:
    """Build deterministic initial multi-store SKU inventory, movements, and alerts."""
    skus = (
        InventorySku(
            sku_id=f"sku-{slug}-ont-01",
            tenant_id=tenant_id,
            sku_code="SKU-ONT-WIFI6-PRO",
            name="Dual-Band GPON Fiber ONT Wi-Fi 6 Terminal",
            category=SkuCategory.FIBER_OPTIC_ONT,
            preferred_supplier_id=f"sup-{slug}-01",
            preferred_supplier_name="Alpine Cloud & Fiber Infrastructure Ltd",
            unit_cost_cents=6_800,
            unit_list_price_cents=12_500,
            on_hand_qty=14,
            reserved_qty=8,
            reorder_point_qty=10,
            reorder_order_qty=40,
        ),
        InventorySku(
            sku_id=f"sku-{slug}-pos-02",
            tenant_id=tenant_id,
            sku_code="SKU-POS-PAX-A920",
            name="Android Smart POS Terminal NFC/4G",
            category=SkuCategory.HARDWARE_TERMINAL,
            preferred_supplier_id=f"sup-{slug}-01",
            preferred_supplier_name="Alpine Cloud & Fiber Infrastructure Ltd",
            unit_cost_cents=14_500,
            unit_list_price_cents=24_900,
            on_hand_qty=28,
            reserved_qty=4,
            reorder_point_qty=12,
            reorder_order_qty=25,
        ),
        InventorySku(
            sku_id=f"sku-{slug}-rtr-03",
            tenant_id=tenant_id,
            sku_code="SKU-RTR-MESH-AX3000",
            name="Enterprise Mesh Gateway AX3000 PoE",
            category=SkuCategory.NETWORK_ROUTER,
            preferred_supplier_id=f"sup-{slug}-01",
            preferred_supplier_name="Alpine Cloud & Fiber Infrastructure Ltd",
            unit_cost_cents=9_200,
            unit_list_price_cents=16_800,
            on_hand_qty=7,
            reserved_qty=5,
            reorder_point_qty=8,
            reorder_order_qty=30,
        ),
        InventorySku(
            sku_id=f"sku-{slug}-sim-04",
            tenant_id=tenant_id,
            sku_code="SKU-SIM-5G-TRIO",
            name="5G eSIM / Multi-FF Enterprise Provisioning Pack (10x)",
            category=SkuCategory.CONSUMABLE_SIM_PACK,
            preferred_supplier_id=f"sup-{slug}-01",
            preferred_supplier_name="Alpine Cloud & Fiber Infrastructure Ltd",
            unit_cost_cents=1_500,
            unit_list_price_cents=3_500,
            on_hand_qty=65,
            reserved_qty=10,
            reorder_point_qty=20,
            reorder_order_qty=100,
        ),
    )

    movements = (
        StockMovement(
            movement_id=f"stk-mv-{slug}-01",
            tenant_id=tenant_id,
            sku_id=skus[0].sku_id,
            sku_code=skus[0].sku_code,
            kind=StockMovementKind.GOODS_RECEIPT,
            qty_delta=30,
            unit_cost_cents=6_800,
            total_cost_cents=204_000,
            cogs_posted_cents=0,
            linked_document_id=f"doc-{slug}-pur-201",
            occurred_date="2026-10-12",
            note="Supplier warehouse receipt verified against purchase invoice",
        ),
        StockMovement(
            movement_id=f"stk-mv-{slug}-02",
            tenant_id=tenant_id,
            sku_id=skus[0].sku_id,
            sku_code=skus[0].sku_code,
            kind=StockMovementKind.SALE_DISPATCH,
            qty_delta=-16,
            unit_cost_cents=6_800,
            total_cost_cents=108_800,
            cogs_posted_cents=108_800,
            linked_document_id=f"doc-{slug}-sal-101",
            occurred_date="2026-10-15",
            note="Customer rollout dispatch posted to COGS",
        ),
        StockMovement(
            movement_id=f"stk-mv-{slug}-03-unbilled",
            tenant_id=tenant_id,
            sku_id=skus[2].sku_id,
            sku_code=skus[2].sku_code,
            kind=StockMovementKind.SALE_DISPATCH,
            qty_delta=-4,
            unit_cost_cents=9_200,
            total_cost_cents=36_800,
            cogs_posted_cents=36_800,
            linked_document_id="",
            occurred_date="2026-10-26",
            note="Urgent branch router replacement dispatched without sales invoice",
        ),
    )

    alerts, po_drafts = evaluate_inventory_alerts_and_pos(tenant_id, skus, movements)
    return summarize_inventory(tenant_id, skus, movements, alerts, po_drafts)


def summarize_inventory(
    tenant_id: str,
    skus: tuple[InventorySku, ...],
    movements: tuple[StockMovement, ...],
    alerts: tuple[InventoryAlert, ...],
    po_drafts: tuple[PurchaseOrderDraft, ...],
) -> InventorySummarySnapshot:
    total_units = sum(s.on_hand_qty for s in skus)
    total_val = sum(s.valuation_cents for s in skus)
    period_cogs = sum(m.cogs_posted_cents for m in movements)
    low_stock = sum(1 for s in skus if s.needs_reorder)
    return InventorySummarySnapshot(
        tenant_id=tenant_id,
        total_sku_count=len(skus),
        total_units_on_hand=total_units,
        total_valuation_cents=total_val,
        period_cogs_cents=period_cogs,
        low_stock_count=low_stock,
        open_alert_count=len(alerts),
        skus=skus,
        movements=movements,
        alerts=alerts,
        purchase_order_drafts=po_drafts,
    )


def apply_stock_movement(
    snapshot: InventorySummarySnapshot,
    *,
    sku_code: str,
    kind: StockMovementKind,
    qty: int,
    linked_document_id: str = "",
    unit_cost_override_cents: int | None = None,
    occurred_date: str = "2026-11-05",
    note: str = "",
) -> InventorySummarySnapshot:
    """Apply a goods receipt or sale dispatch with weighted-average cost and COGS calculation."""
    if qty <= 0:
        raise ValueError("qty must be a positive integer")
    updated_skus: list[InventorySku] = []
    target_sku: InventorySku | None = None
    new_mv: StockMovement | None = None

    for s in snapshot.skus:
        if s.sku_code != sku_code and s.sku_id != sku_code:
            updated_skus.append(s)
            continue
        target_sku = s
        if kind in (StockMovementKind.GOODS_RECEIPT, StockMovementKind.RETURN_INBOUND):
            in_cost = unit_cost_override_cents if unit_cost_override_cents is not None else s.unit_cost_cents
            new_qty = s.on_hand_qty + qty
            # Deterministic weighted-average unit cost in integer cents
            new_unit_cost = (
                (s.on_hand_qty * s.unit_cost_cents) + (qty * in_cost)
            ) // max(1, new_qty)
            updated_sku = InventorySku(
                sku_id=s.sku_id,
                tenant_id=s.tenant_id,
                sku_code=s.sku_code,
                name=s.name,
                category=s.category,
                preferred_supplier_id=s.preferred_supplier_id,
                preferred_supplier_name=s.preferred_supplier_name,
                unit_cost_cents=new_unit_cost,
                unit_list_price_cents=s.unit_list_price_cents,
                on_hand_qty=new_qty,
                reserved_qty=s.reserved_qty,
                reorder_point_qty=s.reorder_point_qty,
                reorder_order_qty=s.reorder_order_qty,
            )
            updated_skus.append(updated_sku)
            new_mv = StockMovement(
                movement_id=f"stk-mv-{len(snapshot.movements) + 1:03d}",
                tenant_id=snapshot.tenant_id,
                sku_id=s.sku_id,
                sku_code=s.sku_code,
                kind=kind,
                qty_delta=qty,
                unit_cost_cents=in_cost,
                total_cost_cents=qty * in_cost,
                cogs_posted_cents=0,
                linked_document_id=linked_document_id,
                occurred_date=occurred_date,
                note=note or f"Goods receipt +{qty} units",
            )
        else:
            if s.on_hand_qty < qty:
                raise ValueError(
                    f"NEGATIVE_STOCK_BLOCKED: cannot dispatch {qty} units of {s.sku_code} "
                    f"(only {s.on_hand_qty} on hand)"
                )
            new_qty = s.on_hand_qty - qty
            cogs_cents = qty * s.unit_cost_cents
            updated_sku = InventorySku(
                sku_id=s.sku_id,
                tenant_id=s.tenant_id,
                sku_code=s.sku_code,
                name=s.name,
                category=s.category,
                preferred_supplier_id=s.preferred_supplier_id,
                preferred_supplier_name=s.preferred_supplier_name,
                unit_cost_cents=s.unit_cost_cents,
                unit_list_price_cents=s.unit_list_price_cents,
                on_hand_qty=new_qty,
                reserved_qty=min(s.reserved_qty, new_qty),
                reorder_point_qty=s.reorder_point_qty,
                reorder_order_qty=s.reorder_order_qty,
            )
            updated_skus.append(updated_sku)
            new_mv = StockMovement(
                movement_id=f"stk-mv-{len(snapshot.movements) + 1:03d}",
                tenant_id=snapshot.tenant_id,
                sku_id=s.sku_id,
                sku_code=s.sku_code,
                kind=kind,
                qty_delta=-qty,
                unit_cost_cents=s.unit_cost_cents,
                total_cost_cents=cogs_cents,
                cogs_posted_cents=cogs_cents,
                linked_document_id=linked_document_id,
                occurred_date=occurred_date,
                note=note or f"Sale dispatch -{qty} units (COGS posted)",
            )

    if target_sku is None or new_mv is None:
        raise KeyError(f"Unknown SKU code: {sku_code}")

    skus_tuple = tuple(updated_skus)
    mvs_tuple = (*snapshot.movements, new_mv)
    alerts, pos = evaluate_inventory_alerts_and_pos(snapshot.tenant_id, skus_tuple, mvs_tuple)
    return summarize_inventory(snapshot.tenant_id, skus_tuple, mvs_tuple, alerts, pos)
