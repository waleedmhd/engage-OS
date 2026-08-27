"""Regression test for Msg-I2 / Meta-I2 (P1.4).

GET /messages/{conversation_id} previously returned total = len(items)
(the page size), so the frontend could never paginate past page 1. This
seeds more messages than the page limit and asserts the response carries
the *real* total (total > len(items)).
"""

from __future__ import annotations

import pytest

from app.core.security import create_access_token
from tests.factories import make_contact, make_conversation, make_message, make_user


def _token(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"}


@pytest.mark.asyncio
async def test_list_messages_total_is_real_count_not_page_size(
    committed_db, client
):
    user = make_user(committed_db, role="agent")
    contact = make_contact(committed_db)
    conv = make_conversation(committed_db, contact=contact, state="AI_ACTIVE")
    for i in range(7):
        make_message(committed_db, conversation=conv, content=f"m{i}")
    committed_db.commit()

    resp = await client.get(
        f"/api/v1/messages/{conv.id}?limit=3&offset=0", headers=_token(user)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 3
    assert body["total"] == 7
    assert body["total"] > len(body["items"])
