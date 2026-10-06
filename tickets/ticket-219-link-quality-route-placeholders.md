# Ticket 219: Flag unresolved route placeholders in raw HTML links

## Goal

Report internal links whose href still contains an unfilled framework route
pattern, which crawlers reading raw HTML follow into 404s.

## Background

rainbet.com's server-rendered header links read
`/casino/[type]/[slug]?modal=auth&tab=login`. Hydration corrects them in the
browser, so users never see the problem, but the raw HTML carried 18,080 such
links across 111 patterns, all returning 404. The link-quality report did not
flag them because the targets were never crawled.

## Tasks

- Add a link-quality rule matching unresolved segments: Next.js `[x]`,
  `[...x]`, `[[...x]]`; Express/Vue `:x`; template `{x}`, `{{x}}`, `${x}`;
  and their percent-encoded forms.
- Report pattern, instances, unique source pages, DOM location and whether the
  rendered DOM differs (when render evidence exists).
- Treat it as a defect only for raw-HTML hrefs; do not flag strings in
  scripts or data attributes.

## Definition of Done

- Fixtures for each syntax, including percent-encoded brackets, are flagged.
- Legitimate paths containing brackets in query values are not flagged.
- The rainbet run reports the 111 patterns.
