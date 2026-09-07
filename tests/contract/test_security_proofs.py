"""Security proofs for the portal integration contract (tickets 3344, 153).

Proves, with running code rather than documentation:

(a) credentials and DSNs have an invocation path that never touches process
    argv, and never appear in log output or saved artifacts;
(b) Basic and Bearer credentials are attached to the configured site and are
    STRIPPED on cross-origin redirects, while surviving same-origin redirects;
    and
(c) a set of planted, known test secrets is recursively ABSENT from every
    output format the security evidence pipeline can produce — stdout, log
    records, exception messages, tracebacks, JSON, JSONL, CSV and HTML
    (ticket 153).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest
from aiohttp import web

from crawler_cli.__main__ import _build_auth, _build_parser
from crawler_cli.auth import AuthConfig
from crawler_cli.backends import AiohttpBackend, CurlCffiBackend, PlaywrightBackend
from crawler_cli.config import CrawlConfig
from crawler_cli.engine import CrawlEngine
from crawler_cli.models import CrawlJobResult, CrawlResult
from crawler_cli.persistence import MemoryStore
from crawler_cli.redaction import (
    REDACTED,
    SECRETS,
    CorrelationDigest,
    bounded_snippet,
    install_log_redaction,
    redact_exception,
    redact_form_fields,
    redact_headers,
    redact_traceback,
    sanitize_dsn,
    sanitize_proxy_url,
)
from crawler_cli.security_evidence import (
    EvidenceSerializer,
    FindingPolicy,
    FindingRule,
    SecurityFact,
    redacted_projection,
)
from crawler_cli.serialization import (
    CRAWL_ARTIFACT_SCHEMA_VERSION,
    serialize_crawl_job,
    serialize_crawl_result,
    serialize_job_summary_metadata,
)

BASIC_SECRET = "argv-free-basic-secret"
BEARER_SECRET = "argv-free-bearer-secret"

HTTP_BACKENDS = [
    AiohttpBackend,
    CurlCffiBackend,
    pytest.param(
        PlaywrightBackend,
        marks=pytest.mark.playwright_smoke,
        id="playwright",
    ),
]


async def _start_app(app: web.Application) -> tuple[web.AppRunner, str]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets
    assert sockets
    port = sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


# --- (a) secrets stay out of argv ----------------------------------------------


def test_bearer_token_env_keeps_secret_out_of_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLER_TEST_TOKEN", BEARER_SECRET)
    argv = ["crawl", "https://example.com", "--auth-type", "bearer", "--auth-token-env", "CRAWLER_TEST_TOKEN"]
    assert BEARER_SECRET not in " ".join(argv)
    auth = _build_auth(_build_parser().parse_args(argv))
    assert auth is not None
    assert auth.token == BEARER_SECRET
    assert auth.auth_headers() == {"Authorization": f"Bearer {BEARER_SECRET}"}


def test_bearer_token_file_keeps_secret_out_of_argv(tmp_path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text(f"{BEARER_SECRET}\n", encoding="utf-8")
    argv = ["crawl", "https://example.com", "--auth-type", "bearer", "--auth-token-file", str(token_file)]
    auth = _build_auth(_build_parser().parse_args(argv))
    assert auth is not None
    assert auth.token == BEARER_SECRET


def test_bearer_token_sources_are_mutually_exclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLER_TEST_TOKEN", BEARER_SECRET)
    args = _build_parser().parse_args(
        ["crawl", "https://example.com", "--auth-token", "argv-token", "--auth-token-env", "CRAWLER_TEST_TOKEN"]
    )
    with pytest.raises(ValueError, match="Provide only one"):
        _build_auth(args)


def test_unset_token_env_fails_without_leaking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRAWLER_TEST_TOKEN", raising=False)
    args = _build_parser().parse_args(["crawl", "https://example.com", "--auth-token-env", "CRAWLER_TEST_TOKEN"])
    with pytest.raises(ValueError, match="CRAWLER_TEST_TOKEN"):
        _build_auth(args)


# --- (a) secrets stay out of logs and artifacts --------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "auth",
    [
        AuthConfig(auth_type="basic", username="user", password=BASIC_SECRET),
        AuthConfig(auth_type="bearer", token=BEARER_SECRET),
    ],
    ids=["basic", "bearer"],
)
async def test_authenticated_crawl_logs_and_artifact_never_contain_secret(auth: AuthConfig, caplog, capsys) -> None:
    """A DEBUG-level authenticated crawl (with a redirect hop) leaks no secret
    into log records, stdout/stderr, or the serialized artifact."""

    async def start(request: web.Request) -> web.StreamResponse:
        raise web.HTTPMovedPermanently("/dest")

    async def dest(request: web.Request) -> web.Response:
        return web.Response(text="<html><body><p>ok</p></body></html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/dest", dest)
    runner, base = await _start_app(app)

    caplog.set_level(logging.DEBUG)
    config = CrawlConfig(
        auth=auth,
        follow_redirects=True,
        respect_robots_txt=False,
        same_host_only=False,
        enable_content_hashing=True,
        # Loopback fixture server; the ticket-149 destination guard has its own
        # suite. This proof is about secrets never reaching logs or artifacts.
        destination_guard="off",
    )
    engine = CrawlEngine(config, store=MemoryStore())
    try:
        job = await engine.crawl_list([f"{base}/start"])
    finally:
        await engine.close()
        await runner.cleanup()

    assert job.results and job.results[0].status == 200
    captured = capsys.readouterr()
    for secret in (BASIC_SECRET, BEARER_SECRET):
        assert secret not in caplog.text
        for record in caplog.records:
            assert secret not in str(record.args)
        assert secret not in captured.out
        assert secret not in captured.err
        # Saved artifacts must be safe to hand to downstream systems: response
        # headers only, no request Authorization material.
        assert secret not in json.dumps(serialize_crawl_job(job))


# --- (b) credential scope across redirects -------------------------------------


def _backend(backend_cls, auth: AuthConfig):
    name_map = {
        AiohttpBackend: "aiohttp",
        CurlCffiBackend: "curl_cffi",
        PlaywrightBackend: "playwright",
    }
    return backend_cls(
        CrawlConfig(
            backend=name_map[backend_cls],
            auth=auth,
            follow_redirects=True,
            # Loopback fixture server; see the note above.
            destination_guard="off",
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_cls", HTTP_BACKENDS, ids=["aiohttp", "curl_cffi", "playwright"])
async def test_bearer_token_not_forwarded_to_cross_origin_redirect(backend_cls) -> None:
    seen: dict[str, str | None] = {}
    redirect_to = ""

    async def start(request: web.Request) -> web.StreamResponse:
        seen["start"] = request.headers.get("Authorization")
        raise web.HTTPFound(redirect_to)

    async def destination(request: web.Request) -> web.Response:
        seen["destination"] = request.headers.get("Authorization")
        return web.Response(text="ok")

    start_app = web.Application()
    start_app.router.add_get("/", start)
    destination_app = web.Application()
    destination_app.router.add_get("/", destination)
    start_runner, start_url = await _start_app(start_app)
    destination_runner, destination_url = await _start_app(destination_app)
    redirect_to = f"{destination_url}/"
    backend = _backend(backend_cls, AuthConfig(auth_type="bearer", token=BEARER_SECRET))
    try:
        result = await backend.fetch(f"{start_url}/")
    finally:
        await backend.close()
        await start_runner.cleanup()
        await destination_runner.cleanup()

    assert result.status == 200
    assert seen["start"] == f"Bearer {BEARER_SECRET}"
    assert seen["destination"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_cls", HTTP_BACKENDS, ids=["aiohttp", "curl_cffi", "playwright"])
@pytest.mark.parametrize(
    "auth",
    [
        AuthConfig(auth_type="basic", username="user", password="pass"),
        AuthConfig(auth_type="bearer", token=BEARER_SECRET),
    ],
    ids=["basic", "bearer"],
)
async def test_credentials_survive_same_origin_redirect(backend_cls, auth: AuthConfig) -> None:
    """Same-origin hops (e.g. /old -> /new during a migration crawl) must keep
    the credentials, or authenticated staging crawls would 401 mid-chain."""
    seen: dict[str, str | None] = {}

    async def start(request: web.Request) -> web.StreamResponse:
        seen["start"] = request.headers.get("Authorization")
        raise web.HTTPMovedPermanently("/dest")

    async def dest(request: web.Request) -> web.Response:
        seen["dest"] = request.headers.get("Authorization")
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/dest", dest)
    runner, base = await _start_app(app)
    backend = _backend(backend_cls, auth)
    try:
        result = await backend.fetch(f"{base}/start")
    finally:
        await backend.close()
        await runner.cleanup()

    assert result.status == 200
    assert seen["start"] is not None
    assert seen["dest"] == seen["start"]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_cls", HTTP_BACKENDS, ids=["aiohttp", "curl_cffi", "playwright"])
async def test_domain_scoped_auth_not_sent_to_other_hosts(backend_cls) -> None:
    """--auth is host-scoped via AuthConfig.domain: a fetch of a different host
    must not carry the Authorization header at all."""
    seen: dict[str, str | None] = {}

    async def page(request: web.Request) -> web.Response:
        seen["page"] = request.headers.get("Authorization")
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", page)
    runner, base = await _start_app(app)
    auth = AuthConfig(auth_type="bearer", token=BEARER_SECRET, domain="protected.example")
    backend = _backend(backend_cls, auth)
    try:
        result = await backend.fetch(f"{base}/")
    finally:
        await backend.close()
        await runner.cleanup()

    assert result.status == 200
    assert seen["page"] is None


# --- (c) recursive known-secret absence proof (ticket 153) ----------------------

# Every value below is a KNOWN TEST SECRET planted into a different part of the
# evidence pipeline. None of them may survive into any output. Each entry is
# planted in the place named by its key, so a failure names the leaking path.
PLANTED_SECRETS: dict[str, str] = {
    "response_header": "planted-header-api-key-alpha",
    "set_cookie": "planted-session-cookie-bravo",
    "query_string": "planted-query-token-charlie",
    "form_value": "planted-form-password-delta",
    "stack_trace": "planted-stack-secret-echo",
    "dsn_password": "planted-dsn-password-foxtrot",
    "proxy_password": "planted-proxy-password-golf",
    "bearer_token": "planted-bearer-token-hotel",
    "basic_password": "planted-basic-password-india",
    "private_key_body": "planted-private-key-material-juliet",
    "email_address": "planted.person@example.invalid",
}

PLANTED_DSN = f"postgresql://crawler:{PLANTED_SECRETS['dsn_password']}@db.internal:5432/crawl"
PLANTED_PROXY = f"http://proxyuser:{PLANTED_SECRETS['proxy_password']}@proxy.internal:8080"
PLANTED_PRIVATE_KEY = (
    f"-----BEGIN RSA PRIVATE KEY-----\n{PLANTED_SECRETS['private_key_body']}\n-----END RSA PRIVATE KEY-----"
)

PROOF_DIGEST = CorrelationDigest.from_key(b"secret-absence-proof-key-01234567", run_id="run-proof")
PROOF_OBSERVED_AT = datetime(2026, 8, 21, 9, 0, 0, tzinfo=timezone.utc)

PROOF_RULE = FindingRule(
    rule_id="crawler-cli.test.secret-absence",
    title="Planted secret material",
    category="test",
    description="A synthetic finding whose every field was seeded with a known test secret.",
    severity="info",
    confidence="low",
    remediation="None; this rule exists only to prove the redaction pipeline.",
    limitations="Synthetic fixture, not a real observation.",
)


@pytest.fixture
def registered_process_secrets() -> Iterator[None]:
    """Register the secrets this *process* knows, as the CLI would at startup.

    Site-supplied secrets (a response header, a Set-Cookie value, a query
    parameter) are deliberately NOT registered: those must be caught by the
    redaction policy alone, which is the case that matters for a real crawl.
    """
    SECRETS.register(PLANTED_SECRETS["bearer_token"], label="auth-token")
    SECRETS.register(PLANTED_SECRETS["stack_trace"], label="auth-token")
    SECRETS.register_basic_credentials("alice", PLANTED_SECRETS["basic_password"])
    try:
        yield
    finally:
        SECRETS.clear()


def _iter_strings(value: Any) -> Iterator[str]:
    """Yield every string reachable anywhere inside a nested structure."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_strings(item)
    else:
        yield str(value)


