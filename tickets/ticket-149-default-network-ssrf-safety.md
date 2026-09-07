# Ticket 149: Default destination-network and SSRF safety

## Goal

Prevent the crawler from reaching loopback, private, link-local, reserved, or
cloud-metadata destinations through an untrusted URL, redirect, sitemap, DNS
change, or browser subresource unless the operator explicitly authorises that
network class.

This protects the machine running `crawler_cli`. It is not an SSRF payload
scanner for the target site.

## Background (2026-08-21)

The engine rejects unsupported schemes, credential-bearing sitemap URLs, and
out-of-scope hosts. It does not provide a default IP-class policy for ordinary
crawls. A seed or redirect can therefore name `localhost`, a private address,
link-local metadata, or a hostname that resolves differently between checking
and connecting.

`portal-url-policy/1` provides a strong opt-in seam for Portal-managed aiohttp
connections: the external policy authorises a URL and returns a pinned literal
address. Its declared coverage deliberately excludes browser navigation,
browser subresources, and live comparisons. The general CLI needs an honest
baseline safety policy, and security-adjacent modes must fail closed when a
backend cannot provide the declared protection.

Ticket 148 answers “was this origin declared in the job scope?” This ticket
answers the separate question “where will this connection actually go?” Both
checks are required.

## Default policy

- Permit only `http` and `https` target URLs.
- Resolve every target hostname and reject it if any candidate address is not
  globally routable. Treat mixed public/private answers as denied, not as an
  invitation to choose the public answer.
- Reject IPv4 and IPv6 loopback, private, link-local, multicast, unspecified,
  reserved, documentation/test ranges, and IPv4-mapped equivalents.
- Maintain an explicit deny entry for common link-local metadata destinations;
  do not rely only on hostname spelling.
- Reject literal integer, hexadecimal, octal, shortened, zone-qualified, or
  other non-canonical IP spellings unless normalized safely by one parser.
- Re-authorize and re-resolve each redirect target. Approval of the first URL
  never carries across origins.
- Pin the approved address to the connection wherever the backend permits it,
  closing the DNS-check/DNS-connect time-of-check gap.
- Apply request, response-byte, redirect-hop, and timeout limits before an
  exception can create an unbounded retry path.

## Explicit private-network use

- Add `--allow-private-network` only for operators crawling systems they own.
- The flag is accepted in a security-adjacent mode only when the ticket-148
  scope manifest also sets `allow_private_network: true`.
- Requiring both controls is deliberate: the manifest records permission and
  the CLI flag records this invocation's intent.
- Emit a prominent warning and artifact field when enabled.
- An optional exact CIDR allowlist may narrow the exception. Do not implement
  “all RFC1918” as the only granularity if exact CIDRs are practical.

## Backend coverage

### aiohttp

- Reuse or generalize the pinned-resolver/one-shot connection mechanism used by
  the Portal policy.
- Perform the policy check for initial, robots, sitemap, probe, and every
  redirect connection.
- Never return a checked hostname to an unconstrained resolver afterward.

### curl_cffi

- Determine whether the installed API supports address pinning equivalent to
  curl's resolve mapping.
- If it can pin, add tested parity. If it can only pre-resolve, declare the
  residual rebinding limitation in the capability object.
- Security-adjacent commands requiring strict protection must reject a backend
  whose capability is insufficient; they must not print a warning and proceed.

### Playwright and Obscura

- Intercept top-level navigation, redirects, popups, workers, and subresource
  URLs and reject disallowed schemes/origins before dispatch where possible.
- Document whether the browser process can bind DNS to the approved address.
- URL interception without connection pinning is not full rebinding safety.
- Strict security modes must fail closed if the selected browser path cannot
  meet the required destination guarantee. Ordinary browser crawls may proceed
  only with an accurate capability warning/artifact field.

### Proxies

- Distinguish local DNS resolution from remote proxy resolution.
- If a proxy hides the destination address from the crawler, strict mode must
  require a policy-aware proxy/gateway contract or reject the combination.
- A proxy URL itself is configuration infrastructure; target-scope permission
  does not authorize arbitrary connections to proxy endpoints.

## Observability

- Add structured rejection reasons: `private_address`, `loopback`,
  `link_local`, `reserved_address`, `mixed_dns_answer`, `dns_rebinding_risk`,
  `unsupported_address_literal`, and `backend_guard_unavailable`.
- Record zero HTTP status for pre-connection denials and keep them separate
  from DNS failures and target HTTP errors.
- Serialize a capability declaration identifying protected paths: initial,
  redirect, robots, sitemap, probes, browser navigation, and browser
  subresources.
- Never log resolved proxy credentials or full sensitive URLs.

## Implementation tasks

1. Add a shared destination policy using `ipaddress` and a single hostname/IP
   normalization path.
2. Integrate it behind the engine/backend fetch boundary, not only discovery.
3. Generalize safe connection pinning for aiohttp without weakening the Portal
   policy's external authorization contract.
4. Add backend capability declarations and strict-mode startup validation.
5. Add double-confirmed private-network exceptions and optional exact CIDRs.
6. Apply the guard to all auxiliary fetches and live-comparison paths.
7. Add structured summary/artifact fields and documentation.

## Test matrix

