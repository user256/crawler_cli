# Ticket 214: Stop reporting the Next.js RSC payload script as broken schema

## Goal

The structured-data parser must not emit a `BrokenScriptSchema` instance for
framework hydration scripts that were never intended as JSON-LD.

## Background

On the 2026-09-25 rainbet.com crawl every `self.__next_f.push([...])` script
(the Next.js App Router React Server Components payload, no `type` attribute)
was stored as `BrokenScriptSchema` with the error
`JSON-LD content in script tag without proper type attribute`. It reached
32 pages in the first 3,000 crawled and would surface in the technical-audit
schema diagnostics as a site defect. The site's real JSON-LD blocks parsed
correctly alongside it.

## Tasks

- Only treat an untyped `<script>` as candidate JSON-LD when its trimmed body
  starts with `{` or `[` and contains `@context` or `@type`; skip bodies that
  start with an identifier or call expression (`self.__next_f.push`,
  `window.__NUXT__=`, `__NEXT_DATA__` without `type="application/json"`).
- Keep genuine defects: a body that is valid JSON-LD but sits in a script
  without `type="application/ld+json"` still deserves the warning.
- Add fixtures for the Next.js RSC payload and for a genuinely mistyped
  JSON-LD block.

## Definition of Done

- The RSC payload fixture yields no schema instance.
- The mistyped JSON-LD fixture still yields `BrokenScriptSchema`.
- `technical-audit` schema diagnostics for the rainbet run no longer list the
  32 pages.
