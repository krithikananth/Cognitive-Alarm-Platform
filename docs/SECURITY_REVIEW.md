# Security Review & Penetration Test Report

**System:** Intelligent Cognitive Alarm Platform (ICAP)
**Review date:** 2026-08-12
**Scope:** Backend API (FastAPI), SPA (React), reverse proxy (nginx), container stack
**Method:** White-box review of application source, configuration and container
definitions; automated dependency/SAST scanning; an executable abuse-case test
suite (`backend/tests/test_security_owasp.py`); and **runtime verification of
the edge against a real nginx container** (`backend/tests/test_tls_runtime.py`),
which builds `nginx/Dockerfile`, serves `nginx/nginx.conf` and speaks real TLS
and HTTP to it.
**Out of scope:** Physical security, social engineering, the Google OAuth
provider itself, and the hosting platform beneath Docker.

---

## 1. Executive summary

The platform's authentication and access-control implementation is strong:
session revocation, per-account and per-address brute-force lockout, OAuth
anti-CSRF state, HttpOnly cookies and database-backed role checks were all
verified and hold up under adversarial testing. The material weaknesses found
were in the layers *around* the application — transport security, information
disclosure, supply-chain hygiene and audit logging — rather than in its core
authorization logic.

Nine issues were identified. All nine are closed. Three residual risks remain
accepted with justification (§5).

| ID | Finding | Severity | Status |
|----|---------|----------|--------|
| ICAP-S-01 | No TLS; all traffic served over plaintext HTTP | **High** | Fixed, runtime-verified |
| ICAP-S-02 | No HSTS — trivially downgraded even once TLS exists | **Medium** | Fixed, runtime-verified |
| ICAP-S-03 | No Content-Security-Policy | **Medium** | Fixed, runtime-verified |
| ICAP-S-04 | OpenAPI schema, Swagger UI and ReDoc public in production | **Medium** | Fixed, runtime-verified |
| ICAP-S-05 | Six dependencies with published CVEs; no scanning at all | **High** | Fixed |
| ICAP-S-06 | `eval()` on generated arithmetic in challenge generation | **Medium** | Fixed |
| ICAP-S-07 | Security events produced no audit record (OWASP A09) | **Medium** | Fixed |
| ICAP-S-08 | `Content-Disposition` filename built by unescaped interpolation | **Low** | Fixed |
| ICAP-S-09 | Alert webhook accepted any URL scheme (`file://`, `gopher://`) | **Low** | Fixed |

---

## 2. Test coverage by OWASP Top 10 (2021)

| Category | Before | Now | Evidence |
|----------|--------|-----|----------|
| A01 Broken access control | Covered | Covered | `test_rbac.py`, `test_rbac_matrix.py` (40 tests) |
| A02 Cryptographic failures | Partial | Covered | TLS 1.2+ **verified at runtime** (1.0/1.1 refused, ECDHE suite), bcrypt, HS256 with key-strength validation |
| A03 Injection | **Not tested** | Covered | `TestSqlInjection`, `TestHeaderAndLogInjection`, `TestCodeExecution` (27 tests) |
| A04 Insecure design | Partial | Covered | OAuth state, challenge integrity, rate limiting |
| A05 Security misconfiguration | Partial | Covered | `TestApiSchemaExposure`, `TestEdgeTlsAndHeaders` (17 tests) + 36 runtime edge tests |
| A06 Vulnerable components | **Not tested** | Covered | `TestVulnerableComponents`, `TestTriagedFindings` (15 tests) + `scripts/security_scan.py` |
| A07 Auth failures | Covered | Covered | `test_auth_security.py` (56 tests) |
| A08 Integrity failures | **Not tested** | Covered | `TestMassAssignment`, `TestChallengeIntegrity`, `TestTokenIntegrity` (14 tests) |
| A09 Logging & monitoring | **Not tested** | Covered | `TestSecurityLogging` (11 tests) |
| A10 SSRF | **Not tested** | Covered | `TestServerSideRequestForgery` (13 tests) |

