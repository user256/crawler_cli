from __future__ import annotations

import asyncio
import asyncpg
import json
import time
from collections.abc import Sequence
from typing import Any, TypedDict, cast
from urllib.parse import urlparse

from .amp import VARIANT_KIND_AMP, classify_amp_variants, urls_match
from .compression import compress_html, decompress_html, is_compressed
from .detection.analytics import AnalyticsDetectionResult
from .hashing import sha256_hash, simhash64, simhash_to_signed, simhash_to_unsigned
from .models import CrawlResult, DiscoveredLink
from .schema import create_schema_content_hash, identify_schema_relationships


# --- Query-row schemas (ticket 083) -----------------------------------------
# TypedDicts for the rows the intent-overlap query helpers return/consume,
# keyed by the actual SELECT column aliases.  These replace the
# ``list[dict[str, Any]]`` returns so mypy checks the column names/types again
# (persistence.py is deliberately outside the mypy ignore blanket — ticket 070).
# Nullability follows the schema and the LEFT JOINs: a column reached through a
# LEFT JOIN can be NULL even when its table declares it NOT NULL.


class SignatureEmbeddingRow(TypedDict):
    url_id: int
    url: str
    text: str | None
    signature_hash: str | None
    embedded_hash: str | None
    embedded_model: str | None


class SignaturePageRow(TypedDict):
    url_id: int
    url: str
    html: str
    title: str | None
    h1: str | None
    meta_description: str | None


class IntentSignatureRow(TypedDict):
    url_id: int
    main_text: str | None
    extraction_method: str | None
    signal_confidence: str | None
    signature_hash: str | None
    signature_model_input: str | None


class IdentityPageRow(TypedDict):
    url_id: int
    url: str
    html_lang: str | None
    status: int | None
    word_count: int | None
    final_url: str | None


class HreflangIdentityRow(TypedDict):
    url_id: int
    norm_url: str | None
    hreflang_group: str | None
    resolved_hreflang_code: str | None
    lang_bucket: str | None


class UrlVariantRow(TypedDict):
    url: str
    norm_url: str
    representative: str | None


class AnalysisRow(TypedDict):
    url_id: int
    url: str
    kind: str | None
    norm_url: str | None
    hreflang_group: str | None
    hreflang_code: str | None
    variant_of: str | None
    status: int | None
    title: str | None
    h1: str | None
    word_count: int | None
    main_text: str | None
    overall_indexable: bool | None
    signal_confidence: str | None
    extraction_method: str | None
    signature_model_input: str | None
    embedding: list[float] | None
    embedding_model: str | None
    canonical_url: str | None
    signature_hash: str | None
    variant_kind: str | None


class AmpHygieneRow(TypedDict):
    """One AMP variant's canonical-hygiene status (ticket 103), for
    ``amp_issues.csv``.  ``base_url`` is the paired non-AMP page when known
    (from ``rel="amphtml"`` or the URL shape); ``issue`` is empty for a healthy
    AMP page that canonicals to its base."""

    url: str
    base_url: str
    variant_kind: str
    confirmed_by: str
    canonical_url: str
    has_canonical: bool
    issue: str


DEFAULT_CRAWL_RUN_ID = "legacy"


