"""Knowledge proxy: workspace-scoped CRUD for collections + documents,
plus search. RBAC and audit done here; knowledge-svc trusts us.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

import httpx
from agenticos_shared.audit import AuditEvent, safe_payload
from agenticos_shared.auth import Principal
from agenticos_shared.errors import AgenticOSError
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from ..audit_bus import get_emitter
from ..auth.deps import current_principal, require_workspace_role
from ..settings import Settings, get_settings

router = APIRouter(tags=["knowledge"])


async def _proxy_json(
    method: str, path: str, settings: Settings, *, json: Any | None = None
) -> tuple[int, Any]:
    url = f"{settings.knowledge_svc_url.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.request(method, url, json=json)
    if r.status_code >= 400:
        try:
            problem = r.json()
        except Exception:
            problem = {"detail": r.text}
        raise AgenticOSError(
            problem.get("detail") or "knowledge-svc error",
            status=r.status_code,
            code=problem.get("code") or "knowledge_error",
            title=problem.get("title") or "Knowledge service error",
        )
    if r.status_code == 204:
        return 204, None
    return r.status_code, r.json()


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------
@router.get("/workspaces/{workspace_id}/collections")
async def list_collections(
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("document:read"))],
    settings: Annotated[Settings, Depends(get_settings)],
):
    _, ws_id = ctx
    _, body = await _proxy_json("GET", f"/workspaces/{ws_id}/collections", settings)
    return body


@router.post("/workspaces/{workspace_id}/collections", status_code=status.HTTP_201_CREATED)
async def create_collection(
    body: dict,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("document:write"))],
    settings: Annotated[Settings, Depends(get_settings)],
):
    principal, ws_id = ctx
    _, out = await _proxy_json("POST", f"/workspaces/{ws_id}/collections", settings, json=body)
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="collection.create",
            resource_type="collection",
            resource_id=str(out.get("id") if isinstance(out, dict) else ""),
            payload=safe_payload(body),
            ip=request.client.host if request.client else None,
        )
    )
    return out


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@router.get("/workspaces/{workspace_id}/documents")
async def list_documents(
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("document:read"))],
    settings: Annotated[Settings, Depends(get_settings)],
    collection_id: UUID | None = None,
):
    _, ws_id = ctx
    path = f"/workspaces/{ws_id}/documents"
    if collection_id is not None:
        path += f"?collection_id={collection_id}"
    _, body = await _proxy_json("GET", path, settings)
    return body


@router.post(
    "/workspaces/{workspace_id}/documents",
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    workspace_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile = File(...),
    collection_id: UUID | None = Form(default=None),
    title: str | None = Form(default=None),
    embed_alias: str | None = Form(default=None),
):
    # RBAC manual check (Form params + path can't share workspace_role dep cleanly).
    from agenticos_shared.errors import ForbiddenError, NotFoundError
    from agenticos_shared.models import Workspace, WorkspaceMember
    from sqlalchemy import select

    from ..auth.deps import PERMISSIONS, ROLE_RANK
    from ..db import get_sessionmaker

    sm = get_sessionmaker()
    with sm() as db:
        ws = db.get(Workspace, workspace_id)
        if ws is None or ws.tenant_id != principal.tenant_id:
            raise NotFoundError("workspace not found")
        row = db.execute(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == principal.user_id,
            )
        ).scalar_one_or_none()
        if "superuser" not in principal.roles and (
            row is None or ROLE_RANK.get(row, -1) < PERMISSIONS["document:write"]
        ):
            raise ForbiddenError("document:write required")

    blob = await file.read()
    files = {
        "file": (file.filename or "upload", blob, file.content_type or "application/octet-stream")
    }
    data = {}
    if collection_id is not None:
        data["collection_id"] = str(collection_id)
    if title is not None:
        data["title"] = title
    if embed_alias is not None:
        data["embed_alias"] = embed_alias

    url = f"{settings.knowledge_svc_url.rstrip('/')}/workspaces/{workspace_id}/documents"
    async with httpx.AsyncClient(timeout=300.0) as c:
        r = await c.post(url, files=files, data=data)
    if r.status_code >= 400:
        try:
            problem = r.json()
        except Exception:
            problem = {"detail": r.text}
        raise AgenticOSError(
            problem.get("detail") or "ingest failed",
            status=r.status_code,
            code=problem.get("code") or "ingest_error",
            title=problem.get("title") or "Ingest error",
        )

    body = r.json()
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=workspace_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="document.upload",
            resource_type="document",
            resource_id=str(body.get("id")),
            payload={
                "title": body.get("title"),
                "size_bytes": body.get("size_bytes"),
                "mime": body.get("mime"),
                "chunk_count": body.get("chunk_count"),
            },
            ip=request.client.host if request.client else None,
        )
    )
    return body


@router.delete(
    "/workspaces/{workspace_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    document_id: UUID,
    request: Request,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("document:write"))],
    settings: Annotated[Settings, Depends(get_settings)],
):
    principal, ws_id = ctx
    await _proxy_json("DELETE", f"/documents/{document_id}", settings)
    await get_emitter().emit(
        AuditEvent(
            tenant_id=principal.tenant_id,
            workspace_id=ws_id,
            actor_id=principal.user_id,
            actor_email=principal.email,
            action="document.delete",
            resource_type="document",
            resource_id=str(document_id),
            ip=request.client.host if request.client else None,
        )
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
@router.post("/workspaces/{workspace_id}/search")
async def search(
    body: dict,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("document:read"))],
    settings: Annotated[Settings, Depends(get_settings)],
):
    _, ws_id = ctx
    payload = {**body, "workspace_id": str(ws_id)}
    _, out = await _proxy_json("POST", "/search", settings, json=payload)
    return out


@router.post("/workspaces/{workspace_id}/collections/{collection_id}/search")
async def search_collection(
    collection_id: UUID,
    body: dict,
    ctx: Annotated[tuple[Principal, UUID], Depends(require_workspace_role("document:read"))],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Collection-scoped hybrid search (PLAN §4 — POST /collections/{id}/search)."""

    _, ws_id = ctx
    payload = {
        **body,
        "workspace_id": str(ws_id),
        "collection_id": str(collection_id),
    }
    _, out = await _proxy_json("POST", "/search", settings, json=payload)
    return out