Also covered, though not a Top-10 category in their own right: cross-site
scripting (`TestCrossSiteScripting`), path traversal (`TestPathTraversal`) and
open redirect (`TestOpenRedirect`).

**Suite total: 184 application tests + 36 edge runtime tests, all passing.**

---

## 3. Findings in detail

### ICAP-S-01 — No transport security (High)

**Observed.** `nginx/nginx.conf` had a single `listen 8080;` server with no
`ssl_certificate`, no port 443 listener and no redirect. Session cookies were
issued with `Secure` in production, meaning the SPA could not have functioned
over the only transport actually offered.

**Impact.** Every credential, session cookie and JWT crossed the network in
cleartext. A network-adjacent attacker could read or modify any request.

**Remediation.** A TLS listener on 8443 with TLS 1.2/1.3 only, forward-secret
cipher suites and session tickets disabled. Port 8080 now serves nothing but a
`308` redirect to HTTPS (health probes excepted, so container checks are not
bounced). `nginx/docker-entrypoint-tls.sh` provisions a self-signed certificate
when no CA-issued one is mounted, so the stack cannot silently start in
plaintext. `docker-compose.yml` publishes 443 and mounts a writable volume for
the certificate material.

**Verified by.** Static: `TestEdgeTlsAndHeaders::test_tls_listener_exists`,
`test_only_modern_tls_versions_are_offered`, `test_plain_http_is_redirected`,
`test_tls_certificate_is_provisioned_before_startup`, `test_https_port_is_published`.
**Runtime** (`test_tls_runtime.py`, against a real nginx container): TLS 1.2 and
1.3 negotiate; TLS 1.0 and 1.1 are refused at the handshake; the default
negotiation lands on TLS 1.3; the agreed TLS 1.2 suite is ECDHE (forward
secret); the entrypoint's generated certificate validates against
`localhost` via its SAN; and plain HTTP returns `308` to `https://` preserving
path and query, while `/nginx-health` is not redirected.

---

### ICAP-S-02 — No HSTS (Medium)

**Observed.** No `Strict-Transport-Security` header anywhere.

**Impact.** Even after TLS is enabled, a first-visit or typed-URL request goes
over HTTP and is strippable (sslstrip-style downgrade).

**Remediation.** `max-age=31536000; includeSubDomains`, set **only** on the TLS
listener — emitting HSTS from a plaintext origin is meaningless and browsers
ignore it. `preload` is deliberately *not* set: submitting to the preload list
is a one-way action that should be a conscious operational decision, not a
default baked into a template.

**Verified by.** Static: `test_hsts_is_set_and_long_lived`,
`test_hsts_is_only_sent_over_tls`. **Runtime**: the header is present on HTTPS
responses with `max-age=31536000` and `includeSubDomains`, is present on error
responses (`/docs` → 404) as well as successful ones, and is **absent** from the
plain-HTTP listener.

---

### ICAP-S-03 — No Content-Security-Policy (Medium)

**Observed.** Only `X-Content-Type-Options`, `X-Frame-Options` and
`Referrer-Policy` were set. No CSP, so any injected script would execute with
full privileges.

**Impact.** CSP is the last line of defence when an XSS sink is introduced. Its
absence turns a single future mistake into full session compromise.

**Remediation.** A policy with `default-src 'self'`, `object-src 'none'`,
`frame-ancestors 'none'`, `base-uri 'self'` and `form-action 'self'`.
Critically, **`script-src` does not contain `'unsafe-inline'` or
`'unsafe-eval'`** — this required setting `INLINE_RUNTIME_CHUNK=false` in the
frontend build, because Create React App inlines the webpack runtime into
`index.html` by default and that alone would have forced an unsafe policy.

`style-src` retains `'unsafe-inline'`: recharts and framer-motion inject
`<style>` elements at runtime. This is a known, accepted weakening — style
injection is far less dangerous than script injection — and is recorded in §5.