class CrawlRunRecord(TypedDict):
    run_id: str
    mode: str
    status: str
    seed_urls: list[str]
    config_hash: str
    config: dict[str, Any]
    created_at: int
    updated_at: int


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS urls (
        id SERIAL PRIMARY KEY,
        url TEXT UNIQUE NOT NULL,
        kind TEXT CHECK (kind IN ('html','sitemap','sitemap_index','image','asset','other')),
        classification TEXT CHECK (classification IN ('internal','subdomain','network','external','social')),
        discovered_from_id INTEGER,
        is_from_sitemap BOOLEAN DEFAULT FALSE,
        is_from_hreflang BOOLEAN DEFAULT FALSE,
        first_seen INTEGER,
        last_seen INTEGER,
        headers_compressed BYTEA,
        FOREIGN KEY (discovered_from_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pages (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL UNIQUE,
        headers_json TEXT,
        html_compressed BYTEA,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS html_languages (
        id SERIAL PRIMARY KEY,
        language_code TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meta_descriptions (
        id SERIAL PRIMARY KEY,
        description TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS content (
        url_id INTEGER PRIMARY KEY,
        title TEXT,
        meta_description_id INTEGER,
        h1_tags TEXT,
        h2_tags TEXT,
        word_count INTEGER,
        html_lang_id INTEGER,
        content_length INTEGER,
        content_hash_sha256 TEXT,
        content_hash_simhash BIGINT,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (meta_description_id) REFERENCES meta_descriptions (id),
        FOREIGN KEY (html_lang_id) REFERENCES html_languages (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS robots_directive_strings (
        id SERIAL PRIMARY KEY,
        directive TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS robots_directives (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        source TEXT CHECK (source IN ('html_meta', 'http_header')) NOT NULL,
        directive_id INTEGER NOT NULL,
        value TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (directive_id) REFERENCES robots_directive_strings (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_urls (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        canonical_url_id INTEGER NOT NULL,
        source TEXT CHECK (source IN ('html_head', 'http_header')) NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (canonical_url_id) REFERENCES urls (id)
    )
    """,
    # ticket 103: the page->AMP edge from <link rel="amphtml">, mirroring
    # canonical_urls.  url_id is the base page, amphtml_url_id its declared AMP
    # variant.  rel="amphtml" is an HTML-head-only signal, hence source fixed to
    # 'html_head' (kept as a column for symmetry / future header sources).
    """
    CREATE TABLE IF NOT EXISTS amphtml_urls (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        amphtml_url_id INTEGER NOT NULL,
        source TEXT CHECK (source IN ('html_head', 'http_header')) NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (amphtml_url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hreflang_languages (
        id SERIAL PRIMARY KEY,
        language_code TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hreflang_http_header (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        hreflang_id INTEGER NOT NULL,
        href_url_id INTEGER NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (hreflang_id) REFERENCES hreflang_languages (id),
        FOREIGN KEY (href_url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hreflang_html_head (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        hreflang_id INTEGER NOT NULL,
        href_url_id INTEGER NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (hreflang_id) REFERENCES hreflang_languages (id),
        FOREIGN KEY (href_url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hreflang_sitemap (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        hreflang_id INTEGER NOT NULL,
        href_url_id INTEGER NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (hreflang_id) REFERENCES hreflang_languages (id),
        FOREIGN KEY (href_url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS page_metadata (
        url_id INTEGER PRIMARY KEY,
        initial_status_code INTEGER,
        final_status_code INTEGER,
        final_url_id INTEGER,
        fetched_at INTEGER,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (final_url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS indexability (
        url_id INTEGER PRIMARY KEY,
        html_meta_allows BOOLEAN NOT NULL,
        http_header_allows BOOLEAN NOT NULL,
        overall_indexable BOOLEAN NOT NULL,
        FOREIGN KEY (url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS crawl_runs (
        run_id TEXT PRIMARY KEY,
        mode TEXT NOT NULL DEFAULT 'open',
        status TEXT NOT NULL DEFAULT 'created',
        seed_urls_json TEXT NOT NULL DEFAULT '[]',
        config_hash TEXT NOT NULL DEFAULT '',
        config_json TEXT NOT NULL DEFAULT '{}',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS frontier (
        id SERIAL PRIMARY KEY,
        run_id TEXT NOT NULL DEFAULT 'legacy',
        url_id INTEGER NOT NULL,
        depth INTEGER NOT NULL,
        parent_id INTEGER,
        status TEXT NOT NULL CHECK (status IN ('queued','pending','done')),
        enqueued_at INTEGER,
        updated_at INTEGER,
        priority_score DOUBLE PRECISION DEFAULT 0.0,
        sitemap_priority DOUBLE PRECISION DEFAULT 0.5,
        inlinks_count INTEGER DEFAULT 0,
        content_type_score DOUBLE PRECISION DEFAULT 1.0,
        reset_count INTEGER DEFAULT 0,
        retry_count INTEGER DEFAULT 0,
        retry_at INTEGER DEFAULT 0,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (parent_id) REFERENCES urls (id),
        UNIQUE (run_id, url_id)
    )
    """,
    """
    ALTER TABLE content ADD COLUMN IF NOT EXISTS content_hash_sha256 TEXT
    """,
    """
    ALTER TABLE content ADD COLUMN IF NOT EXISTS content_hash_simhash BIGINT
    """,
    """
    ALTER TABLE page_metadata ADD COLUMN IF NOT EXISTS ttfb_seconds DOUBLE PRECISION
    """,
    """
    ALTER TABLE page_metadata ADD COLUMN IF NOT EXISTS total_duration_seconds DOUBLE PRECISION
    """,
    """
    ALTER TABLE page_metadata ADD COLUMN IF NOT EXISTS lcp_ms DOUBLE PRECISION
    """,
    """
    ALTER TABLE page_metadata ADD COLUMN IF NOT EXISTS cls DOUBLE PRECISION
    """,
    """
    ALTER TABLE page_metadata ADD COLUMN IF NOT EXISTS inp_ms DOUBLE PRECISION
    """,
    """
    ALTER TABLE content ADD COLUMN IF NOT EXISTS custom_data JSONB
    """,
    """
    ALTER TABLE frontier ADD COLUMN IF NOT EXISTS run_id TEXT
    """,
    """
    UPDATE frontier SET run_id = 'legacy' WHERE run_id IS NULL
    """,
    """
    ALTER TABLE frontier ALTER COLUMN run_id SET DEFAULT 'legacy'
    """,
    """
    ALTER TABLE frontier ALTER COLUMN run_id SET NOT NULL
    """,
    """
    ALTER TABLE frontier DROP CONSTRAINT IF EXISTS frontier_url_id_key
    """,
    """
    ALTER TABLE frontier ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0
    """,
    """
    ALTER TABLE frontier ADD COLUMN IF NOT EXISTS retry_at INTEGER DEFAULT 0
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_frontier_status ON frontier(status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_frontier_priority ON frontier(priority_score DESC, enqueued_at ASC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_frontier_run_status ON frontier(run_id, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_frontier_run_priority ON frontier(run_id, priority_score DESC, enqueued_at ASC)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_frontier_run_url ON frontier(run_id, url_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS crawl_metadata (
        key TEXT PRIMARY KEY,
        run_id TEXT NOT NULL DEFAULT 'legacy',
        value_json TEXT NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    ALTER TABLE crawl_metadata ADD COLUMN IF NOT EXISTS run_id TEXT
    """,
    """
    UPDATE crawl_metadata SET run_id = 'legacy' WHERE run_id IS NULL
    """,
    """
    ALTER TABLE crawl_metadata ALTER COLUMN run_id SET DEFAULT 'legacy'
    """,
    """
    ALTER TABLE crawl_metadata ALTER COLUMN run_id SET NOT NULL
    """,
    """
    INSERT INTO crawl_runs (run_id, mode, status, seed_urls_json, config_hash, config_json, created_at, updated_at)
    VALUES ('legacy', 'open', 'legacy', '[]', '', '{}', EXTRACT(EPOCH FROM NOW())::INTEGER, EXTRACT(EPOCH FROM NOW())::INTEGER)
    ON CONFLICT (run_id) DO NOTHING
    """,
    """
    INSERT INTO crawl_runs (run_id, mode, status, seed_urls_json, config_hash, config_json, created_at, updated_at)
    SELECT
        'legacy',
        'open',
        'legacy',
        '[]',
        '',
        '{}',
        COALESCE(MIN(enqueued_at), EXTRACT(EPOCH FROM NOW())::INTEGER),
        EXTRACT(EPOCH FROM NOW())::INTEGER
    FROM frontier
    WHERE run_id = 'legacy'
    ON CONFLICT (run_id) DO NOTHING
    """,
    """
    CREATE TABLE IF NOT EXISTS url_sources (
        url_id INTEGER NOT NULL REFERENCES urls(id),
        source TEXT NOT NULL CHECK (source IN ('seed', 'link', 'sitemap', 'archive_org', 'robots_sitemap')),
        detail TEXT,
        detail_key TEXT GENERATED ALWAYS AS (COALESCE(detail, '')) STORED,
        first_seen_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (url_id, source, detail_key)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_url_sources_source ON url_sources(source)
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_types (
        id SERIAL PRIMARY KEY,
        type_name TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_instances (
        id SERIAL PRIMARY KEY,
        content_hash TEXT UNIQUE NOT NULL,
        schema_type_id INTEGER NOT NULL,
        format TEXT CHECK (format IN ('json-ld', 'microdata', 'rdfa')) NOT NULL,
        raw_data TEXT NOT NULL,
        parsed_data JSONB,
        is_valid BOOLEAN NOT NULL DEFAULT TRUE,
        validation_errors JSONB,
        severity TEXT CHECK (severity IN ('info', 'warning', 'error', 'critical')) DEFAULT 'info',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (schema_type_id) REFERENCES schema_types (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS page_schema_references (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        schema_instance_id INTEGER NOT NULL,
        position INTEGER,
        property_name TEXT,
        is_main_entity BOOLEAN DEFAULT FALSE,
        parent_entity_id INTEGER,
        discovered_at INTEGER NOT NULL,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (schema_instance_id) REFERENCES schema_instances (id),
        FOREIGN KEY (parent_entity_id) REFERENCES page_schema_references (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_data (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        schema_type_id INTEGER NOT NULL,
        format TEXT CHECK (format IN ('json-ld', 'microdata', 'rdfa')) NOT NULL,
        raw_data TEXT NOT NULL,
        parsed_data JSONB,
        position INTEGER,
        is_valid BOOLEAN NOT NULL DEFAULT TRUE,
        validation_errors JSONB,
        severity TEXT CHECK (severity IN ('info', 'warning', 'error', 'critical')) DEFAULT 'info',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (url_id, schema_type_id, position),
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (schema_type_id) REFERENCES schema_types (id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_schema_instances_content_hash ON schema_instances(content_hash)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_page_schema_references_url ON page_schema_references(url_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_schema_data_url ON schema_data(url_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS anchor_texts (
        id SERIAL PRIMARY KEY,
        text TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fragments (
        id SERIAL PRIMARY KEY,
        fragment TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS xpaths (
        id SERIAL PRIMARY KEY,
        xpath TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS internal_links (
        id SERIAL PRIMARY KEY,
        source_url_id INTEGER NOT NULL,
        target_url_id INTEGER,
        anchor_text_id INTEGER,
        xpath_id INTEGER,
        href_url_id INTEGER NOT NULL,
        fragment_id INTEGER,
        url_parameters TEXT,
        discovered_at INTEGER NOT NULL,
        UNIQUE (source_url_id, target_url_id, xpath_id),
        FOREIGN KEY (source_url_id) REFERENCES urls (id),
        FOREIGN KEY (target_url_id) REFERENCES urls (id),
        FOREIGN KEY (anchor_text_id) REFERENCES anchor_texts (id),
        FOREIGN KEY (xpath_id) REFERENCES xpaths (id),
        FOREIGN KEY (href_url_id) REFERENCES urls (id),
        FOREIGN KEY (fragment_id) REFERENCES fragments (id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_internal_links_source ON internal_links(source_url_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_internal_links_target ON internal_links(target_url_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS page_embeddings (
        url_id INTEGER PRIMARY KEY,
        embedding_json JSONB NOT NULL,
        model TEXT NOT NULL,
        text_length INTEGER,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_page_embeddings_model ON page_embeddings(model)
    """,
    """
    ALTER TABLE urls ADD COLUMN IF NOT EXISTS norm_url TEXT
    """,
    """
    ALTER TABLE urls ADD COLUMN IF NOT EXISTS hreflang_group TEXT
    """,
    """
    ALTER TABLE urls ADD COLUMN IF NOT EXISTS resolved_hreflang_code TEXT
    """,
    """
    ALTER TABLE urls ADD COLUMN IF NOT EXISTS lang_bucket TEXT
    """,
    """
    ALTER TABLE urls ADD COLUMN IF NOT EXISTS variant_of_id INTEGER
    """,
    # ticket 103: page-variant kind on the URL identity.  Extensible enum
    # ('amp' today; print/feed variants could follow) — deliberately plain TEXT
    # with no CHECK so new kinds need no further migration.
    """
    ALTER TABLE urls ADD COLUMN IF NOT EXISTS variant_kind TEXT
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_urls_variant_kind ON urls(variant_kind) WHERE variant_kind IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_urls_hreflang_group ON urls(hreflang_group)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_urls_norm_url ON urls(norm_url)
    """,
    """
    ALTER TABLE page_embeddings ADD COLUMN IF NOT EXISTS signature_hash TEXT
    """,
    """
    ALTER TABLE page_embeddings ADD COLUMN IF NOT EXISTS dim INTEGER
    """,
    """
    CREATE TABLE IF NOT EXISTS intent_signatures (
        url_id INTEGER PRIMARY KEY,
        main_text_compressed BYTEA,
        extraction_method TEXT,
        signal_confidence TEXT,
        signature_hash TEXT,
        signature_model_input TEXT,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_intent_signatures_hash ON intent_signatures(signature_hash)
    """,
    """
    CREATE TABLE IF NOT EXISTS crawl_comparison_sessions (
        id SERIAL PRIMARY KEY,
        baseline_label TEXT NOT NULL,
        candidate_label TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS crawl_comparison_urls (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        path TEXT NOT NULL,
        baseline_url TEXT,
        candidate_url TEXT,
        exists_on_baseline BOOLEAN NOT NULL DEFAULT FALSE,
        exists_on_candidate BOOLEAN NOT NULL DEFAULT FALSE,
        baseline_title TEXT,
        candidate_title TEXT,
        baseline_h1 TEXT,
        candidate_h1 TEXT,
        baseline_meta_description TEXT,
        candidate_meta_description TEXT,
        baseline_word_count INTEGER,
        candidate_word_count INTEGER,
        is_moved_content BOOLEAN NOT NULL DEFAULT FALSE,
        moved_from_path TEXT,
        moved_to_path TEXT,
        redirect_chain TEXT,
        baseline_schema_types JSONB,
        candidate_schema_types JSONB,
        links_added JSONB,
        links_removed JSONB,
        UNIQUE (session_id, path),
        FOREIGN KEY (session_id) REFERENCES crawl_comparison_sessions (id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_crawl_comparison_urls_session ON crawl_comparison_urls(session_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS analytics_vendors (
        id SERIAL PRIMARY KEY,
        vendor TEXT UNIQUE NOT NULL,
        category TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS page_analytics_hits (
        id BIGSERIAL PRIMARY KEY,
        page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
        vendor_id INTEGER NOT NULL REFERENCES analytics_vendors(id),
        identifier TEXT,
        evidence_type TEXT NOT NULL,
        evidence_snippet TEXT,
        confidence REAL NOT NULL,
        detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_page_analytics_hits_page ON page_analytics_hits(page_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_page_analytics_hits_vendor ON page_analytics_hits(vendor_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_page_analytics_hits_identifier ON page_analytics_hits(identifier) WHERE identifier IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_page_analytics_hits_page_vendor_id ON page_analytics_hits(page_id, vendor_id, identifier)
    """,
    """
    DELETE FROM robots_directives a
    USING robots_directives b
    WHERE a.ctid < b.ctid
      AND a.url_id = b.url_id
      AND a.source = b.source
      AND a.directive_id = b.directive_id
      AND a.value IS NOT DISTINCT FROM b.value
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_robots_directives_fact
    ON robots_directives(url_id, source, directive_id, value)
    """,
    """
    DELETE FROM canonical_urls a
    USING canonical_urls b
    WHERE a.ctid < b.ctid
      AND a.url_id = b.url_id
      AND a.canonical_url_id = b.canonical_url_id
      AND a.source = b.source
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_canonical_urls_fact
    ON canonical_urls(url_id, canonical_url_id, source)
    """,
    """
    DELETE FROM amphtml_urls a
    USING amphtml_urls b
    WHERE a.ctid < b.ctid
      AND a.url_id = b.url_id
      AND a.amphtml_url_id = b.amphtml_url_id
      AND a.source = b.source
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_amphtml_urls_fact
    ON amphtml_urls(url_id, amphtml_url_id, source)
    """,
    """
    DELETE FROM hreflang_http_header a
    USING hreflang_http_header b
    WHERE a.ctid < b.ctid
      AND a.url_id = b.url_id
      AND a.hreflang_id = b.hreflang_id
      AND a.href_url_id = b.href_url_id
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_hreflang_http_header_fact
    ON hreflang_http_header(url_id, hreflang_id, href_url_id)
    """,
    """
    DELETE FROM hreflang_html_head a
    USING hreflang_html_head b
    WHERE a.ctid < b.ctid
      AND a.url_id = b.url_id
      AND a.hreflang_id = b.hreflang_id
      AND a.href_url_id = b.href_url_id
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_hreflang_html_head_fact
    ON hreflang_html_head(url_id, hreflang_id, href_url_id)
    """,
    """
    DELETE FROM hreflang_sitemap a
    USING hreflang_sitemap b
    WHERE a.ctid < b.ctid
      AND a.url_id = b.url_id
      AND a.hreflang_id = b.hreflang_id
      AND a.href_url_id = b.href_url_id
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_hreflang_sitemap_fact
    ON hreflang_sitemap(url_id, hreflang_id, href_url_id)
    """,
    """
    DELETE FROM page_analytics_hits a
    USING page_analytics_hits b
    WHERE a.ctid < b.ctid
      AND a.page_id = b.page_id
      AND a.vendor_id = b.vendor_id
      AND a.evidence_type = b.evidence_type
      AND a.identifier IS NOT DISTINCT FROM b.identifier
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_page_analytics_hits_fact
    ON page_analytics_hits(page_id, vendor_id, evidence_type, COALESCE(identifier, ''))
    """,
]

COMPARISON_VIEW_STATEMENTS = [
    """
    CREATE OR REPLACE VIEW view_url_moves AS
    SELECT
        cu.session_id,
        s.baseline_label,
        s.candidate_label,
        cu.path,
        cu.moved_from_path,
        cu.moved_to_path,
        cu.redirect_chain,
        'Content moved via redirect' AS move_type
    FROM crawl_comparison_urls cu
    JOIN crawl_comparison_sessions s ON s.id = cu.session_id
    WHERE cu.is_moved_content = TRUE
    """,
    """
    CREATE OR REPLACE VIEW view_content_differences AS
    SELECT
        cu.session_id,
        s.baseline_label,
        s.candidate_label,
        cu.path,
        cu.baseline_title,
        cu.candidate_title,
        cu.baseline_h1,
        cu.candidate_h1,
        cu.baseline_meta_description,
        cu.candidate_meta_description,
        cu.baseline_word_count,
        cu.candidate_word_count,
        CASE WHEN cu.baseline_title IS NOT DISTINCT FROM cu.candidate_title THEN 'Match' ELSE 'Different' END AS title_match,
        CASE WHEN cu.baseline_h1 IS NOT DISTINCT FROM cu.candidate_h1 THEN 'Match' ELSE 'Different' END AS h1_match,
        CASE WHEN cu.baseline_meta_description IS NOT DISTINCT FROM cu.candidate_meta_description THEN 'Match' ELSE 'Different' END AS meta_description_match,
        CASE WHEN cu.baseline_word_count = cu.candidate_word_count THEN 'Match' ELSE 'Different' END AS word_count_match
    FROM crawl_comparison_urls cu
    JOIN crawl_comparison_sessions s ON s.id = cu.session_id
    WHERE cu.exists_on_baseline AND cu.exists_on_candidate
      AND (
        cu.baseline_title IS DISTINCT FROM cu.candidate_title
        OR cu.baseline_h1 IS DISTINCT FROM cu.candidate_h1
        OR cu.baseline_meta_description IS DISTINCT FROM cu.candidate_meta_description
        OR cu.baseline_word_count IS DISTINCT FROM cu.candidate_word_count
      )
    """,
    """
    CREATE OR REPLACE VIEW view_schema_comparison AS
    SELECT
        cu.session_id,
        s.baseline_label,
        s.candidate_label,
        cu.path,
        cu.baseline_schema_types,
        cu.candidate_schema_types,
        CASE
            WHEN cu.baseline_schema_types IS NOT DISTINCT FROM cu.candidate_schema_types THEN 'Match'
            ELSE 'Different'
        END AS schema_match
    FROM crawl_comparison_urls cu
    JOIN crawl_comparison_sessions s ON s.id = cu.session_id
    WHERE cu.exists_on_baseline AND cu.exists_on_candidate
    """,
]

# Tables owned by crawler_cli (used for truncate / row-count summaries).
CRAWL_TABLES: tuple[str, ...] = (
    "page_analytics_hits",
    "page_schema_references",
    "internal_links",
    "page_embeddings",
    "intent_signatures",
    "crawl_comparison_urls",
    "robots_directives",
    "canonical_urls",
    "amphtml_urls",
    "hreflang_http_header",
    "hreflang_html_head",
    "hreflang_sitemap",
    "page_metadata",
    "indexability",
    "content",
    "pages",
    "schema_data",
    "frontier",
    "url_sources",
    "urls",
    "html_languages",
    "meta_descriptions",
    "robots_directive_strings",
    "hreflang_languages",
    "anchor_texts",
    "fragments",
    "xpaths",
    "schema_instances",
    "schema_types",
    "analytics_vendors",
    "crawl_comparison_sessions",
    "crawl_metadata",
    "crawl_runs",
)


def database_name_from_dsn(dsn: str) -> str:
    path = urlparse(dsn).path.strip("/")
    if not path:
        return "postgres"
    return path.split("/")[0]


def encode_html_for_storage(text: str, *, compress: bool) -> bytes | None:
    if not text:
        return None
    if compress:
        return compress_html(text)
    return text.encode("utf-8")


class MemoryStore:
    """Lightweight frontier store for local crawls that do not need Postgres."""

    def __init__(self) -> None:
        now = int(time.time())
        self.active_run_id = DEFAULT_CRAWL_RUN_ID
        self.frontier: dict[str, dict[str, Any]] = {}
        self.frontiers: dict[str, dict[str, dict[str, Any]]] = {DEFAULT_CRAWL_RUN_ID: self.frontier}
        self.saved_metadata: dict[str, dict[str, object]] = {}
        self.run_metadata: dict[tuple[str, str], dict[str, object]] = {}
        self.crawl_runs: dict[str, CrawlRunRecord] = {
            DEFAULT_CRAWL_RUN_ID: {
                "run_id": DEFAULT_CRAWL_RUN_ID,
                "mode": "open",
                "status": "legacy",
                "seed_urls": [],
                "config_hash": "",
                "config": {},
                "created_at": now,
                "updated_at": now,
            }
        }
        self.sources: dict[str, set[tuple[str, str | None]]] = {}

    def _resolve_run_id(self, run_id: str | None = None) -> str:
        return run_id or self.active_run_id

    def _frontier_for(self, run_id: str | None = None) -> dict[str, dict[str, Any]]:
        resolved = self._resolve_run_id(run_id)
        if resolved == DEFAULT_CRAWL_RUN_ID:
            return self.frontier
        return self.frontiers.setdefault(resolved, {})

    def set_active_crawl_run(self, run_id: str) -> None:
        self.active_run_id = run_id
        self._frontier_for(run_id)

    async def create_crawl_run(
        self,
        run_id: str,
        *,
        seed_urls: Sequence[str],
        config_hash: str,
        config: dict[str, object],
        status: str = "running",
    ) -> None:
        if run_id in self.crawl_runs:
            raise ValueError(f"crawl run already exists: {run_id}")
        now = int(time.time())
        self.crawl_runs[run_id] = {
            "run_id": run_id,
            "mode": "open",
            "status": status,
            "seed_urls": list(seed_urls),
            "config_hash": config_hash,
            "config": dict(config),
            "created_at": now,
            "updated_at": now,
        }
        self.set_active_crawl_run(run_id)

    async def get_crawl_run(self, run_id: str) -> CrawlRunRecord | None:
        return self.crawl_runs.get(run_id)

    async def update_crawl_run_status(self, run_id: str, status: str) -> None:
        run = self.crawl_runs.get(run_id)
        if run is None:
            return
        run["status"] = status
        run["updated_at"] = int(time.time())

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def initialize(self) -> None:
        return None

    async def save_metadata(self, key: str, value: dict[str, object]) -> None:
        value = {**value, "run_id": self.active_run_id}
        self.saved_metadata[key] = value
        self.run_metadata[(self.active_run_id, key)] = value

    async def persist(self, result: CrawlResult) -> None:
        return None

    async def enqueue_frontier(
        self,
        frontier_data: Sequence[tuple[str, int, str | None, float | None] | tuple[str, int, str | None]],
        *,
        source: str | None = None,
        source_detail: str | None = None,
        run_id: str | None = None,
    ) -> int:
        inserted = 0
        current_time = int(time.time())
        frontier = self._frontier_for(run_id)
        for item in frontier_data:
            url, depth, parent_url = item[0], item[1], item[2]
            priority_score = float(item[3]) if len(item) > 3 and item[3] is not None else 0.0
            if url in frontier:
                continue
            frontier[url] = {
                "depth": depth,
                "parent_url": parent_url,
                "status": "queued",
                "enqueued_at": current_time,
                "updated_at": current_time,
                "priority_score": priority_score,
                "reset_count": 0,
                "retry_count": 0,
                "retry_at": 0,
            }
            if source:
                await self.record_source_by_url(url, source, source_detail)
            inserted += 1
        return inserted

    async def frontier_next_batch(
        self, batch_size: int, *, run_id: str | None = None
    ) -> list[tuple[str, int, str | None, int]]:
        now = int(time.time())
        frontier = self._frontier_for(run_id)
        rows: list[tuple[str, int, str | None, int, float, int]] = []
        for url, state in frontier.items():
            if state["status"] != "queued" or int(state.get("retry_at", 0)) > now:
                continue
            rows.append(
                (
                    url,
                    int(state["depth"]),
                    cast(str | None, state.get("parent_url")),
                    int(state.get("retry_count", 0)),
                    float(state.get("priority_score", 0.0)),
                    int(state.get("enqueued_at", 0)),
                )
            )
        rows.sort(key=lambda row: (-row[4], row[5], row[0]))
        batch = rows[:batch_size]
        for url, *_ in batch:
            frontier[url]["status"] = "pending"
            frontier[url]["updated_at"] = now
        return [(url, depth, parent_url, retry_count) for url, depth, parent_url, retry_count, _, _ in batch]

    async def frontier_mark_retry(
        self, url: str, retry_count: int, delay_seconds: float, *, run_id: str | None = None
    ) -> None:
        frontier = self._frontier_for(run_id)
        state = frontier.setdefault(
            url,
            {
                "depth": 0,
                "parent_url": None,
                "status": "queued",
                "enqueued_at": int(time.time()),
                "updated_at": int(time.time()),
                "priority_score": 0.0,
                "reset_count": 0,
                "retry_count": 0,
                "retry_at": 0,
            },
        )
        state["status"] = "queued"
        state["retry_count"] = retry_count
        state["retry_at"] = int(time.time() + max(0.0, delay_seconds))
        state["updated_at"] = int(time.time())

    async def frontier_mark_done(self, urls: list[str], *, run_id: str | None = None) -> None:
        current_time = int(time.time())
        frontier = self._frontier_for(run_id)
        for url in urls:
            state = frontier.setdefault(
                url,
                {
                    "depth": 0,
                    "parent_url": None,
                    "status": "done",
                    "enqueued_at": current_time,
                    "updated_at": current_time,
                    "priority_score": 0.0,
                    "reset_count": 0,
                    "retry_count": 0,
                    "retry_at": 0,
                },
            )
            state["status"] = "done"
            state["updated_at"] = current_time
            state["retry_count"] = 0
            state["retry_at"] = 0

    async def frontier_reset_pending_to_queued(self, urls: list[str], *, run_id: str | None = None) -> None:
        current_time = int(time.time())
        frontier = self._frontier_for(run_id)
        for url in urls:
            state = frontier.get(url)
            if state is None or state["status"] != "pending":
                continue
            state["status"] = "queued"
            state["updated_at"] = current_time

    async def frontier_reset_all_pending_to_queued(self, *, run_id: str | None = None) -> int:
        reset = 0
        current_time = int(time.time())
        frontier = self._frontier_for(run_id)
        for state in frontier.values():
            if state["status"] != "pending":
                continue
            state["status"] = "queued"
            state["updated_at"] = current_time
            state["reset_count"] = int(state.get("reset_count", 0)) + 1
            reset += 1
        return reset

    async def record_source(self, url_id: int, source: str, detail: str | None = None) -> None:
        return None

    async def record_source_by_url(self, url: str, source: str, detail: str | None = None) -> None:
        self.sources.setdefault(url, set()).add((source, detail))

    async def record_sources_bulk(
        self,
        url_detail_pairs: list[tuple[str, str | None]],
        source: str,
    ) -> None:
        for url, detail in url_detail_pairs:
            await self.record_source_by_url(url, source, detail)

    async def persist_sitemap_hreflang_bulk(
        self,
        page_hreflang_pairs: list[tuple[str, list]],
    ) -> None:
        return None

    async def urls_fetched_since(self, urls: list[str], cutoff_epoch: int) -> set[str]:
        # MemoryStore keeps no fetch history, so nothing is ever "fresh".
        return set()

    async def frontier_stats(self, *, run_id: str | None = None) -> tuple[int, int, int]:
        frontier = self._frontier_for(run_id)
        queued = sum(1 for state in frontier.values() if state["status"] == "queued")
        pending = sum(1 for state in frontier.values() if state["status"] == "pending")
        done = sum(1 for state in frontier.values() if state["status"] == "done")
        return queued, pending, done


class AsyncpgStore:
    def __init__(
        self,
        dsn: str,
        *,
        compress_html: bool = True,
        store_html: bool = True,
    ) -> None:
        self.dsn = dsn
        self.compress_html = compress_html
        self.store_html = store_html
        self.active_run_id = DEFAULT_CRAWL_RUN_ID
        self.pool: asyncpg.Pool | None = None

    def _resolve_run_id(self, run_id: str | None = None) -> str:
        return run_id or self.active_run_id

    def set_active_crawl_run(self, run_id: str) -> None:
        self.active_run_id = run_id

    async def connect(self) -> None:
        if self.pool is None:
            self.pool = await asyncpg.create_pool(dsn=self.dsn)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def initialize(self) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            for statement in SCHEMA_STATEMENTS:
                await conn.execute(statement)

    async def initialize_comparison_views(self) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            for statement in COMPARISON_VIEW_STATEMENTS:
                await conn.execute(statement)

    async def create_crawl_run(
        self,
        run_id: str,
        *,
        seed_urls: Sequence[str],
        config_hash: str,
        config: dict[str, object],
        status: str = "running",
    ) -> None:
        await self.connect()
        assert self.pool is not None
        now = int(time.time())
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO crawl_runs (
                    run_id, mode, status, seed_urls_json, config_hash, config_json, created_at, updated_at
                )
                VALUES ($1, 'open', $2, $3, $4, $5, $6, $6)
                ON CONFLICT (run_id) DO NOTHING
                """,
                run_id,
                status,
                json.dumps(list(seed_urls), sort_keys=True),
                config_hash,
                json.dumps(config, sort_keys=True),
                now,
            )
        if result.split()[-1] == "0":
            raise ValueError(f"crawl run already exists: {run_id}")
        self.set_active_crawl_run(run_id)

    async def get_crawl_run(self, run_id: str) -> CrawlRunRecord | None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT run_id, mode, status, seed_urls_json, config_hash, config_json, created_at, updated_at
                FROM crawl_runs
                WHERE run_id = $1
                """,
                run_id,
            )
        if row is None:
            return None
        try:
            seed_urls = json.loads(str(row["seed_urls_json"]))
        except json.JSONDecodeError:
            seed_urls = []
        try:
            config = json.loads(str(row["config_json"]))
        except json.JSONDecodeError:
            config = {}
        return {
            "run_id": str(row["run_id"]),
            "mode": str(row["mode"]),
            "status": str(row["status"]),
            "seed_urls": [str(seed) for seed in seed_urls] if isinstance(seed_urls, list) else [],
            "config_hash": str(row["config_hash"]),
            "config": config if isinstance(config, dict) else {},
            "created_at": int(row["created_at"]),
            "updated_at": int(row["updated_at"]),
        }

    async def update_crawl_run_status(self, run_id: str, status: str) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE crawl_runs
                SET status = $2,
                    updated_at = $3
                WHERE run_id = $1
                """,
                run_id,
                status,
                int(time.time()),
            )

    async def save_metadata(self, key: str, value: dict[str, object]) -> None:
        await self.connect()
        assert self.pool is not None
        run_id = self.active_run_id
        metadata_key = key if run_id == DEFAULT_CRAWL_RUN_ID else f"{run_id}:{key}"
        value = {**value, "run_id": run_id}
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO crawl_metadata (key, run_id, value_json, updated_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (key) DO UPDATE
                SET value_json = EXCLUDED.value_json,
                    run_id = EXCLUDED.run_id,
                    updated_at = EXCLUDED.updated_at
                """,
                metadata_key,
                run_id,
                json.dumps(value, sort_keys=True),
                int(time.time()),
            )

    async def _get_or_create_url(
        self,
        conn: asyncpg.Connection,
        url: str,
        *,
        kind: str = "html",
        classification: str = "internal",
        is_from_hreflang: bool = False,
    ) -> int:
        query = """
            INSERT INTO urls (url, kind, classification, is_from_hreflang)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (url) DO UPDATE
            SET kind = EXCLUDED.kind,
                classification = EXCLUDED.classification,
                is_from_hreflang = urls.is_from_hreflang OR EXCLUDED.is_from_hreflang
            RETURNING id
        """
        row = await conn.fetchrow(query, url, kind, classification, is_from_hreflang)
        return int(row["id"])

    async def _get_or_create_lookup(self, conn: asyncpg.Connection, table: str, column: str, value: str) -> int:
        row = await conn.fetchrow(
            f"""
            INSERT INTO {table} ({column})
            VALUES ($1)
            ON CONFLICT ({column}) DO UPDATE SET {column} = EXCLUDED.{column}
            RETURNING id
            """,
            value,
        )
        return int(row["id"])

    async def _bulk_get_or_create_urls(self, conn: asyncpg.Connection, urls: list[str]) -> dict[str, int]:
        if not urls:
            return {}
        # Sorted (not just deduped) so the INSERT acquires `urls` row locks in a
        # stable order across concurrent transactions — prevents deadlocks when
        # multiple workers bulk-resolve overlapping URL sets (e.g. sitemap +
        # link discovery enqueueing the same catalog).
        unique_urls = sorted(set(urls))
        rows = await conn.fetch(
            """
            WITH input_urls AS (
                SELECT unnest($1::text[]) AS url
            ),
            inserted AS (
                INSERT INTO urls (url, kind, classification)
                SELECT url, 'html', 'internal' FROM input_urls
                ON CONFLICT (url) DO NOTHING
                RETURNING id, url
            )
            SELECT id, url FROM inserted
            UNION ALL
            SELECT u.id, u.url FROM urls u
            JOIN input_urls i ON u.url = i.url
            """,
            unique_urls,
        )
        return {str(r["url"]): int(r["id"]) for r in rows}

    async def _bulk_get_or_create_lookups(
        self, conn: asyncpg.Connection, table: str, column: str, values: list[str]
    ) -> dict[str, int]:
        if not values:
            return {}
        # Sorted (not just deduped) so concurrent transactions bulk-inserting
        # overlapping values (e.g. shared nav anchor texts/xpaths across pages)
        # acquire row locks in the same order — mirrors the fix in
        # _bulk_get_or_create_urls, which prevents DeadlockDetectedError.
        unique_values = sorted(set(values))
        rows = await conn.fetch(
            f"""
            WITH input_vals AS (
                SELECT unnest($1::text[]) AS val
            ),
            inserted AS (
                INSERT INTO {table} ({column})
                SELECT val FROM input_vals
                ON CONFLICT ({column}) DO NOTHING
                RETURNING id, {column} AS val
            )
            SELECT id, val FROM inserted
            UNION ALL
            SELECT t.id, t.{column} AS val FROM {table} t
            JOIN input_vals i ON t.{column} = i.val
            """,
            unique_values,
        )
        return {str(r["val"]): int(r["id"]) for r in rows}

    async def _retry_on_deadlock(self, op, *args, _attempts: int = 8, **kwargs):
        """Run an async store operation, retrying on Postgres deadlock /
        serialization failures with exponential backoff.

        Concurrent crawl workers upserting overlapping `urls` / `frontier` rows
        can deadlock even with deterministic lock ordering. Every wrapped op is
        a single self-contained transaction whose statements are idempotent
        (ON CONFLICT DO NOTHING / DO UPDATE), so re-running it is safe.
        """
        for attempt in range(_attempts):
            try:
                return await op(*args, **kwargs)
            except (asyncpg.DeadlockDetectedError, asyncpg.SerializationError):
                if attempt + 1 >= _attempts:
                    raise
                await asyncio.sleep(0.05 * (2**attempt))

    async def enqueue_frontier(
        self,
        frontier_data: Sequence[tuple[str, int, str | None, float | None] | tuple[str, int, str | None]],
        *,
        source: str | None = None,
        source_detail: str | None = None,
        run_id: str | None = None,
    ) -> int:
        """Lifted in shape from WIP batch_enqueue_frontier, narrowed to asyncpg only."""
        if not frontier_data:
            return 0

        await self.connect()
        assert self.pool is not None
        return await self._retry_on_deadlock(
            self._enqueue_frontier_once,
            frontier_data,
            source=source,
            source_detail=source_detail,
            run_id=self._resolve_run_id(run_id),
        )

    async def _enqueue_frontier_once(
        self,
        frontier_data: Sequence[tuple[str, int, str | None, float | None] | tuple[str, int, str | None]],
        *,
        source: str | None = None,
        source_detail: str | None = None,
        run_id: str | None = None,
    ) -> int:
        assert self.pool is not None
        resolved_run_id = self._resolve_run_id(run_id)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                urls_to_resolve: list[str] = []
                for item in frontier_data:
                    child_url = item[0]
                    parent_url = item[2] if len(item) > 2 else None
                    urls_to_resolve.append(child_url)
                    if parent_url:
                        urls_to_resolve.append(parent_url)

                # Resolve all URLs in ONE sorted, set-based statement rather than
                # a loop of individual INSERT ... ON CONFLICT upserts. The loop
                # form holds row locks across many statements and still deadlocks
                # under heavy concurrency (overlapping facet URLs from multiple
                # workers); _bulk_get_or_create_urls sorts internally and resolves
                # them in a single round-trip, which removes the interleaving.
                url_to_id = await self._bulk_get_or_create_urls(conn, urls_to_resolve)

                child_ids = [url_to_id[item[0]] for item in frontier_data]
                existing_rows = await conn.fetch(
                    """
                    SELECT url_id, status
                    FROM frontier
                    WHERE run_id = $1 AND url_id = ANY($2::int[])
                    """,
                    resolved_run_id,
                    child_ids,
                )
                existing_ids = {int(row["url_id"]) for row in existing_rows}
                filtered = [item for item in frontier_data if url_to_id[item[0]] not in existing_ids]
                if not filtered:
                    return 0

                current_time = int(time.time())
                batch_data = []
                for item in filtered:
                    child_url, depth, parent_url = item[0], item[1], item[2]
                    priority_score = float(item[3]) if len(item) > 3 and item[3] is not None else 0.0
                    batch_data.append(
                        (
                            resolved_run_id,
                            url_to_id[child_url],
                            depth,
                            url_to_id[parent_url] if parent_url else None,
                            "queued",
                            current_time,
                            current_time,
                            priority_score,
                            0.5,
                            0,
                            1.0,
                            0,
                            0,
                            0,
                        )
                    )

                await conn.executemany(
                    """
                    INSERT INTO frontier (
                        run_id, url_id, depth, parent_id, status, enqueued_at, updated_at,
                        priority_score, sitemap_priority, inlinks_count, content_type_score, reset_count,
                        retry_count, retry_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    ON CONFLICT (run_id, url_id) DO NOTHING
                    """,
                    batch_data,
                )
                if source:
                    source_batch = [(url_to_id[item[0]], source, source_detail) for item in filtered]
                    await conn.executemany(
                        """
                        INSERT INTO url_sources (url_id, source, detail)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (url_id, source, detail_key) DO NOTHING
                        """,
                        source_batch,
                    )
                return len(batch_data)

    async def frontier_next_batch(
        self, batch_size: int, *, run_id: str | None = None
    ) -> list[tuple[str, int, str | None, int]]:
        """Lifted from WIP frontier_next_batch: atomically claim queued URLs as pending."""
        await self.connect()
        assert self.pool is not None
        resolved_run_id = self._resolve_run_id(run_id)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT f.url_id, u.url, f.depth, p.url AS parent_url, f.retry_count
                    FROM frontier f
                    JOIN urls u ON f.url_id = u.id
                    LEFT JOIN urls p ON f.parent_id = p.id
                    WHERE f.run_id = $2 AND f.status = 'queued' AND f.retry_at <= $3
                    ORDER BY f.priority_score DESC, f.enqueued_at ASC
                    LIMIT $1
                    FOR UPDATE OF f SKIP LOCKED
                    """,
                    batch_size * 2,
                    resolved_run_id,
                    int(time.time()),
                )
                if not rows:
                    return []

                unique_rows: list[asyncpg.Record] = []
                seen_urls: set[str] = set()
                for row in rows:
                    url = str(row["url"])
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    unique_rows.append(row)
                    if len(unique_rows) >= batch_size:
                        break

                claimed_ids = [int(row["url_id"]) for row in unique_rows]
                await conn.execute(
                    """
                    UPDATE frontier
                    SET status = 'pending', updated_at = $1
                    WHERE run_id = $2 AND url_id = ANY($3::int[])
                    """,
                    int(time.time()),
                    resolved_run_id,
                    claimed_ids,
                )
                return [
                    (
                        str(row["url"]),
                        int(row["depth"]),
                        str(row["parent_url"]) if row["parent_url"] else None,
                        int(row["retry_count"] or 0),
                    )
                    for row in unique_rows
                ]

    async def frontier_mark_retry(
        self, url: str, retry_count: int, delay_seconds: float, *, run_id: str | None = None
    ) -> None:
        await self.connect()
        assert self.pool is not None
        resolved_run_id = self._resolve_run_id(run_id)
        async with self.pool.acquire() as conn:
            url_id = await self._get_or_create_url(conn, url)
            retry_at = int(time.time() + max(0.0, delay_seconds))
            await conn.execute(
                """
                UPDATE frontier
                SET status = 'queued',
                    retry_count = $2,
                    retry_at = $3,
                    updated_at = $4
                WHERE run_id = $5 AND url_id = $1
                """,
                url_id,
                retry_count,
                retry_at,
                int(time.time()),
                resolved_run_id,
            )

    async def frontier_mark_done(self, urls: list[str], *, run_id: str | None = None) -> None:
        if not urls:
            return

        await self.connect()
        assert self.pool is not None
        resolved_run_id = self._resolve_run_id(run_id)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                url_ids = [await self._get_or_create_url(conn, url) for url in urls]
                current_time = int(time.time())
                await conn.execute(
                    """
                    INSERT INTO frontier (
                        run_id, url_id, depth, status, enqueued_at, updated_at,
                        priority_score, reset_count
                    )
                    SELECT $2, ids.url_id, 0, 'done', $1, $1, 0.0, 0
                    FROM UNNEST($3::int[]) AS ids(url_id)
                    ON CONFLICT (run_id, url_id) DO UPDATE
                    SET status = 'done',
                        updated_at = EXCLUDED.updated_at,
                        reset_count = 0,
                        retry_count = 0,
                        retry_at = 0
                    WHERE frontier.status IN ('pending', 'queued')
                    """,
                    current_time,
                    resolved_run_id,
                    url_ids,
                )

    async def frontier_reset_pending_to_queued(self, urls: list[str], *, run_id: str | None = None) -> None:
        if not urls:
            return
        await self.connect()
        assert self.pool is not None
        resolved_run_id = self._resolve_run_id(run_id)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                url_ids = [await self._get_or_create_url(conn, url) for url in urls]
                await conn.execute(
                    """
                    UPDATE frontier
                    SET status = 'queued', updated_at = $1
                    WHERE run_id = $2 AND url_id = ANY($3::int[]) AND status = 'pending'
                    """,
                    int(time.time()),
                    resolved_run_id,
                    url_ids,
                )

    async def frontier_reset_all_pending_to_queued(self, *, run_id: str | None = None) -> int:
        await self.connect()
        assert self.pool is not None
        resolved_run_id = self._resolve_run_id(run_id)
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE frontier
                SET status = 'queued', updated_at = $1, reset_count = reset_count + 1
                WHERE run_id = $2 AND status = 'pending'
                """,
                int(time.time()),
                resolved_run_id,
            )
        return int(result.split()[-1])

    async def record_source(self, url_id: int, source: str, detail: str | None = None) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO url_sources (url_id, source, detail)
                VALUES ($1, $2, $3)
                ON CONFLICT (url_id, source, detail_key) DO NOTHING
                """,
                url_id,
                source,
                detail,
            )

    async def record_source_by_url(self, url: str, source: str, detail: str | None = None) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            url_id = await self._get_or_create_url(conn, url)
            await conn.execute(
                """
                INSERT INTO url_sources (url_id, source, detail)
                VALUES ($1, $2, $3)
                ON CONFLICT (url_id, source, detail_key) DO NOTHING
                """,
                url_id,
                source,
                detail,
            )

    async def record_sources_bulk(
        self,
        url_detail_pairs: list[tuple[str, str | None]],
        source: str,
    ) -> None:
        """Bulk-record url_sources rows using a single connection and executemany.

        *url_detail_pairs* is a list of (url, detail_or_None).  Duplicate
        (url_id, source, detail_key) combos are silently skipped via ON CONFLICT.
        """
        if not url_detail_pairs:
            return
        await self.connect()
        assert self.pool is not None
        await self._retry_on_deadlock(self._record_sources_bulk_once, url_detail_pairs, source)

    async def _record_sources_bulk_once(
        self,
        url_detail_pairs: list[tuple[str, str | None]],
        source: str,
    ) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            urls = [u for u, _ in url_detail_pairs]
            url_id_map = await self._bulk_get_or_create_urls(conn, urls)
            rows = [(url_id_map[url], source, detail) for url, detail in url_detail_pairs if url in url_id_map]
            # Sort by url_id so concurrent inserts lock url_sources rows in a
            # consistent order (deadlock avoidance).
            rows.sort(key=lambda r: r[0])
            if rows:
                await conn.executemany(
                    """
                    INSERT INTO url_sources (url_id, source, detail)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (url_id, source, detail_key) DO NOTHING
                    """,
                    rows,
                )

    async def persist_sitemap_hreflang_bulk(
        self,
        page_hreflang_pairs: list[tuple[str, list]],
    ) -> None:
        """Persist sitemap-derived hreflang rows in a single bulk operation.

        *page_hreflang_pairs* is a list of (page_url, hreflang_links) where
        each hreflang_links item has .hreflang (language code) and .href.
        Uses bulk upserts to avoid N+1 round-trips (ticket-065).
        """
        if not page_hreflang_pairs:
            return
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            # Collect all distinct URLs and language codes for bulk upsert.
            page_urls = [u for u, _ in page_hreflang_pairs]
            href_urls = [link.href for _, links in page_hreflang_pairs for link in links]
            lang_codes = [link.hreflang for _, links in page_hreflang_pairs for link in links]

            all_urls = list(dict.fromkeys(page_urls + href_urls))
            url_id_map = await self._bulk_get_or_create_urls(conn, all_urls)
            lang_id_map = await self._bulk_get_or_create_lookups(
                conn, "hreflang_languages", "language_code", list(dict.fromkeys(lang_codes))
            )

            rows = []
            for page_url, links in page_hreflang_pairs:
                page_url_id = url_id_map.get(page_url)
                if page_url_id is None:
                    continue
                for link in links:
                    href_url_id = url_id_map.get(link.href)
                    lang_id = lang_id_map.get(link.hreflang)
                    if href_url_id is None or lang_id is None:
                        continue
                    rows.append((page_url_id, lang_id, href_url_id))

            if rows:
                await conn.executemany(
                    """
                    INSERT INTO hreflang_sitemap (url_id, hreflang_id, href_url_id)
                    VALUES ($1, $2, $3)
                    ON CONFLICT DO NOTHING
                    """,
                    rows,
                )

    async def urls_fetched_since(self, urls: list[str], cutoff_epoch: int) -> set[str]:
        """Return the subset of *urls* already fetched successfully (HTTP 200)
        at or after *cutoff_epoch* — the staleness filter for --refresh-days
        (ticket 080)."""
        if not urls:
            return set()
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.url
                FROM urls u
                JOIN page_metadata pm ON pm.url_id = u.id
                WHERE u.url = ANY($1::text[])
                  AND pm.final_status_code = 200
                  AND pm.fetched_at IS NOT NULL
                  AND pm.fetched_at >= $2
                """,
                urls,
                cutoff_epoch,
            )
        return {str(row["url"]) for row in rows}

    async def urls_with_source(self, source: str) -> list[str]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.url
                FROM urls u
                JOIN url_sources us ON us.url_id = u.id
                WHERE us.source = $1
                ORDER BY u.url
                """,
                source,
            )
            return [str(row["url"]) for row in rows]

    async def simhash_neighbours(self, target: int, max_distance: int = 8) -> list[tuple[str, int]]:
        """Return URLs whose simhash is within Hamming distance of target."""
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.url, c.content_hash_simhash
                FROM content c
                JOIN urls u ON u.id = c.url_id
                WHERE c.content_hash_simhash IS NOT NULL
                """
            )
        results: list[tuple[str, int]] = []
        for row in rows:
            sim = row["content_hash_simhash"]
            if sim is None:
                continue
            try:
                sim_int = simhash_to_unsigned(int(sim))
            except (ValueError, TypeError):
                continue
            distance = bin(sim_int ^ int(target)).count("1")
            if distance <= max_distance:
                results.append((str(row["url"]), distance))
        results.sort(key=lambda x: x[1])
        return results

    async def frontier_stats(self, *, run_id: str | None = None) -> tuple[int, int, int]:
        await self.connect()
        assert self.pool is not None
        resolved_run_id = self._resolve_run_id(run_id)
        async with self.pool.acquire() as conn:
            queued = await conn.fetchval(
                "SELECT COUNT(*) FROM frontier WHERE run_id = $1 AND status = 'queued'", resolved_run_id
            )
            pending = await conn.fetchval(
                "SELECT COUNT(*) FROM frontier WHERE run_id = $1 AND status = 'pending'", resolved_run_id
            )
            done = await conn.fetchval(
                "SELECT COUNT(*) FROM frontier WHERE run_id = $1 AND status = 'done'", resolved_run_id
            )
        return int(queued or 0), int(pending or 0), int(done or 0)

    async def persist(self, result: CrawlResult) -> None:
        """Persist crawl result to database.

        Always stores page_metadata so we know the URL was fetched and what
        status it returned. Only stores content/extracted data when extraction
        succeeded (extracted is not None).

        IMPORTANT: When the final URL differs from the requested URL (e.g., JS
        redirect in Playwright), extracted data (canonical, hreflang, robots,
        content) is stored against the FINAL URL — the URL that actually served
        the content. The requested URL only gets page_metadata recording the
        redirect.
        """
        await self.connect()
        assert self.pool is not None
        await self._retry_on_deadlock(self._persist_once, result)

    async def _clear_page_snapshot(
        self,
        conn: asyncpg.Connection,
        *,
        url_id: int,
        page_id: int | None,
    ) -> None:
        await conn.execute("DELETE FROM robots_directives WHERE url_id = $1", url_id)
        await conn.execute("DELETE FROM canonical_urls WHERE url_id = $1", url_id)
        await conn.execute("DELETE FROM hreflang_http_header WHERE url_id = $1", url_id)
        await conn.execute("DELETE FROM hreflang_html_head WHERE url_id = $1", url_id)
        await conn.execute("DELETE FROM hreflang_sitemap WHERE url_id = $1", url_id)
        await conn.execute("DELETE FROM page_schema_references WHERE url_id = $1", url_id)
        await conn.execute("DELETE FROM schema_data WHERE url_id = $1", url_id)
        await conn.execute("DELETE FROM internal_links WHERE source_url_id = $1", url_id)
        if page_id is not None:
            await conn.execute("DELETE FROM page_analytics_hits WHERE page_id = $1", page_id)

    async def _persist_once(self, result: CrawlResult) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Pre-touch every `urls` row this transaction will create/update,
                # in sorted order, BEFORE doing per-URL work. This makes concurrent
                # persist() transactions acquire the shared `urls` row locks in the
                # same order, which is what prevents the DeadlockDetectedError seen
                # under multi-worker crawls (the later _get_or_create_url calls then
                # just re-lock rows this transaction already holds).
                prelock_urls = [result.requested_url, result.final_url]
                if result.extracted is not None:
                    if result.extracted.canonical:
                        prelock_urls.append(result.extracted.canonical)
                    if result.extracted.x_canonical:
                        prelock_urls.append(result.extracted.x_canonical)
                    if result.extracted.amphtml:
                        # ticket 103: the amphtml href gets a `urls` row too, so it
                        # MUST be folded into this same sorted bulk pre-lock rather
                        # than locked separately in _persist_amphtml, or concurrent
                        # persist() transactions can deadlock on the urls rows.
                        prelock_urls.append(result.extracted.amphtml)
                    prelock_urls.extend(link.href for link in result.extracted.hreflang_links if link.href)
                if result.discovered_links:
                    # Internal links are bulk-locked again later in
                    # _persist_internal_links; touching them here too means
                    # ALL url rows this transaction will ever lock go through
                    # one combined sorted bulk insert. Without this, two
                    # separate sorted-but-disjoint bulk calls (this one, then
                    # the internal-links one) can still deadlock against each
                    # other when their url sets overlap but are locked in two
                    # different statements.
                    prelock_urls.extend(link.href for link in result.discovered_links if link.href)
                await self._bulk_get_or_create_urls(conn, prelock_urls)

                requested_url_id = await self._get_or_create_url(conn, result.requested_url)
                final_url_id = await self._get_or_create_url(conn, result.final_url)

                # Always store page_metadata for the REQUESTED URL
                # so we know the fetch was attempted and where it landed
                await conn.execute(
                    """
                    INSERT INTO page_metadata
                        (url_id, initial_status_code, final_status_code, final_url_id,
                         fetched_at, ttfb_seconds, total_duration_seconds, lcp_ms, cls, inp_ms)
                    VALUES ($1, $2, $3, $4, EXTRACT(EPOCH FROM NOW())::INTEGER, $5, $6, $7, $8, $9)
                    ON CONFLICT (url_id) DO UPDATE
                    SET initial_status_code = EXCLUDED.initial_status_code,
                        final_status_code = EXCLUDED.final_status_code,
                        final_url_id = EXCLUDED.final_url_id,
                        fetched_at = EXCLUDED.fetched_at,
                        ttfb_seconds = EXCLUDED.ttfb_seconds,
                        total_duration_seconds = EXCLUDED.total_duration_seconds,
                        lcp_ms = EXCLUDED.lcp_ms,
                        cls = EXCLUDED.cls,
                        inp_ms = EXCLUDED.inp_ms
                    """,
                    requested_url_id,
                    result.status,
                    result.status,
                    final_url_id,
                    result.ttfb_seconds,
                    result.total_duration_seconds,
                    result.lcp_ms,
                    result.cls,
                    result.inp_ms,
                )

                if result.extracted is None:
                    # Fetch succeeded/failed but no extractable content
                    return

                # Determine which URL should own the extracted content.
                # If final_url differs from requested_url (JS redirect), the
                # content was served by the final URL, so store against final_url.
                content_url_id = final_url_id if result.final_url != result.requested_url else requested_url_id

                # Also store page_metadata for the final URL if it's different
                # (so it has a metadata record even if never directly crawled)
                if content_url_id != requested_url_id:
                    await conn.execute(
                        """
                        INSERT INTO page_metadata (url_id, initial_status_code, final_status_code, final_url_id, fetched_at)
                        VALUES ($1, $2, $3, $4, EXTRACT(EPOCH FROM NOW())::INTEGER)
                        ON CONFLICT (url_id) DO UPDATE
                        SET initial_status_code = EXCLUDED.initial_status_code,
                            final_status_code = EXCLUDED.final_status_code,
                            final_url_id = EXCLUDED.final_url_id,
                            fetched_at = EXCLUDED.fetched_at
                        """,
                        content_url_id,
                        result.status,
                        result.status,
                        final_url_id,
                    )

                # Store full content against the URL that actually served it
                html_blob = None
                if self.store_html and result.raw_html:
                    html_blob = encode_html_for_storage(
                        result.raw_html,
                        compress=self.compress_html,
                    )
                page_id = await conn.fetchval(
                    """
                    INSERT INTO pages (url_id, headers_json, html_compressed)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (url_id) DO UPDATE
                    SET headers_json = EXCLUDED.headers_json,
                        html_compressed = EXCLUDED.html_compressed
                    RETURNING id
                    """,
                    content_url_id,
                    json.dumps(result.headers, sort_keys=True),
                    html_blob,
                )
                await self._clear_page_snapshot(
                    conn,
                    url_id=content_url_id,
                    page_id=int(page_id) if page_id is not None else None,
                )

                meta_description_id = None
                if result.extracted.meta_description:
                    meta_description_id = await self._get_or_create_lookup(
                        conn,
                        "meta_descriptions",
                        "description",
                        result.extracted.meta_description,
                    )

                html_lang_id = None
                if result.extracted.html_lang:
                    html_lang_id = await self._get_or_create_lookup(
                        conn,
                        "html_languages",
                        "language_code",
                        result.extracted.html_lang,
                    )

                await conn.execute(
                    """
                    INSERT INTO content (
                        url_id, title, meta_description_id, h1_tags, h2_tags, word_count, html_lang_id, content_length
                        , content_hash_sha256, content_hash_simhash, custom_data
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
                    ON CONFLICT (url_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        meta_description_id = EXCLUDED.meta_description_id,
                        h1_tags = EXCLUDED.h1_tags,
                        h2_tags = EXCLUDED.h2_tags,
                        word_count = EXCLUDED.word_count,
                        html_lang_id = EXCLUDED.html_lang_id,
                        content_length = EXCLUDED.content_length,
                        content_hash_sha256 = EXCLUDED.content_hash_sha256,
                        content_hash_simhash = EXCLUDED.content_hash_simhash,
                        custom_data = EXCLUDED.custom_data
                    """,
                    content_url_id,
                    result.extracted.title,
                    meta_description_id,
                    "\n".join(result.extracted.headings["h1"]),
                    "\n".join(result.extracted.headings["h2"]),
                    result.extracted.word_count,
                    html_lang_id,
                    len(result.raw_html or ""),
                    result.content_hash_sha256,
                    simhash_to_signed(result.content_hash_simhash),
                    json.dumps(result.custom_data) if result.custom_data else None,
                )

                await self._persist_directives(conn, content_url_id, result)
                await self._persist_canonical(conn, content_url_id, result)
                await self._persist_amphtml(conn, content_url_id, result)
                await self._persist_hreflang(conn, content_url_id, result)
                if result.extracted.schema_data:
                    await self._persist_schema(conn, content_url_id, result.extracted.schema_data)
                if result.discovered_links:
                    await self._persist_internal_links(
                        conn,
                        content_url_id,
                        result.discovered_links,
                    )
                if result.detected_analytics is not None and page_id is not None:
                    await self._persist_analytics(conn, int(page_id), result.detected_analytics)

                overall_indexable = (
                    result.status == 200
                    and not result.extracted.meta_robots.noindex
                    and not result.extracted.x_robots_tag.noindex
                )
                await conn.execute(
                    """
                    INSERT INTO indexability (url_id, html_meta_allows, http_header_allows, overall_indexable)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (url_id) DO UPDATE
                    SET html_meta_allows = EXCLUDED.html_meta_allows,
                        http_header_allows = EXCLUDED.http_header_allows,
                        overall_indexable = EXCLUDED.overall_indexable
                    """,
                    content_url_id,
                    not result.extracted.meta_robots.noindex,
                    not result.extracted.x_robots_tag.noindex,
                    overall_indexable,
                )

    async def _persist_analytics(
        self,
        conn: asyncpg.Connection,
        page_id: int,
        detected: AnalyticsDetectionResult,
    ) -> None:
        """Persist analytics hits for a page inside the current transaction."""
        if not detected.hits:
            return

        # Seed vendors idempotently
        vendor_rows = [(hit.vendor, hit.category) for hit in detected.hits]
        await conn.executemany(
            """
            INSERT INTO analytics_vendors (vendor, category)
            VALUES ($1, $2)
            ON CONFLICT (vendor) DO NOTHING
            """,
            vendor_rows,
        )

        # Fetch vendor IDs
        vendor_names = [hit.vendor for hit in detected.hits]
        rows = await conn.fetch(
            "SELECT id, vendor FROM analytics_vendors WHERE vendor = ANY($1::text[])",
            vendor_names,
        )
        vendor_to_id = {str(r["vendor"]): int(r["id"]) for r in rows}

        batch = []
        for hit in detected.hits:
            vendor_id = vendor_to_id.get(hit.vendor)
            if vendor_id is None:
                continue
            batch.append(
                (
                    page_id,
                    vendor_id,
                    hit.identifier,
                    hit.evidence_type,
                    hit.evidence_snippet[:200],
                    hit.confidence,
                )
            )

        if batch:
            await conn.executemany(
                """
                INSERT INTO page_analytics_hits
                    (page_id, vendor_id, identifier, evidence_type, evidence_snippet, confidence)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT DO NOTHING
                """,
                batch,
            )

    async def _persist_directives(self, conn: asyncpg.Connection, url_id: int, result: CrawlResult) -> None:
        assert result.extracted is not None
        sources = {
            "html_meta": result.extracted.meta_robots.raw,
            "http_header": result.extracted.x_robots_tag.raw,
        }
        for source, directives in sources.items():
            for directive in directives:
                directive_id = await self._get_or_create_lookup(
                    conn,
                    "robots_directive_strings",
                    "directive",
                    directive,
                )
                await conn.execute(
                    """
                    INSERT INTO robots_directives (url_id, source, directive_id, value)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT DO NOTHING
                    """,
                    url_id,
                    source,
                    directive_id,
                    directive,
                )

    async def _persist_canonical(self, conn: asyncpg.Connection, url_id: int, result: CrawlResult) -> None:
        assert result.extracted is not None
        mappings = [
            ("html_head", result.extracted.canonical),
            ("http_header", result.extracted.x_canonical),
        ]
        for source, canonical_url in mappings:
            if not canonical_url:
                continue
            canonical_url_id = await self._get_or_create_url(conn, canonical_url)
            await conn.execute(
                """
                INSERT INTO canonical_urls (url_id, canonical_url_id, source)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                url_id,
                canonical_url_id,
                source,
            )

    async def _persist_amphtml(self, conn: asyncpg.Connection, url_id: int, result: CrawlResult) -> None:
        """Persist the <link rel="amphtml"> edge (ticket 103), mirroring
        :meth:`_persist_canonical`.  The amphtml href already went through the
        sorted bulk pre-lock in _persist_once, so _get_or_create_url here just
        re-locks a row this transaction already holds."""
        assert result.extracted is not None
        amphtml_url = result.extracted.amphtml
        if not amphtml_url:
            return
        amphtml_url_id = await self._get_or_create_url(conn, amphtml_url)
        await conn.execute(
            """
            INSERT INTO amphtml_urls (url_id, amphtml_url_id, source)
            VALUES ($1, $2, 'html_head')
            ON CONFLICT DO NOTHING
            """,
            url_id,
            amphtml_url_id,
        )

    async def _persist_hreflang(self, conn: asyncpg.Connection, url_id: int, result: CrawlResult) -> None:
        assert result.extracted is not None
        for link in result.extracted.hreflang_links:
            hreflang_id = await self._get_or_create_lookup(
                conn,
                "hreflang_languages",
                "language_code",
                link.hreflang,
            )
            href_url_id = await self._get_or_create_url(
                conn,
                link.href,
                classification="network",
                is_from_hreflang=True,
            )
            table_map = {
                "http_header": "hreflang_http_header",
                "html_head": "hreflang_html_head",
                "sitemap": "hreflang_sitemap",
            }
            table = table_map[link.source]
            await conn.execute(
                f"""
                INSERT INTO {table} (url_id, hreflang_id, href_url_id)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                url_id,
                hreflang_id,
                href_url_id,
            )

    @staticmethod
    def _parse_schema_position(position: object) -> int:
        # ``position`` arrives as a schema-item "position" value pulled from a
        # ``dict[str, object]`` (int index, "<n>-<m>" @graph string, or absent),
        # so its concrete static type at the call site is ``object`` — not an Any
        # widening.  The isinstance ladder narrows it defensively; keeping the
        # param ``object`` (rather than ``int | str | None``) is what lets the
        # ``dict[str, object]`` caller pass through without a cast (ticket 083).
        if position is None:
            return 0
        if isinstance(position, int):
            return position
        if isinstance(position, str):
            try:
                return int(position.split("-")[0])
            except (ValueError, AttributeError):
                return 0
        return 0

    @staticmethod
    def _normalize_schema_format(format_type: str) -> str:
        if format_type in {"json-ld", "microdata", "rdfa"}:
            return format_type
        return "json-ld"

    async def _persist_schema(
        self,
        conn: asyncpg.Connection,
        url_id: int,
        schema_items: list[dict[str, object]],
    ) -> None:
        valid_formats = {"json-ld", "microdata", "rdfa"}
        persistable = [
            item
            for item in schema_items
            if item.get("format") in valid_formats or item.get("format") not in {"meta", "comment"}
        ]
        if not persistable:
            return

        async def get_or_create_schema_type_id(schema_type: str) -> int:
            row = await conn.fetchrow(
                """
                INSERT INTO schema_types (type_name)
                VALUES ($1)
                ON CONFLICT (type_name) DO UPDATE SET type_name = EXCLUDED.type_name
                RETURNING id
                """,
                schema_type,
            )
            return int(row["id"])

        async def get_or_create_schema_instance(schema_data: dict[str, object]) -> int:
            parsed_raw = schema_data.get("parsed_data")
            if parsed_raw:
                parsed_obj = json.loads(parsed_raw) if isinstance(parsed_raw, str) else parsed_raw
            else:
                parsed_obj = {}
            # parsed_obj may be a dict or (for JSON-LD arrays) a list at
            # runtime; create_schema_content_hash normalises both.  The cast
            # documents that rather than narrowing behaviour (ticket-070).
            content_hash = schema_data.get("content_hash") or create_schema_content_hash(
                cast("dict[str, Any]", parsed_obj)
            )
            existing = await conn.fetchrow(
                "SELECT id FROM schema_instances WHERE content_hash = $1",
                content_hash,
            )
            if existing:
                return int(existing["id"])

            schema_type = str(schema_data.get("type", "Unknown"))
            schema_type_id = await get_or_create_schema_type_id(schema_type)
            format_type = self._normalize_schema_format(str(schema_data.get("format", "json-ld")))
            validation_errors = schema_data.get("validation_errors", [])
            row = await conn.fetchrow(
                """
                INSERT INTO schema_instances (
                    content_hash, schema_type_id, format, raw_data, parsed_data,
                    is_valid, validation_errors, severity
                )
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7::jsonb, $8)
                ON CONFLICT (content_hash) DO UPDATE SET content_hash = EXCLUDED.content_hash
                RETURNING id
                """,
                content_hash,
                schema_type_id,
                format_type,
                schema_data.get("raw_data", ""),
                json.dumps(parsed_obj) if parsed_obj else None,
                schema_data.get("is_valid", True),
                json.dumps(validation_errors),
                schema_data.get("severity", "info"),
            )
            return int(row["id"])

        relationships = identify_schema_relationships(persistable)
        main_entity = relationships["main_entity"]
        properties = relationships["properties"]
        related_entities = relationships["related_entities"]
        now_ts = int(time.time())

        async def insert_ref(
            schema_instance_id: int,
            *,
            position: int = 0,
            is_main: bool = False,
            property_name: str | None = None,
            parent_id: int | None = None,
        ) -> int:
            row = await conn.fetchrow(
                """
                INSERT INTO page_schema_references (
                    url_id, schema_instance_id, position, property_name,
                    is_main_entity, parent_entity_id, discovered_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                url_id,
                schema_instance_id,
                position,
                property_name,
                is_main,
                parent_id,
                now_ts,
            )
            return int(row["id"])

        main_ref_id: int | None = None
        if main_entity:
            main_id = await get_or_create_schema_instance(main_entity)
            main_ref_id = await insert_ref(
                main_id,
                position=self._parse_schema_position(main_entity.get("position", 0)),
                is_main=True,
            )

        for prop in properties:
            inst_id = await get_or_create_schema_instance(prop)
            prop_name = str(prop.get("type", "")).lower() if prop.get("type") else None
            await insert_ref(
                inst_id,
                position=self._parse_schema_position(prop.get("position", 0)),
                property_name=prop_name,
                parent_id=main_ref_id,
            )

        for rel in related_entities:
            inst_id = await get_or_create_schema_instance(rel)
            await insert_ref(
                inst_id,
                position=self._parse_schema_position(rel.get("position", 0)),
                parent_id=main_ref_id,
            )

        for item in persistable:
            schema_type = str(item.get("type", "Unknown"))
            schema_type_id = await get_or_create_schema_type_id(schema_type)
            format_type = self._normalize_schema_format(str(item.get("format", "json-ld")))
            parsed_raw = item.get("parsed_data")
            if parsed_raw:
                parsed_json = parsed_raw if isinstance(parsed_raw, str) else json.dumps(parsed_raw)
            else:
                parsed_json = None
            await conn.execute(
                """
                INSERT INTO schema_data (
                    url_id, schema_type_id, format, raw_data, parsed_data,
                    position, is_valid, validation_errors, severity
                )
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8::jsonb, $9)
                ON CONFLICT (url_id, schema_type_id, position) DO UPDATE
                SET raw_data = EXCLUDED.raw_data,
                    parsed_data = EXCLUDED.parsed_data,
                    is_valid = EXCLUDED.is_valid,
                    validation_errors = EXCLUDED.validation_errors,
                    severity = EXCLUDED.severity
                """,
                url_id,
                schema_type_id,
                format_type,
                item.get("raw_data", ""),
                parsed_json,
                self._parse_schema_position(item.get("position", 0)),
                item.get("is_valid", True),
                json.dumps(item.get("validation_errors", [])),
                item.get("severity", "info"),
            )

    async def _persist_internal_links(
        self,
        conn: asyncpg.Connection,
        source_url_id: int,
        links: list[DiscoveredLink],
    ) -> None:
        if not links:
            return

        now_ts = int(time.time())
        batch: list[tuple[int, int | None, int | None, int | None, int, int | None, str | None, int]] = []
        seen: set[tuple[int, int, int | None, int | None, int | None, str | None]] = set()

        hrefs = [link.href for link in links]
        anchors = [link.anchor_text for link in links if link.anchor_text]
        xpaths = [link.xpath for link in links if link.xpath]
        fragments = [link.fragment for link in links if link.fragment]

        href_map = await self._bulk_get_or_create_urls(conn, hrefs)
        anchor_map = await self._bulk_get_or_create_lookups(conn, "anchor_texts", "text", anchors)
        xpath_map = await self._bulk_get_or_create_lookups(conn, "xpaths", "xpath", xpaths)
        fragment_map = await self._bulk_get_or_create_lookups(conn, "fragments", "fragment", fragments)

        for link in links:
            href_url_id = href_map.get(link.href)
            if not href_url_id:
                continue
            target_url_id = href_url_id

            anchor_text_id = anchor_map.get(link.anchor_text) if link.anchor_text else None
            xpath_id = xpath_map.get(link.xpath) if link.xpath else None
            fragment_id = fragment_map.get(link.fragment) if link.fragment else None

            dedupe_key = (
                source_url_id,
                href_url_id,
                anchor_text_id,
                xpath_id,
                fragment_id,
                link.url_parameters,
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            batch.append(
                (
                    source_url_id,
                    target_url_id,
                    anchor_text_id,
                    xpath_id,
                    href_url_id,
                    fragment_id,
                    link.url_parameters,
                    now_ts,
                )
            )

        if batch:
            await conn.executemany(
                """
                INSERT INTO internal_links (
                    source_url_id, target_url_id, anchor_text_id, xpath_id,
                    href_url_id, fragment_id, url_parameters, discovered_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (source_url_id, target_url_id, xpath_id) DO NOTHING
                """,
                batch,
            )

    async def fetch_pages_for_embeddings(
        self,
        *,
        urls: list[str] | None = None,
    ) -> list[tuple[int, str, str]]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            if urls:
                rows = await conn.fetch(
                    """
                    SELECT p.url_id, u.url, p.html_compressed
                    FROM pages p
                    JOIN urls u ON u.id = p.url_id
                    WHERE u.url = ANY($1::text[]) AND p.html_compressed IS NOT NULL
                    """,
                    urls,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT p.url_id, u.url, p.html_compressed
                    FROM pages p
                    JOIN urls u ON u.id = p.url_id
                    WHERE p.html_compressed IS NOT NULL
                    """
                )
        return [(int(row["url_id"]), str(row["url"]), decompress_html(bytes(row["html_compressed"]))) for row in rows]

    async def embedding_url_ids(self, *, model: str) -> set[int]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT url_id FROM page_embeddings WHERE model = $1",
                model,
            )
        return {int(row["url_id"]) for row in rows}

    async def store_embedding(
        self,
        url_id: int,
        embedding: list[float],
        *,
        model: str,
        text_length: int,
        signature_hash: str | None = None,
    ) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO page_embeddings
                    (url_id, embedding_json, model, text_length, signature_hash, dim)
                VALUES ($1, $2::jsonb, $3, $4, $5, $6)
                ON CONFLICT (url_id) DO UPDATE
                SET embedding_json = EXCLUDED.embedding_json,
                    model = EXCLUDED.model,
                    text_length = EXCLUDED.text_length,
                    signature_hash = EXCLUDED.signature_hash,
                    dim = EXCLUDED.dim,
                    created_at = CURRENT_TIMESTAMP
                """,
                url_id,
                json.dumps(embedding),
                model,
                text_length,
                signature_hash,
                len(embedding),
            )

    async def fetch_signature_rows_for_embeddings(
        self,
        *,
        urls: list[str] | None = None,
    ) -> list[SignatureEmbeddingRow]:
        """Return intent-signature rows joined with any existing embedding, for
        hash-gated signature embedding (ticket 077).

        Each row carries the signature input text, its current ``signature_hash``,
        and the ``signature_hash``/``model`` recorded on the last embedding so
        the caller can skip unchanged pages.
        """
        await self.connect()
        assert self.pool is not None
        base_query = """
            SELECT s.url_id, u.url, s.signature_model_input AS text,
                   s.signature_hash,
                   e.signature_hash AS embedded_hash, e.model AS embedded_model
            FROM intent_signatures s
            JOIN urls u ON u.id = s.url_id
            LEFT JOIN page_embeddings e ON e.url_id = s.url_id
            WHERE s.signature_model_input IS NOT NULL
        """
        async with self.pool.acquire() as conn:
            if urls:
                rows = await conn.fetch(base_query + " AND u.url = ANY($1::text[])", urls)
            else:
                rows = await conn.fetch(base_query)
        return [
            {
                "url_id": int(row["url_id"]),
                "url": str(row["url"]),
                "text": row["text"],
                "signature_hash": row["signature_hash"],
                "embedded_hash": row["embedded_hash"],
                "embedded_model": row["embedded_model"],
            }
            for row in rows
        ]

    async def embedding_models(self) -> list[str]:
        """Distinct embedding models present in page_embeddings (mixed-model
        guard support, ticket 077 / enforced in 079)."""
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT DISTINCT model FROM page_embeddings ORDER BY model")
        return [str(row["model"]) for row in rows]

    async def fetch_pages_for_signatures(
        self,
        *,
        urls: list[str] | None = None,
    ) -> list[SignaturePageRow]:
        """Return stored HTML pages joined with title/h1/meta for signature
        computation (ticket 076)."""
        await self.connect()
        assert self.pool is not None
        base_query = """
            SELECT p.url_id, u.url, p.html_compressed,
                   c.title, c.h1_tags AS h1, md.description AS meta_description
            FROM pages p
            JOIN urls u ON u.id = p.url_id
            LEFT JOIN content c ON c.url_id = p.url_id
            LEFT JOIN meta_descriptions md ON md.id = c.meta_description_id
            WHERE p.html_compressed IS NOT NULL
        """
        async with self.pool.acquire() as conn:
            if urls:
                rows = await conn.fetch(base_query + " AND u.url = ANY($1::text[])", urls)
            else:
                rows = await conn.fetch(base_query)
        return [
            {
                "url_id": int(row["url_id"]),
                "url": str(row["url"]),
                "html": decompress_html(bytes(row["html_compressed"])),
                "title": row["title"],
                "h1": row["h1"],
                "meta_description": row["meta_description"],
            }
            for row in rows
        ]

    async def existing_signature_hashes(self) -> dict[int, str]:
        """Map url_id -> stored signature_hash (ticket 076 gating)."""
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT url_id, signature_hash FROM intent_signatures WHERE signature_hash IS NOT NULL"
            )
        return {int(row["url_id"]): str(row["signature_hash"]) for row in rows}

    async def store_intent_signatures_bulk(self, rows: list[IntentSignatureRow]) -> None:
        """Upsert intent-signature rows (ticket 076).

        Each row carries ``url_id``, ``main_text`` (compressed on write),
        ``extraction_method``, ``signal_confidence``, ``signature_hash`` and
        ``signature_model_input`` provenance.
        """
        if not rows:
            return
        await self.connect()
        assert self.pool is not None
        batch = [
            (
                int(r["url_id"]),
                compress_html(r["main_text"]) if r.get("main_text") is not None else None,
                r.get("extraction_method"),
                r.get("signal_confidence"),
                r.get("signature_hash"),
                r.get("signature_model_input"),
            )
            for r in rows
        ]
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO intent_signatures
                    (url_id, main_text_compressed, extraction_method, signal_confidence,
                     signature_hash, signature_model_input, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, NOW())
                ON CONFLICT (url_id) DO UPDATE
                SET main_text_compressed = EXCLUDED.main_text_compressed,
                    extraction_method = EXCLUDED.extraction_method,
                    signal_confidence = EXCLUDED.signal_confidence,
                    signature_hash = EXCLUDED.signature_hash,
                    signature_model_input = EXCLUDED.signature_model_input,
                    updated_at = NOW()
                """,
                batch,
            )

    async def fetch_hreflang_edges(self) -> list[tuple[str, str, str | None]]:
        """All crawler-captured hreflang edges (url, alt_url, code) unioned from
        the three edge tables (ticket 078). 100% crawler-derived."""
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT su.url AS url, tu.url AS alt_url, hl.language_code AS code
                FROM (
                    SELECT url_id, href_url_id, hreflang_id FROM hreflang_http_header
                    UNION ALL
                    SELECT url_id, href_url_id, hreflang_id FROM hreflang_html_head
                    UNION ALL
                    SELECT url_id, href_url_id, hreflang_id FROM hreflang_sitemap
                ) e
                JOIN urls su ON su.id = e.url_id
                JOIN urls tu ON tu.id = e.href_url_id
                JOIN hreflang_languages hl ON hl.id = e.hreflang_id
                """
            )
        return [(str(r["url"]), str(r["alt_url"]), r["code"]) for r in rows]

    async def fetch_pages_for_identity(self) -> list[IdentityPageRow]:
        """Fetched pages with the fields needed for language + variant
        resolution (ticket 078)."""
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.id AS url_id, u.url AS url,
                       hl.language_code AS html_lang,
                       pm.final_status_code AS status,
                       c.word_count AS word_count,
                       fu.url AS final_url
                FROM urls u
                JOIN page_metadata pm ON pm.url_id = u.id
                LEFT JOIN content c ON c.url_id = u.id
                LEFT JOIN html_languages hl ON hl.id = c.html_lang_id
                LEFT JOIN urls fu ON fu.id = pm.final_url_id
                """
            )
        return [
            {
                "url_id": int(r["url_id"]),
                "url": str(r["url"]),
                "html_lang": r["html_lang"],
                "status": r["status"],
                "word_count": r["word_count"],
                "final_url": r["final_url"],
            }
            for r in rows
        ]

    async def store_hreflang_identity(self, rows: list[HreflangIdentityRow]) -> None:
        """Bulk-update urls with norm_url / hreflang_group / resolved code /
        lang_bucket (ticket 078)."""
        if not rows:
            return
        await self.connect()
        assert self.pool is not None
        batch = [
            (
                int(r["url_id"]),
                r.get("norm_url"),
                r.get("hreflang_group"),
                r.get("resolved_hreflang_code"),
                r.get("lang_bucket"),
            )
            for r in rows
        ]
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                UPDATE urls
                SET norm_url = $2,
                    hreflang_group = $3,
                    resolved_hreflang_code = $4,
                    lang_bucket = $5
                WHERE id = $1
                """,
                batch,
            )

    async def store_url_variants(self, variant_pairs: list[tuple[int, int]]) -> None:
        """Set urls.variant_of_id for folded variants (ticket 078).  Reps and
        non-variants are reset to NULL first so a rebuild is idempotent."""
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("UPDATE urls SET variant_of_id = NULL WHERE variant_of_id IS NOT NULL")
                if variant_pairs:
                    await conn.executemany(
                        "UPDATE urls SET variant_of_id = $2 WHERE id = $1",
                        variant_pairs,
                    )

    async def fetch_url_variant_rows(self) -> list[UrlVariantRow]:
        """Variant groups (norm_url, representative, variants) for reporting
        (ticket 078; CSV written by ticket 079)."""
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.url AS url, u.norm_url AS norm_url, r.url AS representative
                FROM urls u
                LEFT JOIN urls r ON r.id = u.variant_of_id
                WHERE u.norm_url IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM urls u2
                    WHERE u2.norm_url = u.norm_url AND u2.id <> u.id
                  )
                ORDER BY u.norm_url, u.url
                """
            )
        return [
            {
                "url": str(r["url"]),
                "norm_url": str(r["norm_url"]),
                "representative": r["representative"],
            }
            for r in rows
        ]

    async def classify_amp_variants(self) -> list[AmpHygieneRow]:
        """Classify AMP variants structurally and record ``variant_kind='amp'``
        on their URL identity (ticket 103).

        Uses only crawler-captured evidence — the ``rel="amphtml"`` edges in
        ``amphtml_urls``, AMP URL shape, canonical edges and content hashes —
        via the pure :func:`crawler_cli.amp.classify_amp_variants`.  Idempotent:
        re-running only ever (re)sets ``variant_kind`` to ``'amp'``.

        Returns one :class:`AmpHygieneRow` per classified AMP page for the
        canonical-hygiene report (``amp_issues.csv``)."""
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            page_rows = await conn.fetch(
                """
                SELECT u.id AS url_id, u.url AS url,
                       c.content_hash_sha256 AS content_hash,
                       canu.url AS canonical_url
                FROM urls u
                JOIN page_metadata pm ON pm.url_id = u.id
                LEFT JOIN content c ON c.url_id = u.id
                LEFT JOIN LATERAL (
                    SELECT cu.canonical_url_id
                    FROM canonical_urls cu
                    WHERE cu.url_id = u.id
                    ORDER BY cu.id
                    LIMIT 1
                ) can ON TRUE
                LEFT JOIN urls canu ON canu.id = can.canonical_url_id
                -- Only pages actually served (200) are AMP-hygiene candidates:
                -- a non-200 AMP URL is reported as non-200, not as a missing
                -- canonical, and compute_exclusion ranks non-200 first anyway.
                WHERE pm.final_status_code = 200
                """
            )
            amphtml_rows = await conn.fetch(
                """
                SELECT au.amphtml_url_id AS target_id, base.url AS base_url
                FROM amphtml_urls au
                JOIN urls base ON base.id = au.url_id
                """
            )

        pages = [
            {
                "url_id": int(r["url_id"]),
                "url": str(r["url"]),
                "canonical_url": r["canonical_url"],
                "content_hash": r["content_hash"],
            }
            for r in page_rows
        ]
        amphtml_base_by_target = {int(r["target_id"]): str(r["base_url"]) for r in amphtml_rows}
        canonical_by_id = {int(r["url_id"]): r["canonical_url"] for r in page_rows}

        classifications = classify_amp_variants(pages, amphtml_base_by_target)
        if not classifications:
            return []

        amp_ids = [c.url_id for c in classifications]
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE urls SET variant_kind = $1 WHERE id = ANY($2::int[])",
                    VARIANT_KIND_AMP,
                    sorted(amp_ids),
                )

        hygiene: list[AmpHygieneRow] = []
        for c in classifications:
            canonical = canonical_by_id.get(c.url_id)
            if not canonical:
                issue = "missing-canonical"
            elif c.base_url and urls_match(str(canonical), c.base_url):
                issue = ""
            else:
                # Canonical present but not pointing at the detected base page.
                issue = "canonical-not-base"
            hygiene.append(
                {
                    "url": c.url,
                    "base_url": c.base_url or "",
                    "variant_kind": VARIANT_KIND_AMP,
                    "confirmed_by": c.confirmed_by,
                    "canonical_url": str(canonical) if canonical else "",
                    "has_canonical": bool(canonical),
                    "issue": issue,
                }
            )
        hygiene.sort(key=lambda row: row["url"])
        return hygiene

    async def fetch_analysis_rows(self) -> list[AnalysisRow]:
        """Load every fetched page with the fields the intent-overlap analysis
        needs, including its embedding vector (ticket 079)."""
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.id AS url_id, u.url AS url, u.kind AS kind,
                       u.norm_url AS norm_url, u.hreflang_group AS hreflang_group,
                       u.resolved_hreflang_code AS hreflang_code,
                       u.variant_kind AS variant_kind,
                       vu.url AS variant_of,
                       pm.final_status_code AS status,
                       c.title AS title, c.h1_tags AS h1, c.word_count AS word_count,
                       s.main_text_compressed AS main_text_compressed,
                       ix.overall_indexable AS overall_indexable,
                       s.signal_confidence AS signal_confidence,
                       s.extraction_method AS extraction_method,
                       s.signature_hash AS signature_hash,
                       s.signature_model_input AS signature_model_input,
                       e.embedding_json AS embedding_json, e.model AS embedding_model,
                       canu.url AS canonical_url
                FROM urls u
                JOIN page_metadata pm ON pm.url_id = u.id
                LEFT JOIN urls vu ON vu.id = u.variant_of_id
                LEFT JOIN content c ON c.url_id = u.id
                LEFT JOIN indexability ix ON ix.url_id = u.id
                LEFT JOIN intent_signatures s ON s.url_id = u.id
                LEFT JOIN page_embeddings e ON e.url_id = u.id
                LEFT JOIN LATERAL (
                    SELECT cu.canonical_url_id
                    FROM canonical_urls cu
                    WHERE cu.url_id = u.id
                    ORDER BY cu.id
                    LIMIT 1
                ) can ON TRUE
                LEFT JOIN urls canu ON canu.id = can.canonical_url_id
                """
            )
        out: list[AnalysisRow] = []
        for r in rows:
            embedding = None
            raw = r["embedding_json"]
            if raw is not None:
                embedding = json.loads(raw) if isinstance(raw, str) else raw
            main_text = None
            raw_main_text = r["main_text_compressed"]
            if raw_main_text is not None:
                main_text = decompress_html(bytes(raw_main_text))
            out.append(
                {
                    "url_id": int(r["url_id"]),
                    "url": str(r["url"]),
                    "kind": r["kind"],
                    "norm_url": r["norm_url"],
                    "hreflang_group": r["hreflang_group"],
                    "hreflang_code": r["hreflang_code"],
                    "variant_of": r["variant_of"],
                    "status": r["status"],
                    "title": r["title"],
                    "h1": r["h1"],
                    "word_count": r["word_count"],
                    "main_text": main_text,
                    "overall_indexable": r["overall_indexable"],
                    "signal_confidence": r["signal_confidence"],
                    "extraction_method": r["extraction_method"],
                    "signature_model_input": r["signature_model_input"],
                    "embedding": embedding,
                    "embedding_model": r["embedding_model"],
                    "canonical_url": r["canonical_url"],
                    "signature_hash": r["signature_hash"],
                    "variant_kind": r["variant_kind"],
                }
            )
        return out

    async def hreflang_group_summary(self) -> dict[str, int]:
        """Counts of groups and grouped URLs (ticket 078)."""
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            groups = await conn.fetchval(
                "SELECT COUNT(DISTINCT hreflang_group) FROM urls WHERE hreflang_group IS NOT NULL"
            )
            grouped_urls = await conn.fetchval("SELECT COUNT(*) FROM urls WHERE hreflang_group IS NOT NULL")
        return {"groups": int(groups or 0), "grouped_urls": int(grouped_urls or 0)}

    async def persist_comparison_session(
        self,
        *,
        baseline_label: str,
        candidate_label: str,
        rows: list[dict[str, object]],
    ) -> int:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                session_id = await conn.fetchval(
                    """
                    INSERT INTO crawl_comparison_sessions (baseline_label, candidate_label)
                    VALUES ($1, $2)
                    RETURNING id
                    """,
                    baseline_label,
                    candidate_label,
                )
                batch = [
                    (
                        session_id,
                        row["path"],
                        row.get("baseline_url"),
                        row.get("candidate_url"),
                        row.get("exists_on_baseline", False),
                        row.get("exists_on_candidate", False),
                        row.get("baseline_title"),
                        row.get("candidate_title"),
                        row.get("baseline_h1"),
                        row.get("candidate_h1"),
                        row.get("baseline_meta_description"),
                        row.get("candidate_meta_description"),
                        row.get("baseline_word_count"),
                        row.get("candidate_word_count"),
                        row.get("is_moved_content", False),
                        row.get("moved_from_path"),
                        row.get("moved_to_path"),
                        row.get("redirect_chain"),
                        json.dumps(row.get("baseline_schema_types", [])),
                        json.dumps(row.get("candidate_schema_types", [])),
                        json.dumps(row.get("links_added", [])),
                        json.dumps(row.get("links_removed", [])),
                    )
                    for row in rows
                ]
                if batch:
                    await conn.executemany(
                        """
                        INSERT INTO crawl_comparison_urls (
                            session_id, path, baseline_url, candidate_url,
                            exists_on_baseline, exists_on_candidate,
                            baseline_title, candidate_title,
                            baseline_h1, candidate_h1,
                            baseline_meta_description, candidate_meta_description,
                            baseline_word_count, candidate_word_count,
                            is_moved_content, moved_from_path, moved_to_path, redirect_chain,
                            baseline_schema_types, candidate_schema_types,
                            links_added, links_removed
                        )
                        VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                            $15, $16, $17, $18, $19::jsonb, $20::jsonb, $21::jsonb, $22::jsonb
                        )
                        ON CONFLICT (session_id, path) DO UPDATE
                        SET baseline_url = EXCLUDED.baseline_url,
                            candidate_url = EXCLUDED.candidate_url,
                            exists_on_baseline = EXCLUDED.exists_on_baseline,
                            exists_on_candidate = EXCLUDED.exists_on_candidate,
                            baseline_title = EXCLUDED.baseline_title,
                            candidate_title = EXCLUDED.candidate_title,
                            baseline_h1 = EXCLUDED.baseline_h1,
                            candidate_h1 = EXCLUDED.candidate_h1,
                            baseline_meta_description = EXCLUDED.baseline_meta_description,
                            candidate_meta_description = EXCLUDED.candidate_meta_description,
                            baseline_word_count = EXCLUDED.baseline_word_count,
                            candidate_word_count = EXCLUDED.candidate_word_count,
                            is_moved_content = EXCLUDED.is_moved_content,
                            moved_from_path = EXCLUDED.moved_from_path,
                            moved_to_path = EXCLUDED.moved_to_path,
                            redirect_chain = EXCLUDED.redirect_chain,
                            baseline_schema_types = EXCLUDED.baseline_schema_types,
                            candidate_schema_types = EXCLUDED.candidate_schema_types,
                            links_added = EXCLUDED.links_added,
                            links_removed = EXCLUDED.links_removed
                        """,
                        batch,
                    )
                return int(session_id)

    async def table_row_counts(self) -> dict[str, int]:
        await self.connect()
        assert self.pool is not None
        counts: dict[str, int] = {}
        async with self.pool.acquire() as conn:
            for table in CRAWL_TABLES:
                value = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                counts[table] = int(value or 0)
        return counts

    async def pages_relation_bytes(self) -> int:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            value = await conn.fetchval("SELECT COALESCE(pg_total_relation_size('pages'::regclass), 0)")
        return int(value or 0)

    async def html_storage_stats(self) -> dict[str, int]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM pages WHERE html_compressed IS NOT NULL")
            legacy = await conn.fetchval(
                """
                SELECT COUNT(*) FROM pages
                WHERE html_compressed IS NOT NULL
                  AND (length(html_compressed) = 0 OR get_byte(html_compressed, 0) <> 1)
                """
            )
            with_html = await conn.fetchval(
                """
                SELECT COUNT(*) FROM pages p
                JOIN page_metadata pm ON pm.url_id = p.url_id
                WHERE p.html_compressed IS NOT NULL
                """
            )
            missing_hash = await conn.fetchval(
                """
                SELECT COUNT(*) FROM pages p
                WHERE p.html_compressed IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM content c
                    WHERE c.url_id = p.url_id AND c.content_hash_sha256 IS NOT NULL
                  )
                """
            )
        return {
            "pages_with_html": int(total or 0),
            "pages_legacy_uncompressed": int(legacy or 0),
            "pages_with_metadata_and_html": int(with_html or 0),
            "pages_with_html_missing_hash": int(missing_hash or 0),
        }

    async def truncate_crawl_tables(self) -> None:
        await self.connect()
        assert self.pool is not None
        table_list = ", ".join(CRAWL_TABLES)
        async with self.pool.acquire() as conn:
            await conn.execute(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE")

    async def drop_crawl_database(self, *, maintenance_dsn: str | None = None) -> None:
        db_name = database_name_from_dsn(self.dsn)
        if maintenance_dsn is None:
            parsed = urlparse(self.dsn)
            maintenance_dsn = (
                f"{parsed.scheme}://{parsed.netloc}/postgres"
                if parsed.scheme
                else self.dsn.rsplit("/", 1)[0] + "/postgres"
            )
        admin = await asyncpg.connect(maintenance_dsn)
        try:
            await admin.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = $1 AND pid <> pg_backend_pid()
                """,
                db_name,
            )
            await admin.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        finally:
            await admin.close()
        await self.close()

    async def compact_html_storage(
        self,
        *,
        batch_size: int = 500,
        dry_run: bool = False,
    ) -> dict[str, int]:
        await self.connect()
        assert self.pool is not None
        bytes_before = await self.pages_relation_bytes()
        updated = 0
        skipped = 0
        async with self.pool.acquire() as conn:
            while True:
                rows = await conn.fetch(
                    """
                    SELECT url_id, html_compressed
                    FROM pages
                    WHERE html_compressed IS NOT NULL
                      AND (length(html_compressed) = 0 OR get_byte(html_compressed, 0) <> $1)
                    ORDER BY url_id
                    LIMIT $2
                    """,
                    1,
                    batch_size,
                )
                if not rows:
                    break
                for row in rows:
                    raw = bytes(row["html_compressed"])
                    if is_compressed(raw):
                        skipped += 1
                        continue
                    text = decompress_html(raw)
                    compressed = compress_html(text)
                    if dry_run:
                        updated += 1
                        continue
                    await conn.execute(
                        "UPDATE pages SET html_compressed = $2 WHERE url_id = $1",
                        int(row["url_id"]),
                        compressed,
                    )
                    updated += 1
        bytes_after = bytes_before if dry_run else await self.pages_relation_bytes()
        return {
            "rows_updated": updated,
            "rows_skipped_already_compressed": skipped,
            "pages_bytes_before": bytes_before,
            "pages_bytes_after": bytes_after,
        }

    async def backfill_content_hashes(
        self,
        *,
        batch_size: int = 500,
        dry_run: bool = False,
    ) -> dict[str, int]:
        await self.connect()
        assert self.pool is not None
        updated = 0
        async with self.pool.acquire() as conn:
            while True:
                rows = await conn.fetch(
                    """
                    SELECT p.url_id, p.html_compressed
                    FROM pages p
                    WHERE p.html_compressed IS NOT NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM content c
                        WHERE c.url_id = p.url_id AND c.content_hash_sha256 IS NOT NULL
                      )
                    ORDER BY p.url_id
                    LIMIT $1
                    """,
                    batch_size,
                )
                if not rows:
                    break
                for row in rows:
                    html = decompress_html(bytes(row["html_compressed"]))
                    sha = sha256_hash(html)
                    sim = simhash64(html)
                    if dry_run:
                        updated += 1
                        continue
                    await conn.execute(
                        """
                        INSERT INTO content (url_id, content_hash_sha256, content_hash_simhash, content_length)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (url_id) DO UPDATE
                        SET content_hash_sha256 = EXCLUDED.content_hash_sha256,
                            content_hash_simhash = EXCLUDED.content_hash_simhash,
                            content_length = COALESCE(content.content_length, EXCLUDED.content_length)
                        """,
                        int(row["url_id"]),
                        sha,
                        sim,
                        len(html),
                    )
                    updated += 1
        return {"rows_updated": updated}

    async def purge_stored_html(
        self,
        *,
        drop_headers: bool = False,
        vacuum: bool = False,
        dry_run: bool = False,
    ) -> dict[str, int]:
        await self.connect()
        assert self.pool is not None
        bytes_before = await self.pages_relation_bytes()
        async with self.pool.acquire() as conn:
            with_html = await conn.fetchval("SELECT COUNT(*) FROM pages WHERE html_compressed IS NOT NULL")
            if dry_run:
                bytes_after = bytes_before
            else:
                if drop_headers:
                    await conn.execute(
                        """
                        UPDATE pages
                        SET html_compressed = NULL, headers_json = NULL
                        WHERE html_compressed IS NOT NULL OR headers_json IS NOT NULL
                        """
                    )
                else:
                    await conn.execute("UPDATE pages SET html_compressed = NULL WHERE html_compressed IS NOT NULL")
                if vacuum:
                    await conn.execute("VACUUM ANALYZE pages")
                bytes_after = await self.pages_relation_bytes()
        return {
            "pages_cleared": int(with_html or 0),
            "pages_bytes_before": bytes_before,
            "pages_bytes_after": bytes_after,
        }