def assert_no_planted_secret(where: str, payload: Any) -> None:
    """Assert that no planted secret appears anywhere inside *payload*."""
    haystack = "\n".join(_iter_strings(payload))
    for name, secret in PLANTED_SECRETS.items():
        assert secret not in haystack, f"planted {name!r} secret leaked into {where}"


def _proof_findings():
    """Build findings whose every evidence surface carries a planted secret."""
    policy = FindingPolicy([PROOF_RULE])
    facts = [
        SecurityFact(
            rule_id=PROOF_RULE.rule_id,
            url=(
                "https://alice:"
                f"{PLANTED_SECRETS['basic_password']}@example.com/reset"
                f"?token={PLANTED_SECRETS['query_string']}&next=/account"
                f"#access_token={PLANTED_SECRETS['query_string']}"
            ),
            source="response_header",
            detector="secret-absence-proof",
            detector_version="1.0.0",
            observed_at=PROOF_OBSERVED_AT,
            attributes={
                "headers": redact_headers(
                    {
                        "X-API-Key": PLANTED_SECRETS["response_header"],
                        "Authorization": f"Bearer {PLANTED_SECRETS['bearer_token']}",
                        "Set-Cookie": [
                            f"SESSIONID={PLANTED_SECRETS['set_cookie']}; Path=/",
                            f"csrftoken={PLANTED_SECRETS['set_cookie']}; Path=/",
                        ],
                        "Server": "nginx",
                    }
                ),
                "form_fields": redact_form_fields({"password": PLANTED_SECRETS["form_value"]}),
                "database": sanitize_dsn(PLANTED_DSN),
                "proxy": sanitize_proxy_url(PLANTED_PROXY),
                "contact": f"reported by {PLANTED_SECRETS['email_address']}",
            },
            snippets=(
                bounded_snippet(f"Authorization: Bearer {PLANTED_SECRETS['bearer_token']}"),
                bounded_snippet(PLANTED_PRIVATE_KEY),
                bounded_snippet(f"<input type=hidden name=csrf value={PLANTED_SECRETS['form_value']}>"),
            ),
        )
    ]
    return policy.evaluate_all(facts)


