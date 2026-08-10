"""Tests for admin notification settings and broadcast announcements."""

from app.models.notification import Notification, NotificationType
from app.models.system_settings import SystemSettings
from app.schemas.system_settings import SystemNotificationSettingsUpdate
from app.services.system_settings_service import SystemSettingsService


class TestSystemSettingsService:
    def test_get_or_create_singleton(self, db_session):
        a = SystemSettingsService.get_or_create(db_session)
        b = SystemSettingsService.get_or_create(db_session)
        assert a.id == 1
        assert b.id == 1
        assert (
            db_session.query(SystemSettings).count() == 1
        )

    def test_update_partial(self, db_session, admin_user):
        row = SystemSettingsService.update(
            db_session,
            SystemNotificationSettingsUpdate(
                email_notifications_enabled=False,
                habit_score_alert_threshold=40.0,
            ),
            updated_by_user_id=admin_user.id,
        )
        assert row.email_notifications_enabled is False
        assert row.push_notifications_enabled is True
        assert row.habit_score_alert_threshold == 40.0
        assert row.updated_by_user_id == admin_user.id

    def test_broadcast_creates_notifications(
        self, db_session, test_user, admin_user
    ):
        result = SystemSettingsService.broadcast_announcement(
            db_session,
            title="Platform Update",
            body="We shipped notification settings.",
            send_push=True,
            created_by_user_id=admin_user.id,
        )
        # test_user + admin_user are both active
        assert result["users_targeted"] == 2
        # in-app + push per user
        assert result["notifications_created"] == 4
        assert result["push_queued"] == 2

        announcements = (
            db_session.query(Notification)
            .filter(Notification.notification_type == NotificationType.ANNOUNCEMENT)
            .all()
        )
        assert len(announcements) == 4
        assert all(n.title == "Platform Update" for n in announcements)


class TestAdminNotificationSettingsAPI:
    def test_get_requires_admin(self, client, auth_headers):
        res = client.get(
            "/api/v1/admin/notification-settings",
            headers=auth_headers,
        )
        assert res.status_code == 403

    def test_get_and_put_settings(self, client, admin_headers):
        get_res = client.get(
            "/api/v1/admin/notification-settings",
            headers=admin_headers,
        )
        assert get_res.status_code == 200
        data = get_res.json()
        assert data["email_notifications_enabled"] is True
        assert data["push_notifications_enabled"] is True
        assert data["maintenance_mode"] is False
        assert "habit_score_alert_threshold" in data
        assert "smtp_configured" in data
        assert "fcm_available" in data

        put_res = client.put(
            "/api/v1/admin/notification-settings",
            headers=admin_headers,
            json={
                "email_notifications_enabled": False,
                "push_notifications_enabled": False,
                "maintenance_mode": True,
                "maintenance_message": "Upgrading servers",
                "habit_score_alert_threshold": 25,
                "consistency_alert_threshold": 35,
                "snooze_alert_threshold": 20,
            },
        )
        assert put_res.status_code == 200
        updated = put_res.json()
        assert updated["email_notifications_enabled"] is False
        assert updated["push_notifications_enabled"] is False
        assert updated["maintenance_mode"] is True
        assert updated["maintenance_message"] == "Upgrading servers"
        assert updated["habit_score_alert_threshold"] == 25
        assert updated["consistency_alert_threshold"] == 35
        assert updated["snooze_alert_threshold"] == 20

        # Turn maintenance off so later tests are not affected within this class
        client.put(
            "/api/v1/admin/notification-settings",
            headers=admin_headers,
            json={"maintenance_mode": False},
        )

    def test_put_empty_rejected(self, client, admin_headers):
        res = client.put(
            "/api/v1/admin/notification-settings",
            headers=admin_headers,
            json={},
        )
        assert res.status_code == 400

    def test_broadcast(self, client, admin_headers, test_user, admin_user):
        res = client.post(
            "/api/v1/admin/announcements/broadcast",
            headers=admin_headers,
            json={
                "title": "Hello everyone",
                "body": "This is a test announcement.",
                "send_push": False,
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["users_targeted"] == 2
        # in-app only when send_push=False
        assert data["notifications_created"] == 2
        assert data["push_queued"] == 0

    def test_public_system_status(self, client, admin_headers):
        client.put(
            "/api/v1/admin/notification-settings",
            headers=admin_headers,
            json={
                "maintenance_mode": True,
                "maintenance_message": "Brief outage",
            },
        )
        res = client.get("/api/v1/system/status")
        assert res.status_code == 200
        body = res.json()
        assert body["maintenance_mode"] is True
        assert body["maintenance_message"] == "Brief outage"

        client.put(
            "/api/v1/admin/notification-settings",
            headers=admin_headers,
            json={"maintenance_mode": False},
        )

    def test_maintenance_blocks_non_admin_writes(
        self, client, admin_headers, auth_headers
    ):
        client.put(
            "/api/v1/admin/notification-settings",
            headers=admin_headers,
            json={
                "maintenance_mode": True,
                "maintenance_message": "Closed for upgrades",
            },
        )
        # Non-admin mutating request should be blocked
        blocked = client.put(
            "/api/v1/profiles/me",
            headers=auth_headers,
            json={"timezone": "UTC"},
        )
        assert blocked.status_code == 503
        assert blocked.json().get("maintenance_mode") is True

        # Admin can still update settings
        ok = client.put(
            "/api/v1/admin/notification-settings",
            headers=admin_headers,
            json={"maintenance_mode": False},
        )
        assert ok.status_code == 200
