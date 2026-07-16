"""verify_read_only: dictionary-based read-only proof (ORA-002/ORA-003).

The verification never executes a probe statement against the source: it
reads session_privs (system ANY-privileges) and all_tab_privs (object-level
grants for USER) and fails closed on any write capability from either set.
"""

from __future__ import annotations

import pytest

from app.dataplatform.oracle.connection import verify_read_only
from tests_dataplatform.conftest import FakeOracleConnection


class TestVerifyReadOnly:
    def test_clean_account_evidence_includes_empty_object_grants(self):
        connection = FakeOracleConnection(
            script=[
                [("CREATE SESSION",), ("SELECT ANY DICTIONARY",)],  # session_privs
                [],  # all_tab_privs
            ]
        )
        evidence = verify_read_only(connection)
        assert evidence["session_privileges"] == [
            "CREATE SESSION",
            "SELECT ANY DICTIONARY",
        ]
        # Backward-compatible keys plus the object-grant evidence set.
        assert evidence["write_privileges_found"] == []
        assert evidence["object_write_grants"] == []

    def test_object_level_write_grants_fail_closed_naming_table_and_privilege(self):
        connection = FakeOracleConnection(
            script=[
                [("CREATE SESSION",)],
                [("PURCHASE_ORDERS", "UPDATE"), ("MACHINES", "DELETE")],
            ]
        )
        with pytest.raises(PermissionError) as excinfo:
            verify_read_only(connection)
        message = str(excinfo.value)
        assert "PURCHASE_ORDERS:UPDATE" in message
        assert "MACHINES:DELETE" in message
        assert "ORA-002/ORA-003" in message

    def test_system_any_write_privileges_still_fail_closed(self):
        connection = FakeOracleConnection(
            script=[
                [("CREATE SESSION",), ("INSERT ANY TABLE",)],
                [],
            ]
        )
        with pytest.raises(PermissionError, match="INSERT ANY TABLE"):
            verify_read_only(connection)

    def test_object_grant_query_is_static_and_scoped_to_current_user(self):
        connection = FakeOracleConnection(script=[[("CREATE SESSION",)], []])
        verify_read_only(connection)
        executed = connection.cursor().executed
        sqls = [sql for sql, _binds in executed]
        assert any("session_privs" in sql for sql in sqls)
        grant_sql = next(sql for sql in sqls if "all_tab_privs" in sql)
        assert "grantee = USER" in grant_sql  # static, no interpolation
        for privilege in (
            "'INSERT'",
            "'UPDATE'",
            "'DELETE'",
            "'ALTER'",
            "'INDEX'",
            "'REFERENCES'",
        ):
            assert privilege in grant_sql