`connect-src` is restricted to the app's own origin plus the three Firebase
Cloud Messaging hosts required for push registration.

**Verified by.** Static: `test_csp_is_defined`,
`test_csp_does_not_allow_inline_scripts`,
`test_csp_blocks_framing_and_object_embedding`,
`test_frontend_build_avoids_inline_scripts`. **Runtime**: the delivered header
parses to `default-src 'self'`, `script-src` exactly `'self'` (no
`'unsafe-inline'`, no `'unsafe-eval'`), `frame-ancestors 'none'`,
`object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, and a
`connect-src` that still permits the FCM registration hosts — checked on both
SPA and `/api/` responses.

---

### ICAP-S-04 — API schema publicly exposed in production (Medium)

**Observed.** `create_app()` hard-coded `docs_url="/docs"` and
`redoc_url="/redoc"`, and `/openapi.json` defaulted on. nginx proxied all three
unauthenticated in every environment.

**Impact.** A complete, machine-readable map of 126 routes, their parameters,
schemas and auth requirements — ideal reconnaissance, and it advertises
admin-only surface to anonymous visitors.

**Remediation.** Defence in depth. The backend derives `api_docs_enabled` from
`ENVIRONMENT`: in production the routes are **never registered** (not merely
blocked), and `/` stops advertising them. `ENABLE_API_DOCS=true` can re-enable
them deliberately for an internal deployment. Independently, nginx returns `404`
for `/docs`, `/redoc` and `/openapi.json`, so a misconfigured `ENVIRONMENT`
cannot start publishing the schema unnoticed.

**Verified by.** `TestApiSchemaExposure` (4 tests),
`test_schema_endpoints_are_refused_at_the_edge`, and at runtime
`test_the_api_schema_is_refused_at_the_edge` — `/docs`, `/redoc` and
`/openapi.json` all return `404` from the running edge with no Swagger payload.

---

### ICAP-S-05 — Vulnerable dependencies, no scanning (High)

**Observed.** No dependency scanning, no SAST, no CI security gate, no automated
update mechanism. A first scan found **six** Python packages with published
advisories, including `python-jose` — the JWT library itself.

**Remediation.**

*Tooling.* `scripts/security_scan.py` runs `pip-audit`, `bandit` and
`npm audit` behind one command and one exit code. A scanner that is not
installed reports `skipped` and exits non-zero — a missing scanner must never
look like a clean result. `.github/workflows/security.yml` runs it on every push
and weekly on a schedule (so a CVE published against unchanged code is still
found), and `.github/dependabot.yml` keeps the pins current.

*Fixes applied.*

| Package | Was | Now | Advisories cleared |
|---------|-----|-----|--------------------|
| `python-jose` | 3.3.0 | 3.4.0 | PYSEC-2024-232/233, PYSEC-2025-185 |
| `starlette` | 0.38.6 (transitive) | 0.47.2 (now pinned) | 1 of 7; see §5 for why the rest are blocked |
| `fastapi` | 0.115.0 | 0.116.1 | required to permit the starlette fix |
| `python-multipart` | 0.0.17 | 0.0.31 | all 7 |
| `python-dotenv` | 1.0.1 | 1.2.2 | PYSEC-2026-2270 |
| `pytest` | 8.3.0 | 9.0.3 | PYSEC-2026-1845 |

`starlette` is now pinned explicitly rather than floating as a transitive
dependency, so a future FastAPI bump cannot silently reintroduce a vulnerable
version. The full 1402-test backend suite was re-run against the upgraded stack
and passes.

*Triage.* `security-allowlist.json` records the findings that cannot be fixed
today, each with a reason and a **review date**; the runner fails once a date
passes. This keeps the gate green-but-honest instead of permanently red (a
permanently red gate gets switched off).

**Verified by.** `TestVulnerableComponents` (8 tests) — including that every
Python dependency is pinned with `==`, that the scan runner covers all three
scanners, that a skipped scanner is not treated as a pass, and that CI runs both
the scanners and this suite.

---

### ICAP-S-06 — `eval()` in challenge generation (Medium)

**Observed.** `challenge_service.py` evaluated generated arithmetic with
`eval(equation)` in three branches.

**Impact.** Not exploitable as written — the expression is assembled from
`random.randint()` values and a fixed operator set, with no user input reaching
it. It is recorded as Medium rather than Informational because it is a live
remote-code-execution primitive sitting one refactor away from a user-supplied
string; the AI challenge provider already introduces externally-generated
content into neighbouring code paths.

**Remediation.** `solve_arithmetic()` parses the expression with `ast.parse` and
walks the tree, accepting only integer literals and `+ - * unary±`. Anything
else raises. Results are identical; the primitive is gone.

**Verified by.** `TestCodeExecution` — the solver still computes the same
results, and refuses `__import__('os').system(...)`, attribute traversal,
conditionals and `exec`. `test_challenge_generation_does_not_use_eval` guards
against reintroduction, and `test_challenges.py` (102 tests) confirms unchanged
generation behaviour.

---

### ICAP-S-07 — No security audit trail (Medium, OWASP A09)

**Observed.** Failed logins, lockouts, rejected tokens and denied admin requests
produced **no log record of any kind**. `rate_limit.py` contained no logging at
all. Compounding this, `verify_token()` raises its own `HTTPException`, so
invalid-token rejections bypassed the dependency layer entirely — the single
most common attack signal was completely invisible.

**Impact.** Credential stuffing, token brute-forcing and privilege-escalation
probing were undetectable in progress and unreconstructable afterwards.

**Remediation.** `app/core/security_events.py` emits structured events on a
dedicated `app.security` logger, so the category can be routed and retained
independently. Wired into login success/failure, inactive-account attempts,
lockout transitions, token rejection (with `verify_token`'s exception now
re-raised through the audited path) and every denied role check.

Two properties are enforced centrally rather than trusted to call sites:

* **No credential can be logged.** Any field whose name matches
  `password|secret|token|api_key|authorization|cookie` is dropped before the
  record is built, regardless of what the caller passed.
* **No value can forge a log line.** Control characters are stripped and values
  truncated, so a newline in an attacker-supplied username cannot fabricate a
  second record — belt and braces alongside the JSON formatter's escaping.

Each record carries the request correlation ID, so an audit entry joins directly
to the access log and to any browser error report from the same action.

**Verified by.** `TestSecurityLogging` (11 tests), including
`test_credentials_never_reach_the_log`, `test_a_secret_passed_explicitly_is_dropped`
and `test_crlf_in_a_username_cannot_forge_a_log_line`.

---

### ICAP-S-08 — `Content-Disposition` built by interpolation (Low)

**Observed.** Both export endpoints built the header as
`f'attachment; filename="{filename}"'` with no escaping.

**Impact.** Low — the filename is assembled from an enum-validated report type
and validated `date` objects, so no injection path exists today. It is a
latent response-splitting sink.

**Remediation.** `content_disposition()` / `safe_attachment_filename()` in
`report_export.py` reduce the name to `[A-Za-z0-9._-]`, removing quotes, CR/LF
and path separators. Used by both `/reports/{type}/export` and
`/admin/system-reports/{type}/export`.

**Verified by.** `test_export_filename_cannot_break_the_header`,
`test_export_filename_cannot_carry_a_path`, `test_real_export_header_is_clean`.

---

### ICAP-S-09 — Alert webhook accepted any URL scheme (Low)

**Observed.** `metrics_alert_service._post_webhook` passed the configured URL
straight to `urllib.request.urlopen`, which honours `file://`, `ftp://` and
other handlers (bandit B310).

