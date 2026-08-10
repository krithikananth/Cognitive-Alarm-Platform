"""Schemas for user lifestyle Reports."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ReportTypeInfo(BaseModel):
    type: str
    title: str
    description: str


class ReportTypeListResponse(BaseModel):
    reports: List[ReportTypeInfo]


class ReportPeriod(BaseModel):
    days: int
    start_date: str
    end_date: str
    window_start: str
    window_end: str


class ReportResponse(BaseModel):
    report_type: str
    title: str
    description: str
    generated_at: str
    period: ReportPeriod
    is_empty: bool
    empty_message: Optional[str] = None
    sections: Dict[str, Any] = Field(default_factory=dict)
    insights: List[Any] = Field(default_factory=list)