def _serializer() -> EvidenceSerializer:
    return EvidenceSerializer(run_id="run-proof", digest=PROOF_DIGEST)


def test_planted_secrets_absent_from_json_output(tmp_path, registered_process_secrets) -> None:
    path = _serializer().write_json(tmp_path / "findings.json", _proof_findings())
    text = path.read_text(encoding="utf-8")
    assert_no_planted_secret("the JSON artifact", text)
    # The finding really was produced; this is not a vacuous pass.
    assert json.loads(text)["finding_count"] == 1


def test_planted_secrets_absent_from_jsonl_output(tmp_path, registered_process_secrets) -> None:
    path = _serializer().write_jsonl(tmp_path / "findings.jsonl", _proof_findings())
    lines = [line for line in path.read_text(encoding="utf-8").split("\n") if line]
    assert len(lines) == 1
    assert_no_planted_secret("the JSONL artifact", lines)


def test_saved_crawl_artifacts_redact_response_headers_but_keep_them_in_memory(
    tmp_path, registered_process_secrets
) -> None:
    """Crawl-artifact JSON and JSONL may never expose response-header secrets."""
    raw_headers = {
        "Set-Cookie": f"sid={PLANTED_SECRETS['set_cookie']}; Path=/; HttpOnly",
        "X-API-Key": PLANTED_SECRETS["response_header"],
        "Location": f"https://example.test/next?token={PLANTED_SECRETS['query_string']}",
        "X-Debug-Redirect": f"Bearer {PLANTED_SECRETS['bearer_token']}",
    }
    result = CrawlResult(
        requested_url="https://example.test/start",
        final_url="https://example.test/next",
        status=302,
        headers=raw_headers,
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=None,
        raw_html=None,
    )
    job = CrawlJobResult(mode="open", seed_urls=[result.requested_url], results=[result], run_id="run-proof")

    # Detector-facing crawl data is deliberately raw; only serialization projects it.
    assert result.headers is raw_headers
    assert result.headers["Set-Cookie"].endswith("HttpOnly")

    exported_headers = serialize_crawl_result(result)["headers"]
    assert exported_headers["Set-Cookie"] == REDACTED
    assert exported_headers["X-API-Key"] == REDACTED
    assert exported_headers["Location"].endswith(f"token={REDACTED}")
    assert exported_headers["X-Debug-Redirect"] == f"Bearer {REDACTED}"

    json_path = tmp_path / "crawl.json"
    json_path.write_text(json.dumps(serialize_crawl_job(job)), encoding="utf-8")
    jsonl_path = tmp_path / "crawl.jsonl"
    jsonl_path.write_text(
        "\n".join(
            json.dumps(item)
            for item in (
                serialize_crawl_result(result),
                {
                    "__type": "summary",
                    "schema_version": CRAWL_ARTIFACT_SCHEMA_VERSION,
                    "mode": job.mode,
                    "run_id": job.run_id,
                    "seed_urls": job.seed_urls,
                    **serialize_job_summary_metadata(job),
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    assert_no_planted_secret("the saved crawl JSON artifact", json_path.read_text(encoding="utf-8"))
    assert_no_planted_secret("the saved crawl JSONL artifact", jsonl_path.read_text(encoding="utf-8"))


def test_planted_secrets_absent_from_csv_output(tmp_path, registered_process_secrets) -> None:
    path = _serializer().write_csv(tmp_path / "findings.csv", _proof_findings())
    assert_no_planted_secret("the CSV artifact", path.read_text(encoding="utf-8"))


def test_planted_secrets_absent_from_html_output(tmp_path, registered_process_secrets) -> None:
    path = _serializer().write_html(tmp_path / "findings.html", _proof_findings())
    assert_no_planted_secret("the HTML report", path.read_text(encoding="utf-8"))


def test_planted_secrets_absent_from_the_report_structure(registered_process_secrets) -> None:
    """Walk the structure itself, not only its rendering: a nested key, tuple
    or non-string leaf could otherwise hide a secret that ``json.dumps`` would
    have shown but a consumer reading the object would still see."""
    payload = _serializer().report_payload(_proof_findings())
    assert_no_planted_secret("the report structure", payload)


def test_planted_secrets_absent_from_the_gui_projection(registered_process_secrets) -> None:
    payload = _serializer().report_payload(_proof_findings())
    assert_no_planted_secret("the GUI/API projection", redacted_projection(payload))


def test_planted_secrets_absent_from_stdout(capsys, registered_process_secrets) -> None:
    print(json.dumps(_serializer().report_payload(_proof_findings()), indent=2))
    captured = capsys.readouterr()
    assert_no_planted_secret("stdout", captured.out)
    assert_no_planted_secret("stderr", captured.err)


def test_planted_secrets_absent_from_log_records(caplog, registered_process_secrets) -> None:
    logger = logging.getLogger("crawler_cli.tests.secret_absence")
    install_log_redaction(logger)
    caplog.set_level(logging.DEBUG)
    logger.debug("connecting to %s via %s", PLANTED_DSN, PLANTED_PROXY)
    logger.info(
        "response headers %s",
        {"X-API-Key": PLANTED_SECRETS["response_header"], "Set-Cookie": f"sid={PLANTED_SECRETS['set_cookie']}"},
    )
    logger.warning("fetched https://example.com/?token=%s", PLANTED_SECRETS["query_string"])
    assert_no_planted_secret("caplog text", caplog.text)
    for record in caplog.records:
        assert_no_planted_secret("a log record", [record.getMessage(), str(record.args)])


def test_planted_secrets_absent_from_exception_text_and_tracebacks(registered_process_secrets) -> None:
    def open_backend() -> None:
        raise RuntimeError(f"backend startup failed for {PLANTED_DSN} through {PLANTED_PROXY}")

    try:
        open_backend()
    except RuntimeError as exc:
        rendered_message = redact_exception(exc)
        rendered_traceback = redact_traceback(exc)
    assert_no_planted_secret("an exception message", rendered_message)
    assert_no_planted_secret("a traceback", rendered_traceback)
    assert "RuntimeError" in rendered_message
    assert "Traceback" in rendered_traceback


def test_secret_loading_failure_names_the_source_not_the_value(monkeypatch) -> None:
    """An unset credential source must fail by naming the variable only."""
    monkeypatch.delenv("CRAWLER_PLANTED_TOKEN", raising=False)
    args = _build_parser().parse_args(["crawl", "https://example.com", "--auth-token-env", "CRAWLER_PLANTED_TOKEN"])
    with pytest.raises(ValueError) as excinfo:
        _build_auth(args)
    assert "CRAWLER_PLANTED_TOKEN" in str(excinfo.value)
    assert_no_planted_secret("a secret-loading exception", redact_traceback(excinfo.value))