**Impact.** Low — the URL is operator configuration, not user input, and cannot
be set through any API (verified). A typo or a compromised config value could
nonetheless turn the alerting path into a local-file read.

**Remediation.** Scheme restricted to `http`/`https`; anything else is refused
and logged.

**Verified by.** `TestServerSideRequestForgery::test_alert_webhook_target_is_not_settable_over_the_api`.

---

## 4. Attack scenarios tested and repelled

Confirmed **not** exploitable:

* **SQL injection** — 7 payloads (`' OR '1'='1`, `'; DROP TABLE users; --`,
  `UNION SELECT ... hashed_password`, …) against the login form, admin user
  search, and both sort parameters. Search is parameterized; sort fields and
  order are regex-whitelisted at the schema layer and mapped to column objects,
  so an injected value returns `422` and never reaches SQL. Tables verified
  intact afterwards.
* **Cross-site scripting** — 5 payloads stored via alarm titles and profile
  names. All round-trip as JSON string values; no endpoint returns `text/html`;
  exports remain `application/pdf`.
* **Path traversal** — 6 payloads against report type, export format, admin
  system-report type and numeric path parameters. All rejected; no file content
  ever returned. A static guard asserts no request handler calls `open()` or
  `FileResponse`.
* **SSRF** — 6 payloads (`169.254.169.254` metadata, `file://`, `gopher://`
  Redis) into every field that accepts a URL-shaped string. The client-error
  reporter records `url` but never requests it — asserted by making `urlopen`
  raise for the duration of the test. A static guard asserts the only outbound
  calls in the API layer are in `auth.py`, to Google's constant OAuth hosts.
