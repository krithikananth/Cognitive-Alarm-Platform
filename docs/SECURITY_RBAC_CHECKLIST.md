# PART 4 — Role-Based Security Testing Checklist

Manual verification checklist for the three roles in the Intelligent Cognitive
Alarm Platform. Each item is written so a tester can reproduce it in a browser
or with `curl`, independently of the automated suites.

**Roles under test:** `user`, `wellness_coach`, `admin`
(values mirror `UserRole` in [backend/app/models/user.py](../backend/app/models/user.py))

**Automated counterparts**

| Suite | File | Scope |
| --- | --- | --- |
| Backend RBAC (original) | [backend/tests/test_rbac.py](../backend/tests/test_rbac.py) | Admin user-management + dashboard |
| Backend role matrix | [backend/tests/test_rbac_matrix.py](../backend/tests/test_rbac_matrix.py) | Full deny-matrix, tokens, IDOR |
| Frontend route roles | [frontend/src/App.roleRouting.test.js](../frontend/src/App.roleRouting.test.js) | Dashboard routing per role |
| Frontend route security | [frontend/src/App.roleSecurity.test.js](../frontend/src/App.roleSecurity.test.js) | Direct URL, refresh, logout+Back, expiry |

**How to run**

```powershell
cd backend;  python -m pytest tests/test_rbac.py tests/test_rbac_matrix.py -v
cd frontend; $env:CI="true"; npx react-scripts test --watchAll=false --testPathPattern "role"
```

---

## 1. Test accounts

| # | Account | Role | Purpose |
| --- | --- | --- | --- |
| 1.1 | `user_a@test.local` | `user` | Baseline low-privilege actor |
| 1.2 | `user_b@test.local` | `user` | Victim for horizontal escalation (IDOR) |
| 1.3 | `coach_a@test.local` | `wellness_coach` | Assigned `user_a` only |
| 1.4 | `coach_b@test.local` | `wellness_coach` | Assigned `user_b` only |
| 1.5 | `admin@test.local` | `admin` | Full administrative actor |
| 1.6 | `inactive@test.local` | `user` | `is_active = false` |

> `coach_a` must have an **active** row in `coach_assignments` for `user_a`, and
> **no** row for `user_b`. This is what makes step 4 meaningful.

---

## 2. Role matrix — expected outcome per surface

Legend: **ALLOW** = 200 / page renders · **DENY** = 403 / Access Denied ·
**HIDE** = 404 (existence not disclosed) · **AUTH** = 401 redirect to login

| Surface | Anonymous | `user` | `wellness_coach` | `admin` |
| --- | --- | --- | --- | --- |
| `GET /api/v1/admin/*` (17 routes) | AUTH | DENY | DENY | ALLOW |
| `GET /api/v1/users/` (admin list) | AUTH | DENY | DENY | ALLOW |
| `PUT /api/v1/users/{id}` (role change) | AUTH | DENY | DENY | ALLOW |
| `POST /api/v1/users/{id}/deactivate` | AUTH | DENY | DENY | ALLOW |
| `DELETE /api/v1/users/{id}` | AUTH | DENY | DENY | ALLOW |
| `GET /api/v1/coach/*` (10 routes) | AUTH | DENY | ALLOW | ALLOW |
| `GET /api/v1/coach/clients/{assigned}` | AUTH | DENY | ALLOW | scoped |
| `GET /api/v1/coach/clients/{unassigned}` | AUTH | DENY | **HIDE** | scoped |
| `GET /api/v1/users/profile` (own) | AUTH | ALLOW | ALLOW | ALLOW |
| `GET /api/v1/alarms` (own) | AUTH | ALLOW | ALLOW | ALLOW |
| Page `/admin` | → `/login` | Access Denied | Access Denied | ALLOW |
| Page `/wellness` | → `/login` | Access Denied | ALLOW | Access Denied |
| Page `/dashboard` | → `/login` | ALLOW | → `/wellness` | ALLOW |

---

## 3. USER role

### 3.1 Cannot access privileged pages

| # | Step | Expected |
| --- | --- | --- |
| 3.1.1 | Log in as `user_a`, type `/admin` in the address bar | Redirected to `/access-denied`; Admin page never mounts |
| 3.1.2 | Type `/wellness` in the address bar | Redirected to `/access-denied` |
| 3.1.3 | Confirm the sidebar shows no "Admin Panel" or "Coach" link | Links absent, not merely hidden by CSS |
| 3.1.4 | Open DevTools → Network while on `/access-denied` | **No** request to `/api/v1/admin/*` or `/api/v1/coach/*` was fired |

