# Ticket 392: Downgrade other answers only when a run gate answers Yes

## Goal

Fix a defect found in QA of the merged Stream A, B and C technical-audit work on 2026-10-06, before it reaches master.

## Problem

The question runner downgraded every crawl answer to Needs validation unless both run gates (Q26, Q81) were Healthy. Q81 is Needs validation whenever response-time drift could not be tested (fewer than 20 timed fetches) and Pending on audits saved before `rate_limited_count` existed, so small crawls and every older audit lost all Healthy answers.

## Evidence

`answer_questions` computed `gate_ok = all(status == Healthy)`. Stream B QA review, defect 1.

## Tasks

- [x] Fail the gate only when a gate answers Yes; a gate that could not be fully tested keeps its own scope gap and adds a note to the other answers.
- [x] Regression tests: untested drift and missing count leave Q13 Healthy with a note; a Yes gate still downgrades.

## Definition of Done

- [x] Q81 at Needs validation or Pending no longer downgrades other answers.
- [x] A Yes on Q26 or Q81 still downgrades every crawl answer.
- [x] Full suite green.

## Status

implemented (local) (Priority: **P1**). Source: stream integration QA, 2026-10-06.
