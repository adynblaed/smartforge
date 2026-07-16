"""Deterministic sample dataset for the development sandbox seed.

`cli sample-seed` (development only) drives the REAL pipeline — staged
Parquet, atomic publish + manifest, dlt merge, catalog refresh, dbt — with
this dataset standing in for the omega Oracle source. The shapes mirror the
legacy reports the platform replaces (OPEN_ORDERS_BACKLOG, the
INV_ALLOCATION_SUMMARY pegging report), including a three-level work-order
genealogy (root -> child -> grandchild) and an MRP plan whose running
balances are computed here so lake, warehouse, and marts all reconcile.

Content is deterministic; only timestamps track the wall clock so freshness
reads honestly. No row leaves this module without a reviewed contract —
tables are keyed by the same qualified names as config/tables.yml.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from app.dataplatform.oracle.metadata import InferredColumn, InferredTable
from app.dataplatform.registry import Registry

# Compact type kinds: (oracle_type, postgres_type, arrow_type, duckdb_type)
_KINDS: dict[str, tuple[str, str, str, str]] = {
    "id": ("NUMBER", "BIGINT", "int64", "BIGINT"),
    "int": ("NUMBER", "BIGINT", "int64", "BIGINT"),
    "qty": ("NUMBER", "NUMERIC(18,4)", "decimal128(18,4)", "DECIMAL(18,4)"),
    "money": ("NUMBER", "NUMERIC(18,2)", "decimal128(18,2)", "DECIMAL(18,2)"),
    "num": ("NUMBER", "NUMERIC(12,2)", "decimal128(12,2)", "DECIMAL(12,2)"),
    "text": ("VARCHAR2", "TEXT", "string", "VARCHAR"),
    "ts": ("TIMESTAMP(6)", "TIMESTAMP", "timestamp(us)", "TIMESTAMP"),
    "bool": ("NUMBER", "BOOLEAN", "bool", "BOOLEAN"),
}


def _columns(
    spec: list[tuple[str, str]], primary_key: list[str]
) -> list[InferredColumn]:
    out: list[InferredColumn] = []
    for name, kind in spec:
        oracle, postgres, arrow, duckdb = _KINDS[kind]
        out.append(
            InferredColumn(
                name=name,
                destination_name=name.lower(),
                oracle_type=oracle,
                postgres_type=postgres,
                arrow_type=arrow,
                duckdb_type=duckdb,
                nullable=name not in primary_key,
                is_primary_key=name in primary_key,
            )
        )
    return out


def _qty(value: float | int) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _money(value: float | int) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# The dataset. All cross-references (parent WOs, sales-order pegging, PO
# lines vs headers, MRP balances) are internally consistent by construction.
# ---------------------------------------------------------------------------

_OPS = "PRO, LAS, BRA, QUA, SHI"  # routing summary style from the WO tracker


def build_sample_dataset(
    registry: Registry, now: dt.datetime | None = None
) -> dict[str, tuple[InferredTable, list[dict[str, Any]]]]:
    """All contracted tables -> (inferred schema, Oracle-shaped rows)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    now = now.replace(tzinfo=None, microsecond=0)  # source-local like Oracle
    today = dt.datetime(now.year, now.month, now.day)

    def day(offset: int) -> dt.datetime:
        return today + dt.timedelta(days=offset)

    ts = now - dt.timedelta(minutes=7)
    created = now - dt.timedelta(days=30)

    dataset: dict[str, tuple[InferredTable, list[dict[str, Any]]]] = {}

    def add(
        qualified: str, spec: list[tuple[str, str]], rows: list[dict[str, Any]]
    ) -> None:
        contract = registry.get(qualified)
        inferred = InferredTable(
            contract=contract,
            columns=_columns(spec, contract.primary_key),
            estimated_rows=len(rows),
            primary_key_verified=True,
            cursor_verified=True,
        )
        inferred.schema_hash = inferred.compute_schema_hash()
        dataset[qualified] = (inferred, rows)

    # ------------------------------------------------------------- lookups
    add(
        "OMEGA.STATUS_LOOKUP",
        [
            ("STATUS_CODE", "text"),
            ("STATUS_DOMAIN", "text"),
            ("DESCRIPTION", "text"),
            ("SORT_ORDER", "int"),
        ],
        [
            {"STATUS_CODE": c, "STATUS_DOMAIN": d, "DESCRIPTION": desc, "SORT_ORDER": i}
            for i, (c, d, desc) in enumerate(
                [
                    ("OR", "WORK_ORDER", "Open - released"),
                    ("ON", "WORK_ORDER", "Open - not released"),
                    ("CL", "WORK_ORDER", "Closed"),
                    ("SO_OPEN", "SALES_ORDER", "Open"),
                    ("SO_SHIPPED", "SALES_ORDER", "Shipped"),
                    ("PO_OPEN", "PURCHASE_ORDER", "Open"),
                    ("PO_RECEIVED", "PURCHASE_ORDER", "Received"),
                ]
            )
        ],
    )

    # ------------------------------------------------------------ machines
    machine_spec = [
        ("MACHINE_ID", "id"),
        ("MACHINE_CODE", "text"),
        ("MACHINE_NAME", "text"),
        ("MACHINE_TYPE", "text"),
        ("LINE_CODE", "text"),
        ("FACTORY_CODE", "text"),
        ("STATUS", "text"),
        ("RATED_OUTPUT_PER_HOUR", "num"),
        ("COMMISSIONED_AT", "ts"),
        ("IS_DECOMMISSIONED", "bool"),
        ("LAST_UPDATE_TS", "ts"),
    ]
    machines = [
        (1, "LASER-01", "Fiber Laser 6kW", "laser"),
        (2, "PUNCH-01", "CNC Turret Punch", "punch"),
        (3, "BRAKE-01", "Press Brake 130T", "press_brake"),
        (4, "BRAKE-02", "Press Brake 220T", "press_brake"),
        (5, "WELD-01", "Robotic Weld Cell A", "weld"),
        (6, "WELD-02", "Robotic Weld Cell B", "weld"),
        (7, "ASSY-01", "Assembly Line 1", "assembly"),
        (8, "PAINT-01", "Powder Coat Line", "paint"),
    ]
    add(
        "OMEGA.MACHINES",
        machine_spec,
        [
            {
                "MACHINE_ID": mid,
                "MACHINE_CODE": code,
                "MACHINE_NAME": name,
                "MACHINE_TYPE": mtype,
                "LINE_CODE": f"LINE-{(mid - 1) % 3 + 1}",
                "FACTORY_CODE": "FFM-NV1",
                "STATUS": "running",
                "RATED_OUTPUT_PER_HOUR": _money(40 + mid * 5),
                "COMMISSIONED_AT": created - dt.timedelta(days=400 + mid * 30),
                "IS_DECOMMISSIONED": False,
                "LAST_UPDATE_TS": ts,
            }
            for mid, code, name, mtype in machines
        ],
    )

    # ----------------------------------------------------------- suppliers
    add(
        "OMEGA.SUPPLIERS",
        [
            ("SUPPLIER_ID", "id"),
            ("SUPPLIER_CODE", "text"),
            ("SUPPLIER_NAME", "text"),
            ("COUNTRY_CODE", "text"),
            ("RATING", "num"),
            ("LAST_UPDATE_TS", "ts"),
        ],
        [
            {
                "SUPPLIER_ID": sid,
                "SUPPLIER_CODE": code,
                "SUPPLIER_NAME": name,
                "COUNTRY_CODE": "US",
                "RATING": _money(rating),
                "LAST_UPDATE_TS": ts,
            }
            for sid, code, name, rating in [
                (1, "STL-CO", "Sierra Steel Supply", 4.6),
                (2, "ALU-CO", "Cascade Aluminum Co", 4.2),
                (3, "HDW-CO", "Summit Hardware Group", 3.9),
                (4, "PWD-CO", "Nova Powder Coatings", 4.8),
            ]
        ],
    )

    # ----------------------------------------------------------- customers
    add(
        "OMEGA.CUSTOMERS",
        [
            ("CUSTOMER_ID", "id"),
            ("CUSTOMER_CODE", "text"),
            ("CUSTOMER_NAME", "text"),
            ("SEGMENT", "text"),
            ("COUNTRY_CODE", "text"),
            ("CREDIT_LIMIT", "money"),
            ("LAST_UPDATE_TS", "ts"),
        ],
        [
            {
                "CUSTOMER_ID": cid,
                "CUSTOMER_CODE": code,
                "CUSTOMER_NAME": name,
                "SEGMENT": segment,
                "COUNTRY_CODE": "US",
                "CREDIT_LIMIT": _money(limit),
                "LAST_UPDATE_TS": ts,
            }
            for cid, code, name, segment, limit in [
                (1, "ACME", "Acme Robotics", "industrial_automation", 250_000),
                (2, "VRTX", "Vertex Data Centers", "data_center", 500_000),
                (3, "MERI", "Meridian Transit Systems", "transit", 750_000),
                (4, "HELI", "Helios Energy", "energy", 300_000),
                (5, "CASC", "Cascade Semiconductors", "semiconductor", 400_000),
            ]
        ],
    )

    # ------------------------------------------------------ inventory items
    # (item_code, description, category, uom, on_hand, reorder, safety,
    #  lead_days, min_order, item_type, unit_cost, supplier)
    items = [
        (
            "4001-143-99",
            "-70 DOOR PANEL ASM_LH",
            "finished_good",
            "Ea",
            4,
            2,
            0,
            10,
            1,
            "S/M",
            620.0,
            None,
        ),
        (
            "4001-142-99",
            "-70 DOOR PANEL ASM_RH",
            "finished_good",
            "Ea",
            2,
            2,
            0,
            10,
            1,
            "S/M",
            620.0,
            None,
        ),
        (
            "4004-171-01",
            "ENCLOSURE, POWDER COATED",
            "finished_good",
            "Ea",
            6,
            4,
            0,
            15,
            1,
            "S/M",
            480.0,
            None,
        ),
        (
            "A2V00002437083",
            "FRAME, CPL",
            "finished_good",
            "Ea",
            12,
            6,
            0,
            12,
            1,
            "S/M",
            92.5,
            None,
        ),
        (
            "04-0000622",
            "WELDMENT, ENCLOSURE, SST",
            "subassembly",
            "Ea",
            8,
            6,
            6,
            5,
            1,
            "S/M",
            210.0,
            None,
        ),
        (
            "000864901",
            "BRACKET",
            "component",
            "Ea",
            28,
            40,
            36,
            5,
            20,
            "S/M",
            6.4,
            None,
        ),
        (
            "10370",
            "18 GA, CRS, 48 x 84",
            "raw_material",
            "Ea",
            1200,
            600,
            500,
            5,
            400,
            "SHEET",
            41.8,
            1,
        ),
        (
            "10036",
            "(STOCK) 12 GA, CRS, 48 x 120",
            "raw_material",
            "Ea",
            300,
            150,
            0,
            5,
            200,
            "SHEET",
            62.3,
            1,
        ),
        (
            "80552",
            'UNISTRUT P1000 - 1-5/8"',
            "raw_material",
            "Ft",
            17934,
            8000,
            0,
            10,
            5000,
            "STRUT",
            2.1,
            3,
        ),
        (
            "10017",
            ".090, 5052 H-32 AL, 48 x 96",
            "raw_material",
            "Ea",
            60,
            120,
            0,
            5,
            100,
            "SHEET",
            58.9,
            2,
        ),
    ]
    add(
        "OMEGA.INVENTORY_ITEMS",
        [
            ("ITEM_ID", "id"),
            ("ITEM_CODE", "text"),
            ("DESCRIPTION", "text"),
            ("CATEGORY", "text"),
            ("UOM", "text"),
            ("QTY_ON_HAND", "qty"),
            ("REORDER_POINT", "qty"),
            ("SAFETY_STOCK", "qty"),
            ("MRP_LEAD_TIME_DAYS", "int"),
            ("MIN_ORDER_QTY", "qty"),
            ("ITEM_TYPE", "text"),
            ("UNIT_COST", "qty"),
            ("SUPPLIER_ID", "id"),
            ("LAST_UPDATE_TS", "ts"),
        ],
        [
            {
                "ITEM_ID": i + 1,
                "ITEM_CODE": code,
                "DESCRIPTION": desc,
                "CATEGORY": cat,
                "UOM": uom,
                "QTY_ON_HAND": _qty(on_hand),
                "REORDER_POINT": _qty(reorder),
                "SAFETY_STOCK": _qty(safety),
                "MRP_LEAD_TIME_DAYS": lead,
                "MIN_ORDER_QTY": _qty(min_order),
                "ITEM_TYPE": itype,
                "UNIT_COST": _qty(cost),
                "SUPPLIER_ID": supplier,
                "LAST_UPDATE_TS": ts,
            }
            for i, (
                code,
                desc,
                cat,
                uom,
                on_hand,
                reorder,
                safety,
                lead,
                min_order,
                itype,
                cost,
                supplier,
            ) in enumerate(items)
        ],
    )

    # ---------------------------------------------------------- work orders
    # Genealogy: roots (assemblies, pegged to sales orders) split into
    # children (weldments/frames), which split into grandchildren (brackets).
    # (id, parent, machine, item, qty, status, op, so_no, so_line, due_off)
    wo_rows_spec: list[
        tuple[int, int | None, int, str, int, str, str, str | None, int | None, int]
    ] = [
        # two closed historical roots (completed volume for the marts)
        (752398, None, 7, "4001-143-99", 20, "CL", "SHI", "314101", 1, -6),
        (752399, None, 7, "4001-142-99", 20, "CL", "SHI", "314101", 2, -6),
        # open roots
        (752401, None, 7, "4001-143-99", 30, "OR", "ASS", "314216", 1, 7),
        (752402, None, 7, "4001-142-99", 30, "OR", "ASS", "314216", 2, 7),
        (752403, None, 6, "A2V00002437083", 120, "OR", "WEL", "313313", 1, 12),
        (752404, None, 8, "4004-171-01", 24, "OR", "PAI", "314168", 1, 10),
        (752405, None, 7, "4001-143-99", 20, "ON", "PRO", "314190", 1, 14),
        (752406, None, 5, "04-0000622", 12, "OR", "WEL", "313980", 1, 5),
        # children (subassemblies for the open roots)
        (752411, 752401, 5, "04-0000622", 30, "OR", "WEL", None, None, 4),
        (752412, 752402, 5, "04-0000622", 30, "OR", "WEL", None, None, 4),
        (752413, 752403, 4, "000864901", 240, "OR", "BRA", None, None, 8),
        (752414, 752404, 5, "04-0000622", 24, "OR", "WEL", None, None, 6),
        (752415, 752405, 5, "04-0000622", 20, "ON", "PRO", None, None, 10),
        # grandchildren (component fabrication under the children)
        (752421, 752411, 3, "000864901", 60, "OR", "BRA", None, None, 2),
        (752422, 752412, 3, "000864901", 60, "OR", "BRA", None, None, 2),
        (752423, 752414, 3, "000864901", 48, "ON", "PRO", None, None, 3),
    ]
    item_desc = {code: desc for code, desc, *_ in items}
    add(
        "OMEGA.WORK_ORDERS",
        [
            ("WORK_ORDER_ID", "id"),
            ("PARENT_WORK_ORDER_ID", "id"),
            ("MACHINE_ID", "id"),
            ("WO_NUMBER", "text"),
            ("TITLE", "text"),
            ("WO_TYPE", "text"),
            ("ITEM_NO", "text"),
            ("QTY_ORDERED", "qty"),
            ("QTY_COMPLETED", "qty"),
            ("STATUS", "text"),
            ("PRIORITY", "text"),
            ("CURRENT_OPERATION", "text"),
            ("SALES_ORDER_NO", "text"),
            ("SALES_ORDER_LINE", "int"),
            ("SCHEDULED_DATE", "ts"),
            ("DUE_DATE", "ts"),
            ("COMPLETED_AT", "ts"),
            ("LABOR_HOURS", "num"),
            ("COST_TOTAL", "money"),
            ("IS_CANCELLED", "bool"),
            ("CREATED_AT", "ts"),
            ("LAST_UPDATE_TS", "ts"),
        ],
        [
            {
                "WORK_ORDER_ID": wid,
                "PARENT_WORK_ORDER_ID": parent,
                "MACHINE_ID": machine,
                "WO_NUMBER": str(wid),
                "TITLE": f"{'Make' if status != 'CL' else 'Made'} {item_desc[item]}",
                "WO_TYPE": "production",
                "ITEM_NO": item,
                "QTY_ORDERED": _qty(qty),
                "QTY_COMPLETED": _qty(qty if status == "CL" else 0),
                "STATUS": status,
                "PRIORITY": "100",
                "CURRENT_OPERATION": op,
                "SALES_ORDER_NO": so_no,
                "SALES_ORDER_LINE": so_line,
                "SCHEDULED_DATE": day(due_off - 2),
                "DUE_DATE": day(due_off),
                "COMPLETED_AT": day(due_off) if status == "CL" else None,
                "LABOR_HOURS": _money(qty * 0.4),
                "COST_TOTAL": _money(qty * 31.5),
                "IS_CANCELLED": False,
                "CREATED_AT": created,
                "LAST_UPDATE_TS": ts,
            }
            for wid, parent, machine, item, qty, status, op, so_no, so_line, due_off in wo_rows_spec
        ],
    )

    # ----------------------------------------------------- sales order lines
    # (order, line, customer, item, order_qty, balance, available, unit_price,
    #  wo, due_off)
    so_spec: list[tuple[str, int, int, str, int, int, int, float, int | None, int]] = [
        ("314216", 1, 1, "4001-143-99", 30, 30, 4, 868.01, 752401, 7),
        ("314216", 2, 1, "4001-142-99", 30, 30, 2, 868.01, 752402, 7),
        ("313313", 1, 3, "A2V00002437083", 300, 120, 12, 9.25, 752403, 12),
        ("314168", 1, 2, "4004-171-01", 24, 24, 6, 712.40, 752404, 10),
        ("314190", 1, 4, "4001-143-99", 20, 20, 0, 868.01, 752405, 14),
        ("313980", 1, 5, "04-0000622", 12, 12, 8, 305.00, 752406, 5),
        ("314204", 1, 5, "000864901", 20, 20, 18, 12.90, None, 9),
        ("314225", 1, 2, "80552", 2400, 2400, 2400, 3.15, None, 11),
    ]
    add(
        "OMEGA.SALES_ORDER_LINES",
        [
            ("ORDER_NO", "text"),
            ("LINE_NO", "int"),
            ("CUSTOMER_ID", "id"),
            ("CUSTOMER_PO_NO", "text"),
            ("ITEM_NO", "text"),
            ("ITEM_DESCRIPTION", "text"),
            ("ITEM_TYPE", "text"),
            ("ORDER_QTY", "qty"),
            ("BALANCE_QTY", "qty"),
            ("AVAILABLE_QTY", "qty"),
            ("AMOUNT_USD", "money"),
            ("PRIORITY", "int"),
            ("WORK_ORDER_ID", "id"),
            ("CURRENT_OPERATION", "text"),
            ("ORDER_DATE", "ts"),
            ("DUE_DATE", "ts"),
            ("IS_CANCELLED", "bool"),
            ("LAST_UPDATE_TS", "ts"),
        ],
        [
            {
                "ORDER_NO": order_no,
                "LINE_NO": line_no,
                "CUSTOMER_ID": customer,
                "CUSTOMER_PO_NO": f"CPO-{order_no}-{line_no:03d}",
                "ITEM_NO": item,
                "ITEM_DESCRIPTION": item_desc[item],
                "ITEM_TYPE": "S/M",
                "ORDER_QTY": _qty(order_qty),
                "BALANCE_QTY": _qty(balance),
                "AVAILABLE_QTY": _qty(available),
                "AMOUNT_USD": _money(balance * unit_price),
                "PRIORITY": 100,
                "WORK_ORDER_ID": wo,
                "CURRENT_OPERATION": _OPS if wo else None,
                "ORDER_DATE": created + dt.timedelta(days=3),
                "DUE_DATE": day(due_off),
                "IS_CANCELLED": False,
                "LAST_UPDATE_TS": ts,
            }
            for order_no, line_no, customer, item, order_qty, balance, available, unit_price, wo, due_off in so_spec
        ],
    )

    # ------------------------------------------------------ purchase orders
    po_lines_spec: list[tuple[int, int, str, int, float, int]] = [
        # (po_id, line, item, qty, unit_price, due_off)
        (9001, 1, "10370", 800, 41.80, 3),
        (9001, 2, "10370", 800, 41.80, 10),
        (9001, 3, "10036", 400, 62.30, 9),
        (9002, 1, "80552", 20000, 2.10, 8),
        (9003, 1, "10017", 200, 58.90, 20),  # AL arrives after the horizon
    ]
    item_ids = {code: i + 1 for i, (code, *_rest) in enumerate(items)}
    po_totals: dict[int, Decimal] = {}
    for po_id, _line, _item, qty, price, _off in po_lines_spec:
        po_totals[po_id] = po_totals.get(po_id, Decimal("0")) + _money(qty * price)
    add(
        "OMEGA.PURCHASE_ORDERS",
        [
            ("PO_ID", "id"),
            ("PO_NUMBER", "text"),
            ("SUPPLIER_ID", "id"),
            ("STATUS", "text"),
            ("ORDER_DATE", "ts"),
            ("EXPECTED_DATE", "ts"),
            ("RECEIVED_DATE", "ts"),
            ("TOTAL_AMOUNT", "money"),
            ("CURRENCY_CODE", "text"),
            ("IS_CANCELLED", "bool"),
            ("LAST_UPDATE_TS", "ts"),
        ],
        [
            {
                "PO_ID": po_id,
                "PO_NUMBER": f"PO-{536870 + po_id - 9000}",
                "SUPPLIER_ID": supplier,
                "STATUS": "OPEN",
                "ORDER_DATE": created + dt.timedelta(days=8),
                "EXPECTED_DATE": day(expected_off),
                "RECEIVED_DATE": None,
                "TOTAL_AMOUNT": po_totals[po_id],
                "CURRENCY_CODE": "USD",
                "IS_CANCELLED": False,
                "LAST_UPDATE_TS": ts,
            }
            for po_id, supplier, expected_off in [
                (9001, 1, 3),
                (9002, 3, 8),
                (9003, 2, 20),
            ]
        ],
    )
    add(
        "OMEGA.PURCHASE_ORDER_LINES",
        [
            ("PO_ID", "id"),
            ("LINE_NUMBER", "int"),
            ("ITEM_ID", "id"),
            ("QTY_ORDERED", "qty"),
            ("QTY_RECEIVED", "qty"),
            ("UNIT_PRICE", "qty"),
            ("LINE_AMOUNT", "money"),
            ("ORDER_DATE", "ts"),
            ("LAST_UPDATE_TS", "ts"),
        ],
        [
            {
                "PO_ID": po_id,
                "LINE_NUMBER": line,
                "ITEM_ID": item_ids[item],
                "QTY_ORDERED": _qty(qty),
                "QTY_RECEIVED": _qty(0),
                "UNIT_PRICE": _qty(price),
                "LINE_AMOUNT": _money(qty * price),
                "ORDER_DATE": created + dt.timedelta(days=8),
                "LAST_UPDATE_TS": ts,
            }
            for po_id, line, item, qty, price, due_off in po_lines_spec
        ],
    )

    # ----------------------------------------------------------- MRP pegging
    # Generated from a per-item demand/supply schedule; BALANCE_QTY is the
    # running net so the mart's window-sum provably reproduces the source.
    # Events: (day_offset, source_type, qty, ref) where ref becomes the
    # job/order/po reference for its source type.
    schedule: dict[str, list[tuple[int, str, float, str | None]]] = {
        "4001-143-99": [
            (7, "Sales Order", 30, "314216"),
            (7, "Work Order", 30, "752401"),
            (14, "Sales Order", 20, "314190"),
            (14, "Work Order", 20, "752405"),
        ],
        "4001-142-99": [
            (7, "Sales Order", 30, "314216"),
            (7, "Work Order", 30, "752402"),
        ],
        "A2V00002437083": [
            (12, "Sales Order", 120, "313313"),
            (12, "Work Order", 120, "752403"),
        ],
        "4004-171-01": [
            (10, "Sales Order", 24, "314168"),
            (10, "Work Order", 24, "752404"),
        ],
        # Weldment subassembly: consumed by the root assembly orders
        # (WO Comp. -> pegged to the CONSUMING work order), supplied by its
        # own child work orders.
        "04-0000622": [
            (4, "Work Order", 30, "752411"),
            (4, "Work Order", 30, "752412"),
            (5, "Sales Order", 12, "313980"),
            (5, "Work Order", 12, "752406"),
            (6, "Work Order", 24, "752414"),
            (6, "WO Comp.", 30, "752401"),
            (6, "WO Comp.", 30, "752402"),
            (9, "WO Comp.", 24, "752404"),
            (10, "Work Order", 20, "752415"),
            (13, "WO Comp.", 20, "752405"),
        ],
        # Brackets: consumed by the weldment children, made by grandchildren.
        "000864901": [
            (2, "Work Order", 60, "752421"),
            (2, "Work Order", 60, "752422"),
            (3, "Work Order", 48, "752423"),
            (3, "WO Comp.", 60, "752411"),
            (3, "WO Comp.", 60, "752412"),
            (5, "WO Comp.", 48, "752414"),
            (8, "Work Order", 240, "752413"),
            (9, "Sales Order", 20, "314204"),
            (11, "WO Comp.", 240, "752403"),
        ],
        # Raw sheet: BOM component demand + purchase-order supply. Dips
        # below safety stock (500) before the second receipt lands.
        "10370": [
            (1, "BOM Comp.", 380, "000864901"),
            (2, "BOM Comp.", 320, "000864901"),
            (3, "Purchase Order", 800, "9001"),
            (4, "BOM Comp.", 340, "04-0000622"),
            (6, "BOM Comp.", 420, "04-0000622"),
            (8, "BOM Comp.", 260, "000864901"),
            (10, "Purchase Order", 800, "9001"),
        ],
        "10036": [
            (5, "BOM Comp.", 120, "4004-171-01"),
            (9, "Purchase Order", 400, "9001"),
            (11, "BOM Comp.", 90, "4004-171-01"),
        ],
        "80552": [
            (6, "BOM Comp.", 6000, "A2V00002437083"),
            (8, "Purchase Order", 20000, "9002"),
            (11, "Sales Order", 2400, "314225"),
        ],
        # Aluminum sheet: heavy demand, PO lands after the horizon -> a real
        # shortage the MRP page must surface.
        "10017": [
            (3, "BOM Comp.", 80, "4001-143-99"),
            (6, "BOM Comp.", 90, "4001-142-99"),
            (10, "BOM Comp.", 60, "4001-143-99"),
        ],
    }
    supply_types = {"Work Order", "Purchase Order"}
    on_hand = {row[0]: row[4] for row in items}
    pegging_rows: list[dict[str, Any]] = []
    pegging_id = 0

    def peg_row(**values: Any) -> None:
        nonlocal pegging_id
        pegging_id += 1
        base: dict[str, Any] = {
            "PEGGING_ID": pegging_id,
            "SOURCE_TYPE": None,
            "ITEM_NO": None,
            "DUE_DATE": None,
            "PEGGED_DUE_DATE": None,
            "ORDER_BY_DATE": None,
            "SUPPLY_QTY": None,
            "DEMAND_QTY": None,
            "BALANCE_QTY": None,
            "EXCEPTION_DESC": None,
            "WORK_ORDER_ID": None,
            "PEGGED_WORK_ORDER_ID": None,
            "ORDER_NO": None,
            "PO_NO": None,
            "STATUS": None,
            "PRIORITY": None,
            "LAST_UPDATE_TS": ts,
        }
        base.update(values)
        pegging_rows.append(base)

    for item_code, events in schedule.items():
        balance = float(on_hand[item_code])
        peg_row(
            ITEM_NO=item_code,
            SOURCE_TYPE="On Hand Quantity",
            DUE_DATE=day(0),
            PEGGED_DUE_DATE=day(0),
            BALANCE_QTY=_qty(balance),
        )
        for offset, source_type, event_qty, ref in sorted(events, key=lambda e: e[0]):
            is_supply = source_type in supply_types
            balance += event_qty if is_supply else -event_qty
            peg_row(
                ITEM_NO=item_code,
                SOURCE_TYPE=source_type,
                DUE_DATE=day(offset),
                PEGGED_DUE_DATE=day(offset),
                ORDER_BY_DATE=day(offset - 5) if is_supply else None,
                SUPPLY_QTY=_qty(event_qty) if is_supply else None,
                DEMAND_QTY=None if is_supply else _qty(event_qty),
                BALANCE_QTY=_qty(balance),
                EXCEPTION_DESC="Below Zero" if balance < 0 else None,
                WORK_ORDER_ID=(
                    int(ref) if source_type == "Work Order" and ref else None
                ),
                PEGGED_WORK_ORDER_ID=(
                    int(ref) if source_type == "WO Comp." and ref else None
                ),
                ORDER_NO=ref
                if source_type in ("Sales Order", "WO Comp.", "BOM Comp.")
                else None,
                PO_NO=ref if source_type == "Purchase Order" else None,
                STATUS="OR" if source_type in ("Work Order", "WO Comp.") else None,
                PRIORITY=100 if source_type in ("Work Order", "WO Comp.") else None,
            )
    add(
        "OMEGA.MRP_PEGGING",
        [
            ("PEGGING_ID", "id"),
            ("ITEM_NO", "text"),
            ("SOURCE_TYPE", "text"),
            ("DUE_DATE", "ts"),
            ("PEGGED_DUE_DATE", "ts"),
            ("ORDER_BY_DATE", "ts"),
            ("SUPPLY_QTY", "qty"),
            ("DEMAND_QTY", "qty"),
            ("BALANCE_QTY", "qty"),
            ("EXCEPTION_DESC", "text"),
            ("WORK_ORDER_ID", "id"),
            ("PEGGED_WORK_ORDER_ID", "id"),
            ("ORDER_NO", "text"),
            ("PO_NO", "text"),
            ("STATUS", "text"),
            ("PRIORITY", "int"),
            ("LAST_UPDATE_TS", "ts"),
        ],
        pegging_rows,
    )

    # ------------------------------------------------------ production runs
    add(
        "OMEGA.PRODUCTION_RUNS",
        [
            ("RUN_ID", "id"),
            ("MACHINE_ID", "id"),
            ("JOB_CODE", "text"),
            ("PRODUCT_CODE", "text"),
            ("RUN_DATE", "ts"),
            ("RUN_STARTED_AT", "ts"),
            ("RUN_ENDED_AT", "ts"),
            ("UNITS_PLANNED", "int"),
            ("UNITS_PRODUCED", "int"),
            ("UNITS_SCRAPPED", "int"),
            ("LAST_UPDATE_TS", "ts"),
        ],
        [
            {
                "RUN_ID": 500 + i,
                "MACHINE_ID": (i % 8) + 1,
                "JOB_CODE": f"JOB-{752390 + i}",
                "PRODUCT_CODE": items[i % len(items)][0],
                "RUN_DATE": day(-(i % 7) - 1),
                "RUN_STARTED_AT": day(-(i % 7) - 1) + dt.timedelta(hours=8),
                "RUN_ENDED_AT": day(-(i % 7) - 1) + dt.timedelta(hours=15),
                "UNITS_PLANNED": 60 + i * 3,
                "UNITS_PRODUCED": 58 + i * 3,
                "UNITS_SCRAPPED": i % 3,
                "LAST_UPDATE_TS": ts,
            }
            for i in range(10)
        ],
    )

    # ---------------------------------------------------- telemetry events
    add(
        "OMEGA.TELEMETRY_EVENTS",
        [
            ("EVENT_ID", "id"),
            ("MACHINE_ID", "id"),
            ("EVENT_DATE", "ts"),
            ("EVENT_TS", "ts"),
            ("METRIC_CODE", "text"),
            ("METRIC_VALUE", "qty"),
            ("UNIT", "text"),
        ],
        [
            {
                "EVENT_ID": 10_000 + i,
                "MACHINE_ID": (i % 8) + 1,
                "EVENT_DATE": day(-(i // 24)),
                "EVENT_TS": now - dt.timedelta(hours=i),
                "METRIC_CODE": "temperature_c" if i % 2 == 0 else "vibration_mm_s",
                "METRIC_VALUE": _qty(
                    62.5 + (i % 20) if i % 2 == 0 else 0.18 + (i % 9) * 0.03
                ),
                "UNIT": "C" if i % 2 == 0 else "mm/s",
            }
            for i in range(96)
        ],
    )

    # ------------------------------------------- quality inspections/defects
    add(
        "OMEGA.QUALITY_INSPECTIONS",
        [
            ("INSPECTION_ID", "id"),
            ("RUN_ID", "id"),
            ("MACHINE_ID", "id"),
            ("INSPECTION_DATE", "ts"),
            ("INSPECTED_AT", "ts"),
            ("INSPECTOR_CODE", "text"),
            ("RESULT", "text"),
            ("DEFECT_COUNT", "int"),
            ("LAST_UPDATE_TS", "ts"),
        ],
        [
            {
                "INSPECTION_ID": 700 + i,
                "RUN_ID": 500 + i % 10,
                "MACHINE_ID": (i % 8) + 1,
                "INSPECTION_DATE": day(-(i % 7) - 1),
                "INSPECTED_AT": day(-(i % 7) - 1) + dt.timedelta(hours=16),
                "INSPECTOR_CODE": f"QA-{(i % 3) + 1:02d}",
                "RESULT": "FAIL" if i % 6 == 0 else "PASS",
                "DEFECT_COUNT": 1 if i % 6 == 0 else 0,
                "LAST_UPDATE_TS": ts,
            }
            for i in range(12)
        ],
    )
    add(
        "OMEGA.DEFECTS",
        [
            ("DEFECT_ID", "id"),
            ("INSPECTION_ID", "id"),
            ("MACHINE_ID", "id"),
            ("DEFECT_CODE", "text"),
            ("SEVERITY", "text"),
            ("DETECTED_DATE", "ts"),
            ("DISPOSITION", "text"),
            ("LAST_UPDATE_TS", "ts"),
        ],
        [
            {
                "DEFECT_ID": 800 + i,
                "INSPECTION_ID": 700 + i * 6,
                "MACHINE_ID": (i * 6 % 8) + 1,
                "DEFECT_CODE": code,
                "SEVERITY": severity,
                "DETECTED_DATE": day(-(i * 2) - 1),
                "DISPOSITION": "rework",
                "LAST_UPDATE_TS": ts,
            }
            for i, (code, severity) in enumerate(
                [("BURR", "minor"), ("WELD_POROSITY", "major")]
            )
        ],
    )

    return dataset