### 3.2 Cannot access admin APIs

| # | Step | Expected |
| --- | --- | --- |
| 3.2.1 | `GET /api/v1/admin/dashboard` with `user_a` token | `403 Admin privileges required` |
| 3.2.2 | `GET /api/v1/admin/statistics` | 403 |
| 3.2.3 | `GET /api/v1/admin/users` | 403 |
| 3.2.4 | `GET /api/v1/admin/users/{admin_id}` | 403 |
| 3.2.5 | `GET /api/v1/admin/alarms` | 403 |
| 3.2.6 | `GET /api/v1/admin/analytics` | 403 |
| 3.2.7 | `GET /api/v1/admin/reports` | 403 |
| 3.2.8 | `GET /api/v1/admin/recommendations` | 403 |
| 3.2.9 | `GET /api/v1/admin/system-reports` | 403 |
| 3.2.10 | `GET /api/v1/admin/system-reports/user/export?format=pdf` | 403 — no report bytes returned |
| 3.2.11 | `GET` and `PUT /api/v1/admin/notification-settings` | 403 |
| 3.2.12 | `GET`, `POST`, `DELETE /api/v1/admin/coach-assignments` | 403 |
| 3.2.13 | `POST /api/v1/admin/announcements/broadcast` | 403 — no notification is delivered |
| 3.2.14 | `GET /api/v1/users/` | 403 — no roster leak |
| 3.2.15 | `DELETE /api/v1/users/{other_id}` | 403 — target account still exists afterwards |

### 3.3 Cannot access coach-only APIs

| # | Step | Expected |
| --- | --- | --- |
| 3.3.1 | `GET /api/v1/coach/overview` with `user_a` token | `403 Wellness coach privileges required` |
| 3.3.2 | `GET /api/v1/coach/clients` | 403 |
| 3.3.3 | `GET /api/v1/coach/clients/{id}` and all 7 analytics sub-routes | 403 on every one |

### 3.4 Cannot escalate or reach another user's data

| # | Step | Expected |
| --- | --- | --- |
| 3.4.1 | `PUT /api/v1/users/{own_id}` with `{"role": "admin"}` | 403 — role unchanged in DB |
| 3.4.2 | `PUT /api/v1/users/{own_id}` with `{"is_active": true, "role": "wellness_coach"}` | 403 |
| 3.4.3 | `GET /api/v1/users/{user_b_id}` as `user_a` | 403 |
| 3.4.4 | `GET /api/v1/alarms/{user_b_alarm_id}` as `user_a` | 403 or 404 — never `user_b`'s payload |
| 3.4.5 | Edit `localStorage.user` to `{"role":"admin"}`, reload | `/admin` may briefly route, but every API call returns 403 and no admin data renders |

---

## 4. WELLNESS_COACH role

### 4.1 Cannot access admin-only pages

| # | Step | Expected |
| --- | --- | --- |
| 4.1.1 | Log in as `coach_a`, type `/admin` | Redirected to `/access-denied` |
| 4.1.2 | Confirm landing page after login is `/wellness` | Coach dashboard, not `/dashboard` or `/admin` |
| 4.1.3 | Type `/dashboard` | Redirected back to `/wellness` |

### 4.2 Cannot access admin-only APIs

| # | Step | Expected |
| --- | --- | --- |
| 4.2.1 | Repeat every request in **3.2.1 – 3.2.15** with the `coach_a` token | 403 on all 17 admin routes and all 6 user-management routes |
| 4.2.2 | `POST /api/v1/admin/coach-assignments` assigning `user_b` to self | 403 — coach cannot widen their own roster |

### 4.3 Can access only permitted user information

| # | Step | Expected |
| --- | --- | --- |
| 4.3.1 | `GET /api/v1/coach/overview` as `coach_a` | 200; counts reflect assigned clients only |
| 4.3.2 | `GET /api/v1/coach/clients` | 200; list contains `user_a`, **not** `user_b` |
| 4.3.3 | `GET /api/v1/coach/clients/{user_a_id}` | 200 |
| 4.3.4 | `GET /api/v1/coach/clients/{user_b_id}` (assigned to `coach_b`) | **404**, not 403 — existence is not disclosed |
| 4.3.5 | `GET /api/v1/coach/clients/999999` (nonexistent) | 404 — identical response to 4.3.4 |
| 4.3.6 | Repeat 4.3.4 against all 7 analytics sub-routes | 404 on every one |
| 4.3.7 | Admin sets the `coach_a → user_a` assignment `is_active = false`; retry 4.3.3 | 404 on the **next request**, no re-login needed |
| 4.3.8 | Compare a metric in 4.3.3 with the same metric on `user_a`'s own dashboard | Identical values — no privileged over-disclosure |
| 4.3.9 | Confirm the client payload excludes password hashes and reset tokens | Absent from JSON |

