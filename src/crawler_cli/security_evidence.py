"""The shared security finding and evidence contract (ticket 153).

This module owns the boundary between what a detector observes and what the
product publishes. It exists so that the detectors added by later tickets
cannot each invent their own fields, severities, evidence snippets and
redaction behaviour, which is how a reporting pipeline ends up leaking a
session cookie into a spreadsheet.

The pipeline has three deliberately separate stages:

Facts
    A detector emits a :class:`SecurityFact`: a structured, detector-owned
    observation with a raw URL, a source, and a mapping of attributes. A fact
    carries no severity, no title and no prose, because those are product
    policy rather than observation.

Policy
    A :class:`FindingPolicy` maps a fact's ``rule_id`` onto a registered
    :class:`FindingRule` and produces a :class:`SecurityFinding`. Severity,
    confidence, remediation text and the non-claims of a passive detector all
    live here, which means they can be revised without recrawling anything.

Serialization
    A single :class:`EvidenceSerializer` renders findings to JSON, JSONL, CSV
    and HTML. It is the only place that applies redaction, the evidence
    budget, the schema version and CSV formula-injection hygiene. Detectors
    never write an output file themselves.

Severity here is a product policy value. It is not CVSS, and this module never
fabricates CWE or CVE identifiers; a rule may carry references, but only ones
its author supplied deliberately.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .redaction import (
    REDACTED,
    CorrelationDigest,
    EvidenceSnippet,
    RedactionPolicy,
    UrlProjection,
    csv_safe_cell,
    project_url,
    scrub_structure,
    scrub_text,
)

SECURITY_FINDING_SCHEMA_VERSION = "crawler-cli/security-finding/1"
"""Schema identifier stamped on every security finding artifact.

Downstream consumers pin on this exact string. Any change to the field set,
to the meaning of a field, or to the redaction guarantees is a contract change
that bumps the version and updates the golden fixture.
"""

Severity = Literal["info", "low", "medium", "high", "critical"]
Confidence = Literal["low", "medium", "high"]
FindingStatus = Literal["observed", "resolved", "changed", "unknown", "not_applicable"]
EvidenceSource = Literal[
    "response_header",
    "response_body",
    "html_element",
    "cookie",
    "url",
    "tls_handshake",
    "sitemap",
    "dns",
    "derived_comparison",
]

SEVERITY_ORDER: tuple[Severity, ...] = ("info", "low", "medium", "high", "critical")
"""Severity values in ascending order, for sorting and summary counts."""


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC value."""
    return datetime.now(timezone.utc)


