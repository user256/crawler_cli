# Ticket 225: Show the run and audit dates in the Markdown projection

## Goal

The recipient Markdown projection must state when the crawl ran and when the
audit was generated.

## Background

On the 2026-09-28 master rerun of the rainbet.com audit, `--markdown-out`
printed `Date: unknown` and `Audit date: unknown`, although the crawl run row
has `created_at` and the audit runs at a known time. A client summary without
dates cannot be compared with later retests.

## Tasks

- Populate the crawl date from the run record and the audit date from the
  generation time, both in ISO 8601 with a time zone.
- Keep `unknown` only when the run record genuinely lacks a timestamp.

## Definition of Done

- A fixture run with `created_at` renders both dates.
- A run without a timestamp still renders `unknown` for the crawl date.
