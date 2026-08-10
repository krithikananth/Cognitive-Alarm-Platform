"""
Full end-to-end audit of all product features against a live API.

Usage:
  python -m pytest tests/audit_e2e_full.py -v -s
  # or against running server:
  python tests/audit_e2e_full.py
"""

from __future__ import annotations

import json
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx

BASE = "http://localhost:8000/api/v1"
PASS = []
FAIL = []
SKIP = []


class AuditClient:
    def __init__(self, base: str = BASE):
        self.base = base.rstrip("/")
        self.client = httpx.Client(base_url=self.base, timeout=30.0)
        self.token: Optional[str] = None
        self.refresh: Optional[str] = None
        self.user: dict = {}
        self.alarm_id: Optional[int] = None
        self.admin_token: Optional[str] = None

    def headers(self, admin: bool = False) -> dict:
        t = self.admin_token if admin else self.token
        if not t:
            return {}
        return {"Authorization": f"Bearer {t}"}

    def req(
        self,
        method: str,
        path: str,
        *,
        admin: bool = False,
        expect: int | tuple = 200,
        **kwargs,
    ) -> httpx.Response:
        r = self.client.request(
            method, path, headers=self.headers(admin=admin), **kwargs
        )
        expected = expect if isinstance(expect, tuple) else (expect,)
        if r.status_code not in expected:
            raise AssertionError(
                f"{method} {path} -> {r.status_code} (expected {expected}): "
                f"{r.text[:500]}"
            )
        return r


def record(feature: str, ok: bool, detail: str = "", err: Exception | None = None):
    entry = {"feature": feature, "detail": detail}
    if ok:
        PASS.append(entry)
        print(f"  PASS  {feature}" + (f" — {detail}" if detail else ""))
    else:
        msg = detail
        if err:
            msg = f"{detail}: {err}" if detail else str(err)
        FAIL.append({"feature": feature, "detail": msg, "trace": traceback.format_exc()})
        print(f"  FAIL  {feature} — {msg}")


def run_step(feature: str, fn: Callable[[], Any]):
    try:
        detail = fn()
        record(feature, True, detail if isinstance(detail, str) else "")
        return detail
    except Exception as e:
        record(feature, False, err=e)
        return None