---

## 5. ADMIN role — intended access is present

| # | Step | Expected |
| --- | --- | --- |
| 5.1 | Log in as `admin` | Lands on `/admin` |
| 5.2 | `GET` each of the 13 read-only admin routes | 200 with populated payloads |
| 5.3 | `GET /api/v1/users/` | 200, list of all users |
| 5.4 | `PUT /api/v1/users/{user_a_id}` with `{"role":"wellness_coach"}` | 200, role updated |
| 5.5 | `PUT /api/v1/users/{user_a_id}` with `{"role":"superuser"}` | 422 — invalid enum rejected |
| 5.6 | `POST /api/v1/users/{user_a_id}/deactivate` then `/activate` | 200 both times, flag toggles |
| 5.7 | `POST /api/v1/users/{own_admin_id}/deactivate` | **400** — self-lockout prevented |
| 5.8 | `POST /api/v1/admin/coach-assignments` then `DELETE` | 200; coach visibility changes accordingly |
| 5.9 | `GET /api/v1/coach/overview` as admin | 200 — admins may inspect the coach surface |
| 5.10 | Type `/wellness` as admin | Access Denied — coach *page* is role-exclusive by design |

---

## 6. Direct URL navigation

| # | Step | Expected |
| --- | --- | --- |
| 6.1 | As `user`, paste `/admin` directly | `/access-denied`; guard runs before the page mounts |
| 6.2 | As `user`, paste `/wellness` | `/access-denied` |
| 6.3 | As `coach`, paste `/admin` | `/access-denied` |
| 6.4 | As anonymous, paste `/admin`, `/dashboard`, `/wellness`, `/alarms`, `/analytics`, `/reports`, `/profile` | Every one redirects to `/login` |
| 6.5 | As `user`, paste `/admin?role=admin&is_admin=true` | Query string ignored; still `/access-denied` |
| 6.6 | As `user`, paste `/adm%69n` (URL-encoded) | Resolves to `/admin` → `/access-denied`, no bypass |
| 6.7 | Paste an unknown path such as `/nope` while authenticated | In-app 404, no privileged shell exposed |

---

## 7. Refreshing protected pages

| # | Step | Expected |
| --- | --- | --- |
| 7.1 | As `admin` on `/admin`, press F5 | Page re-renders as admin; no flash of `/login` |
| 7.2 | As `user` on `/access-denied` (after trying `/admin`), press F5 | Stays denied; does not "fall through" to the admin page |
| 7.3 | As `coach` on `/wellness`, press F5 | Roster reloads, still scoped to assigned clients |
| 7.4 | Clear `localStorage` in DevTools, then press F5 on `/admin` | Redirected to `/login` |
| 7.5 | Refresh rapidly 5× on `/admin` as `user` | No race window in which admin content renders |

---

## 8. Logout and browser Back

| # | Step | Expected |
| --- | --- | --- |
| 8.1 | Log in as `admin`, open `/admin`, log out, press Back | `/login` — admin content is not restored |
| 8.2 | Log in as `user`, open `/dashboard`, log out, press Back | `/login` |
| 8.3 | After 8.1, confirm no JWT is present in `localStorage` and the `icap_access_token` / `icap_refresh_token` cookies are gone | Only the non-sensitive `user` object is ever stored; both auth cookies are cleared |
| 8.7 | After 8.1, replay the pre-logout access token with `Authorization: Bearer` | 401 `Token has been revoked` — logout records the token id in `revoked_tokens` |
| 8.4 | After 8.1, press Back repeatedly through the whole history | Never re-renders a protected page |
| 8.5 | After 8.1, open DevTools → Network and press Back | No authenticated API request is issued |
| 8.6 | Log out as `admin`, log in as `user` in the same tab, press Back | Admin page not restored from bfcache |

---

## 9. Expired / invalid session

