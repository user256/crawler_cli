import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "tech-audit-tickets" / "scripts" / "audit_sheet.py"
spec = importlib.util.spec_from_file_location("audit_sheet", SCRIPT)
audit_sheet = importlib.util.module_from_spec(spec)
sys.modules["audit_sheet"] = audit_sheet
spec.loader.exec_module(audit_sheet)

HEADER = ["", *audit_sheet.HEADERS]
GOOD = [
    "1.",
    "Invalid sportsbook paths return a successful page",
    "Nonexistent sportsbook paths, including /sportsbook/zzqx-made-up-9731, return HTTP 200. 1,262 links are affected.",
    "Return 404 for invalid sportsbook routes while preserving legitimate pages.",
    "Invalid sportsbook URLs return 404. Valid routes return the intended page.",
    "Issue",
    "Low",
    "Open /sportsbook/zzqx-made-up-9731 and inspect its HTTP status.",
    "See Sportsbook routes",
]


def sheet(*tickets, count=None):
    n = len(tickets) if count is None else count
    return [[], ["", "", "", "Site.com – Technical SEO Audit"], ["", f"Count of tickets: {n}"], ["", "Audit performed by: A"], HEADER, *tickets]


def messages(rows, tabs=frozenset({"Tickets", "Sportsbook routes"})):
    return [(p.column, p.severity, p.message) for p in audit_sheet.lint(rows, set(tabs))]


def test_clean_ticket_passes():
    assert messages(sheet(GOOD)) == []


def test_contract_errors():
    bad = list(GOOD)
    bad[4] = ""
    bad[5] = "Critical"
    bad[8] = "See Missing tab"
    rows = sheet(bad, count=3)
    rows[1][3] = "This is a template, make a copy"
    rows[3][1] = "Audit performed by: John Doe"
    errors = {(c, m.split(";")[0]) for c, s, m in messages(rows) if s == "error"}
    assert ("Acceptance Criteria", "Empty cell.") in errors
    assert any(c == "Ticket Classification" for c, _ in errors)
    assert any(c == "count of tickets" for c, _ in errors)
    assert any(c == "banner" for c, _ in errors)
    assert any(c == "audit performed by" for c, _ in errors)
    assert any(c == "Notes / Documentation" and "Missing tab" in m for c, m in errors)


def test_style_warnings():
    bad = list(GOOD)
    bad[1] = "Fix redirecting H2 hyperlinks on hubs"
    bad[2] = "A number of links need to optimize 12345 pages at https://x.com/2024999"
    bad[4] = "Implement one of the suggested solutions"
    bad[6] = "High"
    warns = [(c, m) for c, s, m in messages(sheet(GOOD, bad)) if s == "warn"]
    text = " ".join(m for _, m in warns)
    assert "Starts with 'Fix'" in text
    assert "a number of" in text
    assert "'12345' needs a thousands separator" in text
    assert "2024999" not in text  # numbers inside URLs are ignored
    assert "optimise" in text
    assert "implement one of" in text
    assert "order High" in text


def test_apply_writes_rows_numbers_and_header(tmp_path, monkeypatch):
    rows = sheet()
    rows[1][3] = "This is a template, make a copy"
    calls = []

    class Fake:
        def spreadsheets(self):
            return self

        def values(self):
            return self

        def batchUpdate(self, spreadsheetId, body):
            calls.append(body)
            return self

        def execute(self):
            return {}

    monkeypatch.setattr(audit_sheet, "services", lambda: Fake())
    monkeypatch.setattr(audit_sheet, "read_tabs", lambda s, i: ("T", {"Tickets": rows}))
    ticket = dict(zip(audit_sheet.FIELDS, GOOD[1:]))
    path = tmp_path / "t.json"
    path.write_text(json.dumps([ticket, ticket]))
    assert audit_sheet.main(["apply", "abc", str(path), "--author", "Jo", "--title", "Site.com – Technical SEO Audit"]) == 0
    data = {d["range"]: d["values"] for d in calls[0]["data"]}
    assert data["'Tickets'!B6:I56"][:2] == [GOOD[1:], GOOD[1:]]
    assert data["'Tickets'!A6:A7"] == [["1."], ["2."]]
    assert data["'Tickets'!B3"] == [["Count of tickets: 2"]]
    assert data["'Tickets'!B4"] == [["Audit performed by: Jo"]]
    assert data["'Tickets'!D2"] == [["Site.com – Technical SEO Audit"]]


def test_apply_refuses_to_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_sheet, "services", lambda: None)
    monkeypatch.setattr(audit_sheet, "read_tabs", lambda s, i: ("T", {"Tickets": sheet(GOOD)}))
    path = tmp_path / "t.json"
    path.write_text(json.dumps([dict(zip(audit_sheet.FIELDS, GOOD[1:]))]))
    assert audit_sheet.main(["apply", "abc", str(path)]) == 2


def test_imperative_labels_multi_tab_notes_and_url_spelling():
    t = list(GOOD)
    t[1] = "Consolidate the Google-indexed mirror host"
    t[8] = "See Sportsbook routes; Missing tab\nDocumentation: https://developers.google.com/international/localized-versions"
    out = messages(sheet(t))
    assert ("Label", "warn", "Starts with 'Consolidate': state the problem, not the fix.") in out
    assert any(s == "error" and "'Missing tab'" in m for _, s, m in out)
    assert not any("'Sportsbook routes'" in m for _, _, m in out)
    assert not any("US spelling" in m for _, _, m in out)


def test_note_links_and_runs():
    text = "See Soft 404 Probes; Reference - Archive History\nDocumentation: https://example.com/x\nAudit ID: BCG-02 · Suggested team: Routing"
    tabs = {"Soft 404 Probes": "u#gid=1", "Reference - Archive History": "u#gid=2", "Tickets": "u#gid=0"}
    spans = audit_sheet.note_links(text, tabs, {"BCG-02": "u#gid=3&range=A3"})
    assert [text[s:e] for s, e, _ in spans] == ["Soft 404 Probes", "Reference - Archive History", "https://example.com/x", "BCG-02"]
    runs = audit_sheet.text_runs(text, spans)
    assert [r["startIndex"] for r in runs] == sorted({r["startIndex"] for r in runs})
    assert runs[0] == {"startIndex": 0, "format": {}}
    assert runs[1]["format"]["link"]["uri"] == "u#gid=1"
    assert runs[-1]["format"] == {}
