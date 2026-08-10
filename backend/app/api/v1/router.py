"""API v1 router that aggregates all endpoint routers."""
from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    users,
    profiles,
    alarms,
    admin,
    coach,
    recommendations,
    analytics,
    dashboard,
    notifications,
    reports,
    system,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(profiles.router)
api_router.include_router(alarms.router)
api_router.include_router(recommendations.router)
api_router.include_router(analytics.router)
api_router.include_router(admin.router)
api_router.include_router(coach.router)
api_router.include_router(dashboard.router)
api_router.include_router(notifications.router)
api_router.include_router(reports.router)
api_router.include_router(system.router)

