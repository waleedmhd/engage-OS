"""Unit tests for UserService — repo + audit + token-repo AsyncMocked."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.auth.constants import UserRole
from app.modules.users.constants import (
    AUDIT_ACTION_RESET_PASSWORD,
    ERR_CANNOT_MODIFY_SELF,
    ERR_LAST_ACTIVE_ADMIN,
    ERR_NO_CHANGES,
    PASSWORD_REDACTED,
)
from app.modules.users.schemas import (
    UserCreateRequest,
    UserSectionsUpdateRequest,
    UserUpdateRequest,
)
from app.modules.users.service import UserService


def _user(
    *,
    user_id=None,
    role=UserRole.AGENT.value,
    is_active=True,
    email="a@b.com",
    name="Test",
):
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=user_id or uuid.uuid4(),
        email=email,
        name=name,
        role=role,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


def _make_service():
    svc = UserService(AsyncMock())
    svc.repo = AsyncMock()
    svc._tokens = AsyncMock()
    svc._audit = AsyncMock()
    return svc


# --------------------------------------------------------------------- create


@pytest.mark.asyncio
async def test_create_user_audits_after_state_without_password():
    svc = _make_service()
    actor = uuid.uuid4()
    svc.repo.get_by_email.return_value = None
    created = _user()
    svc.repo.create.return_value = created

    await svc.create_user(
        UserCreateRequest(
            email="new@x.com",
            name="N",
            role=UserRole.AGENT,
            password="hunter22!",
        ),
        actor_id=actor,
    )

    _, kwargs = svc._audit.append.call_args
    assert kwargs["action"] == "create"
    assert kwargs["entity_type"] == "User"
    assert kwargs["actor_id"] == actor
    assert kwargs["before_state"] is None
    assert "password" not in kwargs["after_state"]
    assert "hashed_password" not in kwargs["after_state"]


@pytest.mark.asyncio
async def test_create_user_rejects_duplicate_email():
    svc = _make_service()
    svc.repo.get_by_email.return_value = _user()
    with pytest.raises(ConflictError):
        await svc.create_user(
            UserCreateRequest(
                email="dup@x.com",
                name="N",
                role=UserRole.AGENT,
                password="hunter22!",
            ),
            actor_id=uuid.uuid4(),
        )


# --------------------------------------------------------------------- update


@pytest.mark.asyncio
async def test_update_user_not_found():
    svc = _make_service()
    svc.repo.get.return_value = None
    with pytest.raises(NotFoundError):
        await svc.update_user(uuid.uuid4(), UserUpdateRequest(name="x"), actor_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_update_empty_diff_raises_no_changes():
    svc = _make_service()
    target = _user(name="same")
    svc.repo.get.return_value = target
    with pytest.raises(ConflictError) as exc:
        await svc.update_user(target.id, UserUpdateRequest(name="same"), actor_id=uuid.uuid4())
    assert ERR_NO_CHANGES in str(exc.value)


@pytest.mark.asyncio
async def test_self_demote_blocked():
    svc = _make_service()
    me = _user(role=UserRole.ADMIN.value)
    svc.repo.get.return_value = me
    with pytest.raises(ConflictError) as exc:
        await svc.update_user(
            me.id, UserUpdateRequest(role=UserRole.AGENT), actor_id=me.id
        )
    assert ERR_CANNOT_MODIFY_SELF in str(exc.value)


@pytest.mark.asyncio
async def test_self_deactivate_blocked():
    svc = _make_service()
    me = _user(role=UserRole.ADMIN.value)
    svc.repo.get.return_value = me
    with pytest.raises(ConflictError) as exc:
        await svc.update_user(
            me.id, UserUpdateRequest(is_active=False), actor_id=me.id
        )
    assert ERR_CANNOT_MODIFY_SELF in str(exc.value)


@pytest.mark.asyncio
async def test_self_rename_allowed():
    svc = _make_service()
    me = _user(role=UserRole.ADMIN.value, name="Old")
    svc.repo.get.return_value = me
    svc.repo.apply_updates.return_value = _user(
        user_id=me.id, role=UserRole.ADMIN.value, name="New"
    )
    out = await svc.update_user(
        me.id, UserUpdateRequest(name="New"), actor_id=me.id
    )
    assert out.name == "New"


@pytest.mark.asyncio
async def test_last_admin_block_on_demote():
    svc = _make_service()
    target = _user(role=UserRole.ADMIN.value)
    svc.repo.get.return_value = target
    svc.repo.count_other_active_admins.return_value = 0
    with pytest.raises(ConflictError) as exc:
        await svc.update_user(
            target.id, UserUpdateRequest(role=UserRole.AGENT), actor_id=uuid.uuid4()
        )
    assert ERR_LAST_ACTIVE_ADMIN in str(exc.value)


@pytest.mark.asyncio
async def test_last_admin_block_on_deactivate():
    svc = _make_service()
    target = _user(role=UserRole.ADMIN.value)
    svc.repo.get.return_value = target
    svc.repo.count_other_active_admins.return_value = 0
    with pytest.raises(ConflictError) as exc:
        await svc.update_user(
            target.id, UserUpdateRequest(is_active=False), actor_id=uuid.uuid4()
        )
    assert ERR_LAST_ACTIVE_ADMIN in str(exc.value)


@pytest.mark.asyncio
async def test_demote_with_other_admins_succeeds_and_revokes_tokens():
    svc = _make_service()
    target = _user(role=UserRole.ADMIN.value)
    svc.repo.get.return_value = target
    svc.repo.count_other_active_admins.return_value = 1
    svc.repo.apply_updates.return_value = _user(
        user_id=target.id, role=UserRole.AGENT.value
    )

    await svc.update_user(
        target.id, UserUpdateRequest(role=UserRole.AGENT), actor_id=uuid.uuid4()
    )

    svc._tokens.revoke_all_for_user.assert_awaited_once_with(target.id)


@pytest.mark.asyncio
async def test_deactivate_agent_revokes_tokens():
    svc = _make_service()
    target = _user(role=UserRole.AGENT.value)
    svc.repo.get.return_value = target
    svc.repo.apply_updates.return_value = _user(
        user_id=target.id, role=UserRole.AGENT.value, is_active=False
    )

    await svc.update_user(
        target.id, UserUpdateRequest(is_active=False), actor_id=uuid.uuid4()
    )

    svc._tokens.revoke_all_for_user.assert_awaited_once_with(target.id)


@pytest.mark.asyncio
async def test_rename_does_not_revoke_tokens():
    svc = _make_service()
    target = _user(name="Old")
    svc.repo.get.return_value = target
    svc.repo.apply_updates.return_value = _user(user_id=target.id, name="New")

    await svc.update_user(
        target.id, UserUpdateRequest(name="New"), actor_id=uuid.uuid4()
    )

    svc._tokens.revoke_all_for_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_audit_records_before_and_after():
    svc = _make_service()
    target = _user(name="Old")
    svc.repo.get.return_value = target
    svc.repo.apply_updates.return_value = _user(user_id=target.id, name="New")

    actor = uuid.uuid4()
    await svc.update_user(
        target.id, UserUpdateRequest(name="New"), actor_id=actor
    )

    _, kwargs = svc._audit.append.call_args
    assert kwargs["action"] == "update"
    assert kwargs["entity_type"] == "User"
    assert kwargs["actor_id"] == actor
    assert kwargs["before_state"]["name"] == "Old"
    assert kwargs["after_state"]["name"] == "New"


@pytest.mark.asyncio
async def test_update_email_conflict_raises():
    svc = _make_service()
    target = _user(email="old@x.com")
    other = _user(email="taken@x.com")
    svc.repo.get.return_value = target
    svc.repo.get_by_email.return_value = other
    with pytest.raises(ConflictError):
        await svc.update_user(
            target.id, UserUpdateRequest(email="taken@x.com"), actor_id=uuid.uuid4()
        )


# ------------------------------------------------------------- reset password


@pytest.mark.asyncio
async def test_reset_password_revokes_tokens_and_redacts_audit():
    svc = _make_service()
    target = _user()
    svc.repo.get.return_value = target
    svc.repo.set_password.return_value = target

    actor = uuid.uuid4()
    await svc.reset_password(target.id, "new-strong-pw-123", actor_id=actor)

    svc._tokens.revoke_all_for_user.assert_awaited_once_with(target.id)
    _, kwargs = svc._audit.append.call_args
    assert kwargs["action"] == AUDIT_ACTION_RESET_PASSWORD
    assert kwargs["entity_type"] == "User"
    assert kwargs["actor_id"] == actor
    assert kwargs["before_state"] == {"password": PASSWORD_REDACTED}
    assert kwargs["after_state"] == {"password": PASSWORD_REDACTED}


@pytest.mark.asyncio
async def test_reset_password_user_not_found():
    svc = _make_service()
    svc.repo.get.return_value = None
    with pytest.raises(NotFoundError):
        await svc.reset_password(uuid.uuid4(), "pw-123456", actor_id=uuid.uuid4())


# ------------------------------------------------------------------- listing


@pytest.mark.asyncio
async def test_list_users_clamps_limit():
    svc = _make_service()
    svc.repo.list_paginated.return_value = []
    svc.repo.count.return_value = 0
    out = await svc.list_users(limit=999)
    assert out.limit == 200
    svc.repo.list_paginated.assert_awaited_once()
    _, kwargs = svc.repo.list_paginated.call_args
    assert kwargs["limit"] == 200


# ---------------------------------------------------------- section access


@pytest.mark.asyncio
async def test_get_sections_admin_returns_all():
    svc = _make_service()
    target = _user(role=UserRole.ADMIN.value)
    svc.repo.get.return_value = target

    from app.modules.auth.permission_models import ALL_SECTIONS

    result = await svc.get_user_sections(target.id)
    assert result.sections == ALL_SECTIONS


@pytest.mark.asyncio
async def test_get_sections_agent_with_stored_grants():
    svc = _make_service()
    target = _user(role=UserRole.AGENT.value)
    svc.repo.get.return_value = target
    stored = ["inbox", "contacts", "campaigns"]
    svc.repo.get_accessible_sections = AsyncMock(return_value=stored)

    result = await svc.get_user_sections(target.id)
    assert result.sections == stored


@pytest.mark.asyncio
async def test_get_sections_agent_no_grants_returns_defaults():
    svc = _make_service()
    target = _user(role=UserRole.AGENT.value)
    svc.repo.get.return_value = target
    svc.repo.get_accessible_sections = AsyncMock(return_value=[])

    from app.modules.auth.permission_models import DEFAULT_AGENT_SECTIONS

    result = await svc.get_user_sections(target.id)
    assert result.sections == DEFAULT_AGENT_SECTIONS


@pytest.mark.asyncio
async def test_get_sections_user_not_found():
    svc = _make_service()
    svc.repo.get.return_value = None
    with pytest.raises(NotFoundError):
        await svc.get_user_sections(uuid.uuid4())


@pytest.mark.asyncio
async def test_update_sections_valid():
    svc = _make_service()
    target = _user(role=UserRole.AGENT.value)
    svc.repo.get.return_value = target
    svc.repo.get_accessible_sections = AsyncMock(return_value=["inbox"])
    svc.repo.set_accessible_sections = AsyncMock()

    actor = uuid.uuid4()
    sections = ["inbox", "contacts", "campaigns", "templates", "tag-review"]
    result = await svc.update_user_sections(
        target.id,
        UserSectionsUpdateRequest(sections=sections),
        actor_id=actor,
    )
    assert result.sections == sections
    svc.repo.set_accessible_sections.assert_awaited_once_with(target.id, sections)
    svc._audit.append.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_sections_unknown_key_raises():
    svc = _make_service()
    target = _user(role=UserRole.AGENT.value)
    svc.repo.get.return_value = target

    with pytest.raises(ValidationError) as exc:
        await svc.update_user_sections(
            target.id,
            UserSectionsUpdateRequest(sections=["garbage", "inbox"]),
            actor_id=uuid.uuid4(),
        )
    assert "garbage" in str(exc.value)


@pytest.mark.asyncio
async def test_update_sections_user_not_found():
    svc = _make_service()
    svc.repo.get.return_value = None
    with pytest.raises(NotFoundError):
        await svc.update_user_sections(
            uuid.uuid4(),
            UserSectionsUpdateRequest(sections=["inbox"]),
            actor_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_update_sections_audit_records_before_and_after():
    svc = _make_service()
    target = _user(role=UserRole.AGENT.value)
    svc.repo.get.return_value = target
    svc.repo.get_accessible_sections = AsyncMock(return_value=["inbox"])
    svc.repo.set_accessible_sections = AsyncMock()

    actor = uuid.uuid4()
    new_sections = ["inbox", "contacts"]
    await svc.update_user_sections(
        target.id,
        UserSectionsUpdateRequest(sections=new_sections),
        actor_id=actor,
    )

    _, kwargs = svc._audit.append.call_args
    assert kwargs["action"] == "update"
    assert kwargs["entity_type"] == "user_sections"
    assert kwargs["entity_id"] == target.id
    assert kwargs["actor_id"] == actor
    assert kwargs["before_state"] == {"sections": ["inbox"]}
    assert kwargs["after_state"] == {"sections": new_sections}
