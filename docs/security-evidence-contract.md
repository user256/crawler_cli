# Security evidence contract and redaction policy

Ticket 153. This document describes the shared contract that every
security-adjacent report in `crawler_cli` must use, the default redaction
policy applied to it, and — importantly — what remains sensitive even after
that redaction has run.

`crawler_cli` is an evidence crawler for technical SEO, run against sites the
operator is authorised to fetch (ticket 144). Nothing described here turns it
into a penetration-testing tool. The findings it emits are passive
observations, and every rule is expected to say what it did not check.

## The pipeline

Three stages, deliberately separate:

1. **Facts.** A detector emits a `SecurityFact`: a structured observation with
   a raw URL, a source, a detector version, and a mapping of detector-owned
   attributes. A fact has no severity and no prose, because those are product
   policy rather than observation.
2. **Policy.** A `FindingPolicy` maps the fact's `rule_id` to a registered
   `FindingRule` and produces a `SecurityFinding`. Severity, confidence,
   remediation, references, limitations and non-claims all live here, so they
   can be revised without recrawling anything.
3. **Serialization.** One `EvidenceSerializer` renders findings to JSON,
   JSONL, CSV and HTML. It is the only place that applies redaction, the
   evidence budget, the schema version and CSV hygiene. Detectors never write
   an output file, a log line, or a database row containing evidence
   themselves.

Detectors use `SecurityEvidenceCollector`, which refuses a fact whose rule has
not been registered. That is what stops a new detector from emitting a finding
with no policy behind it.

## Schema

The schema identifier is `crawler-cli/security-finding/1`, stamped on every
finding and on the report envelope. The golden fixtures in
`tests/contract/golden/security_finding_report.json` and
`tests/contract/golden/security_findings.csv` are the frozen contract. A diff
in either is a contract change for every consumer and must bump the version.

Each finding carries: `rule_id`, `title`, `category`, `description`,
`severity` (`info`/`low`/`medium`/`high`/`critical`), `confidence`
(`low`/`medium`/`high`), `status`
(`observed`/`resolved`/`changed`/`unknown`/`not_applicable`), the redacted
`url` plus `url_digest`, `host`, `path`, `source`, `detector`,
`detector_version`, `observed_at`, `remediation`, `references`,
`limitations`, `non_claims`, budgeted `evidence`, and bounded `snippets`.

Severity is a product policy value. It is not CVSS, and no CWE or CVE
identifier is ever fabricated.

## Redaction policy

**Headers.** Values are removed for `Authorization`, `Proxy-Authorization`,
`Cookie`, `Set-Cookie`, `X-API-Key` and the other well-known token headers,
for any configured exact name, and for any header name containing `token`,
`secret`, `password`, `api-key`, `auth`, `credential` or `session`. Matching
is case-insensitive and preserves duplicate and multi-value forms. Header
values that are *not* redacted by name are still scrubbed as free text, so a
`Location` header carrying a signed URL does not leak.

**Cookies.** `Set-Cookie` is parsed into cookie *names* plus approved
attributes (`Secure`, `HttpOnly`, `SameSite`, `Path`, `Domain`, and whether an
expiry was present). Values are never retained in any form other than a keyed
digest.

**URLs.** Userinfo is removed unconditionally. Values are removed for the
documented sensitive query keys (`token`, `key`, `secret`, `password`,
`passcode`, `auth`, `signature`, `session`, `code`, `email`, and others), for
configured exact keys, and for configured regular expressions. Parameter
names, their order, and their original percent-encoding are preserved. A
non-empty fragment is replaced while the fact that a fragment existed is kept.

**Internal identity versus exported projection.** The raw URL remains the
crawler's identity: the frontier key, the redirect and canonical comparison
value, and the `urls` row. `project_url` returns an additional, export-only
`UrlProjection`. Redaction is never applied in place, because two URLs that
differ only in a redacted value (`?token=a` and `?token=b`) would otherwise
collapse into one record and break redirect and canonical analysis. The
projection distinguishes them with a keyed digest.

