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

### BUG-002 — Password reset client stubs → Fixed (deferred feature)

Removed unused `forgotPassword` / `resetPassword` from `frontend/src/services/api.js`. Login still shows “Password reset is not available yet.” Backend routes intentionally absent until email flow ships.

### BUG-003 — Wake consistency score vs displayed std drift → Fixed

`analyze_wake_consistency` now rounds `std_wake_minutes` once, then computes `consistency_score` from that value so displayed std reconstructs the score exactly.

### BUG-004 — Habit component name “challenge_completion” → Documented

Documented in `habit_score.py`: component is verified-dismiss share of (dismissed + snoozes), not puzzle accuracy. Formula unchanged.

### Admin login redirect → Fixed

Password login and `/` home redirect now send `role === 'admin'` to `/admin` (aligned with OAuth callback).

### BUG-005 — Mid-cycle snoozes ignored for streak/consistency → Fixed

On verified dismiss, mid-cycle snoozes (`1 .. snooze_limit-1`) now reset `streak_days` and apply a milder consistency penalty (−5). Clean wakes still +5 / streak++; snooze-exhausted still −10 / streak reset. Mirrored in `habit_score.derive_habit_score_inputs_from_events` and `alarms.py` dismiss path.

---

## Open (accepted for demo)

None.

---

## Informational findings (not defects)

### INFO-001 — Dual profile APIs

`/api/v1/profiles/me*` and `/api/v1/users/profile*` both exist. SPA uses `/users/*` only. Habit-score SSOT agrees across both surfaces.

### INFO-002 — Focused behavioral endpoints unused by Analytics page

`Analytics.jsx` calls `GET /analytics/behavioral`. Focused routes are implemented and tested but unused by the UI.

---

## Demo caveats (not bugs)

- Alarm ringing is browser-based: tab must be open; ring window is ~120s past `next_trigger_at`. Use **Test Ring** on Alarms for demos.
- Password reset / email recovery not shipped.
- `docker-compose` runs db + redis + backend only; run frontend with `npm start`.
