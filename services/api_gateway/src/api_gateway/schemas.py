"""Pydantic request/response models for the api-gateway."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Many enterprise IdPs use ``user@local`` style addresses for service accounts
# and many test fixtures use ``user@x.test``; we accept any non-empty email-ish
# string in responses to avoid IdP interop surprises.
LooseEmail = str

WorkspaceRole = Literal["owner", "admin", "builder", "member", "viewer"]


# ---------------------------------------------------------------------------
# Auth / Me
# ---------------------------------------------------------------------------
class LoginResponse(BaseModel):
    """Response from ``POST /auth/oidc/login`` — the URL to redirect to."""

    authorize_url: str
    state: str


class WorkspaceMembership(BaseModel):
    workspace_id: UUID
    workspace_slug: str
    workspace_name: str
    role: WorkspaceRole


class MeResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    email: LooseEmail
    display_name: str | None = None
    is_superuser: bool = False
    workspaces: list[WorkspaceMembership] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------
class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")


class WorkspaceOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    slug: str
    created_at: datetime


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
class MemberAdd(BaseModel):
    email: LooseEmail = Field(min_length=1, max_length=320)
    role: WorkspaceRole = "member"


class MemberUpdate(BaseModel):
    role: WorkspaceRole


class MemberOut(BaseModel):
    user_id: UUID
    email: LooseEmail
    display_name: str | None = None
    role: WorkspaceRole
    added_at: datetime
