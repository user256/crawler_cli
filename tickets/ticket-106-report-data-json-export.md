# Ticket 106: Machine-readable JSON export of the intent-overlap report (+ 2D/3D projection coords)

## Goal
The six CSVs are good for spreadsheets but poor as a data source for any
interactive front-end. Emit one `report_data.json` alongside them containing
the full analysis result — pages, pairs, clusters, summary, and a
low-dimensional projection of each page's embedding — so an HTML viewer
(ticket 107) or any other consumer can render the crawl without re-querying
Postgres or re-parsing CSVs.

## Background
- The user's prior standalone workflow (Colab: Screaming Frog embeddings CSV
  → UMAP 3D → KMeans → plotly scatter with hover/legend toggles) proves the
  visualisation value; this ticket ports the *data* half crawler-natively.
  Reference script saved at the conversation level; key carry-overs: UMAP
  projection, per-cluster membership, centroid-similarity "authority" metric,
  off-topic outlier flag.
- Everything needed is already in the store or computed during analysis:
  normalized vectors (`page_embeddings`), cluster membership, risk labels,
  and — once tickets 101–105 merge — pair `relation`/`section`, `pair_class`
  (time-sequenced), `thin`, `url_class` (parameterised), `variant_kind`
  (amp). This ticket should land AFTER those merges and include their fields.
- `run_manifest.json` already establishes the JSON-envelope convention
  (version/timestamp/args/summary) — extend that pattern, don't invent a new
  one.

## Tasks
- New output `report_data.json` written by `write_reports` (or a sibling
  function) when a new `--json-report` flag is passed to `intent-overlap`
  (default off; file can be a few MB on large crawls).
- Envelope: `version`, `generated_at`, `embedding_model`, `thresholds`,
  the existing summary block, plus:
  - `pages[]`: url, cluster_id, coords (see below), risk, excluded reason,
    url_class, variant_kind, word_count, main_text_words, main_text_chars,
    signature_words, signature_chars, section, signal_confidence,
    max_similarity, nearest_url, suggested_canonical, centroid_similarity
    (cosine to the site centroid — the Colab "authority score"), off_topic
    flag (bottom percentile of centroid_similarity, threshold in the
    envelope).

#### `pages[]` diagnostic length contract (shared with `pages.csv`)

Ticket 109 / 113: JSON export and the interactive report must expose the
same thin-content diagnostic surface as `pages.csv`. Required fields:

| Field | Meaning |
| --- | --- |
| `word_count` | Raw crawled page word count (chrome-inflated; contrast only) |
| `main_text_words` | Word count of extracted `main_text` |
| `main_text_chars` | Character length of extracted `main_text` |
| `signature_words` | Word count of `signature_model_input` (embedded text) |
| `signature_chars` | Character length of `signature_model_input` |
| `signal_confidence` | Extraction confidence (`high` / `low`) |

Missing evidence stays distinct from measured zeros (null/absent vs `0`).
Do not omit the three post-109 fields (`main_text_words`,
`main_text_chars`, `signature_chars`) from the exporter or report viewer.

  - `pairs[]`: url_a, url_b, similarity, relation, pair_class, thin,
    sim_percentile.
  - `clusters[]`: id, member urls, size, suggested_canonical/action,
    time_sequenced/thin/relation flags, plus a **crawler-native label**:
    derive from the members' longest common path prefix + top distinguishing
    terms from their signatures (NO external LLM calls — the Colab script's
    GPT labelling is explicitly out of scope; stay 100% crawler-powered).
- Projection: 2D (and optionally 3D) coords per embedded page.
  - UMAP via a new optional `[viz]` extra (`umap-learn`), lazily imported
    with the standard "install the extra" error message pattern.
  - Deterministic (fixed seed) so re-runs diff cleanly.
  - PCA fallback via numpy (already required by the analysis) when
    umap-learn is absent — degraded but functional, and note which method
    was used in the envelope (`projection: {method, dims, seed}`).
  - Excluded pages get no coords (they're not embedded/compared) but still
    appear in `pages[]` with their exclusion reason so the viewer can show
    "what was filtered and why".
- Size guard: log the file size; above ~50k pages skip pair listing below a
  configurable similarity floor (`--json-min-similarity`, default = the
  overlap threshold) — pairs are the O(N²) risk, pages/clusters are linear.
- Tests: envelope shape, determinism (two runs → identical JSON given same
  seed), PCA fallback path, exclusion rows without coords, cluster label
  derivation, size-floor behaviour.

## Definition of Done
- `intent-overlap --json-report` on the thompsons-scotland store produces a
  `report_data.json` that validates against the documented schema, contains
  coords for all 2409 embedded pages, carries the 101–105 tag fields, and is
  deterministic across re-runs. ruff/mypy/tests green; README documents the
  flag, the `[viz]` extra, and the schema (short table of top-level keys).

## Constraint
100% crawler-powered. No LLM/API calls for cluster labelling — labels derive
from URL paths and stored signatures only. Output lands in the run's `--out`
dir (never committed; runs/ is untracked).

## Status
`done` (2026-07-15) — `intent-overlap --json-report` writes `report_data.json`
(pages/pairs/clusters + 2D UMAP-or-PCA coords, crawler-native cluster labels,
centroid-similarity / off-topic). Schema includes `main_text_words` /
`main_text_chars` / `signature_chars` alongside signature/word diagnostics.
Optional `[viz]` extra for umap-learn; PCA fallback via numpy. ruff/mypy/tests
green.
