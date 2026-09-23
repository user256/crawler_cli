# Ticket 176: Make GUI List `maxPages` honest

## Goal

Stop the GUI from presenting and forwarding a List-mode page limit that
`crawler_cli` silently ignores.

## Background (2026-07-22 ticket review)

The GUI Configuration modal exposes “Max pages” for both Spider and List jobs.
`startLiveCrawl` sends `maxPages`, and `build_crawl_argv` always maps it to
`--max-pages`. The CLI deliberately documents that flag as an **open-crawl**
limit, while `crawl_list` passes the entire CSV to `crawl_many` and never reads
`default_open_crawl_limit`.

A List job configured for 200 pages therefore crawls every URL in a larger CSV
without warning. This is separate from ticket **163**, which fixes where those
results are stored and how the list run is identified.

## Decision (pick one, then make every surface match)

1. **Bound List mode (preferred GUI behaviour):** define `--max-pages` as the
   maximum input URLs attempted in both modes, truncate the deduplicated CSV
   list deterministically, and report omitted input count.
2. **Open-only limit:** reject or omit `maxPages` for List jobs and disable/hide
   the GUI control in that mode with explanatory text.

Do not silently accept and ignore the value.

## Tasks

- Implement one of the explicit semantics above across GUI, CLI help, engine,
  summaries, and documentation.
- Define ordering/deduplication relative to the limit and what `0` means.
- Add a GUI argv/API regression and a CLI/engine CSV larger than the configured
  limit.
- Keep ticket **165**'s content-vs-attempt budget decision scoped to open
  frontier crawling; List input limiting should remain deterministic.

## Definition of Done

- A GUI List `maxPages` value is either enforced or refused before launch.
- CLI help and GUI labels state the same mode-specific semantics.
- Automated coverage proves a large CSV cannot silently exceed an accepted
  finite List limit.

## Status

proposed (Priority: **P2**) — GUI/CLI wiring correctness; found while reviewing
the 2026-07-22 audit tickets.
