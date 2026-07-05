from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

from .persistence import AsyncpgStore

# Default local (sentence-transformers) model — multilingual, essential for the
# casino.org 350-locale portfolio (intent_overlap.py embed() default).
DEFAULT_LOCAL_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_OPENAI_MODEL = "text-embedding-3-small"

# A local encoder maps a batch of texts to normalized float32 vectors.
LocalEncoder = Callable[[Sequence[str]], list[list[float]]]


def clean_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


async def generate_embedding(
    text: str,
    *,
    api_key: str,
    model: str = "text-embedding-3-small",
    session: aiohttp.ClientSession | None = None,
) -> list[float] | None:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "input": text, "encoding_format": "float"}
    owns_session = session is None
    if owns_session:
        session = aiohttp.ClientSession()
    try:
        async with session.post(
            "https://api.openai.com/v1/embeddings",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as response:
            response.raise_for_status()
            body = await response.json()
    finally:
        if owns_session and session is not None:
            await session.close()
    data = body.get("data") or []
    if not data:
        return None
    return list(data[0]["embedding"])


@dataclass(slots=True)
class EmbeddingJobResult:
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class MixedModelError(RuntimeError):
    """Raised when embeddings in a store span more than one model — cosine
    similarity is only meaningful within a single model (ticket 077 guard,
    enforced by analyse in ticket 079)."""


def ensure_single_model(models: Sequence[str]) -> str:
    """Return the single embedding model or raise :class:`MixedModelError`."""
    distinct = sorted({m for m in models if m})
    if len(distinct) > 1:
        raise MixedModelError(
            "page_embeddings contains multiple models "
            f"({', '.join(distinct)}); re-embed with a single model or filter by one. "
            "Cosine similarity is only comparable within one model."
        )
    return distinct[0] if distinct else ""


def _load_sentence_transformer(model: str, revision: str | None) -> Any:
    """Import sentence-transformers lazily; raise a clear error naming the
    extra if it is missing.  Separated so tests can monkeypatch it."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise RuntimeError(
            "sentence-transformers is not installed. Install the local embedding "
            'extra: pip install "crawler-cli[embeddings-local]"'
        ) from exc
    kwargs = {"revision": revision} if revision else {}
    return SentenceTransformer(model, **kwargs)


def make_local_encoder(
    model: str = DEFAULT_LOCAL_MODEL,
    *,
    revision: str | None = None,
    batch_size: int = 64,
) -> LocalEncoder:
    """Build a local encoder using sentence-transformers with
    ``normalize_embeddings=True`` so cosine reduces to dot product downstream
    (intent_overlap.py embed()).  The model is loaded lazily on first call."""
    import numpy as np

    st_model: Any = None

    def encode(texts: Sequence[str]) -> list[list[float]]:
        nonlocal st_model
        if st_model is None:
            st_model = _load_sentence_transformer(model, revision)
        vecs = st_model.encode(list(texts), batch_size=batch_size, normalize_embeddings=True)
        arr = np.asarray(vecs, dtype=np.float32)
        return [row.tolist() for row in arr]

    return encode


async def generate_signature_embeddings_for_store(
    store: AsyncpgStore,
    *,
    model: str = DEFAULT_LOCAL_MODEL,
    encoder: LocalEncoder | None = None,
    revision: str | None = None,
    batch_size: int = 64,
    force: bool = False,
    urls: list[str] | None = None,
    source: str = "signature",
) -> EmbeddingJobResult:
    """Embed ticket-076 intent signatures with a local model, skipping pages
    whose ``signature_hash`` and ``model`` already match a stored embedding
    (ticket 077 hash gating).

    ``source="signature"`` embeds the stored signature input; ``"page-text"``
    embeds cleaned HTML (no hash gating, url_id+model skip only).
    """
    result = EmbeddingJobResult()

    if source == "signature":
        rows = await store.fetch_signature_rows_for_embeddings(urls=urls)
    else:
        pages = await store.fetch_pages_for_embeddings(urls=urls)
        rows = [
            {
                "url_id": uid,
                "url": url,
                "text": clean_text_from_html(html),
                "signature_hash": None,
                "embedded_hash": None,
                "embedded_model": model if not force else None,
            }
            for uid, url, html in pages
        ]

    to_embed: list[dict[str, Any]] = []
    for row in rows:
        text = row.get("text")
        if not text:
            result.skipped += 1
            continue
        if not force and source == "signature":
            same_model = row.get("embedded_model") == model
            same_hash = row.get("signature_hash") is not None and row.get("embedded_hash") == row.get("signature_hash")
            if same_model and same_hash:
                result.skipped += 1
                continue
        elif not force and row.get("embedded_model") == model:
            result.skipped += 1
            continue
        to_embed.append(row)

    if not to_embed:
        return result

    if encoder is None:
        encoder = make_local_encoder(model, revision=revision, batch_size=batch_size)

    texts = [str(row["text"]) for row in to_embed]
    try:
        vectors = encoder(texts)
    except Exception as exc:  # noqa: BLE001 - surface a clean job error
        result.failed += len(to_embed)
        result.errors.append(str(exc))
        return result

    for row, vector in zip(to_embed, vectors):
        try:
            await store.store_embedding(
                int(row["url_id"]),
                vector,
                model=model,
                text_length=len(str(row["text"])),
                signature_hash=row.get("signature_hash"),
            )
            result.processed += 1
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            result.errors.append(f"url_id={row.get('url_id')}: {exc}")
    return result


async def generate_embeddings_for_store(
    store: AsyncpgStore,
    *,
    api_key: str,
    model: str = "text-embedding-3-small",
    batch_size: int = 10,
    delay_seconds: float = 1.0,
    skip_existing: bool = True,
    urls: list[str] | None = None,
) -> EmbeddingJobResult:
    pages = await store.fetch_pages_for_embeddings(urls=urls)
    existing_ids: set[int] = set()
    if skip_existing:
        existing_ids = await store.embedding_url_ids(model=model)

    result = EmbeddingJobResult()
    async with aiohttp.ClientSession() as session:
        batch: list[tuple[int, str, str]] = []
        for url_id, url, html in pages:
            if skip_existing and url_id in existing_ids:
                result.skipped += 1
                continue
            text = clean_text_from_html(html)
            if not text:
                result.skipped += 1
                continue
            batch.append((url_id, url, text))
            if len(batch) < batch_size:
                continue
            await _process_embedding_batch(
                store,
                batch,
                api_key=api_key,
                model=model,
                session=session,
                result=result,
            )
            batch = []
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
        if batch:
            await _process_embedding_batch(
                store,
                batch,
                api_key=api_key,
                model=model,
                session=session,
                result=result,
            )
    return result


async def _process_embedding_batch(
    store: AsyncpgStore,
    batch: list[tuple[int, str, str]],
    *,
    api_key: str,
    model: str,
    session: aiohttp.ClientSession,
    result: EmbeddingJobResult,
) -> None:
    for url_id, _url, text in batch:
        try:
            embedding = await generate_embedding(
                text,
                api_key=api_key,
                model=model,
                session=session,
            )
            if embedding is None:
                result.failed += 1
                result.errors.append(f"no embedding returned for url_id={url_id}")
                continue
            await store.store_embedding(url_id, embedding, model=model, text_length=len(text))
            result.processed += 1
        except Exception as exc:
            result.failed += 1
            result.errors.append(f"url_id={url_id}: {exc}")
