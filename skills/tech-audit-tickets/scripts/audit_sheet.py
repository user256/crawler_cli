#!/usr/bin/env python3
"""Read, lint and fill the Tickets tab of a Technical SEO Audit Google Sheet.

  dump  <sheet>                 print every tab as numbered, pipe-separated rows
  lint  <sheet> [--tab Tickets] check tickets against the field guide
  apply <sheet> <tickets.json>  write tickets into the Tickets tab and update the count
  link-notes <sheet>            hyperlink evidence tabs, URLs and audit IDs in Notes cells

<sheet> is a Google Sheets URL or spreadsheet ID. Auth uses the OAuth token in
GOOGLE_DOCS_OAUTH_TOKEN_FILE (default ~/.config/google/google-drive-oauth-token.json).
Run with: uv run --project ~/GitRepos/crawler_cli --extra google-sheets python audit_sheet.py ...
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass

FIELDS = ("label", "description", "solution", "acceptance", "classification", "priority", "replicate", "notes")
HEADERS = (
    "Label",
    "Description",
    "Suggested Solution",
    "Acceptance Criteria",
    "Ticket Classification",
    "Priority",
    "How to Replicate",
    "Notes / Documentation",
)
CLASSIFICATIONS = ("Error", "Issue", "Warning", "Improvement")
PRIORITIES = ("High", "Medium", "Low")
FIX_VERBS = {
    "fix", "remove", "add", "update", "create", "replace", "implement", "improve",
    "move", "block", "ensure", "make", "use", "set", "change", "delete", "redirect",
    "consolidate", "return", "align", "reduce", "collapse", "normalise", "normalize", "limit",
    "serve", "restore", "mark", "review", "prevent", "avoid", "convert", "enable", "define",
    "apply", "correct", "resolve", "localise", "localize", "rename", "merge", "migrate",
}
US_SPELLINGS = {
    "optimize": "optimise", "optimization": "optimisation", "prioritize": "prioritise",
    "canonicalize": "canonicalise", "canonicalized": "canonicalised", "localize": "localise",
    "localized": "localised", "organization": "organisation", "behavior": "behaviour",
    "analyze": "analyse", "color": "colour", "normalize": "normalise", "normalized": "normalised",
}
WEAK_CRITERIA = ("implement one of", "implement a suggested", "should ", "search console shows", "improved ")
VAGUE_COUNTS = ("a number of", "a large number", "a handful", "several ", "many ", "some pages")
URL_RE = re.compile(r"https?://\S+|(?<![\w.])/[\w\-./?=&%#\[\]+:]*")


@dataclass
class Problem:
    row: int  # 1-based sheet row
    column: str
    severity: str  # "error" breaks the template contract, "warn" breaks house style
    message: str

    def __str__(self) -> str:
        return f"row {self.row:>3} {self.column:<22} {self.severity:<5} {self.message}"


def sheet_id(value: str) -> str:
    match = re.search(r"/spreadsheets/(?:u/\d+/)?d/([A-Za-z0-9_-]+)", value)
    return match.group(1) if match else value.strip()


def services():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token = os.environ.get("GOOGLE_DOCS_OAUTH_TOKEN_FILE") or os.path.expanduser(
        "~/.config/google/google-drive-oauth-token.json"
    )
    creds = Credentials.from_authorized_user_file(token)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("sheets", "v4", credentials=creds)


def read_tabs(sheets, spreadsheet: str) -> tuple[str, dict[str, list[list[str]]]]:
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet, fields="properties.title,sheets.properties.title").execute()
    titles = [s["properties"]["title"] for s in meta["sheets"]]
    ranges = [f"'{t}'" for t in titles]
    res = sheets.spreadsheets().values().batchGet(spreadsheetId=spreadsheet, ranges=ranges).execute()
    return meta["properties"]["title"], {t: vr.get("values", []) for t, vr in zip(titles, res["valueRanges"])}


def find_header(rows: list[list[str]]) -> tuple[int, int]:
    """Return (0-based row index, 0-based column index) of the 'Label' header cell."""
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            if cell.strip().lower() == "label" and any("description" in x.lower() for x in row[c + 1 : c + 3]):
                return r, c
    raise ValueError("No Tickets header row with 'Label' followed by 'Description' was found.")


def parse_tickets(rows: list[list[str]]) -> tuple[list[tuple[int, dict[str, str]]], int, int]:
    header_row, label_col = find_header(rows)
    tickets = []
    for r in range(header_row + 1, len(rows)):
        cells = rows[r][label_col : label_col + len(FIELDS)]
        cells += [""] * (len(FIELDS) - len(cells))
        if not any(c.strip() for c in cells):
            continue
        tickets.append((r + 1, dict(zip(FIELDS, (c.strip() for c in cells)))))
    return tickets, header_row, label_col


def _strip_urls(text: str) -> str:
    return URL_RE.sub(" ", text)


def lint(rows: list[list[str]], tab_names: set[str]) -> list[Problem]:
    problems: list[Problem] = []
    tickets, header_row, _ = parse_tickets(rows)
    preamble = [" ".join(r) for r in rows[:header_row]]

    for n, text in enumerate(preamble, 1):
        if "this is a template" in text.lower():
            problems.append(Problem(n, "banner", "error", "Template banner text is still present; replace it with '<Domain> – Technical SEO Audit'."))
        if "john doe" in text.lower():
            problems.append(Problem(n, "audit performed by", "error", "'Audit performed by' is still the placeholder John Doe."))
        m = re.search(r"count of tickets:\s*(\d+)", text, re.I)
        if m and int(m.group(1)) != len(tickets):
            problems.append(Problem(n, "count of tickets", "error", f"Header says {m.group(1)} tickets but {len(tickets)} rows are filled."))

    last_priority = -1
    for row, t in tickets:
        for field, header in zip(FIELDS, HEADERS):
            if not t[field]:
                problems.append(Problem(row, header, "error", "Empty cell."))

        if t["classification"] and t["classification"] not in CLASSIFICATIONS:
            problems.append(Problem(row, "Ticket Classification", "error", f"'{t['classification']}' is not one of {', '.join(CLASSIFICATIONS)}."))
        if t["priority"]:
            if t["priority"] not in PRIORITIES:
                problems.append(Problem(row, "Priority", "error", f"'{t['priority']}' is not one of {', '.join(PRIORITIES)}."))
            else:
                rank = PRIORITIES.index(t["priority"])
                if rank < last_priority:
                    problems.append(Problem(row, "Priority", "warn", f"{t['priority']} ticket sits below a lower-priority ticket; order High → Medium → Low."))
                last_priority = max(last_priority, rank)

        label = t["label"]
        if label:
            words = label.split()
            if words[0].lower() in FIX_VERBS:
                problems.append(Problem(row, "Label", "warn", f"Starts with '{words[0]}': state the problem, not the fix."))
            if len(words) < 4:
                problems.append(Problem(row, "Label", "warn", "Very short; name the page group and the fault."))
            if len(words) > 14:
                problems.append(Problem(row, "Label", "warn", f"{len(words)} words; keep labels to 5–12."))

        desc = t["description"]
        if desc:
            bare = _strip_urls(desc)
            if not re.search(r"\d", bare):
                problems.append(Problem(row, "Description", "warn", "No count; lead with how many pages, links or URLs."))
            for phrase in VAGUE_COUNTS:
                if phrase in desc.lower():
                    problems.append(Problem(row, "Description", "warn", f"Vague quantity '{phrase.strip()}'; give the count."))
            for num in re.findall(r"(?<![\d,.])\d{4,}(?![\d,])", bare):
                if not (len(num) == 4 and num[:2] in ("19", "20")):
                    problems.append(Problem(row, "Description", "warn", f"'{num}' needs a thousands separator."))

        sol = t["solution"]
        if sol and sol.split()[0].lower() in ("we", "it", "there", "this", "the"):
            problems.append(Problem(row, "Suggested Solution", "warn", "Start with an imperative verb (Remove, Replace, Return…)."))

        acc = t["acceptance"].lower()
        for phrase in WEAK_CRITERIA:
            if phrase in acc:
                problems.append(Problem(row, "Acceptance Criteria", "warn", f"Contains '{phrase.strip()}'; describe a checkable end state."))

        rep = t["replicate"]
        if rep and not URL_RE.search(rep) and not re.search(r"ahrefs|semrush|search console|gsc|majestic", rep, re.I):
            problems.append(Problem(row, "How to Replicate", "warn", "No URL, path or named tool report to open."))

        notes = t["notes"]
        m = re.match(r"see\s+([^\n]+)", notes, re.I)
        if notes and not m:
            problems.append(Problem(row, "Notes / Documentation", "warn", "Start with 'See <evidence tab>'."))
        elif m:
            # "See Tab A; Tab B" names several evidence tabs; each must exist.
            for tab in (x.strip().rstrip(".") for x in re.split(r"[;,]", m.group(1))):
                if tab not in tab_names:
                    problems.append(Problem(row, "Notes / Documentation", "error", f"Evidence tab '{tab}' does not exist in this spreadsheet."))
                elif re.search(r"[_]|^[a-z0-9-]+$", tab):
                    problems.append(Problem(row, "Notes / Documentation", "warn", f"Tab '{tab}' looks like an export name; use plain words."))

        for field, header in zip(FIELDS, HEADERS):
            text = _strip_urls(t[field]).lower()
            for us, uk in US_SPELLINGS.items():
                if re.search(rf"\b{us}", text):
                    problems.append(Problem(row, header, "warn", f"US spelling '{us}'; use '{uk}'."))
    return problems


def cmd_dump(args) -> int:
    title, tabs = read_tabs(services(), sheet_id(args.sheet))
    print(f"# {title}")
    for name, rows in tabs.items():
        if args.tab and name != args.tab:
            continue
        print(f"\n## TAB {name} ({len(rows)} rows)")
        for n, row in enumerate(rows, 1):
            if n > args.max_rows:
                print(f"… {len(rows) - args.max_rows} more rows")
                break
            if any(c.strip() for c in row):
                print(f"{n}\t" + " | ".join(c.replace("\n", "⏎") for c in row))
    return 0


def cmd_lint(args) -> int:
    _, tabs = read_tabs(services(), sheet_id(args.sheet))
    if args.tab not in tabs:
        print(f"No '{args.tab}' tab; tabs are: {', '.join(tabs)}", file=sys.stderr)
        return 2
    problems = lint(tabs[args.tab], set(tabs))
    for p in problems:
        print(p)
    errors = sum(p.severity == "error" for p in problems)
    print(f"\n{errors} errors, {len(problems) - errors} warnings")
    return 1 if errors else 0


def cmd_apply(args) -> int:
    sheets = services()
    spreadsheet = sheet_id(args.sheet)
    with open(args.tickets) as fh:
        tickets = json.load(fh)
    for i, t in enumerate(tickets, 1):
        missing = [f for f in FIELDS if not str(t.get(f, "")).strip()]
        if missing:
            print(f"Ticket {i} is missing {', '.join(missing)}", file=sys.stderr)
            return 2
    _, tabs = read_tabs(sheets, spreadsheet)
    rows = tabs[args.tab]
    tickets_before, header_row, label_col = parse_tickets(rows)
    if tickets_before and not args.replace:
        print(f"{len(tickets_before)} tickets already present; pass --replace to overwrite them.", file=sys.stderr)
        return 2

    def col(i: int) -> str:
        s = ""
        i += 1
        while i:
            i, rem = divmod(i - 1, 26)
            s = chr(65 + rem) + s
        return s

    first = header_row + 2  # 1-based first data row
    clear_to = max(first + len(tickets), first + len(tickets_before) + 50)
    num_col = col(label_col - 1) if label_col else None
    data = [{
        "range": f"'{args.tab}'!{col(label_col)}{first}:{col(label_col + len(FIELDS) - 1)}{clear_to}",
        "values": [[t[f] for f in FIELDS] for t in tickets] + [[""] * len(FIELDS)] * (clear_to - first + 1 - len(tickets)),
    }]
    if num_col:
        data.append({"range": f"'{args.tab}'!{num_col}{first}:{num_col}{first + len(tickets) - 1}",
                     "values": [[f"{i}."] for i in range(1, len(tickets) + 1)]})
    for r, row in enumerate(rows[:header_row]):
        for c, cell in enumerate(row):
            if re.match(r"\s*count of tickets:", cell, re.I):
                data.append({"range": f"'{args.tab}'!{col(c)}{r + 1}", "values": [[f"Count of tickets: {len(tickets)}"]]})
            if args.author and re.match(r"\s*audit performed by:", cell, re.I):
                data.append({"range": f"'{args.tab}'!{col(c)}{r + 1}", "values": [[f"Audit performed by: {args.author}"]]})
            if args.title and "this is a template" in cell.lower():
                data.append({"range": f"'{args.tab}'!{col(c)}{r + 1}", "values": [[args.title]]})
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet, body={"valueInputOption": "RAW", "data": data}
    ).execute()
    print(f"Wrote {len(tickets)} tickets to '{args.tab}' starting at row {first}.")
    return 0


LINK_STYLE = {"underline": True, "foregroundColorStyle": {"rgbColor": {"red": 0.07, "green": 0.33, "blue": 0.8}}}


def note_links(text: str, tab_urls: dict[str, str], audit_urls: dict[str, str]) -> list[tuple[int, int, str]]:
    """Return (start, end, uri) spans to link in a Notes cell.

    Evidence-tab names on the leading "See" line link to their tab, bare URLs link
    to themselves, and an "Audit ID: X" links to that ID's row in the audit log.
    """
    spans = []
    see = re.match(r"(see\s+)([^\n]+)", text, re.I)
    if see:
        pos = see.start(2)
        for part in re.split(r"([;,])", see.group(2)):
            name = part.strip().rstrip(".")
            if name in tab_urls:
                start = pos + part.index(name)
                spans.append((start, start + len(name), tab_urls[name]))
            pos += len(part)
    for m in re.finditer(r"https?://[^\s]+", text):
        spans.append((m.start(), m.end(), m.group(0)))
    for m in re.finditer(r"Audit ID:\s*(\S+)", text):
        if m.group(1) in audit_urls:
            spans.append((m.start(1), m.end(1), audit_urls[m.group(1)]))
    return sorted(spans)


def text_runs(text: str, spans: list[tuple[int, int, str]]) -> list[dict]:
    """Sheets textFormatRuns: each run lasts until the next, so close every link with a plain run."""
    runs = [{"startIndex": 0, "format": {}}]
    for start, end, uri in spans:
        runs.append({"startIndex": start, "format": {**LINK_STYLE, "link": {"uri": uri}}})
        if end < len(text):
            runs.append({"startIndex": end, "format": {}})
    # Drop runs that a later run at the same index overrides.
    return [r for i, r in enumerate(runs) if i + 1 == len(runs) or runs[i + 1]["startIndex"] != r["startIndex"]]


def cmd_link_notes(args) -> int:
    sheets = services()
    spreadsheet = sheet_id(args.sheet)
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet, fields="sheets.properties(title,sheetId)").execute()
    gids = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    base = f"https://docs.google.com/spreadsheets/d/{spreadsheet}/edit"
    tab_urls = {title: f"{base}#gid={gid}" for title, gid in gids.items()}
    _, tabs = read_tabs(sheets, spreadsheet)
    audit_urls = {}
    if args.audit_tab in tabs:
        for r, row in enumerate(tabs[args.audit_tab]):
            if row and row[0].strip():
                audit_urls[row[0].strip()] = f"{base}#gid={gids[args.audit_tab]}&range=A{r + 1}"
    tickets, _, label_col = parse_tickets(tabs[args.tab])
    notes_col = label_col + FIELDS.index("notes")
    requests, linked = [], 0
    for row, t in tickets:
        spans = note_links(t["notes"], tab_urls, audit_urls)
        if not spans:
            continue
        linked += len(spans)
        requests.append({"updateCells": {
            "range": {"sheetId": gids[args.tab], "startRowIndex": row - 1, "endRowIndex": row,
                      "startColumnIndex": notes_col, "endColumnIndex": notes_col + 1},
            "rows": [{"values": [{"userEnteredValue": {"stringValue": t["notes"]},
                                  "textFormatRuns": text_runs(t["notes"], spans)}]}],
            "fields": "userEnteredValue,textFormatRuns",
        }})
    if requests:
        sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet, body={"requests": requests}).execute()
    print(f"Linked {linked} references across {len(requests)} Notes cells.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("dump")
    p.add_argument("sheet")
    p.add_argument("--tab")
    p.add_argument("--max-rows", type=int, default=200)
    p.set_defaults(func=cmd_dump)
    p = sub.add_parser("lint")
    p.add_argument("sheet")
    p.add_argument("--tab", default="Tickets")
    p.set_defaults(func=cmd_lint)
    p = sub.add_parser("apply")
    p.add_argument("sheet")
    p.add_argument("tickets", help="JSON list of objects with keys: " + ", ".join(FIELDS))
    p.add_argument("--tab", default="Tickets")
    p.add_argument("--replace", action="store_true", help="overwrite tickets already in the tab")
    p.add_argument("--author", help="value for 'Audit performed by'")
    p.add_argument("--title", help="replace the 'This is a template' banner with this title")
    p.set_defaults(func=cmd_apply)
    p = sub.add_parser("link-notes", help="hyperlink evidence tabs, URLs and audit IDs in Notes cells")
    p.add_argument("sheet")
    p.add_argument("--tab", default="Tickets")
    p.add_argument("--audit-tab", default="Audit Log", help="tab whose column A holds audit IDs")
    p.set_defaults(func=cmd_link_notes)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
