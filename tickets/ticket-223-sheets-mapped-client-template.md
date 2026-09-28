# Ticket 223: Publish into a mapped client ticket template

## Goal

Let the Sheets publisher fill an agency's own ticket template through an
explicit column mapping, in addition to the versioned v2 contract (188).

## Background

The Canonicals "Technical SEO Audit - Template" has a Tickets tab (label,
description, suggested solution, acceptance criteria, classification,
priority, how to replicate, notes; frozen header at row 5; a ticket counter
formula; dropdowns sourced from a Config tab). The rainbet audit had to be
published into it by a one-off script. With only the `drive.file` OAuth scope,
Drive refuses to copy a template the app did not create; the Sheets API
`sheets.copyTo` can still copy individual tabs with their formatting,
formulas and data validation.

## Tasks

- Accept a mapping file declaring the target tab, header row, first data row,
  column mapping from audit-action fields, and value maps (priority → High/
  Medium/Low, action type → Error/Issue/Warning/Improvement).
- Validate the template's headers and dropdown sources against the mapping
  before writing.
- When Drive copy is refused, fall back to `sheets.copyTo` per tab, then
  restore tab names so validation references resolve.
- Append evidence tabs after the ticket tab and keep the template's
  configuration tab last.
- Reuse the receipt and read-back verification from ticket 189.

## Definition of Done

- A mocked template with the Canonicals layout is filled and read back.
- Validation dropdowns resolve after the tab-copy fallback.
- A header mismatch fails before any write.