**Keyed correlation digests.** Correlating a sensitive value across findings
uses HMAC-SHA256 with a per-run key, not a plain SHA-256. A plain hash of a
low-entropy value — a four digit code, an e-mail address, a numeric session
id — is reversible by brute force in seconds. The per-run key means digests
are comparable within a run and not across runs, and cannot be precomputed by
somebody who obtains a report.

**Snippets.** Where a snippet is necessary, whitespace is normalised, secret
and PII heuristics are applied, a small byte and line cap is enforced, and a
SHA-256 of the source material is included so a consumer can tell whether the
underlying content changed. When the source contains a value this process
knows to be a secret, the snippet falls back to the digest and no text is
retained at all.

**Exceptions and logs.** `redact_exception` and `redact_traceback` scrub
exception messages and full tracebacks. `SecretRedactingLogFilter` scrubs log
messages, positional and structured arguments, structured extras, and
exception tracebacks attached to a record. Error messages for missing
credentials name the source field or environment variable, never the value.

**Connection strings and proxies.** Database DSNs and proxy URLs are rendered
without credentials everywhere, via `sanitize_dsn` and `sanitize_proxy_url`.

**CSV hygiene.** A cell beginning with `=`, `+`, `-`, `@`, a tab, or a folded
carriage return is prefixed with an apostrophe, because a spreadsheet would
otherwise treat a crawled page title as a formula. Embedded carriage returns
and newlines are folded to spaces. Numbers are left alone.

## Raw sensitive evidence

Raw, unredacted evidence is **off by default**. If it is retained at all:

- `--retain-raw-evidence-dir DIR` writes it to an explicit directory, with
  owner-only permissions (`0700` directory, `0600` files) and a warning header
  in every file;
- `--i-understand-raw-evidence-is-sensitive` is required by every destination;
- `--retain-raw-evidence-in-database` is a **separate** choice. Enabling a
  local file never enables database storage, and never the other way round.

No override causes raw evidence to reach stdout or the logs. Ordinary tests
and CI never exercise real-secret retention.

## Retention and lifecycle

Security rows are run-scoped, following the tickets 041 and 042 precedent for
crawl data. Every retention operation names an exact run id and offers a dry
run that reports counts without changing anything. There is no
delete-by-pattern path.

- `security_findings` — redacted findings; safe to retain after raw evidence
  has gone, and safe to project into the GUI and API.
- `security_evidence_raw` — raw evidence, present only under the explicit
  database override.
- `security_run_retention` — what a run was permitted to keep, and when its
  raw evidence was purged.

`crawler-cli compact-crawl --crawl-run-id ... --drop-security-evidence` purges
one run's raw evidence and keeps its findings.
`--drop-security-findings` is the stronger, separate action.
`crawler-cli delete-crawl` reports the security table counts alongside the
crawl tables and removes them with the rest.

## What is still sensitive after all of this

This is data minimisation, not a guarantee. The following remain possible
after every rule above has run:

- **Arbitrary page content.** A crawled page may contain names, addresses,
  order numbers, internal notes or credentials in text that matches no
  pattern. Redaction cannot recognise what it has never seen.
- **Path segments.** Sensitive values placed in a URL *path* rather than a
  query string (`/reset/9f3a…/`) are preserved, because the path is the
  identity of the resource and removing it would make findings unusable.
- **Custom parameter names.** A site that names its session parameter `ref`
  or `u` will not be matched by the default key list. Add the name via the
  policy's configurable exact keys or regular expressions.
- **Correlation.** A keyed digest still reveals that two records share a
  value. That is its purpose; it is not anonymisation.
- **Aggregation.** Individually harmless facts — a host, a path, a cookie
  name, a header set — can identify an environment or a customer when
  combined.
- **Raw evidence overrides.** Anything retained under an explicit override is
  exactly as sensitive as the material it came from, and the warning header in
  the file says so.
- **Stored HTML.** Raw HTML retention is governed by the existing
  `--no-store-html` and compaction controls, not by this policy. Security
  modes keep no raw body in their own evidence artifacts by default.

Treat any artifact produced from an authenticated crawl as sensitive until a
person has read it.
