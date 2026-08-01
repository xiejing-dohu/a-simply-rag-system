"""持久化与端到端功能测试模块

包含用户 JWT 权限隔离、聊天会话级联删除、Token 额度超限封禁以及密码防爆破锁定测试。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from app.core.security import normalize_username, verify_token
from app.db.mysql import async_session_maker
from app.db.redis import redis_client
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.state_repository import add_message, quota_state, record_token_usage


def test_username_normalization_is_shared_by_case_and_whitespace_variants():
    """测试用户名规范化防重名逻辑"""
    assert normalize_username("  Alice.Admin  ") == "alice.admin"
    assert normalize_username("ALICE.ADMIN") == "alice.admin"


async def register(client, suffix: str, label: str) -> dict:
    """辅助测试函数：注册测试用户"""
    response = await client.post(
        "/auth/register",
        json={
            "username": f"{label}_{suffix}",
            "email": f"{label}_{suffix}@example.com",
            "password": "correct-password",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def login(client, username: str, password: str = "correct-password") -> dict:
    """辅助测试函数：登录测试用户"""
    response = await client.post(
        "/auth/token",
        data={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_user_jwt_chat_isolation_and_quota_persist(api_client):
    """测试用户数据隔离、JWT 解析与 Token 限额统计"""
    suffix = uuid.uuid4().hex[:12]
    first = await register(api_client, suffix, "alice")
    second = await register(api_client, suffix, "bob")
    first_login = await login(api_client, first["username"])
    second_login = await login(api_client, second["username"])
    first_headers = {"Authorization": f"Bearer {first_login['access_token']}"}
    second_headers = {"Authorization": f"Bearer {second_login['access_token']}"}

    try:
        access_payload = verify_token(first_login["access_token"], "access")
        refresh_payload = verify_token(first_login["refresh_token"], "refresh")
        assert int(access_payload["sub"]) == first["id"]
        assert int(refresh_payload["sub"]) == first["id"]

        refresh = await api_client.post(
            "/auth/refresh",
            json={"refresh_token": first_login["refresh_token"]},
        )
        assert refresh.status_code == 200
        verify_token(refresh.json()["access_token"], "access")

        async with async_session_maker() as session:
            stored_user = await session.get(User, first["id"])
            assert stored_user is not None
            assert stored_user.hashed_password != "correct-password"
            assert stored_user.hashed_password.startswith("$pbkdf2-sha256$")

        created = await api_client.post(
            "/chat/conversations",
            headers=first_headers,
            json={
                "title": "隔离测试",
                "model_name": "test-model",
                "rag_enabled": False,
            },
        )
        assert created.status_code == 200, created.text
        conversation_id = created.json()["id"]
        await add_message(
            conversation_id=conversation_id,
            role="user",
            content="only-alice-can-read",
        )

        own_messages = await api_client.get(
            f"/chat/conversations/{conversation_id}/messages",
            headers=first_headers,
        )
        assert own_messages.status_code == 200
        assert own_messages.json()[0]["content"] == "only-alice-can-read"

        foreign_messages = await api_client.get(
            f"/chat/conversations/{conversation_id}/messages",
            headers=second_headers,
        )
        assert foreign_messages.status_code == 404
        foreign_delete = await api_client.delete(
            f"/chat/conversations/{conversation_id}",
            headers=second_headers,
        )
        assert foreign_delete.status_code == 404

        admin_login = await login(api_client, "admin", "admin123")
        admin_headers = {
            "Authorization": f"Bearer {admin_login['access_token']}"
        }
        quota_update = await api_client.put(
            f"/auth/users/{first['id']}",
            headers=admin_headers,
            json={"five_hour_token_limit": 100, "weekly_token_limit": 200},
        )
        assert quota_update.status_code == 200, quota_update.text

        await record_token_usage(
            first["id"],
            {"prompt_tokens": 60, "completion_tokens": 40, "total_tokens": 100},
        )
        me = await api_client.get("/auth/me", headers=first_headers)
        assert me.status_code == 200
        assert me.json()["total_tokens_used"] == 100
        assert me.json()["five_hour_tokens_used"] == 100
        _, retry_after = await quota_state(first["id"])
        assert retry_after is not None and retry_after > 0

        reset = await api_client.post(
            f"/auth/users/{first['id']}/token-usage/reset",
            headers=admin_headers,
            json={"scope": "all"},
        )
        assert reset.status_code == 200
        assert reset.json()["five_hour_tokens_used"] == 0
        assert reset.json()["weekly_tokens_used"] == 0

        logout = await api_client.post(
            "/auth/logout",
            json={"refresh_token": first_login["refresh_token"]},
        )
        assert logout.status_code == 200
        rejected_refresh = await api_client.post(
            "/auth/refresh",
            json={"refresh_token": first_login["refresh_token"]},
        )
        assert rejected_refresh.status_code == 401
    finally:
        async with async_session_maker() as session:
            await session.execute(
                delete(User).where(User.id.in_([first["id"], second["id"]]))
            )
            await session.commit()


@pytest.mark.asyncio
async def test_conversation_delete_cascades_messages(api_client):
    """测试删除对话会话自动级联删除关联消息功能"""
    suffix = uuid.uuid4().hex[:12]
    user = await register(api_client, suffix, "cascade")
    token = await login(api_client, user["username"])
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    try:
        response = await api_client.post(
            "/chat/conversations",
            headers=headers,
            json={"title": "cascade", "model_name": "test-model"},
        )
        conversation_id = response.json()["id"]
        await add_message(
            conversation_id=conversation_id,
            role="user",
            content="will-be-cascaded",
        )
        deleted = await api_client.delete(
            f"/chat/conversations/{conversation_id}",
            headers=headers,
        )
        assert deleted.status_code == 200
        async with async_session_maker() as session:
            assert await session.get(Conversation, conversation_id) is None
            messages = await session.execute(
                select(Message).where(
                    Message.conversation_id == conversation_id
                )
            )
            assert messages.scalar_one_or_none() is None
    finally:
        async with async_session_maker() as session:
            await session.execute(delete(User).where(User.id == user["id"]))
            await session.commit()


@pytest.mark.asyncio
async def test_password_failures_lock_for_five_minutes(api_client):
    """测试连续三次输入错误密码触发 Redis 5分钟账户防爆破锁定机制"""
    suffix = uuid.uuid4().hex[:12]
    user = await register(api_client, suffix, "LockCase")
    username = user["username"]
    assert username == username.casefold()
    try:
        first = await api_client.post(
            "/auth/token",
            data={"username": f"  {username.upper()}  ", "password": "wrong-password"},
        )
        second = await api_client.post(
            "/auth/token",
            data={"username": username.title(), "password": "wrong-password"},
        )
        third = await api_client.post(
            "/auth/token",
            data={"username": username, "password": "wrong-password"},
        )
        assert first.status_code == 401
        assert second.status_code == 401
        assert third.status_code == 429
        assert int(third.headers["Retry-After"]) == 300
        assert await redis_client.ttl(f"auth:lock:{username}") > 0

        admin_login = await login(api_client, "admin", "admin123")
        immutable = await api_client.put(
            f"/auth/users/{admin_login['user']['id']}",
            headers={
                "Authorization": f"Bearer {admin_login['access_token']}"
            },
            json={"role": "employee"},
        )
        assert immutable.status_code == 403
    finally:
        await redis_client.delete(
            f"auth:failures:{username}", f"auth:lock:{username}"
        )
        async with async_session_maker() as session:
            await session.execute(delete(User).where(User.id == user["id"]))
            await session.commit()
