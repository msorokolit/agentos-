"""Long-term memory upsert + search (Python fallback path)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from agenticos_shared.errors import NotFoundError
from memory_svc.long_term import (
    delete_item,
    list_items,
    search_by_embedding,
    upsert_item,
)


def test_upsert_creates_then_updates(db, workspace):
    row = upsert_item(
        db,
        workspace_id=workspace.id,
        scope="user",
        owner_id=None,
        key="prefs",
        value={"a": 1},
        summary="prefs",
    )
    assert row.value == {"a": 1}
    again = upsert_item(
        db,
        workspace_id=workspace.id,
        scope="user",
        owner_id=None,
        key="prefs",
        value={"a": 2, "b": 3},
        summary="updated",
    )
    assert again.id == row.id
    assert again.value == {"a": 2, "b": 3}
    assert again.summary == "updated"


def test_list_items_filters(db, workspace):
    upsert_item(
        db,
        workspace_id=workspace.id,
        scope="user",
        owner_id=None,
        key="a",
        value={},
        summary=None,
    )
    upsert_item(
        db,
        workspace_id=workspace.id,
        scope="agent",
        owner_id=None,
        key="b",
        value={},
        summary=None,
    )
    only_user = list_items(db, workspace_id=workspace.id, scope="user")
    assert {r.key for r in only_user} == {"a"}


def test_delete_404_unknown(db):
    with pytest.raises(NotFoundError):
        delete_item(db, item_id=uuid4())


def test_search_by_embedding_python_fallback(db, workspace):
    aligned = [1.0, 0.0, 0.0]
    misaligned = [0.0, 1.0, 0.0]

    upsert_item(
        db,
        workspace_id=workspace.id,
        scope="workspace",
        owner_id=None,
        key="aligned",
        value={"k": "v"},
        summary="aligned",
        embedding=aligned,
    )
    upsert_item(
        db,
        workspace_id=workspace.id,
        scope="workspace",
        owner_id=None,
        key="misaligned",
        value={"k": "v"},
        summary="misaligned",
        embedding=misaligned,
    )
    pairs = search_by_embedding(
        db,
        workspace_id=workspace.id,
        query_embedding=aligned,
        top_k=1,
    )
    assert len(pairs) == 1
    assert pairs[0][0].key == "aligned"