| # | Step | Expected |
| --- | --- | --- |
| 9.1 | Call any protected API with an expired access token | 401; client transparently refreshes, or clears session and redirects to `/login` |
| 9.2 | Call `/api/v1/admin/dashboard` with a token signed by a **different secret** | 401 — signature rejected |
| 9.3 | Send `Authorization: Bearer not.a.jwt` | 401 |
| 9.4 | Send the **refresh** token in the `Authorization` header | 401 `Invalid token type` — refresh tokens are not accepted as access tokens |
| 9.5 | Send a valid token whose `sub` is a deleted user id | 401 `User not found` |
| 9.6 | Deactivate `admin` while their token is still valid; reuse the token | 403 `Inactive user` on the next request |
| 9.7 | Demote `admin` → `user` while their token is valid; reuse the token | 403 on the next request — no re-login required |
| 9.8 | Promote `user` → `admin` while their token is valid; reuse the token | 200 — privilege is read live from the DB |
| 9.9 | Strip the `Bearer ` prefix and send the raw token | 401 |
| 9.10 | Send no `Authorization` header at all to each of the 27 admin/coach routes | 401 on every one |
| 9.11 | Expire the refresh token too, then act in the UI | Session cleared, redirected to `/login` |

---

## 10. Unauthorized API requests

| # | Step | Expected |
| --- | --- | --- |
| 10.1 | Replay a captured admin request using a `user` token | 403 |
| 10.2 | Replay a captured coach request using a `user` token | 403 |
| 10.3 | Change the HTTP verb on an admin route (e.g. `GET`→`PUT`) as `user` | 403 or 405 — never 200 |
| 10.4 | Add spoofed headers `X-Role: admin`, `X-User-Id: 1` to a `user` request | Ignored; still 403 |
| 10.5 | Inspect any 403/401 body | Generic message; no stack trace, SQL, or internal path |
| 10.6 | Confirm 403 responses set no `Set-Cookie` and leak no admin data in headers | Clean response |

---

## 11. Role manipulation through the frontend

| # | Step | Expected |
| --- | --- | --- |
| 11.1 | Set `localStorage.user = '{"id":1,"role":"admin"}'` as `user_a`, reload, open `/admin` | Page shell may route, but every API call returns 403 — no admin data is ever displayed |
| 11.2 | Forge a JWT with `"role":"admin"` signed with the **correct** secret, for a `user` subject | **403** — the role claim is decorative; authorization reads `users.role` from the DB |
| 11.3 | Forge a JWT with `"role":"wellness_coach"` for a `user` subject | 403 on `/api/v1/coach/*` |
| 11.4 | Set the client-side role to `"ADMIN"` (wrong case) | Access Denied — comparison is exact |
| 11.5 | Set the client-side role to `" admin "` (padded) | Access Denied |
| 11.6 | Set the client-side role to `"superadmin"` or `null` | Access Denied — unknown roles are denied by default |
| 11.7 | Use React DevTools to force `RoleRoute` to render its children | Component may mount, but its API calls all return 403 |
| 11.8 | Change the `client_id` in a coach URL to an unassigned client | 404 — server-side assignment check, not a UI filter |

---

## 12. Sign-off

| Area | Result | Tester | Date |
| --- | --- | --- | --- |
| 3. USER role | ☐ Pass ☐ Fail | | |
| 4. COACH role | ☐ Pass ☐ Fail | | |
| 5. ADMIN role | ☐ Pass ☐ Fail | | |
| 6. Direct URL navigation | ☐ Pass ☐ Fail | | |
| 7. Page refresh | ☐ Pass ☐ Fail | | |
| 8. Logout + Back | ☐ Pass ☐ Fail | | |
| 9. Expired / invalid session | ☐ Pass ☐ Fail | | |
| 10. Unauthorized API requests | ☐ Pass ☐ Fail | | |
| 11. Role manipulation | ☐ Pass ☐ Fail | | |

---

## 13. Deployment note

`SECRET_KEY` has no generated default. Outside production a constant, clearly
insecure development key is used (so restarts do not silently invalidate
sessions); in production `ENVIRONMENT=production` makes the app refuse to start
unless `SECRET_KEY` is present, at least 32 characters, and not a known
placeholder — see [backend/app/core/config.py](../backend/app/core/config.py).
Production also forces `Secure` auth cookies.

Sessions are carried in `HttpOnly` + `SameSite=lax` cookies
([backend/app/core/cookies.py](../backend/app/core/cookies.py)); the SPA never
reads or stores a JWT. Logout revokes the presented token ids
([backend/app/services/token_service.py](../backend/app/services/token_service.py)),
and login / password-reset endpoints are rate limited
([backend/app/core/rate_limit.py](../backend/app/core/rate_limit.py)).
The limiter keeps its counters in process memory, so a multi-worker rollout
enforces the caps per worker — put a shared limiter at the edge (or run a single
auth worker) if you need a global cap.
