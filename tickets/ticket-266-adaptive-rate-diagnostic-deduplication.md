# Ticket 266: Deduplicate adaptive-rate calibration reasons

**Status:** Open — remediation from concluded ticket 261.
**State:** Open
**Priority:** P3
**Module:** engine

Ensure a calibration result emits `rate_limit_remaining_low` at most once while retaining all independently applicable reasons and preserving its recommendation.

## Acceptance criteria

- [ ] A low-remaining-rate fixture yields one such reason.
- [ ] Existing calibration decisions and serialised schema are unchanged.