def main() -> int:
    c = AuditClient()
    suffix = uuid.uuid4().hex[:8]
    email = f"audit_{suffix}@example.com"
    username = f"audit_{suffix}"
    password = "AuditPass123!"
    admin_email = f"admin_audit_{suffix}@example.com"
    admin_user = f"admin_{suffix}"
    admin_pass = "AdminPass123!"

    print("\n=== ICAP Full E2E Audit ===\n")
    print(f"User: {email}\n")

    # Health
    def health():
        r = httpx.get("http://localhost:8000/health", timeout=10)
        assert r.status_code == 200, r.text
        return r.json().get("status", "ok")

    run_step("Health", health)

    # ── Registration ──
    def registration():
        r = c.req(
            "POST",
            "/auth/register",
            json={
                "email": email,
                "username": username,
                "password": password,
                "full_name": "E2E Auditor",
            },
            expect=(200, 201),
        )
        data = r.json()
        assert "id" in data or "email" in data or "access_token" in data, data
        return f"registered {email}"

    run_step("Registration", registration)

    # ── Login ──
    def login():
        r = c.req(
            "POST",
            "/auth/login",
            json={"email": email, "password": password},
            expect=200,
        )
        data = r.json()
        assert "access_token" in data, data
        c.token = data["access_token"]
        c.refresh = data.get("refresh_token")
        me = c.req("GET", "/auth/me", expect=200).json()
        c.user = me
        return f"user_id={me.get('id')} role={me.get('role')}"

    run_step("Login", login)

    # ── Profile ──
    def profile():
        r = c.req("GET", "/users/profile", expect=200)
        prof = r.json()
        upd = c.req(
            "PUT",
            "/users/profile",
            json={"full_name": "E2E Auditor Updated"},
            expect=200,
        ).json()
        assert "E2E Auditor Updated" in str(upd.get("full_name", upd))
        # sleep schedule
        c.req(
            "PUT",
            "/users/profile/sleep-schedule",
            json={
                "preferred_wake_time": "07:00:00",
                "sleep_duration_hours": 8.0,
                "timezone": "Asia/Kolkata",
            },
            expect=200,
        )
        stats = c.req("GET", "/users/profile/stats", expect=200).json()
        return f"keys={list(prof.keys())[:6]} stats_ok={bool(stats)}"

    run_step("Profile", profile)

    # ── Preferences ──
    def preferences():
        prefs = c.req("GET", "/users/profile/preferences", expect=200).json()
        updated = c.req(
            "PUT",
            "/users/profile/preferences",
            json={
                "difficulty_preference": "medium",
                "preferred_challenge_types": ["math", "logic"],
            },
            expect=200,
        ).json()
        # also profiles/me if present
        try:
            c.req("GET", "/profiles/me", expect=200)
            c.req(
                "PUT",
                "/profiles/me",
                json={"difficulty_preference": "hard"},
                expect=200,
            )
        except AssertionError:
            pass
        return f"pref={updated.get('difficulty_preference', prefs)}"

    run_step("Preferences", preferences)

    # ── Alarm ──
    def alarm():
        created = c.req(
            "POST",
            "/alarms/",
            json={
                "title": "E2E Morning Alarm",
                "alarm_time": "07:30:00",
                "alarm_type": "daily",
                "challenge_type": "math",
                "challenge_count": 1,
                "challenge_difficulty": "medium",
                "snooze_enabled": True,
                "snooze_limit": 3,
                "snooze_interval_minutes": 5,
                "is_active": True,
            },
            expect=(200, 201),
        ).json()
        c.alarm_id = created["id"]
        listed = c.req("GET", "/alarms/", expect=200).json()
        alarms = listed["alarms"] if isinstance(listed, dict) else listed
        assert any(a["id"] == c.alarm_id for a in alarms), listed
        c.req(
            "PUT",
            f"/alarms/{c.alarm_id}",
            json={"title": "E2E Morning Alarm Updated"},
            expect=200,
        )
        c.req(
            "PATCH",
            f"/alarms/{c.alarm_id}/toggle",
            json={"is_active": True},
            expect=200,
        )
        upcoming = c.req("GET", "/alarms/upcoming", expect=200).json()
        return f"alarm_id={c.alarm_id} upcoming={len(upcoming) if isinstance(upcoming, list) else 'ok'}"

    run_step("Alarm", alarm)

    # ── Challenge ──
    def challenge():
        assert c.alarm_id, "no alarm"
        ch = c.req("GET", f"/alarms/{c.alarm_id}/challenge", expect=200).json()
        assert "prompt" in ch and "answer" not in ch

        # Read server-stored answer from local SQLite (API never returns it)
        import sqlite3
        from pathlib import Path

        db_path = Path(__file__).resolve().parents[1] / "icap.db"
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT answer FROM challenge_sessions "
                "WHERE alarm_id = ? ORDER BY id DESC LIMIT 1",
                (c.alarm_id,),
            ).fetchone()
        finally:
            conn.close()
        assert row and row[0], "No challenge session answer in DB"
        answer = row[0]

        ver = c.req(
            "POST",
            f"/alarms/{c.alarm_id}/verify",
            json={
                "user_answer": str(answer),
                "time_taken_seconds": 5,
                "challenge_prompt": ch.get("prompt", ""),
                "challenge_difficulty": ch.get("difficulty", "medium"),
            },
            expect=200,
        ).json()
        assert ver.get("is_dismissed") is True or ver.get("status") in (
            "dismissed",
            "correct",
            "in_progress",
        ), ver

        stats = c.req("GET", "/alarms/challenge/stats", expect=200).json()
        c.req("GET", "/alarms/challenge/history", expect=200)
        return (
            f"type={ch.get('type')} difficulty={ch.get('difficulty')} "
            f"dismissed={ver.get('is_dismissed')} stats_ok={bool(stats)}"
        )

    run_step("Challenge", challenge)

    # ── Habit Score ──
    def habit_score():
        # profiles habit-score
        try:
            r = c.req("GET", "/profiles/me/habit-score", expect=200).json()
        except AssertionError:
            r = c.req("GET", "/users/profile/stats", expect=200).json()
        score = r.get("habit_score") or r.get("score") or r.get("total_score")
        return f"payload_keys={list(r.keys())[:8]} score={score}"

    run_step("Habit Score", habit_score)

    # ── Day Streak ──
    def day_streak():
        # Try several known surfaces
        for path in (
            "/profiles/me/habit-score",
            "/dashboard/summary",
            "/users/profile/stats",
            "/alarms/wakefulness",
        ):
            try:
                r = c.req("GET", path, expect=200).json()
                blob = json.dumps(r).lower()
                if "streak" in blob:
                    return f"found in {path}"
            except AssertionError:
                continue
        # dashboard summary with period
        r = c.req(
            "GET", "/dashboard/summary", params={"period": "weekly"}, expect=200
        ).json()
        blob = json.dumps(r).lower()
        if "streak" in blob:
            return "found in dashboard/summary"
        raise AssertionError(f"No streak field found in common endpoints. summary keys={list(r.keys())}")

    run_step("Day Streak", day_streak)

    # ── Analytics ──
    def analytics():
        c.req(
            "POST",
            "/analytics/events",
            json={
                "event_type": "alarm.triggered",
                "entity_type": "alarm",
                "entity_id": c.alarm_id,
                "event_data": {"source": "e2e_audit"},
            },
            expect=(200, 201, 202),
        )
        summary = c.req("GET", "/analytics/summary", expect=200).json()
        behavioral = c.req(
            "GET", "/analytics/behavioral", params={"days": 30}, expect=200
        ).json()
        snooze = c.req(
            "GET", "/analytics/behavioral/snooze", params={"days": 30}, expect=200
        ).json()
        wake = c.req(
            "GET",
            "/analytics/behavioral/wake-consistency",
            params={"days": 30},
            expect=200,
        ).json()
        return f"summary_ok behavioral_keys={list(behavioral.keys())[:5]}"

    run_step("Analytics", analytics)

    # ── Dashboard ──
    def dashboard():
        summary = c.req(
            "GET", "/dashboard/summary", params={"period": "weekly"}, expect=200
        ).json()
        history = c.req("GET", "/dashboard/alarm-history", expect=200).json()
        wake = c.req(
            "GET", "/dashboard/wake-stats", params={"days": 30}, expect=200
        ).json()
        chall = c.req(
            "GET",
            "/dashboard/challenge-performance",
            params={"days": 30},
            expect=200,
        ).json()
        prod = c.req(
            "GET", "/dashboard/productivity", params={"days": 30}, expect=200
        ).json()
        return f"summary_keys={list(summary.keys())[:8]}"

    run_step("Dashboard", dashboard)

    # ── Recommendations ──
    def recommendations():
        all_recs = c.req("GET", "/recommendations", expect=200).json()
        daily = c.req("GET", "/recommendations/daily", expect=200).json()
        sleep = c.req("GET", "/recommendations/sleep", expect=200).json()
        wake = c.req("GET", "/recommendations/wake", expect=200).json()
        prod = c.req("GET", "/recommendations/productivity", expect=200).json()
        count = len(all_recs) if isinstance(all_recs, list) else len(all_recs.get("recommendations", []))
        return f"recs={count} daily_ok"

    run_step("Recommendations", recommendations)

    # ── Notifications ──
    def notifications():
        prefs = c.req("GET", "/notifications/preferences", expect=200).json()
        c.req(
            "PUT",
            "/notifications/preferences",
            json={
                "notifications_enabled": True,
                "bedtime_reminder_enabled": True,
                "wake_reminder_enabled": True,
                "motivational_enabled": True,
                "habit_alerts_enabled": True,
            },
            expect=200,
        )
        feed = c.req("GET", "/notifications/", expect=200).json()
        unread = c.req("GET", "/notifications/unread-count", expect=200).json()
        pending = c.req("GET", "/notifications/pending", expect=200).json()
        test = c.req("POST", "/notifications/test", expect=(200, 201)).json()
        # mark read if any
        items = feed if isinstance(feed, list) else feed.get("notifications", [])
        if items:
            ids = [i["id"] for i in items[:3] if "id" in i]
            if ids:
                c.req(
                    "POST",
                    "/notifications/mark-read",
                    json={"notification_ids": ids},
                    expect=200,
                )
        c.req(
            "POST",
            "/notifications/device-token",
            json={
                "fcm_token": f"e2e-token-{suffix}xx",
                "device_type": "web",
            },
            expect=(200, 201),
        )
        return f"unread={unread} test_ok prefs_ok"

    run_step("Notifications", notifications)

    # ── Reports ──
    def reports():
        listing = c.req("GET", "/reports", expect=200).json()
        # Shape: { "reports": [ { "type": "habit", ... }, ... ] }
        types = []
        if isinstance(listing, dict) and "reports" in listing:
            types = [
                t.get("type") or t.get("id") or t.get("report_type")
                for t in listing["reports"]
            ]
        elif isinstance(listing, list):
            types = [
                t.get("type") or t.get("id") or t.get("report_type") or t
                for t in listing
            ]
        types = [t for t in types if t]
        if not types:
            types = ["habit", "wake", "challenge", "productivity", "sleep"]
        report_type = None
        last_err = None
        body = None
        for t in types:
            tname = t if isinstance(t, str) else str(t)
            try:
                body = c.req("GET", f"/reports/{tname}", expect=200).json()
                report_type = tname
                break
            except AssertionError as e:
                last_err = e
                continue
        if not report_type:
            raise AssertionError(f"No report type worked from {types}: {last_err}")
        # export pdf
        r = c.client.get(
            f"/reports/{report_type}/export",
            params={"format": "pdf"},
            headers=c.headers(),
        )
        if r.status_code != 200:
            raise AssertionError(f"PDF export {r.status_code}: {r.text[:300]}")
        assert len(r.content) > 100, "PDF too small"
        # excel
        r2 = c.client.get(
            f"/reports/{report_type}/export",
            params={"format": "xlsx"},
            headers=c.headers(),
        )
        if r2.status_code != 200:
            # some APIs use excel
            r2 = c.client.get(
                f"/reports/{report_type}/export",
                params={"format": "excel"},
                headers=c.headers(),
            )
        assert r2.status_code == 200, f"Excel export {r2.status_code}: {r2.text[:300]}"
        return f"type={report_type} pdf={len(r.content)}B xlsx={len(r2.content)}B"

    run_step("Reports", reports)

    # ── Admin ──
    def admin():
        denied = c.req("GET", "/admin/dashboard", expect=(401, 403))
        assert denied.status_code in (401, 403)

        # Register + promote via SQLite so admin surfaces are exercised live
        reg = c.client.post(
            "/auth/register",
            json={
                "email": admin_email,
                "username": admin_user,
                "password": admin_pass,
                "full_name": "Admin Auditor",
            },
        )
        assert reg.status_code in (200, 201, 400, 409), reg.text

        import sqlite3
        from pathlib import Path

        db_path = Path(__file__).resolve().parents[1] / "icap.db"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "UPDATE users SET role = 'ADMIN', is_verified = 1 "
                "WHERE email = ?",
                (admin_email,),
            )
            conn.commit()
        finally:
            conn.close()

        lr = c.client.post(
            "/auth/login",
            json={"email": admin_email, "password": admin_pass},
        )
        assert lr.status_code == 200, lr.text
        c.admin_token = lr.json()["access_token"]

        dash = c.req("GET", "/admin/dashboard", admin=True, expect=200).json()
        c.req("GET", "/admin/statistics", admin=True, expect=200)
        c.req("GET", "/admin/recommendations", admin=True, expect=200)
        c.req("GET", "/admin/alarms", admin=True, expect=200)
        c.req("GET", "/admin/analytics", admin=True, expect=200)
        c.req("GET", "/admin/reports", admin=True, expect=200)
        return f"RBAC deny + admin dash keys={list(dash.keys())[:8]}"

    run_step("Admin", admin)

    # ── Logout ──
    def logout():
        c.req("POST", "/auth/logout", expect=(200, 204))
        # me should still work with token unless blacklist — soft check
        return "logout accepted"

    run_step("Logout", logout)

    # Summary
    print("\n=== SUMMARY ===")
    print(f"PASS: {len(PASS)}")
    print(f"FAIL: {len(FAIL)}")
    for f in FAIL:
        print(f"  - {f['feature']}: {f['detail']}")
    print()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
