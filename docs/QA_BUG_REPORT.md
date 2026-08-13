# QA Bug Report — Habit Score, Analytics, APIs

**Date:** 2026-07-16  
**Scope:** Habit Score SSOT, behavioral analytics, analytics ingestion, API inventory, frontend client contract  
**Build under test:** local workspace (`backend` + `frontend`)  
**Status:** Integration fixes applied; see Closed bugs below.

---

## Summary

| Severity | Open | Notes |
|----------|------|-------|
| Critical | 0 | — |
| High | 0 | — |
| Medium | 0 | BUG-001 / BUG-002 resolved |
| Low | 0 | BUG-005 fixed (mid-cycle snooze streak/consistency) |
| Info | 2 | Dual profile APIs; SPA unused focused analytics endpoints |

No calculation defects in Habit Score SSOT or behavioral analytics formulas after rounding fix.

---

## Closed bugs

### BUG-001 — `GET /users/profile/preferences` missing → Fixed

Added `GET /api/v1/users/profile/preferences` returning preferred challenge types, difficulty preference, productivity goals, and habit preferences. Covered by `test_preferences_get_returns_expected_shape`.

### BUG-002 — Password reset client stubs → Fixed (feature shipped)

Password reset is now implemented end to end. `POST /api/v1/auth/forgot-password` and `POST /api/v1/auth/reset-password` are live in `auth.py`, both returning generic messages to prevent email enumeration. `frontend/src/services/api.js` exposes `forgotPassword` / `resetPassword` against those routes, and Login links to the `/forgot-password` and `/reset-password` pages. Covered by `test_forgot_and_reset_password_success` plus token and weak-password rejection tests.

### BUG-003 — Wake consistency score vs displayed std drift → Fixed

`analyze_wake_consistency` now rounds `std_wake_minutes` once, then computes `consistency_score` from that value so displayed std reconstructs the score exactly.

### BUG-004 — Habit component name “challenge_completion” → Documented

Documented in `habit_score.py`: component is verified-dismiss share of (dismissed + snoozes), not puzzle accuracy. Formula unchanged.

### Admin login redirect → Fixed

Password login and `/` home redirect now send `role === 'admin'` to `/admin` (aligned with OAuth callback).

### BUG-005 — Mid-cycle snoozes ignored for consistency → Fixed

On verified dismiss, mid-cycle snoozes (`1 .. snooze_limit-1`) apply a milder
consistency penalty (−5). Clean wakes still +5; snooze-exhausted still −10.
**Day Streak** is calendar-day based (see Day Streak feature): verified challenge
completion counts as a successful day regardless of snoozes; streak increments
at most once per local day and resets after a missed day.

---

## Open (accepted for demo)

None.

---

## Informational findings (not defects)

### INFO-001 — Dual profile APIs

`/api/v1/profiles/me*` and `/api/v1/users/profile*` both exist and are **not**
duplicates: `/profiles/me` exposes `adapted_difficulty`,
`wake_up_consistency_score` and the lifetime counters that the `/users/profile`
bundle does not carry, and `PATCH /profiles/me/goals` is strictly typed where
`PUT /users/profile/goals` is lenient. The differences are pinned by
`backend/tests/test_route_aliases.py`. Habit-score SSOT agrees across both
surfaces.

### INFO-002 — Focused behavioral endpoints unused by the SPA — resolved

The focused routes now have production call sites: the dashboard reads
`/analytics/behavioral/snooze`, `/sleep-adherence` and the weekly/monthly trend
routes, and `frontend/src/services/api.callSites.test.js` fails the build if any
declared client method loses its caller or a backend route loses its client
without a justified exemption.

---

## Demo caveats (not bugs)

_Re-verified 2026-08-13 against the current build._

- Alarm ringing works two ways: in-page while a tab is open (ring window ~120s
  past `next_trigger_at`), and via a server-dispatched push notification when
  FCM is configured and the browser has granted permission. **Test Ring** on the
  Alarms page remains the quickest way to demo the wake cycle.
- ~~Password reset / email recovery not shipped.~~ Shipped — see BUG-002 above.
- ~~`docker-compose` runs db + redis + backend only.~~ The stack now also builds
  the frontend and an Nginx edge (TLS on `:8443`, HTTP `:8080` redirecting to
  HTTPS); only Nginx is published to the host.