* **Open redirect** — 6 payloads through the OAuth `error`, `code` and `state`
  parameters, plus speculative `next` / `redirect_uri` / `returnTo` overrides.
  `frontend_redirect_url()` re-asserts scheme and host after assembly and falls
  back to the bare frontend origin, so every `Location` stays on our origin.
* **Mass assignment** — `role`, `is_active`, `is_verified`, `hashed_password`,
  `id` and `tokens_valid_after` submitted to the self-update endpoint. None are
  applied; `AdminUserUpdate` is pinned to exactly four fields.
* **Challenge forgery** — the answer is never present in any client payload;
  dismissal without solving is refused; a forged verification token is refused;
  and a client-supplied `expected_answer` matching its own `user_answer` does
  **not** produce a pass (the grading key comes from the server session).
* **Token forgery** — `alg: none` tokens rejected; a payload edited to
  `role: admin` fails signature verification and cannot reach admin routes.

---

## 5. Remaining dependency advisories (register)

Nothing below is dismissed. Each entry records the package, the advisories, the
severity, **whether the vulnerable code path is reachable from ICAP**, why it is
still open, and what compensates for it in the meantime.

Reachability was determined by inspection, not assumption. Two facts do most of
the work:

* **ICAP signs and verifies JWTs with HS256 only** (`ALGORITHM = "HS256"`;
  `jwt.encode(..., algorithm=HS256)` / `jwt.decode(..., algorithms=["HS256"])`).
  No RSA/ECDSA key material is ever parsed, so ASN.1 decoding and ECDSA signing
  are not on any ICAP path.
* **The backend mounts no static file handler and no class-based views.**
  `StaticFiles`, `FileResponse`, `HTTPEndpoint`, `request.url_for` and
  `request.base_url` return **zero** matches across `backend/app/`.

The blocking entries are mirrored in `security-allowlist.json` with a
`review_by` date; `scripts/security_scan.py` fails the build once a date passes.

### 5.1 Python

