# Ticket 399: Stream A follow-ups found in integration QA

## Goal

Fix a defect found in QA of the merged Stream A, B and C technical-audit work on 2026-10-06, before it reaches master.

## Problem

Smaller gaps left open when Streams A, B and C were merged: Q44 rows carry the normalised URL rather than the saved originating URL; Q88's denominator counts pages while its unit is templates; a template with fewer than 20 timed pages keeps Q88 at Needs validation; nested `<svg>` inside `<svg>` defeats the foreign-content regex (372); no `/pt-br/` fixture for locale folders (373); `early == 0` skips the Q81 drift test silently; rainbet re-run counts and memory numbers for 371/379 are not recorded in the repo.

## Evidence

Stream A and Stream B QA reviews, nits.

## Tasks

- [ ] Pick up each item with its own test when touched.

## Definition of Done

- [ ] Each item closed or re-filed.

## Status

proposed (Priority: **P3**). Source: stream integration QA, 2026-10-06.
