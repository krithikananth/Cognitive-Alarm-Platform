# Milestone 3 Close-out — Demo & Attempt-Log Audit

**Date:** 2026-07-20  
**Scope:** Adaptive difficulty, habit scoring, behavioral analytics, recommendations  
**README status:** intentionally unchanged (tracked separately)

---

## Deliverable checklist

| Deliverable | Status | Evidence |
| ----------- | ------ | -------- |
| Difficulty fetch/update APIs | Done | `GET/PUT /profiles/me`, `GET/PUT /users/profile/preferences` |
| Analytics ingestion | Done | `POST /analytics/events`, `/batch`, `/summary` |
| Habit-score API + 35/25/20/20 formula | Done | `GET /profiles/me/habit-score`, `habit_score.py` |
| Recommendations API + Redis cache | Done | `GET /recommendations*`, `recommendation_cache.py` |
| Adaptive difficulty (last-N streaks) | Done | `ChallengeService.adapt_difficulty`, profile streak counters |
| Behavioral analytics (pandas/numpy) | Done | `GET /analytics/behavioral*` |
| Difficulty preference UI | Done | Profile → Preferences |
| Habit-score + recommendation cards | Done | Dashboard |
| Attempt-log clean & queryable | Done | `GET /alarms/challenge/log-health` |
| Formula QA + bug report | Done | `test_habit_score.py`, `test_behavioral_analytics.py`, `QA_BUG_REPORT.md` |
| E2E wake → score/difficulty/recs | Done | `test_e2e_wake_workflow.py` (11/11) |

---

## Attempt-log audit (Week 2 prerequisite)

Before demos or Week 4 work, confirm logs are clean:

```bash
# Authenticated request — returns issue counts + samples
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/alarms/challenge/log-health"

# Optional repair of dirty rows for the current user
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/alarms/challenge/log-health?repair=true"
```

Automated coverage: `backend/tests/test_attempt_logs.py`.

**Pass criteria:** `issue_counts` empty (or only accepted INFO findings); challenge / snooze / wake query paths return rows for a user with recent wake activity.

---

## Internal demo script (~10 min)

1. **Preferences** — Profile → Preferences: set Default Difficulty (e.g. `medium`). Save.
2. **Alarm** — Create/enable an alarm with challenge required. Use **Test Ring** (browser tab must stay open).
3. **Solve** — Complete challenges; note difficulty badge.
4. **Dashboard** — Confirm Habit Score widget + Today's Coaching recommendation cards update.
5. **Analytics** — Open Analytics: behavioral overview, habit score breakdown, adaptive difficulty panel.
6. **Adaptive path** — Repeat successful wake cycles (or seed via tests) until difficulty steps ±1 around baseline.
7. **Mid-cycle snooze** — Snooze 1–2 times under the limit, then dismiss: streak resets and consistency takes a mild (−5) penalty; limit-exhaustion still applies −10.
8. **Log health** — Call `/alarms/challenge/log-health` and show a clean audit.

### Demo caveats

- Alarm ringing is browser-based (~120s ring window past `next_trigger_at`). Prefer **Test Ring**.
- `docker-compose` runs db + redis + backend; start frontend with `npm start`.
- Redis soft-fails if disabled — recommendations still compute, just uncached.

---

## Regression commands

```bash
cd backend
pytest tests/test_habit_score.py tests/test_behavioral_analytics.py \
  tests/test_recommendations.py tests/test_recommendation_cache.py \
  tests/test_attempt_logs.py tests/test_e2e_wake_workflow.py \
  tests/test_challenges.py tests/test_qa_api_inventory.py -q
```

Frontend smoke (Milestone 3 API client surfaces):

```bash
cd frontend
npm test -- --watchAll=false src/services/api.milestone3.test.js
```
