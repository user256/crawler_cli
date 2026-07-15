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
    url_class, variant_kind, signature_words, word_count, section,
    signal_confidence, max_similarity, nearest_url, suggested_canonical,
    centroid_similarity (cosine to the site centroid — the Colab
    "authority score"), off_topic flag (bottom percentile of
    centroid_similarity, threshold in the envelope).
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
planned (2026-07-15) — prerequisites 101–105 are merged. Finalise the page and
variant schema after the bounded 108/109 evidence/diagnostic remediations so
ticket 107 can consume a stable contract.
