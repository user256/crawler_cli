"""Unit tests for the local (sentence-transformers) embedding provider and
hash-gated re-embed (ticket 077).  No model download: the SentenceTransformer
is mocked or a fake encoder is injected.
"""

from __future__ import annotations

import math

import pytest

from crawler_cli import embeddings
from crawler_cli.embeddings import (
    DEFAULT_LOCAL_MODEL,
    MixedModelError,
    ensure_single_model,
    generate_signature_embeddings_for_store,
    make_local_encoder,
)


# --------------------------------------------------------------------------
# Mixed-model guard
# --------------------------------------------------------------------------

def test_ensure_single_model_ok():
    assert ensure_single_model(["m1", "m1"]) == "m1"
    assert ensure_single_model([]) == ""


def test_ensure_single_model_rejects_mixed():
    with pytest.raises(MixedModelError, match="multiple models"):
        ensure_single_model(["m1", "m2"])


# --------------------------------------------------------------------------
# Lazy-import error names the extra
# --------------------------------------------------------------------------

def test_local_encoder_lazy_import_error(monkeypatch):
    def _boom(model, revision):
        raise RuntimeError(
            'sentence-transformers is not installed. Install the local embedding '
            'extra: pip install "crawler-cli[embeddings-local]"'
        )

    monkeypatch.setattr(embeddings, "_load_sentence_transformer", _boom)
    encoder = make_local_encoder("some-model")
    with pytest.raises(RuntimeError, match=r"embeddings-local"):
        encoder(["hello"])


# --------------------------------------------------------------------------
# Normalized output + normalize_embeddings=True passed to the model
# --------------------------------------------------------------------------

class _FakeST:
    def __init__(self):
        self.last_kwargs = None

    def encode(self, texts, **kwargs):
        self.last_kwargs = kwargs
        # Return non-unit vectors; the model is asked to normalize, so we
        # emulate that here to assert unit norm downstream.
        import numpy as np

        raw = np.array([[3.0, 4.0] for _ in texts], dtype=np.float32)
        if kwargs.get("normalize_embeddings"):
            raw = raw / np.linalg.norm(raw, axis=1, keepdims=True)
        return raw


def test_local_encoder_requests_normalization_and_returns_unit_vectors(monkeypatch):
    fake = _FakeST()
    monkeypatch.setattr(embeddings, "_load_sentence_transformer", lambda model, revision: fake)
    encoder = make_local_encoder("m", batch_size=8)
    vecs = encoder(["a", "b"])
    assert fake.last_kwargs["normalize_embeddings"] is True
    assert fake.last_kwargs["batch_size"] == 8
    for v in vecs:
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-5)


# --------------------------------------------------------------------------
# Hash-gated re-embed against a fake store
# --------------------------------------------------------------------------

class FakeEmbStore:
    def __init__(self, sig_rows):
        self._rows = sig_rows
        self.embeddings: dict[int, tuple] = {}

    async def fetch_signature_rows_for_embeddings(self, *, urls=None):
        out = []
        for r in self._rows:
            emb = self.embeddings.get(r["url_id"])
            out.append(
                {
                    **r,
                    "embedded_hash": emb[2] if emb else None,
                    "embedded_model": emb[1] if emb else None,
                }
            )
        return out

    async def store_embedding(self, url_id, vector, *, model, text_length, signature_hash=None):
        self.embeddings[url_id] = (vector, model, signature_hash)


def _unit_encoder(texts):
    return [[1.0, 0.0] for _ in texts]


@pytest.mark.asyncio
async def test_signature_embedding_hash_gating():
    rows = [
        {"url_id": 1, "url": "u1", "text": "alpha", "signature_hash": "h1"},
        {"url_id": 2, "url": "u2", "text": "beta", "signature_hash": "h2"},
    ]
    store = FakeEmbStore(rows)

    first = await generate_signature_embeddings_for_store(store, model="M", encoder=_unit_encoder)
    assert first.processed == 2
    assert first.skipped == 0
    assert store.embeddings[1] == ([1.0, 0.0], "M", "h1")

    # Second run, nothing changed -> zero embeds.
    second = await generate_signature_embeddings_for_store(store, model="M", encoder=_unit_encoder)
    assert second.processed == 0
    assert second.skipped == 2

    # Change page 1's signature -> only that page re-embeds.
    rows[0]["signature_hash"] = "h1b"
    third = await generate_signature_embeddings_for_store(store, model="M", encoder=_unit_encoder)
    assert third.processed == 1
    assert third.skipped == 1
    assert store.embeddings[1][2] == "h1b"


@pytest.mark.asyncio
async def test_signature_embedding_force_reembeds_all():
    rows = [{"url_id": 1, "url": "u1", "text": "alpha", "signature_hash": "h1"}]
    store = FakeEmbStore(rows)
    await generate_signature_embeddings_for_store(store, model="M", encoder=_unit_encoder)
    forced = await generate_signature_embeddings_for_store(
        store, model="M", encoder=_unit_encoder, force=True
    )
    assert forced.processed == 1


@pytest.mark.asyncio
async def test_signature_embedding_switching_model_reembeds():
    rows = [{"url_id": 1, "url": "u1", "text": "alpha", "signature_hash": "h1"}]
    store = FakeEmbStore(rows)
    await generate_signature_embeddings_for_store(store, model="M1", encoder=_unit_encoder)
    # Different model -> not skipped (embedded_model mismatch).
    other = await generate_signature_embeddings_for_store(store, model="M2", encoder=_unit_encoder)
    assert other.processed == 1


@pytest.mark.asyncio
async def test_signature_embedding_skips_pages_without_text():
    rows = [{"url_id": 1, "url": "u1", "text": None, "signature_hash": "h1"}]
    store = FakeEmbStore(rows)
    result = await generate_signature_embeddings_for_store(store, model="M", encoder=_unit_encoder)
    assert result.processed == 0
    assert result.skipped == 1


def test_default_local_model_is_multilingual():
    assert "multilingual" in DEFAULT_LOCAL_MODEL
