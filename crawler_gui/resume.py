"""Resume an existing run from its saved scope; invoked only by an explicit GUI action."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import fields

from crawler_cli.config import CrawlConfig
from crawler_cli.engine import CrawlEngine, _crawl_run_config_hash, _crawl_run_config_snapshot
from crawler_cli.persistence import AsyncpgStore


def resume_configuration(row, backend=None):
    saved = json.loads(row["config_json"])
    seeds = json.loads(row["seed_urls_json"])
    if saved.get("authorization_scope") or saved.get("portal_connection_policy"):
        raise ValueError("This run uses a scope manifest or Portal policy. Resume it with the CLI and its original policy.")
    names = {item.name for item in fields(CrawlConfig)}
    values = {key: value for key, value in saved.items() if key in names and key != "portal_connection_policy"}
    for candidate in ([backend] if backend else ["aiohttp", "curl_cffi", "playwright"]):
        config = CrawlConfig(**values, backend=candidate)
        if row["config_hash"] and _crawl_run_config_hash(_crawl_run_config_snapshot(config, seeds)) == row["config_hash"]:
            return config, seeds
    raise ValueError("The saved crawl scope cannot be reconstructed safely with this backend. Use CLI resume with the original configuration.")


async def run(payload):
    store = AsyncpgStore(payload["dsn"])
    await store.connect()
    engine = None
    try:
        async with store.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM crawl_runs WHERE run_id=$1", payload["runId"])
            count = await conn.fetchval("SELECT count(*) FROM frontier WHERE run_id=$1 AND status IN ('queued','pending')", payload["runId"])
        if not row or not count:
            raise ValueError("No queued or pending URLs remain for this run.")
        config, seeds = resume_configuration(row, payload["backend"])
        config.max_concurrency = payload["concurrency"]
        engine = CrawlEngine(config, store=store)
        result = await engine.crawl_open(seeds, run_id=payload["runId"], resume=True, max_urls=payload["maxPages"])
        print(f"Resume finished: {result.crawled_count} URLs crawled", flush=True)
    finally:
        if engine is not None:
            await engine.close()
        await store.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(json.load(sys.stdin)))