| Package | Advisories | Severity | Reachable? | Why unresolved | Mitigation / workaround |
|---|---|---|---|---|---|
| `starlette==0.47.2` | PYSEC-2026-1942 (CVE-2025-62727) — `FileResponse` Range quadratic-time DoS | High | **No** — no `FileResponse` in the codebase | Fixed in 0.49.1, but see the shared blocker below | Not reachable. Additionally `client_max_body_size 10m` and per-route proxy timeouts at the edge |
| `starlette==0.47.2` | PYSEC-2026-2281 (CVE-2026-48818) — `StaticFiles` UNC path SSRF on Windows | High | **No** — `StaticFiles` is never mounted; static assets are served by nginx, and containers are Linux | Fixed in 1.1.0 | Not reachable |
| `starlette==0.47.2` | PYSEC-2026-2280 (CVE-2026-48817) — `HTTPEndpoint` method dispatch via lowercasing | Moderate | **No** — all routes are function-based | Fixed in 1.1.0 | Not reachable |
| `starlette==0.47.2` | PYSEC-2026-161 (CVE-2026-48710), PYSEC-2026-248 (CVE-2026-54282) — `request.url` reconstructed from an unvalidated Host header / path | Moderate | **No** for redirects — every redirect is built by `frontend_redirect_url()` from `settings.FRONTEND_URL`, which re-asserts scheme and host after assembly | Fixed in 1.0.1 / 1.3.0 | Redirect origin is pinned to configuration and covered by `TestOpenRedirect` (18 tests). nginx sets `Host` explicitly on every proxied request |
| `starlette==0.47.2` | PYSEC-2026-249 (CVE-2026-54283) — `request.form()` ignores `max_fields` / `max_part_size` bounds | Moderate | **Yes** — `/auth/token` uses `OAuth2PasswordRequestForm`; it is the only form parser in the app | Fixed in 1.3.1 | `client_max_body_size 10m` caps the request at the edge, and `/auth/token` is rate-limited per account and per IP (`LOGIN_MAX_ATTEMPTS=5`, `LOGIN_IP_MAX_ATTEMPTS=20`), so the parser cannot be driven in a loop |
| `pyasn1==0.4.8` | PYSEC-2026-2263, PYSEC-2026-3455/3456/3457 (CVE-2026-30922, CVE-2026-59884/59885/59886) — quadratic OID/tag parsing and float conversion DoS | Moderate | **No** — reached only through RSA/ECDSA key parsing in `python-jose`; ICAP is HS256-only | **Hard-blocked upstream**: `python-jose 3.4.0` and `pyasn1-modules 0.2.8` both pin `pyasn1<0.5.0`; the fix is 0.6.4 | Not reachable. Would require replacing `python-jose` (e.g. with `pyjwt`) — tracked as a follow-up, not a drop-in change |
| `ecdsa==0.19.2` | PYSEC-2026-1325 (CVE-2024-23342) — Minerva timing attack on P-256 `SigningKey.sign_digest()` | Moderate | **No** — no ECDSA signing; transitive of `python-jose[cryptography]` | **No fixed release exists.** Upstream considers side-channel resistance out of scope for the pure-Python implementation | Not reachable. Removed entirely if `python-jose` is replaced |

**Shared blocker for `starlette`.** Clearing all six needs **1.3.1**. That was
attempted and reverted: `fastapi 0.141.1` + `starlette 1.3.1` installs and boots,
but **9 tests fail** because `route.path_format` changes — breaking route-template
keying in the latency registry, the `http_route` field in the access log, and the
API route inventory. 0.47.2 is the highest version `fastapi 0.116.1` permits, and
it is a pinned direct dependency now, so a FastAPI bump cannot silently drag in
an older one. Completing the migration is tracked as its own piece of work.

### 5.2 JavaScript (shipped browser bundle only)

`npm audit --omit=dev` — 12 advisories: 1 high, 11 moderate.

