"""Qdrant-backed vector store for knowledge-base RAG.

Embeddings + reranking are produced locally with FastEmbed; vectors live in
Qdrant. Everything degrades gracefully: if Qdrant or the models are unavailable
(e.g. CI with no vector service), every public function becomes a no-op /
empty result and the caller falls back to keyword retrieval.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

from app.core.config import settings

logger = logging.getLogger("smartforge.vectorstore")

_NAMESPACE = uuid.UUID("5f9b2c1a-1d3e-4a6b-9c8d-0e1f2a3b4c5d")


def _chunk(text: str, size: int = 800, overlap: int = 120) -> list[str]:
    """Split text into overlapping chunks on paragraph/whitespace boundaries."""
    text = (text or "").strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paragraphs:
        if len(buf) + len(p) + 2 <= size:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            if len(p) <= size:
                buf = p
            else:
                # hard-split an oversized paragraph
                for i in range(0, len(p), size - overlap):
                    chunks.append(p[i : i + size])
                buf = ""
    if buf:
        chunks.append(buf)
    return chunks


class _VectorStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._client: Any = None
        self._embed: Any = None
        self._reranker: Any = None
        self._dim: int | None = None
        self._state: bool | None = None  # None=untried, True/False=result

    # -- lazy initialisation -------------------------------------------------

    def _init(self) -> bool:
        if self._state is not None:
            return self._state
        with self._lock:
            if self._state is not None:
                return self._state
            if not settings.RAG_ENABLED:
                self._state = False
                return False
            try:
                from qdrant_client import QdrantClient
                from qdrant_client.models import Distance, VectorParams

                self._client = QdrantClient(
                    url=settings.QDRANT_URL,
                    api_key=settings.QDRANT_API_KEY,
                    timeout=10,
                )
                # Cheap connectivity probe FIRST — avoids downloading the embed
                # model when Qdrant is offline (CI / local without the service).
                existing = {c.name for c in self._client.get_collections().collections}

                from fastembed import TextEmbedding

                self._embed = TextEmbedding(model_name=settings.EMBED_MODEL)
                probe = next(iter(self._embed.embed(["dimension probe"])))
                self._dim = len(probe)
                if settings.QDRANT_COLLECTION not in existing:
                    self._client.create_collection(
                        collection_name=settings.QDRANT_COLLECTION,
                        vectors_config=VectorParams(
                            size=self._dim, distance=Distance.COSINE
                        ),
                    )
                self._state = True
                logger.info(
                    "Vector store ready (qdrant=%s, model=%s, dim=%s)",
                    settings.QDRANT_URL, settings.EMBED_MODEL, self._dim,
                )
            except Exception as exc:  # noqa: BLE001 — degrade gracefully
                logger.warning("Vector store unavailable, falling back: %s", exc)
                self._state = False
        return self._state

    @property
    def available(self) -> bool:
        return self._init()

    def _reranker_model(self) -> Any:
        if not settings.RAG_RERANK:
            return None
        if self._reranker is None:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                self._reranker = TextCrossEncoder(model_name=settings.RERANK_MODEL)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Reranker unavailable: %s", exc)
                self._reranker = False
        return self._reranker or None

    def _embed_one(self, text: str) -> list[float]:
        return list(map(float, next(iter(self._embed.embed([text])))))

    # -- write paths ---------------------------------------------------------

    def reset(self) -> bool:
        """Drop + recreate the collection so a full re-index leaves no stale
        points (e.g. payloads from an older schema). No-op when unavailable."""
        if not self.available:
            return False
        try:
            from qdrant_client.models import Distance, VectorParams

            self._client.delete_collection(settings.QDRANT_COLLECTION)
            self._client.create_collection(
                collection_name=settings.QDRANT_COLLECTION,
                vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("reset failed: %s", exc)
            return False

    def _upsert_chunks(
        self, doc_id: str, chunks: list[tuple[str, dict[str, Any]]]
    ) -> int:
        """Embed + store (text, payload) chunks under a single document id."""
        from qdrant_client.models import PointStruct

        if not chunks:
            return 0
        texts = [c[0] for c in chunks]
        vectors = [list(map(float, v)) for v in self._embed.embed(texts)]
        points = [
            PointStruct(
                id=str(uuid.uuid5(_NAMESPACE, f"{doc_id}:{i}")),
                vector=vectors[i],
                payload={"doc_id": doc_id, "text": texts[i], **chunks[i][1]},
            )
            for i in range(len(chunks))
        ]
        self._client.upsert(
            collection_name=settings.QDRANT_COLLECTION, wait=True, points=points
        )
        return len(points)

    def upsert_kb(self, kb_id: uuid.UUID | str, name: str, content: str) -> int:
        """(Re)vectorize a Forge Fact (knowledge base). Returns chunks stored."""
        if not self.available:
            return 0
        try:
            doc = str(kb_id)
            self.delete_doc(doc)
            chunks = [
                (c, {"kind": "forge_fact", "name": name, "code": doc})
                for c in _chunk(content)
            ]
            return self._upsert_chunks(doc, chunks)
        except Exception as exc:  # noqa: BLE001
            logger.warning("upsert_kb failed: %s", exc)
            return 0

    def upsert_sop(
        self,
        sop_id: uuid.UUID | str,
        code: str,
        title: str,
        sections: list[tuple[str, str, str]],
    ) -> int:
        """(Re)vectorize an SOP. ``sections`` is a list of (anchor, title, body).

        Each section is embedded as its own chunk so retrieval can deep-link to
        the exact chapter (e.g. SOP-CNC-001 §4 Spindle Bearing Service)."""
        if not self.available:
            return 0
        try:
            doc = str(sop_id)
            self.delete_doc(doc)
            chunks: list[tuple[str, dict[str, Any]]] = []
            for anchor, sec_title, body in sections:
                # Prefix the SOP + section identity so semantic match is strong
                # even on terse section bodies.
                text = f"{code} — {title}\n{sec_title}\n{body}"
                chunks.append(
                    (
                        text,
                        {
                            "kind": "sop",
                            "name": title,
                            "code": code,
                            "anchor": anchor,
                            "section_title": sec_title,
                        },
                    )
                )
            return self._upsert_chunks(doc, chunks)
        except Exception as exc:  # noqa: BLE001
            logger.warning("upsert_sop failed: %s", exc)
            return 0

    def delete_doc(self, doc_id: uuid.UUID | str) -> None:
        if not self.available:
            return
        try:
            from qdrant_client.models import (
                FieldCondition,
                Filter,
                FilterSelector,
                MatchValue,
            )

            self._client.delete(
                collection_name=settings.QDRANT_COLLECTION,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[
                            FieldCondition(
                                key="doc_id", match=MatchValue(value=str(doc_id))
                            )
                        ]
                    )
                ),
                wait=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("delete_doc failed: %s", exc)

    # Back-compat alias (older call sites).
    def delete_kb(self, kb_id: uuid.UUID | str) -> None:
        self.delete_doc(kb_id)

    # -- read path -----------------------------------------------------------

    def search(
        self, query: str, *, kind: str | None = None, top_k: int | None = None
    ) -> list[dict[str, Any]]:
        """Semantic search (+ optional cross-encoder rerank), optionally scoped
        to a single payload ``kind`` ("sop" / "forge_fact")."""
        if not self.available or not (query or "").strip():
            return []
        top_k = top_k or settings.RAG_TOP_K
        try:
            query_filter = None
            if kind:
                from qdrant_client.models import (
                    FieldCondition,
                    Filter,
                    MatchValue,
                )

                query_filter = Filter(
                    must=[FieldCondition(key="kind", match=MatchValue(value=kind))]
                )
            hits = self._client.query_points(
                collection_name=settings.QDRANT_COLLECTION,
                query=self._embed_one(query),
                query_filter=query_filter,
                with_payload=True,
                limit=settings.RAG_CANDIDATES,
            ).points
            results = [
                {
                    "text": h.payload.get("text", ""),
                    "name": h.payload.get("name", ""),
                    "kind": h.payload.get("kind", "forge_fact"),
                    "code": h.payload.get("code", ""),
                    "anchor": h.payload.get("anchor"),
                    "section_title": h.payload.get("section_title"),
                    "doc_id": h.payload.get("doc_id", ""),
                    # legacy key for any older callers
                    "kb_id": h.payload.get("doc_id", ""),
                    "score": float(h.score),
                }
                for h in hits
                if h.payload
            ]
            if not results:
                return []

            reranker = self._reranker_model()
            if reranker is not None and len(results) > 1:
                try:
                    scores = list(reranker.rerank(query, [r["text"] for r in results]))
                    for r, s in zip(results, scores, strict=False):
                        r["score"] = float(s)
                    results.sort(key=lambda r: r["score"], reverse=True)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("rerank failed, using vector order: %s", exc)

            return results[:top_k]
        except Exception as exc:  # noqa: BLE001
            logger.warning("search failed: %s", exc)
            return []


vector_store = _VectorStore()
