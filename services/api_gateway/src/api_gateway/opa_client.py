"""Tiny OPA admin client used by the policy-bundle routes.

OPA exposes ``PUT /v1/policies/{id}`` for uploading a Rego module and
``DELETE /v1/policies/{id}`` for removing one. We push activated bundles
keyed by ``{tenant_id}/{package}`` so every tenant gets its own
namespace inside the same OPA instance.

If OPA is unreachable we log + return False — activation in our DB is
authoritative; the runtime can re-push on next change. The agent-runtime
``policy_check`` node still queries ``/v1/data/agenticos/tool_access``
which OPA evaluates against whatever bundles are currently loaded.
"""

from __future__ import annotations

from uuid import UUID

import httpx
from agenticos_shared.logging import get_logger

log = get_logger(__name__)


def opa_policy_id(*, tenant_id: UUID | None, package: str, name: str) -> str:
    """Stable OPA-side identifier for a bundle."""

    tenant = str(tenant_id) if tenant_id else "_global"
    return f"agenticos__{tenant}__{package}__{name}"


async def push_policy(
    *,
    opa_url: str,
    policy_id: str,
    rego: str,
    timeout: float = 5.0,
) -> bool:
    url = f"{opa_url.rstrip('/')}/v1/policies/{policy_id}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.put(url, content=rego, headers={"Content-Type": "text/plain"})
    except httpx.HTTPError as exc:
        log.warning("opa_push_failed", error=str(exc), policy_id=policy_id)
        return False
    if r.status_code >= 400:
        log.warning(
            "opa_push_status",
            status=r.status_code,
            body=r.text[:300],
            policy_id=policy_id,
        )
        return False
    return True


async def delete_policy(
    *,
    opa_url: str,
    policy_id: str,
    timeout: float = 5.0,
) -> bool:
    url = f"{opa_url.rstrip('/')}/v1/policies/{policy_id}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.delete(url)
    except httpx.HTTPError as exc:
        log.warning("opa_delete_failed", error=str(exc), policy_id=policy_id)
        return False
    # 200 (OK) and 404 (already gone) both count as success.
    return r.status_code < 400 or r.status_code == 404
