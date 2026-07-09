"""API v1 router that aggregates all endpoint routers."""
from fastapi import APIRouter
from app.api.v1.endpoints import auth, users, profiles, alarms, admin

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(profiles.router)
api_router.include_router(alarms.router)
api_router.include_router(admin.router)

