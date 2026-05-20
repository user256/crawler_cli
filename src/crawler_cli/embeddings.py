from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

from .persistence import AsyncpgStore


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
