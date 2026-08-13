"""
User lifestyle Reports API.

Endpoints:
    GET /reports                         — list available report types
    GET /reports/{report_type}           — JSON report preview
    GET /reports/{report_type}/export    — PDF or Excel download
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.report import ReportResponse, ReportTypeListResponse
from app.services.report_export import content_disposition, export_report
from app.services.report_service import REPORT_META, ReportService, ReportType

router = APIRouter(prefix="/reports", tags=["Reports"])


def _parse_report_type(report_type: str) -> ReportType:
    try:
        return ReportType(report_type.lower())
    except ValueError as exc:
        allowed = ", ".join(rt.value for rt in ReportType)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown report type '{report_type}'. Allowed: {allowed}",
        ) from exc


@router.get(
    "",
    response_model=ReportTypeListResponse,
    summary="List available report types",
)
def list_reports(
    current_user: User = Depends(get_current_user),
):
    """Return the five lifestyle report types supported by ICAP."""
    return ReportTypeListResponse(reports=ReportService.list_report_types())


@router.get(
    "/{report_type}",
    response_model=ReportResponse,
    summary="Generate a lifestyle report (JSON)",
)
def get_report(
    report_type: str,
    days: Optional[int] = Query(
        None, ge=1, le=365, description="Lookback window in days (default 30)"
    ),
    start_date: Optional[date] = Query(
        None, description="Inclusive start date (YYYY-MM-DD); requires end_date"
    ),
    end_date: Optional[date] = Query(
        None, description="Inclusive end date (YYYY-MM-DD); requires start_date"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Build a report payload by reusing analytics and dashboard calculations."""
    rt = _parse_report_type(report_type)
    try:
        payload = ReportService.build_report(
            db,
            current_user.id,
            rt,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return payload


@router.get(
    "/{report_type}/export",
    summary="Export a lifestyle report as PDF or Excel",
)
def export_report_file(
    report_type: str,
    format: str = Query(
        "pdf",
        pattern="^(pdf|excel|xlsx)$",
        description="Export format: pdf or excel",
    ),
    days: Optional[int] = Query(None, ge=1, le=365),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download a formatted PDF or Excel report for the given type and period."""
    rt = _parse_report_type(report_type)
    if rt not in REPORT_META:
        raise HTTPException(status_code=404, detail="Unknown report type")

    try:
        payload = ReportService.build_report(
            db,
            current_user.id,
            rt,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        content, media_type, filename = export_report(payload, format)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition(filename),
        },
    )
