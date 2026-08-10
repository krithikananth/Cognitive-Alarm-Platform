"""Public system status endpoints (no auth required)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.system_settings import SystemStatusResponse
from app.services.system_settings_service import SystemSettingsService

router = APIRouter(prefix="/system", tags=["System"])


@router.get(
    "/status",
    response_model=SystemStatusResponse,
    summary="Public platform status",
)
def get_system_status(db: Session = Depends(get_db)):
    """Return maintenance mode flag for client banners (unauthenticated)."""
    row = SystemSettingsService.get_or_create(db)
    return SystemStatusResponse(
        maintenance_mode=bool(row.maintenance_mode),
        maintenance_message=(
            row.maintenance_message if row.maintenance_mode else None
        ),
    )
