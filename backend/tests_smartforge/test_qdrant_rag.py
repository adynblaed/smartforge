"""Live RAG parity test: Qdrant vector search + real Claude.

Skipped unless BOTH a reachable Qdrant (via QDRANT_URL) and an ANTHROPIC_API_KEY
are present. It seeds a knowledge base containing a fact that exists nowhere else
in the system, then asserts ForgeAI retrieves and answers it correctly 10/10
times — proving the vector store is actually grounding the LLM.

Run locally against the compose stack:

    cd backend && \
      QDRANT_URL=http://localhost:6333 \
      ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
      uv run pytest tests_smartforge/test_qdrant_rag.py -v
"""

import os

import pytest

from app.core.config import settings
from app.core.vectorstore import vector_store

REQUIRED = bool(settings.ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY"))

pytestmark = pytest.mark.skipif(
    not (REQUIRED and vector_store.available),
    reason="requires a reachable Qdrant (QDRANT_URL) and an ANTHROPIC_API_KEY",
)

TOKEN = "ZEPHYR-7741"
FACT = (
    f"The SmartForge calibration token for press-01 is {TOKEN}. "
    "It is rotated every quarter by the maintenance lead."
)


def test_forge_rag_answers_10_of_10(internal_client):
    # Seed a knowledge base — auto-vectorized into Qdrant on create.
    created = internal_client.post(
        "/api/v1/ask-ai/knowledge-bases",
        json={
            "name": "Calibration Registry",
            "description": "Per-machine calibration tokens",
            "content": FACT,
        },
    )
    assert created.status_code == 200
    kb_id = created.json()["id"]

    try:
        # Vector search must surface the chunk for the question.
        hits = vector_store.search("calibration token for press-01")
        assert any(TOKEN in h["text"] for h in hits), "vector search missed the KB"

        correct = 0
        answers: list[str] = []
        for _ in range(10):
            r = internal_client.post(
                "/api/v1/ask-ai/forge",
                json={"question": "What is the calibration token for press-01?"},
            )
            assert r.status_code == 200
            body = r.json()
            answers.append(body["answer"])
            if TOKEN in body["answer"]:
                correct += 1
            # the Forge Fact (knowledge base) must be cited as a source
            assert any(
                s["kind"] in ("forge_fact", "knowledge_base") for s in body["sources"]
            )

        assert correct == 10, (
            f"ForgeAI RAG answered {correct}/10 correctly. "
            f"Sample: {answers[0][:200]!r}"
        )
    finally:
        internal_client.delete(f"/api/v1/ask-ai/knowledge-bases/{kb_id}")
