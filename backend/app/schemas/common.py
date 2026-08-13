"""Shared response-model building blocks."""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class AggregateResponse(BaseModel):
    """Base for analytics/aggregate payloads assembled at runtime.

    A ``response_model`` does not only document a route — FastAPI *filters* the
    response through it, and any key the model does not declare is silently
    dropped. Several of these payloads are built by aggregation services whose
    nested blocks grow with the feature set, so a strict model would quietly
    delete fields the frontend already consumes.

    ``extra="allow"`` keeps the contract honest in both directions: the fields
    declared below are validated and published in the OpenAPI schema, while
    anything additional passes through untouched. Endpoints with a small, fixed
    payload use a plain ``BaseModel`` instead and are strict by design.
    """

    model_config = ConfigDict(extra="allow")


class RootResponse(BaseModel):
    """GET / — service identity. Doc links are omitted in production."""

    name: str
    version: str
    description: str
    docs: Optional[str] = None
    redoc: Optional[str] = None


class HealthResponse(BaseModel):
    """GET /health — container and load-balancer probe."""

    status: str
    version: str
