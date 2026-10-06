---
name: tech-audit-tickets
description: Write or clean up the tickets in a Technical SEO Audit Google Sheet (the "Technical SEO Audit - Template with Questions" template, with Questions, Tickets and Config tabs) in the house style of the Rainbet, Raffall, Dotesports and esports.gg audits. Use when asked to write, draft, populate, rewrite, tidy, proofread or lint audit tickets, fill in the audit template, turn audit findings or crawler-cli technical-audit output into tickets, or bring an older audit up to the current style.
---

# Tech audit tickets

This skill turns technical SEO findings into client-ready tickets in the
[Technical SEO Audit template](https://docs.google.com/spreadsheets/d/1JyYbeoXhBq3Y_heUsUXRaZHOmNPSTeNeUhRodWcZ53o/edit?gid=0#gid=0).
It also cleans up existing ticket tabs to match that template's style.
It covers the writing only. To run the audit and collect evidence, use the
`technical-seo-audit` skill; its check rows are the input to this skill.

Skill folder: `~/resources/skills/tech-audit-tickets`

## Read first

- `references/field-guide.md`: column rules, house style, classification and
  priority, evidence-tab layout, and the checklist. **Read it in full before
  writing a single ticket.**
- `references/model-tickets.md`: model tickets keyed to the template's question
  IDs, three full Rainbet tickets, and a before/after cleanup example.

Rainbet is the reference standard. When the other audits differ from it,
follow Rainbet.

## Helper script

`scripts/audit_sheet.py` reads, checks and fills a sheet through the Sheets API
using the OAuth token at `~/.config/google/google-drive-oauth-token.json`
(override with `GOOGLE_DOCS_OAUTH_TOKEN_FILE`). Run it through the crawler_cli
project so the Google libraries are available:

```sh
S=~/resources/skills/tech-audit-tickets/scripts/audit_sheet.py
R="uv run --project ~/GitRepos/crawler_cli --extra google-sheets python $S"
$R dump  <sheet-url>                    # every tab, numbered pipe-separated rows (--tab, --max-rows)
$R lint  <sheet-url>                    # checks the Tickets tab against the field guide
$R apply <sheet-url> tickets.json --author "Name" --title "Site.com – Technical SEO Audit"
$R link-notes <sheet-url>               # hyperlink tab names, URLs and audit IDs in Notes cells
```

- `tickets.json` is a list of objects with the keys `label`, `description`,
  `solution`, `acceptance`, `classification`, `priority`, `replicate` and
  `notes`. Every key is required.
- `apply` writes the tickets under the header, numbers them `1.`, `2.` and so on,
  sets `Count of tickets`, and replaces the author and banner placeholders.
  It refuses to overwrite existing tickets unless you pass `--replace`.
- `link-notes` makes each Notes cell clickable: every evidence tab named on the
  `See …` line links to that tab, every URL links to itself, and `Audit ID: X`
  links to X's row in the `Audit Log` tab (`--audit-tab` to change it). Run it
  after every `apply`, because `apply` writes plain text and removes the links.
- `lint` prints `error` rows (template contract broken: empty cells, bad
  dropdown values, a wrong count, a missing evidence tab, leftover placeholders)
  and `warn` rows (house style: fix-verb labels, missing counts, vague quantities,
  missing thousands separators, weak criteria, US spelling, priority order). It
  exits 1 when there are errors. A warning is a prompt to check, not a verdict.
  Use judgement.
- The token's Drive scope is `drive.file`, which may not be allowed to copy the
  template. If a copy fails, ask the user to make the copy (File → Make a copy)
  and send you the link.

## Writing new tickets

1. Get the findings: crawler-cli `technical-audit` check rows, evidence tabs
   the user already has, or notes. Dump the target sheet to see its current
   state and its tab names.
2. Map each finding to its template question IDs (Questions tab). Group
   questions that one fix resolves into one ticket. Split findings that need
   different teams.
3. Build or confirm one evidence tab per ticket, following the evidence-tab
   rules in the field guide. Don't write a ticket until its evidence tab exists.
4. Draft the tickets in `tickets.json` from the matching model ticket. Replace
   every count, path and example with the site's own figures. Never carry over
   another site's numbers.
5. Classify and prioritise each ticket using the tables in the field guide.
   Order them High → Medium → Low, then by impact.
6. Show the user the draft tickets before writing to their sheet, unless they
   have already said to go ahead. Then run `apply`, then `link-notes`, then
   `lint`, and fix anything it flags.
7. Set a status on every row of the Questions tab (Healthy, Issue, Needs
   validation or Pending), if the user asked for the questions to be filled too.

## Cleaning up an existing audit

1. Run `dump` on the sheet and `lint` on its ticket tab. For older layouts,
   such as Raffall's `Audit` tab or esports.gg's `TasksIssues` tab, pass
   `--tab <name>`; the linter looks for a header row with `Label`. If there is
   none (for example, the `Task` / `Problem` headers), map the columns by hand.
2. Rewrite each ticket in house style. Keep the substance: the same finding,
   the same fix and the same evidence. Change only the wording and structure.
   The "Cleaning up an older-style ticket" example in `model-tickets.md` shows
   the transformation.
3. Where a vague quantity ("a number of", "many") can be counted from an
   evidence tab, count it (the number of rows, minus the header). If it can't be
   counted, keep the finding and flag it to the user. Don't invent a figure.
4. Rename evidence tabs that use export names (`status308_outlinks`) only if the
   user agrees. Otherwise leave the tab names alone and make sure each Notes
   cell matches them exactly.
5. Give the user a short list of the changes before writing. When they approve,
   write the result, either into the audit template or back to the source sheet
   as they choose, then run `lint`.

## Hard rules

- Every number in a ticket must come from evidence the user can open. If a
  count is partial, say "at least" or "about".
- Saved-crawl findings that have not been rechecked live are classed as Warning
  and must say that they need a live check.
- Never leave Acceptance Criteria empty, and never write "implement one of the
  suggested solutions".
- Don't delete or overwrite a user's tickets or tabs without their go-ahead.
- Use UK English throughout.