| Package | Advisories | Severity | Reachable? | Why unresolved | Mitigation / workaround |
|---|---|---|---|---|---|
| `undici` (via `firebase`) | 14 advisories incl. request smuggling, CRLF injection, Set-Cookie handling, WebSocket DoS | **High** | **No** — `undici` is a **Node.js** HTTP client. The browser bundle uses the platform `fetch`; undici is pulled in for Firebase's Node build path, which the SPA never loads | Needs a `firebase` major upgrade (10.x → 12.x), which touches FCM push registration and the service worker | Not reachable from the browser. Push delivery is covered by `test_notifications.py` (78 tests) if/when the upgrade is attempted |
| `@firebase/*`, `firebase` | Moderate advisories across auth/firestore/functions/storage | Moderate | Partially — only the auth/messaging surface is used; firestore, functions and storage are not imported anywhere | Same `firebase` major upgrade | ICAP uses Firebase **only** for Cloud Messaging. Unused product modules are still installed but never imported into the bundle |
| `react-router-dom`, `react-router` | Open redirect via backslash in `<Link>`/`useNavigate` (CVE-2025-68470 bypass); open redirect → XSS (CVSS 6.9); constructor injection in SSR hydration (CVSS 6.1) | Moderate | **No** — verified: every navigation target in the SPA is a hard-coded literal or comes from the constant map `homePathForRole()`. The one API-supplied target, `rec.action_path`, is a server-side literal in all 38 occurrences (`/profile`, `/alarms`, `/dashboard`, `/analytics`) and is never derived from user input | Fix requires `react-router` **>7.17.0**, a major upgrade from the pinned 6.x — breaking, and out of scope here | No user-controlled navigation sink exists. SSR hydration is not used (the app is a CSR SPA). Covered by `TestOpenRedirect`; the edge CSP additionally sets `form-action 'self'` and `base-uri 'self'` |

### 5.3 Build-chain advisories (not shipped)

`react-scripts` previously sat under `dependencies`, which put the whole build
toolchain into the production tree and made a production-scoped audit
meaningless — 45 advisories, 19 high. It is now a `devDependency`, reducing the
shipped tree to the 12 above. The remaining ~28 dev-tree advisories
(`webpack-dev-server`, `jest`, `svgo`, `postcss`, …) never reach a user's
browser and do not gate releases. Migrating off the unmaintained CRA toolchain
(e.g. to Vite) is the real fix and would also enable CSP nonces.

### 5.4 Non-dependency residual risk

| Risk | Rationale | Review by |
|---|---|---|
| CSP `style-src 'unsafe-inline'` | recharts and framer-motion inject `<style>` elements at runtime. Script injection remains fully blocked — verified at runtime that `script-src` is exactly `'self'` — which is where the exploitable risk lies | On charting-library upgrade |
| Self-signed certificate by default | Convenience for local runs. Production must mount a CA-issued certificate over `/etc/nginx/tls`; the entrypoint logs a warning on every self-signed start | Before public launch |

---

## 6. Recommendations not yet actioned

These are outside the scope of this review and are recorded for planning:

1. **Migrate off `react-scripts`** (to Vite) — retires the entire dev-chain
   advisory backlog and enables CSP nonces.
2. **Move rate-limit and revocation state to Redis** — both are per-process, so
   a multi-worker deployment enforces them per worker.
3. **Add CSP violation reporting** (`report-to`) to detect injection attempts in
   production.
4. **Ship security logs to an aggregator with alerting** — the events now exist
   and are structured, but nothing watches them yet.
5. **Consider HSTS preload** once the certificate and domain strategy is fixed.

---

## 7. How to reproduce

```bash
# Dependency + static analysis
pip install -r backend/requirements-security.txt
python scripts/security_scan.py

# Executable abuse cases
cd backend
python -m pytest tests/test_security_owasp.py -q

# Runtime edge verification (requires Docker; builds the real nginx image)
python -m pytest tests/test_tls_runtime.py -q

# Full security regression set
python -m pytest -q \
  tests/test_security_owasp.py \
  tests/test_tls_runtime.py \
  tests/test_auth_security.py \
  tests/test_rbac.py \
  tests/test_rbac_matrix.py
```

The runtime suite **skips** (never fails) when Docker is unavailable, so the
rest of the suite still runs on a machine without it. `ICAP_SKIP_EDGE_TESTS=1`
opts out explicitly.