def format_utc(moment: datetime) -> str:
    """Format a datetime as a stable UTC ISO-8601 string ending in ``Z``."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Facts ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SecurityFact:
    """One structured observation from a detector.

    ``url`` is the raw internal crawl identity. It is never serialised
    directly: the serializer projects it into a redacted URL plus a keyed
    correlation digest. Keeping the raw value here means a detector can still
    compare facts against the frontier, the canonical map and the redirect
    chain by exact identity.

    ``attributes`` is detector-owned and free-form by design, but it is
    subject to the central evidence budget and to recursive redaction, so a
    detector cannot smuggle a response body through it.
    """

    rule_id: str
    url: str = field(repr=False)
    source: EvidenceSource
    detector: str
    detector_version: str
    observed_at: datetime = field(default_factory=utc_now)
    attributes: Mapping[str, Any] = field(default_factory=dict)
    snippets: Sequence[EvidenceSnippet] = field(default_factory=tuple)
    status: FindingStatus = "observed"

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("SecurityFact requires a rule_id")
        if not self.detector_version:
            raise ValueError(f"SecurityFact {self.rule_id} requires a detector_version")


# --- Policy ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FindingRule:
    """The product policy attached to one ``rule_id``.

    A rule is registered once, by the detector that owns it, and is the only
    place severity and prose are defined. ``limitations`` is mandatory in
    spirit for passive or heuristic detectors: a finding that cannot say what
    it did not check invites the reader to over-interpret it.
    """

    rule_id: str
    title: str
    category: str
    description: str
    severity: Severity
    confidence: Confidence = "medium"
    remediation: str = ""
    references: tuple[str, ...] = ()
    limitations: str = ""
    non_claims: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(f"rule {self.rule_id}: unknown severity {self.severity!r}")
        if self.confidence not in ("low", "medium", "high"):
            raise ValueError(f"rule {self.rule_id}: unknown confidence {self.confidence!r}")


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    """A fact that policy has turned into something publishable."""

    rule: FindingRule
    fact: SecurityFact
    status: FindingStatus
    severity: Severity
    confidence: Confidence

    @property
    def rule_id(self) -> str:
        return self.rule.rule_id


class FindingPolicy:
    """Registry of rules plus the fact-to-finding evaluation step.

    Severity overrides exist so that an operator can downgrade a rule that is
    noise on their estate without editing detector code, and so that a later
    ticket can raise a severity after a real assessment. Overrides are applied
    here, in one place, rather than inside detectors.
    """

    def __init__(
        self,
        rules: Iterable[FindingRule] = (),
        *,
        severity_overrides: Mapping[str, Severity] | None = None,
    ) -> None:
        self._rules: dict[str, FindingRule] = {}
        for rule in rules:
            self.register(rule)
        self._severity_overrides: dict[str, Severity] = dict(severity_overrides or {})

    def register(self, rule: FindingRule) -> None:
        """Register *rule*, refusing to silently replace an existing one."""
        existing = self._rules.get(rule.rule_id)
        if existing is not None and existing != rule:
            raise ValueError(f"rule {rule.rule_id} is already registered with different policy")
        self._rules[rule.rule_id] = rule

    def rule_for(self, rule_id: str) -> FindingRule:
        """Return the registered rule, or raise if the detector never declared it."""
        try:
            return self._rules[rule_id]
        except KeyError:
            raise KeyError(
                f"no FindingRule registered for {rule_id!r}; a detector must register its rules "
                "with the shared FindingPolicy before emitting facts"
            ) from None

    def registered_rule_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._rules))

    def evaluate(self, fact: SecurityFact) -> SecurityFinding:
        """Turn one fact into a finding using the registered policy."""
        rule = self.rule_for(fact.rule_id)
        severity = self._severity_overrides.get(fact.rule_id, rule.severity)
        return SecurityFinding(
            rule=rule,
            fact=fact,
            status=fact.status,
            severity=severity,
            confidence=rule.confidence,
        )

    def evaluate_all(self, facts: Iterable[SecurityFact]) -> list[SecurityFinding]:
        return [self.evaluate(fact) for fact in facts]


# --- Evidence budget ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceBudget:
    """Hard caps applied to every finding's evidence, by the serializer.

    The budget is what stops a detector from turning an evidence mapping into
    an unbounded response dump. It is applied after redaction, so a value that
    survives redaction can still be dropped for being too large, and the
    finding records that it was dropped rather than pretending it never
    existed.
    """

    max_keys: int = 20
    max_value_chars: int = 256
    max_list_items: int = 10
    max_snippets: int = 3

    def apply(self, attributes: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """Return the budgeted attributes and the names of what was dropped."""
        dropped: list[str] = []
        budgeted: dict[str, Any] = {}
        for index, (key, value) in enumerate(attributes.items()):
            if index >= self.max_keys:
                dropped.append(str(key))
                continue
            budgeted[str(key)] = self._apply_value(value)
        return budgeted, dropped

    def _apply_value(self, value: Any) -> Any:
        if isinstance(value, str):
            if len(value) > self.max_value_chars:
                return value[: self.max_value_chars] + "…[truncated]"
            return value
        if isinstance(value, list):
            trimmed = [self._apply_value(item) for item in value[: self.max_list_items]]
            if len(value) > self.max_list_items:
                trimmed.append(f"…[{len(value) - self.max_list_items} more omitted]")
            return trimmed
        if isinstance(value, dict):
            return {str(key): self._apply_value(item) for key, item in value.items()}
        return value


# --- Serialization -----------------------------------------------------------------

FINDING_CSV_COLUMNS: tuple[str, ...] = (
    "schema_version",
    "run_id",
    "rule_id",
    "title",
    "category",
    "severity",
    "confidence",
    "status",
    "url",
    "url_digest",
    "host",
    "source",
    "detector",
    "detector_version",
    "observed_at",
    "description",
    "remediation",
    "references",
    "limitations",
    "non_claims",
    "evidence",
    "evidence_truncated",
)
"""Column order of the security findings CSV. Part of the frozen contract."""


class EvidenceSerializer:
    """The single serializer for security findings.

    Every output format goes through :meth:`finding_payload`, so redaction,
    the evidence budget, the schema version and the URL projection are applied
    exactly once and identically everywhere. The CSV and HTML writers are thin
    renderings of the same payload, with their own escaping added on top.
    """

    def __init__(
        self,
        *,
        run_id: str,
        digest: CorrelationDigest | None = None,
        policy: RedactionPolicy | None = None,
        budget: EvidenceBudget | None = None,
    ) -> None:
        self.run_id = run_id
        self.digest = digest if digest is not None else CorrelationDigest.for_run(run_id)
        self.policy = policy if policy is not None else RedactionPolicy()
        self.budget = budget if budget is not None else EvidenceBudget()

    # -- one finding ---------------------------------------------------------

    def project(self, raw_url: str) -> UrlProjection:
        """Project a raw crawl URL for export, without altering the raw value."""
        return project_url(raw_url, digest=self.digest, policy=self.policy)

    def finding_payload(self, finding: SecurityFinding) -> dict[str, Any]:
        """Render one finding as the schema-versioned, redacted mapping."""
        fact = finding.fact
        projection = self.project(fact.url)
        redacted_attributes = scrub_structure(dict(fact.attributes), policy=self.policy)
        evidence, dropped = self.budget.apply(redacted_attributes)
        snippets = [snippet.export() for snippet in list(fact.snippets)[: self.budget.max_snippets]]
        snippets_dropped = max(0, len(list(fact.snippets)) - self.budget.max_snippets)
        rule = finding.rule
        payload: dict[str, Any] = {
            "schema_version": SECURITY_FINDING_SCHEMA_VERSION,
            "run_id": self.run_id,
            "rule_id": rule.rule_id,
            "title": rule.title,
            "category": rule.category,
            "description": rule.description,
            "severity": finding.severity,
            "confidence": finding.confidence,
            "status": finding.status,
            "source": fact.source,
            "detector": fact.detector,
            "detector_version": fact.detector_version,
            "observed_at": format_utc(fact.observed_at),
            "remediation": rule.remediation,
            "references": list(rule.references),
            "limitations": rule.limitations,
            "non_claims": list(rule.non_claims),
            "evidence": evidence,
            "evidence_dropped_keys": dropped,
            "evidence_truncated": bool(dropped or snippets_dropped),
            "snippets": snippets,
        }
        payload.update(projection.export())
        return payload

    def report_payload(
        self, findings: Sequence[SecurityFinding], *, generated_at: datetime | None = None
    ) -> dict[str, Any]:
        """Render a full report: schema version, counts and every finding."""
        rendered = [self.finding_payload(finding) for finding in findings]
        counts = {severity: 0 for severity in SEVERITY_ORDER}
        for finding in findings:
            counts[finding.severity] += 1
        return {
            "schema_version": SECURITY_FINDING_SCHEMA_VERSION,
            "run_id": self.run_id,
            "generated_at": format_utc(generated_at if generated_at is not None else utc_now()),
            "finding_count": len(rendered),
            "severity_counts": counts,
            "detector_versions": _detector_versions(findings),
            "findings": rendered,
        }

    # -- output formats ------------------------------------------------------

    def write_json(
        self,
        path: Path,
        findings: Sequence[SecurityFinding],
        *,
        generated_at: datetime | None = None,
    ) -> Path:
        """Write the report as a single indented JSON document."""
        payload = self.report_payload(findings, generated_at=generated_at)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def write_jsonl(self, path: Path, findings: Sequence[SecurityFinding]) -> Path:
        """Write one JSON object per finding, for streaming consumers."""
        lines = [json.dumps(self.finding_payload(finding), sort_keys=True) for finding in findings]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return path

    def csv_rows(self, findings: Sequence[SecurityFinding]) -> list[dict[str, object]]:
        """Build CSV rows with formula-injection hygiene already applied."""
        rows: list[dict[str, object]] = []
        for finding in findings:
            payload = self.finding_payload(finding)
            row = {
                "schema_version": payload["schema_version"],
                "run_id": payload["run_id"],
                "rule_id": payload["rule_id"],
                "title": payload["title"],
                "category": payload["category"],
                "severity": payload["severity"],
                "confidence": payload["confidence"],
                "status": payload["status"],
                "url": payload["url"],
                "url_digest": payload["url_digest"],
                "host": payload["host"],
                "source": payload["source"],
                "detector": payload["detector"],
                "detector_version": payload["detector_version"],
                "observed_at": payload["observed_at"],
                "description": payload["description"],
                "remediation": payload["remediation"],
                "references": " ".join(payload["references"]),
                "limitations": payload["limitations"],
                "non_claims": " ".join(payload["non_claims"]),
                "evidence": json.dumps(payload["evidence"], sort_keys=True),
                "evidence_truncated": str(payload["evidence_truncated"]).lower(),
            }
            rows.append({key: csv_safe_cell(value) for key, value in row.items()})
        return rows

    def write_csv(self, path: Path, findings: Sequence[SecurityFinding]) -> Path:
        """Write the findings CSV, neutralising spreadsheet formulas."""
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FINDING_CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in self.csv_rows(findings):
                writer.writerow(row)
        return path

    def render_html(self, findings: Sequence[SecurityFinding], *, generated_at: datetime | None = None) -> str:
        """Render a minimal HTML report with every value HTML-escaped."""
        payload = self.report_payload(findings, generated_at=generated_at)
        parts = [
            "<!doctype html>",
            '<html lang="en"><head><meta charset="utf-8">',
            f"<title>Security findings — run {html.escape(str(payload['run_id']))}</title>",
            "</head><body>",
            f"<h1>Security findings</h1><p>Schema {html.escape(str(payload['schema_version']))}, "
            f"{payload['finding_count']} finding(s), generated {html.escape(str(payload['generated_at']))}.</p>",
            "<table><thead><tr><th>Rule</th><th>Title</th><th>Severity</th><th>Status</th><th>URL</th>"
            "<th>Evidence</th></tr></thead><tbody>",
        ]
        for row in payload["findings"]:
            evidence = json.dumps(row["evidence"], sort_keys=True)
            parts.append(
                "<tr>"
                f"<td>{html.escape(str(row['rule_id']))}</td>"
                f"<td>{html.escape(str(row['title']))}</td>"
                f"<td>{html.escape(str(row['severity']))}</td>"
                f"<td>{html.escape(str(row['status']))}</td>"
                f"<td>{html.escape(str(row['url']))}</td>"
                f"<td>{html.escape(evidence)}</td>"
                "</tr>"
            )
        parts.append("</tbody></table></body></html>")
        return "\n".join(parts)

    def write_html(
        self,
        path: Path,
        findings: Sequence[SecurityFinding],
        *,
        generated_at: datetime | None = None,
    ) -> Path:
        path.write_text(self.render_html(findings, generated_at=generated_at), encoding="utf-8")
        return path


def _detector_versions(findings: Iterable[SecurityFinding]) -> dict[str, str]:
    """Collect the detector versions represented in a report."""
    versions: dict[str, str] = {}
    for finding in findings:
        versions[finding.fact.detector] = finding.fact.detector_version
    return dict(sorted(versions.items()))


# --- Detector-facing helper -----------------------------------------------------------


class SecurityEvidenceCollector:
    """The API a detector uses, so it cannot bypass the evidence pipeline.

    A detector records facts and never touches a file, a database row, or a
    log line containing evidence. Rules must be registered up front, which
    means an unregistered ``rule_id`` fails immediately at record time instead
    of producing a finding with no policy behind it.
    """

    def __init__(self, *, policy: FindingPolicy, serializer: EvidenceSerializer) -> None:
        self.policy = policy
        self.serializer = serializer
        self._facts: list[SecurityFact] = []

    def record(self, fact: SecurityFact) -> SecurityFact:
        """Record one fact, validating that its rule exists."""
        self.policy.rule_for(fact.rule_id)
        self._facts.append(fact)
        return fact

    def record_status(self, fact: SecurityFact, status: FindingStatus) -> SecurityFact:
        """Record a fact with a lifecycle status other than ``observed``."""
        return self.record(replace(fact, status=status))

    @property
    def facts(self) -> tuple[SecurityFact, ...]:
        return tuple(self._facts)

    def findings(self) -> list[SecurityFinding]:
        """Evaluate every recorded fact through the finding policy."""
        return self.policy.evaluate_all(self._facts)

    def report_payload(self, *, generated_at: datetime | None = None) -> dict[str, Any]:
        return self.serializer.report_payload(self.findings(), generated_at=generated_at)


# --- Raw sensitive evidence override ---------------------------------------------------

RAW_EVIDENCE_WARNING = (
    "WARNING: this file contains RAW, UNREDACTED evidence captured with an explicit "
    "operator override. It may contain credentials, session cookies, and personal data. "
    "Do not attach it to a ticket, a client report, or a support case."
)
"""Header written at the top of every raw evidence file."""


@dataclass(frozen=True, slots=True)
class RawEvidencePolicy:
    """Whether raw, unredacted evidence may be retained, and where.

    Raw evidence is off by default and both of the retention destinations are
    separate, explicit choices. Enabling a local file must never imply
    database storage, because the two have completely different blast radii: a
    file sits on the operator's machine under restrictive permissions, whereas
    a database row is visible to every consumer of the GUI and the API.

    Neither destination changes what reaches stdout or the logs. Those always
    receive the redacted projection.
    """

    file_enabled: bool = False
    directory: Path | None = None
    confirmed: bool = False
    database_enabled: bool = False

    def validate(self) -> None:
        """Raise ``ValueError`` unless every required explicit choice was made."""
        if self.file_enabled:
            if self.directory is None:
                raise ValueError("raw evidence file retention requires an explicit output directory")
            if not self.confirmed:
                raise ValueError(
                    "raw evidence file retention requires explicit confirmation; "
                    "re-run with the confirmation flag if this is an authorised assessment"
                )
        if self.database_enabled and not self.confirmed:
            raise ValueError(
                "raw evidence database retention requires explicit confirmation; it is a separate "
                "choice from local file retention and is never implied by it"
            )

    @property
    def any_enabled(self) -> bool:
        return self.file_enabled or self.database_enabled


def add_raw_evidence_arguments(parser: argparse.ArgumentParser) -> argparse._ArgumentGroup:
    """Attach the raw-evidence override flags to a security-adjacent command.

    The flags are deliberately verbose and deliberately separate. There is no
    single switch that turns on raw retention everywhere, because the point of
    the separation is that an operator has to think about each destination.
    """
    group = parser.add_argument_group("raw security evidence (off by default)")
    group.add_argument(
        "--retain-raw-evidence-dir",
        metavar="DIR",
        default="",
        help=(
            "Retain RAW, UNREDACTED evidence in this directory. Off by default. "
            "Requires --i-understand-raw-evidence-is-sensitive. Files are written with "
            "owner-only permissions and carry a warning header."
        ),
    )
    group.add_argument(
        "--i-understand-raw-evidence-is-sensitive",
        action="store_true",
        help=(
            "Confirm that raw evidence retention is authorised for this assessment. "
            "Required by every raw retention destination."
        ),
    )
    group.add_argument(
        "--retain-raw-evidence-in-database",
        action="store_true",
        help=(
            "Separately opt in to storing RAW, UNREDACTED evidence in PostgreSQL. "
            "This is NOT implied by --retain-raw-evidence-dir; enabling one never enables the other."
        ),
    )
    return group


def raw_evidence_policy_from_args(args: argparse.Namespace) -> RawEvidencePolicy:
    """Build and validate a :class:`RawEvidencePolicy` from parsed CLI args."""
    directory_value = getattr(args, "retain_raw_evidence_dir", "") or ""
    policy = RawEvidencePolicy(
        file_enabled=bool(directory_value),
        directory=Path(directory_value) if directory_value else None,
        confirmed=bool(getattr(args, "i_understand_raw_evidence_is_sensitive", False)),
        database_enabled=bool(getattr(args, "retain_raw_evidence_in_database", False)),
    )
    policy.validate()
    return policy


def write_raw_evidence(policy: RawEvidencePolicy, name: str, content: str) -> Path:
    """Write one raw evidence file under the override policy.

    The directory is created with owner-only permissions and the file is
    written with mode ``0600``. The content is never logged and never printed;
    the caller receives only the path, which is itself safe to display.
    """
    policy.validate()
    if not policy.file_enabled or policy.directory is None:
        raise ValueError("raw evidence file retention is not enabled")
    directory = policy.directory
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    safe_name = "".join(character if character.isalnum() or character in "-_." else "_" for character in name)
    path = directory / safe_name
    path.write_text(f"{RAW_EVIDENCE_WARNING}\n\n{content}", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


# --- Projections for the GUI and API ------------------------------------------------


def redacted_projection(payload: Mapping[str, Any], *, policy: RedactionPolicy | None = None) -> dict[str, Any]:
    """Return the projection a GUI or API consumer receives by default.

    Serialized findings are already redacted, so this is a defence in depth
    pass for consumers that assemble a response out of several sources: it
    scrubs recursively and strips any key that should never have been present.
    """
    active_policy = policy if policy is not None else RedactionPolicy()
    scrubbed = scrub_structure(dict(payload), policy=active_policy)
    for forbidden in ("raw_url", "raw", "raw_evidence", "raw_headers", "raw_body"):
        if forbidden in scrubbed:
            scrubbed[forbidden] = REDACTED
    return scrubbed


def redacted_text(value: str, *, policy: RedactionPolicy | None = None) -> str:
    """Scrub a single free-text value with the shared policy."""
    return scrub_text(value, policy=policy if policy is not None else RedactionPolicy())