- IPv4/IPv6 loopback, RFC1918/ULA, link-local, multicast, unspecified,
  reserved, documentation ranges, and mapped-address forms.
- Public hostname with all-public answers succeeds.
- Mixed public/private answer fails.
- DNS answer changes between authorization and attempted connect; the actual
  connection remains pinned or the backend fails closed.
- Public URL redirecting to a private literal/hostname is blocked before the
  second request.
- Private sitemap, robots-discovered sitemap, hreflang, archive, and probe URLs
  are blocked consistently.
- Browser subresource and popup cases are either blocked or rejected at
  startup as unsupported—never silently unguarded in strict mode.
- Remote-DNS proxy combinations exercise the capability decision.
- Private access needs both manifest permission and the explicit CLI flag.
- Rejection artifacts contain no credentials or sensitive query values.

## Out of scope

- Sending SSRF payloads to application parameters.
- Cloud-provider metadata enumeration.
- Port scanning or service fingerprinting.
- Treating “globally routable” as evidence that the operator is authorised;
  ticket 148 remains authoritative for job scope.

## Definition of Done

- Ordinary HTTP crawling has a documented default destination-IP policy.
- Strict security-adjacent modes cannot use a backend/path whose guard
  capability is incomplete.
- Redirects and auxiliary fetches cannot pivot into a denied network.
- DNS rebinding is closed by connection pinning where strict protection is
  claimed; capability output tells the truth elsewhere.
- Private-network use requires manifest permission plus explicit invocation
  intent and is visible in artifacts.
- The complete IP, redirect, backend, proxy, and no-secret test matrix passes.

## Appendix: verified address-classification traps (added 2026-09-07)

Reviewed prior art exists — see ticket **162**. `portal_adapter.py` on the
unmerged branch `feature/3350-portal-url-policy-v1` (`8fcdb54`) implements the
address-class policy and a per-hop resolve-validate-pin loop, and its tests
carry the DNS-rebinding cases worth reproducing. `master` already has the better
*mechanism* (`AiohttpBackend.fetch_for_purpose` and `_PinnedResolver` in
`backends.py`); what it lacks is the *decision*. Harvest the policy, not the
client.

The prior art's classifier is **not sufficient on its own**. Each result below
was executed against this project's Python before being recorded, and each one
defeats a naive `is_global` / `is_loopback` / `is_private` check:

| Address | Reported by `ipaddress` | Why it matters |
| --- | --- | --- |
| `::ffff:127.0.0.1` | `is_loopback` is **False** (`is_private` True) | A loopback check that does not unwrap `.ipv4_mapped` misses it. Under the private-network exception it would then be permitted. |
| `64:ff9b::7f00:1` | `is_global` is **True** | NAT64 wrapping `127.0.0.1`. An allow rule keyed on `is_global` **permits** it, and a NAT64 gateway translates it back to loopback. Deny `64:ff9b::/96` and `64:ff9b:1::/48` explicitly. |
| `2002:7f00:1::1` | `is_private` True, `is_global` False | 6to4 wrapping `127.0.0.1`; unpack the embedded v4 address rather than relying on the class. |
| `fd00:ec2::254` | `is_private` True, `is_link_local` **False** | AWS IPv6 instance metadata. Inside `fc00::/7`, so `allow_private_network` would permit it. Needs an explicit metadata denylist, not just `is_link_local`. |
| `100.100.100.200` | `is_private` False, `is_global` False | Alibaba metadata. Falls in neither of the two obvious buckets. |

Non-canonical literals are equally real: `0177.0.0.1`, `2130706433`, and
`0x7f.1` were each confirmed to resolve to `127.0.0.1` through `getaddrinfo` on
this host. They must be rejected as `unsupported_address_literal` by a single
normalization path rather than being allowed to reach the resolver and caught by
luck on the far side.

Also not covered by the prior art, and therefore new work: structured rejection
reason codes, an exact-CIDR allowlist (it is all-RFC1918-or-nothing), the
proxy/browser/curl_cffi capability story, the live-comparison fetch paths, and a
distinct `probe` connection purpose.

## Delivery status (2026-09-07, PR #72)

Landed: `destination_policy.py` (address-class decision, embedded-address
unwrapping, metadata denylist, single normalization path, fail-closed mixed
answer sets), the `destination_guard` / `allow_private_network` /
`allow_network_cidrs` config surface with strict-mode fail-closed validation,
and the aiohttp `_GuardedResolver` tier plus the literal-IP pre-request check.

**Not delivered: the deny-by-default posture.** `destination_guard` defaults to
`off`. Turning it on denies loopback for every caller, stopping an ordinary
`crawler-cli http://localhost:3000/` and breaking every test in this repository
that drives a loopback fixture server — unit, security-proof contract, and
Postgres integration alike. That switch needs a repo-wide fixture sweep and its
own review.

Still to land: the posture switch, auxiliary fetch paths (robots, archive), the
CLI double-confirmation flags, honest per-backend capability output, and
rejection reasons in artifacts.

## Status

partially done (2026-09-07, PR #72; Priority: **P1/security**, depends on
**148**; should land before
**146**, **150–152**, and **154**) — crawler-host protection and honest backend
capabilities, not target-side SSRF testing. Prior art and verified
classification traps recorded 2026-09-07; see ticket **162**.
