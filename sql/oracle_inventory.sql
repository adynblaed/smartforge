-- =============================================================================
-- Omega (Oracle) source discovery queries (Specs §7 Phase 0)
-- Run with the READ-ONLY extraction account. These are the same queries the
-- automated discovery uses (app.dataplatform.oracle.metadata); keep in sync.
-- =============================================================================

-- Column inventory for approved schemas
SELECT
    c.owner,
    c.table_name,
    c.column_id,
    c.column_name,
    c.data_type,
    c.data_length,
    c.data_precision,
    c.data_scale,
    c.nullable,
    c.char_used,
    c.char_length
FROM all_tab_columns c
WHERE c.owner IN ('OMEGA')
ORDER BY c.owner, c.table_name, c.column_id;

-- Primary keys
SELECT
    con.owner,
    con.table_name,
    cols.column_name,
    cols.position
FROM all_constraints con
JOIN all_cons_columns cols
  ON cols.owner = con.owner
 AND cols.constraint_name = con.constraint_name
WHERE con.constraint_type = 'P'
  AND con.owner = 'OMEGA'
ORDER BY con.table_name, cols.position;

-- Size and row estimates
SELECT owner, table_name, num_rows, blocks * 8 / 1024 AS approx_mb, last_analyzed
FROM all_tables
WHERE owner = 'OMEGA'
ORDER BY num_rows DESC NULLS LAST;

-- Candidate cursor columns
SELECT owner, table_name, column_name, data_type
FROM all_tab_columns
WHERE owner = 'OMEGA'
  AND (column_name LIKE '%UPDATE%' OR column_name LIKE '%MODIFIED%'
       OR column_name LIKE '%CHANGE%' OR column_name LIKE '%CREATED%'
       OR column_name IN ('ROW_VERSION', 'VERSION_NUMBER', 'EVENT_ID'))
ORDER BY owner, table_name, column_name;

-- Current SCN (seed boundary, SEED-002)
SELECT current_scn FROM v$database;
-- Fallback when V$DATABASE is not granted:
-- SELECT dbms_flashback.get_system_change_number FROM dual;

-- Verify the account is read-only (ORA-002)
SELECT * FROM session_privs ORDER BY privilege;
