"""PostgreSQL warehouse: role-scoped engines, bootstrap, and raw loading.

Identity separation is enforced (IAM-003/PG-001): the loader writes
control/raw/audit, dbt transforms, and the API reads marts read-only.
"""
