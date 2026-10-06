# Ticket 175: Align concurrency defaults and `skip_sitemaps` fingerprint

## Goal
One concurrency default across library and CLI, and honest resume fingerprints
when `--skip-sitemaps` is used.

## Background (2026-07-22 wiring audit)

- `CrawlConfig.max_concurrency` defaults to **10** (`config.py`).
- CLI `_resolve_concurrency` defaults to **15** (`__main__.py`); help text
  says 15. Same binary, two defaults depending on entry path.
- `--skip-sitemaps` only sets `discover_sitemaps=not flag`. `skip_sitemaps`
  stays `False` but is included in `_crawl_run_config_snapshot` /
  resume hashing (`engine.py`). Two configs that both skip sitemaps via
  different fields can disagree in the hash, and CLI skips never set the
  dedicated field.

## Tasks
- Pick a single documented concurrency default; align `CrawlConfig`, CLI
  default, and help.
- Normalise sitemap intent to one effective value before resume hashing (for
  example `sitemap_discovery_enabled = discover_sitemaps and not
  skip_sitemaps`), or enforce one canonical configuration invariant. Merely
  setting both CLI fields does not stop semantically identical library configs
  (`False/False`, `True/True`, `False/True`) from hashing differently.
- Keep CLI fields internally consistent for `--skip-sitemaps`, but hash the
  canonical effective behaviour rather than both raw aliases.
- Fingerprint/resume tests prove CLI and library configurations with equivalent
  sitemap behaviour have the same hash, while enabled vs disabled still differ.
- Brief README note if the chosen default changes either side.

## Definition of Done
- Library and CLI share one default concurrency.
- Resume compatibility hashes effective sitemap behaviour once; equivalent
  configurations cannot spuriously mismatch.
- Tests cover both.

## Status
proposed (Priority: **P3**) — config/docs drift; found in 2026-07-22 audit.
