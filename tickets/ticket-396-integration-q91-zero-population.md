# Ticket 396: Never answer Q91 Healthy from an empty or partial link population

## Goal

Fix a defect found in QA of the merged Stream A, B and C technical-audit work on 2026-10-06, before it reaches master.

## Problem

Stream A's Q91 answerer set `available=True` unconditionally and the evaluator's coverage is complete with no records, so a run without stored HTML (or a compacted run) answered Healthy with denominator 0. Coverage also ignored pages whose HTML was not stored.

## Evidence

Stream A QA review, blocker 2.

## Tasks

- [x] Pending without page rows; 'could not be tested' when no internal anchor was seen.
- [x] Denominator is the total internal anchor count; coverage is incomplete when a page hit the per-page cap, when fewer pages carried link facts than the run stored, or when the run is incomplete.

## Definition of Done

- [x] Q91 is never Healthy from zero anchors or partial HTML coverage.

## Status

implemented (local) (Priority: **P1**). Source: stream integration QA, 2026-10-06.
