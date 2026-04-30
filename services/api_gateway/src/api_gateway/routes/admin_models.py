"""Proxy routes for the model registry — auth + RBAC done here, then we
forward to the llm-gateway which has no user-facing AuthN/AuthZ of its own
(only an internal-token header).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

import httpx
from agenticos_shared.audit import AuditEvent, safe_payload
from agenticos_shared.auth import Principal
from agenticos_shared.errors import AgenticOSError
from fastapi import APIRouter, Depends, Request, status

from ..audit_bus import get_emitter
from ..auth.deps import require_admin
from ..settings import Settings, get_settings

router = APIRouter(prefix="/admin/models", tags=["admin", "models"])


def _headers(settings: Settings) -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if settings.llm_gateway_internal_token:
        h["Authorization"] = f"Bearer {settings.llm_gateway_internal_token}"
    return h


async def _proxy(
    method: str, path: str, settings: Settings, *, json: Any | None = None
) -> tuple[int, Any]:
    url = f"{settings.llm_gateway_url.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=15.0, headers=_headers(settings)) as c:
        r = await c.request(method, url, json=json)
    if r.status_code >= 400:
        try:
            problem = r.json()
        except Exception:
            problem = {"detail": r.text}
        raise AgenticOSError(
            problem.get("detail") or problem.get("title") or "llm-gateway error",
            status=r.status_code,
            code=problem.get("code") or "llm_gateway_error",
            title=problem.get("title") or "LLM gateway error",
        )
    if r.status_code == 204:
        return (204, None)
    return (r.status_code, r.json())


@router.get("")
async def list_models(
    _: Annotated[Principal, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    _, body = await _proxy("GET", "/admin/models", settings)
    return body


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_model(
    body: dict,
    request: Request,
    principal: Annotated[Principal, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    _, out = await _proxy("POST", "/admin/models", settings, json=body)
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="model.create",
            resource_type="model",
            resource_id=str(out.get("id") if isinstance(out, dict) else ""),
            payload=safe_payload(body),
            ip=request.client.host if request.client else None,
            request_id=principal.request_id,
        )
    )
    return out


@router.patch("/{model_id}")
async def update_model(
    model_id: UUID,
    body: dict,
    request: Request,
    principal: Annotated[Principal, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    _, out = await _proxy("PATCH", f"/admin/models/{model_id}", settings, json=body)
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="model.update",
            resource_type="model",
            resource_id=str(model_id),
            payload=safe_payload(body),
            request_id=principal.request_id,
        )
    )
    return out


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_id: UUID,
    principal: Annotated[Principal, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    await _proxy("DELETE", f"/admin/models/{model_id}", settings)
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="model.delete",
            resource_type="model",
            resource_id=str(model_id),
            request_id=principal.request_id,
        )
    )


@router.post("/{model_id}/test")
async def test_model(
    model_id: UUID,
    principal: Annotated[Principal, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    _, out = await _proxy("POST", f"/admin/models/{model_id}/test", settings)
    return out
