"""Admin CRUD for the model registry.

Auth: bearer token (`LLM_GATEWAY_INTERNAL_TOKEN`) — meant to be called
from the api-gateway, which adds its own user-facing RBAC on top.
If no token is configured, endpoints are open (dev mode).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from agenticos_shared.errors import ConflictError, NotFoundError, UnauthorizedError
from agenticos_shared.models import ModelRow
from fastapi import APIRouter, Depends, Header, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import registry
from ..providers import make_provider
from ..providers.base import ProviderError
from ..schemas import ModelCreate, ModelOut, ModelTestResult, ModelUpdate
from ..settings import Settings, get_settings
from .deps import get_db

router = APIRouter(prefix="/admin/models", tags=["admin", "models"])


def require_internal_token(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> None:
    if not settings.internal_token:
        return  # dev mode
    expected = f"Bearer {settings.internal_token}"
    if authorization != expected:
        raise UnauthorizedError("invalid internal token")


def _row_to_out(row: ModelRow) -> ModelOut:
    return ModelOut(
        id=row.id,
        alias=row.alias,
        provider=row.provider,
        endpoint=row.endpoint,
        model_name=row.model_name,
        kind=row.kind,
        capabilities=dict(row.capabilities or {}),
        default_params=dict(row.default_params or {}),
        enabled=row.enabled,
        cost_per_1m_input_usd=float(row.cost_per_1m_input_usd or 0.0),
        cost_per_1m_output_usd=float(row.cost_per_1m_output_usd or 0.0),
    )


@router.get("", response_model=list[ModelOut], dependencies=[Depends(require_internal_token)])
def list_models(db: Annotated[Session, Depends(get_db)]) -> list[ModelOut]:
    rows = db.execute(select(ModelRow).order_by(ModelRow.alias)).scalars().all()
    return [_row_to_out(r) for r in rows]


@router.post(
    "",
    response_model=ModelOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal_token)],
)
async def create_model(body: ModelCreate, db: Annotated[Session, Depends(get_db)]) -> ModelOut:
    row = ModelRow(
        id=uuid4(),
        alias=body.alias,
        provider=body.provider,
        endpoint=body.endpoint,
        model_name=body.model_name,
        kind=body.kind,
        capabilities=body.capabilities,
        default_params=body.default_params,
        enabled=body.enabled,
        cost_per_1m_input_usd=body.cost_per_1m_input_usd,
        cost_per_1m_output_usd=body.cost_per_1m_output_usd,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"model alias '{body.alias}' already exists") from exc
    await registry.reload_cache()
    return _row_to_out(row)


@router.patch(
    "/{model_id}",
    response_model=ModelOut,
    dependencies=[Depends(require_internal_token)],
)
async def update_model(
    model_id: UUID,
    body: ModelUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> ModelOut:
    row = db.get(ModelRow, model_id)
    if row is None:
        raise NotFoundError("model not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(row, k, v)
    db.flush()
    await registry.reload_cache()
    return _row_to_out(row)


@router.delete(
    "/{model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal_token)],
)
async def delete_model(model_id: UUID, db: Annotated[Session, Depends(get_db)]) -> None:
    row = db.get(ModelRow, model_id)
    if row is None:
        raise NotFoundError("model not found")
    db.delete(row)
    db.flush()
    await registry.reload_cache()


@router.post(
    "/{model_id}/test",
    response_model=ModelTestResult,
    dependencies=[Depends(require_internal_token)],
)
async def test_model(model_id: UUID, db: Annotated[Session, Depends(get_db)]) -> ModelTestResult:
    row = db.get(ModelRow, model_id)
    if row is None:
        raise NotFoundError("model not found")
    provider = make_provider(row.provider, endpoint=row.endpoint, model_name=row.model_name)
    try:
        latency = await provider.ping()
        return ModelTestResult(ok=True, latency_ms=latency)
    except ProviderError as exc:
        return ModelTestResult(ok=False, latency_ms=0, detail=exc.detail or str(exc))
