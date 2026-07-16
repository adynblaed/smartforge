"""Deterministic surrogate identifiers for replicated entities (DCT-011).

Every record imported from the legacy omega source can carry
platform-generated UUIDv5 surrogate keys, declared per contract in
config/tables.yml (`surrogate_uids`). Determinism is the contract:

  * the same source key always yields the same UUID — reseeds, incremental
    merges, and replays are idempotent (INC-004);
  * the UUID is stamped once at extraction time, so the lake and the
    warehouse provably carry identical identifiers because both derive
    from the same publication (SEED-009);
  * cross-table references (e.g. a sales-order line pointing at a work
    order) reproduce the referenced row's UUID by naming the same entity.

The namespace is fixed and versioned with the platform; changing it would
re-key every entity and is a breaking change (API-016).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

# Fixed platform namespace: uuid5 of the platform URN under the standard
# URL namespace. Stable across deployments by construction.
PLATFORM_UID_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://smartforge.futureform/dataplatform"
)


def surrogate_uid(
    source_system: str, entity: str, key_values: Sequence[Any]
) -> str | None:
    """Deterministic UUIDv5 for one entity key, or None for absent keys.

    The canonical name is `<source_system>:<entity>:<v1>|<v2>|...` over the
    stringified key values. Any NULL component makes the whole key absent
    (e.g. a root work order has no parent), mirroring SQL NULL semantics.
    """
    if not key_values or any(v is None for v in key_values):
        return None
    canonical = f"{source_system}:{entity}:" + "|".join(
        str(v).strip() for v in key_values
    )
    return str(uuid.uuid5(PLATFORM_UID_NAMESPACE, canonical))
