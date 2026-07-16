# Ticket 121: crawler_gui prototype shell hygiene

**Status:** done (2026-07-16)
**Priority:** P3
**Product:** crawler_gui prototype
**Related:** Tickets 118, 119 (crawler_gui baseline, merged 2026-07-16)

## Problem

The crawler_gui baseline shell that landed with Tickets 118/119 carries two
hygiene issues, both inherited from the initial prototype commit (2c75ece),
neither blocking but worth cleaning up:

1. **Remote network dependency in the shell.** `crawler_gui/index.html` loads
   Google Fonts remotely (`preconnect` + stylesheet to `fonts.googleapis.com` /
   `fonts.gstatic.com`). The intent-overlap viewer itself is fetch-free (it uses
   the statically-imported `REPORT_DATA` fixture), but the page hosting it makes
   a remote request, which contradicts the "no network requests from the
   rendered viewer" spirit of Ticket 119 and prevents true offline use.
2. **Repo bloat / non-owned assets.** The baseline commits a ~1 MB
   `crawler_gui/CrawlZilla.html` plus six `Screenshot from 2026-07-15 *.png`
   files. The README notes CrawlZilla "is not our app" — these are reference
   assets, not product source, and inflate the tracked tree.

## Tasks

- Self-host or drop the Google Fonts links in `index.html` so the prototype
  renders with no external network requests.
- Remove `CrawlZilla.html` and the screenshot PNGs from the tracked tree (keep
  them elsewhere if still useful as reference); if screenshots are wanted in the
  README, add small optimised versions under a dedicated docs path.
- Note in `crawler_gui/README.md` that the grid view's `fetch("./sample-data.json")`
  requires serving over HTTP (it will not run from `file://`); the intent
  viewer does not.

## Definition of Done

crawler_gui renders with no external network requests, the tracked tree no
longer carries the ~1 MB non-owned reference asset and unoptimised screenshots,
and the HTTP-serving requirement for the grid view is documented.

## Completion

- Dropped remote Google Fonts in favour of system font stacks.
- The direct intent-overlap route now bypasses the grid fixture fetch entirely.
- Removed the competitor capture and unoptimised screenshots.
- Added an automated shell-hygiene check and documented the HTTP/offline split.
