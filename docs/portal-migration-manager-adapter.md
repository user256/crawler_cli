# Portal Migration Manager adapter — crawler-cli 0.2.1

`crawler-cli` 0.2.1 adds a deliberately narrow worker entry point:

```text
migration-manager-crawler --capabilities
migration-manager-crawler --config-fd N
```

The general `crawler-cli` command remains unchanged. The adapter exists
because the frozen 0.2.0 integration contract explicitly delegates SSRF
protection to Portal; it is a new release surface and must be pinned as
`crawler-cli==0.2.1`.

## Capability probe

`--capabilities` writes one compact JSON object and exits zero. The manifest
uses integer `schema_version: 1`, release `crawler-cli@v0.2.1`, protocol
`portal-url-policy/1`, all five required `guarded_paths`, a UTC `generated_at`,
and:

```json
{
  "capabilities": {
    "crawl_http": true,
    "crawl_browser": false,
    "crawl_embeddings": false
  }
}
```

The browser navigation and subresource paths are guarded by hard rejection
before any browser or network process starts. Live compare is likewise not a
supported 0.2.1 dispatch operation and is rejected before network access.

## Dispatch and result

`--config-fd N` requires `N >= 3`, reads at most 1 MiB of UTF-8 JSON, and
accepts only `migration-manager/crawl-dispatch/1` for version/release 0.2.1.
The job, attempt, and run IDs, lease fence, target policy, exact-origin
credential rule, initial pin, feature flags, budgets, and result schema are
validated before crawling.

Secrets are never accepted on argv or in the JSON envelope. A bearer token may
be named by the producer's `--auth-token-env VAR` command declaration and is
read from that environment variable. It is sent only to the exact configured
origin and is never included in diagnostics or results.

A valid run writes exactly one final
`migration-manager/run-result/1` JSON envelope. Observations carry hashes and
extracted metadata but no raw response body, headers, credential, or artifact
claim. Artifact availability is therefore truthfully `none`.

## Connection policy and budgets

The adapter uses a fresh one-address aiohttp connector per request with native
redirect following and DNS caching disabled. Immediately before every page,
robots, sitemap, and redirect-hop socket, it:

1. normalizes the HTTP(S) URL and rejects userinfo/fragments;
2. resolves the hostname again;
3. rejects the complete answer set if any address is denied;
4. selects a deterministic permitted address;
5. pins the connector to that address while retaining the hostname for Host
   and TLS SNI.

SaaS permits only globally routable addresses. An appliance can additionally
use RFC1918 or IPv6 ULA addresses only when `allow_private_network` is true.
Loopback, link-local/metadata, reserved, multicast, and unspecified addresses
remain forbidden.

The page, total request, total response-byte, per-response byte, redirect-hop,
sitemap depth, and wall-clock limits apply across the entire adapter process,
including robots and sitemap discovery.
