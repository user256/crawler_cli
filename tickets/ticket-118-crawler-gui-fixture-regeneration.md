# Ticket 118: Keep the crawler_gui fixture generator aligned with the schedule UI

**Status:** proposed
**Priority:** P3
**Product:** crawler_gui prototype
**Related:** scheduled-crawl light-mode interface update

## Problem

`crawler_gui/sample-data.json` now exposes the Schedule navigation entry and
the fixture fields consumed by the scheduled-crawl UI. Its source generator,
`crawler_gui/generate_sample_data.py`, still emits the older navigation state.
Running the documented generator command would therefore silently disable the
Schedule entry again and leave the generated fixture out of parity with the
interface.

## Tasks

- Update `generate_sample_data.py` so its output includes the enabled Schedule
  navigation entry and every schedule/configuration field the UI expects.
- Regenerate `sample-data.json` from the generator; do not hand-edit the
  generated output.
- Add a small parity check or documented verification that prevents the
  generator and checked-in fixture from drifting apart.

## Definition of Done

Regenerating the fixture preserves the scheduled-crawl interface, the generated
JSON is valid, and an automated or repeatable check demonstrates generator and
fixture parity.
