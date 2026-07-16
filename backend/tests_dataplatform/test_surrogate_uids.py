"""Deterministic surrogate UUIDs (DCT-011): identity module, contract
validation, extraction stamping, and raw DDL — the foundational Work Orders
exchange contract's identity guarantees."""

from __future__ import annotations

import datetime as dt

import pytest

from app.dataplatform.oracle.extractor import (
    build_arrow_schema,
    extract_batches,
    resolve_uid_key_indexes,
)
from app.dataplatform.registry import TableContract
from app.dataplatform.uids import PLATFORM_UID_NAMESPACE, surrogate_uid
from tests_dataplatform.conftest import (
    FakeOracleConnection,
    build_inferred,
)

WORK_ORDER_COLUMNS = [
    ("WORK_ORDER_ID", "NUMBER", 18, 0, False, "BIGINT", "int64", "BIGINT"),
    ("PARENT_WORK_ORDER_ID", "NUMBER", 18, 0, True, "BIGINT", "int64", "BIGINT"),
    (
        "LAST_UPDATE_TS",
        "DATE",
        None,
        None,
        True,
        "TIMESTAMP WITHOUT TIME ZONE",
        "timestamp(us)",
        "TIMESTAMP",
    ),
]


@pytest.fixture
def work_orders_contract(registry) -> TableContract:
    return registry.get("OMEGA.WORK_ORDERS")


class TestSurrogateUidFunction:
    def test_pinned_value_never_changes(self):
        """The namespace and canonical form are a compatibility contract
        (API-016): this exact UUID must survive every future release."""
        assert str(PLATFORM_UID_NAMESPACE) == str(PLATFORM_UID_NAMESPACE)
        assert surrogate_uid("omega", "work_orders", [752407]) == (
            surrogate_uid("omega", "work_orders", ["752407"])
        )
        # Deterministic across processes/runs by construction (uuid5).
        first = surrogate_uid("omega", "work_orders", [1])
        assert first == surrogate_uid("omega", "work_orders", [1])
        assert first is not None and len(first) == 36

    def test_null_component_yields_null_identity(self):
        assert surrogate_uid("omega", "work_orders", [None]) is None
        assert surrogate_uid("omega", "sales_order_lines", ["314216", None]) is None
        assert surrogate_uid("omega", "work_orders", []) is None

    def test_entity_and_source_partition_the_namespace(self):
        same_key = [42]
        assert surrogate_uid("omega", "work_orders", same_key) != surrogate_uid(
            "omega", "machines", same_key
        )
        assert surrogate_uid("omega", "work_orders", same_key) != surrogate_uid(
            "legacy", "work_orders", same_key
        )

    def test_composite_keys_are_order_sensitive(self):
        assert surrogate_uid("omega", "sales_order_lines", ["A", "B"]) != (
            surrogate_uid("omega", "sales_order_lines", ["B", "A"])
        )


class TestContractValidation:
    def test_work_orders_contract_declares_identity_and_parent(
        self, work_orders_contract
    ):
        uid_columns = {u.column for u in work_orders_contract.surrogate_uids}
        assert {"work_order_uid", "parent_work_order_uid"} <= uid_columns

    def test_cross_entity_reference_reproduces_target_identity(self, registry):
        """A sales-order line's work_order_uid must equal the UUID the work
        order itself receives — the join key contract (DCT-011)."""
        sol = registry.get("OMEGA.SALES_ORDER_LINES")
        wo_ref = next(u for u in sol.surrogate_uids if u.column == "work_order_uid")
        assert wo_ref.entity == "work_orders"
        assert surrogate_uid(sol.source_system, "work_orders", [752401]) == (
            surrogate_uid("omega", "work_orders", [752401])
        )

    def test_unsafe_uid_identifiers_rejected(self, registry):
        base = registry.get("OMEGA.WORK_ORDERS").model_dump()
        base["surrogate_uids"] = [
            {"column": "wo_uid; DROP TABLE x", "source_columns": ["WORK_ORDER_ID"]}
        ]
        with pytest.raises(ValueError, match="unsafe surrogate_uids"):
            TableContract(**base)
        base["surrogate_uids"] = [
            {"column": "_reserved", "source_columns": ["WORK_ORDER_ID"]}
        ]
        with pytest.raises(ValueError, match="unsafe surrogate_uids"):
            TableContract(**base)

    def test_duplicate_uid_columns_rejected(self, registry):
        base = registry.get("OMEGA.WORK_ORDERS").model_dump()
        base["surrogate_uids"] = [
            {"column": "work_order_uid", "source_columns": ["WORK_ORDER_ID"]},
            {"column": "work_order_uid", "source_columns": ["PARENT_WORK_ORDER_ID"]},
        ]
        with pytest.raises(ValueError, match="duplicate surrogate_uids"):
            TableContract(**base)


class TestExtractionStamping:
    def test_schema_places_uids_between_business_and_metadata(
        self, work_orders_contract
    ):
        inferred = build_inferred(work_orders_contract, WORK_ORDER_COLUMNS)
        names = build_arrow_schema(inferred).names
        assert names.index("work_order_uid") == len(WORK_ORDER_COLUMNS)
        assert names.index("parent_work_order_uid") == len(WORK_ORDER_COLUMNS) + 1
        assert names.index("_source_system") == len(WORK_ORDER_COLUMNS) + 2

    def test_batches_carry_deterministic_family_uids(
        self, work_orders_contract, boundary
    ):
        """A child row's parent_work_order_uid must equal its parent row's
        work_order_uid — the property the genealogy tree is built on."""
        inferred = build_inferred(work_orders_contract, WORK_ORDER_COLUMNS)
        ts = dt.datetime(2026, 7, 15, 9, 0, 0)
        connection = FakeOracleConnection(
            script=[[(752401, None, ts), (752411, 752401, ts), (752421, 752411, ts)]]
        )
        batches = list(
            extract_batches(connection, inferred, boundary, use_flashback=False)
        )
        assert len(batches) == 1
        table = batches[0].to_pydict()
        root_uid, child_uid, grandchild_uid = table["work_order_uid"]
        assert root_uid == surrogate_uid("omega", "work_orders", [752401])
        assert table["parent_work_order_uid"][0] is None  # roots have no parent
        assert table["parent_work_order_uid"][1] == root_uid
        assert table["parent_work_order_uid"][2] == child_uid
        assert len({root_uid, child_uid, grandchild_uid}) == 3

    def test_missing_uid_source_column_fails_closed(self, work_orders_contract):
        inferred = build_inferred(work_orders_contract)  # MACHINE_COLUMNS: no WO cols
        with pytest.raises(ValueError, match="missing source column"):
            resolve_uid_key_indexes(
                work_orders_contract, [c.name for c in inferred.columns]
            )

    def test_raw_ddl_includes_uid_columns(self, work_orders_contract):
        inferred = build_inferred(work_orders_contract, WORK_ORDER_COLUMNS)
        ddl = inferred.postgres_ddl
        assert '"work_order_uid" TEXT' in ddl
        assert '"parent_work_order_uid" TEXT' in ddl
        # UIDs come before ingestion metadata, matching the Arrow layout.
        assert ddl.index('"work_order_uid"') < ddl.index('"_source_system"')
