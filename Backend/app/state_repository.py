from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.db.mysql import async_session_maker
from app.models.conversation import Conversation
from app.models.document_task import DocumentTask
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_document import KnowledgeDocument
from app.models.message import Message
from app.models.user import User

FIVE_HOURS = timedelta(hours=5)
ONE_WEEK = timedelta(days=7)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def seed_root_admin() -> None:
    """Seed the immutable local root administrator after Alembic migration."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.is_root_admin.is_(True)).limit(1)
        )
        if result.scalar_one_or_none() is None:
            session.add(
                User(
                    username="admin",
                    email="admin@example.com",
                    hashed_password=hash_password("admin123"),
                    role="admin",
                    is_root_admin=True,
                    is_active=True,
                    five_hour_window_started_at=utcnow(),
                    weekly_window_started_at=utcnow(),
                )
            )
            await session.commit()


def _iso(value: datetime) -> str:
    return value.isoformat()


def refresh_user_windows(user: User, now: datetime | None = None) -> bool:
    now = now or utcnow()
    changed = False
    if now - user.five_hour_window_started_at >= FIVE_HOURS:
        user.five_hour_tokens_used = 0
        user.five_hour_window_started_at = now
        changed = True
    if now - user.weekly_window_started_at >= ONE_WEEK:
        user.weekly_tokens_used = 0
        user.weekly_window_started_at = now
        changed = True
    return changed


def serialize_user(user: User) -> dict[str, Any]:
    refresh_user_windows(user)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_root_admin": user.is_root_admin,
        "is_active": user.is_active,
        "created_at": _iso(user.created_at),
        "five_hour_token_limit": user.five_hour_token_limit,
        "weekly_token_limit": user.weekly_token_limit,
        "five_hour_tokens_used": user.five_hour_tokens_used,
        "weekly_tokens_used": user.weekly_tokens_used,
        "input_tokens_used": user.input_tokens_used,
        "output_tokens_used": user.output_tokens_used,
        "total_tokens_used": user.total_tokens_used,
        "five_hour_window_started_at": _iso(user.five_hour_window_started_at),
        "weekly_window_started_at": _iso(user.weekly_window_started_at),
        "five_hour_resets_at": _iso(user.five_hour_window_started_at + FIVE_HOURS),
        "weekly_resets_at": _iso(user.weekly_window_started_at + ONE_WEEK),
    }


def serialize_conversation(item: Conversation) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "model_name": item.model_name,
        "knowledge_base_id": item.knowledge_base_id,
        "rag_enabled": item.rag_enabled,
        "retrieval_mode": item.retrieval_mode,
        "max_retrieval_tokens": item.max_retrieval_tokens,
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
    }


def serialize_message(item: Message) -> dict[str, Any]:
    return {
        "id": item.id,
        "conversation_id": item.conversation_id,
        "role": item.role,
        "content": item.content,
        "created_at": _iso(item.created_at),
        "rag_context": item.rag_context,
    }


async def get_user(user_id: int) -> User | None:
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        if user and refresh_user_windows(user):
            await session.commit()
            await session.refresh(user)
        return user


async def get_user_by_username(username: str) -> User | None:
    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()


async def create_user(*, username: str, email: str, hashed_password: str) -> User:
    async with async_session_maker() as session:
        user = User(
            username=username,
            email=email,
            hashed_password=hashed_password,
            role="employee",
            is_root_admin=False,
            is_active=True,
            five_hour_window_started_at=utcnow(),
            weekly_window_started_at=utcnow(),
        )
        session.add(user)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise
        await session.refresh(user)
        return user


async def list_users() -> list[User]:
    async with async_session_maker() as session:
        result = await session.execute(select(User).order_by(User.id))
        users = list(result.scalars().all())
        changed = False
        for user in users:
            changed = refresh_user_windows(user) or changed
        if changed:
            await session.commit()
            for user in users:
                await session.refresh(user)
        return users


async def update_user_fields(user_id: int, changes: dict[str, Any]) -> User | None:
    async with async_session_maker() as session:
        user = await session.get(User, user_id, with_for_update=True)
        if user is None:
            return None
        for field, value in changes.items():
            setattr(user, field, value)
        await session.commit()
        await session.refresh(user)
        return user


async def reset_user_usage(user_id: int, scope: str) -> User | None:
    async with async_session_maker() as session:
        user = await session.get(User, user_id, with_for_update=True)
        if user is None:
            return None
        now = utcnow()
        if scope in {"five_hour", "all"}:
            user.five_hour_tokens_used = 0
            user.five_hour_window_started_at = now
        if scope in {"weekly", "all"}:
            user.weekly_tokens_used = 0
            user.weekly_window_started_at = now
        await session.commit()
        await session.refresh(user)
        return user


async def quota_state(user_id: int) -> tuple[User | None, int | None]:
    """Return the fresh user and Retry-After seconds when a quota is exhausted."""
    async with async_session_maker() as session:
        user = await session.get(User, user_id, with_for_update=True)
        if user is None:
            return None, None
        now = utcnow()
        changed = refresh_user_windows(user, now)
        retry_after: int | None = None
        if (
            user.five_hour_token_limit is not None
            and user.five_hour_tokens_used >= user.five_hour_token_limit
        ):
            retry_after = max(
                1,
                int(
                    (
                        user.five_hour_window_started_at + FIVE_HOURS - now
                    ).total_seconds()
                ),
            )
        if (
            user.weekly_token_limit is not None
            and user.weekly_tokens_used >= user.weekly_token_limit
        ):
            weekly_retry = max(
                1,
                int(
                    (
                        user.weekly_window_started_at + ONE_WEEK - now
                    ).total_seconds()
                ),
            )
            retry_after = (
                weekly_retry if retry_after is None else max(retry_after, weekly_retry)
            )
        if changed:
            await session.commit()
            await session.refresh(user)
        return user, retry_after


async def record_token_usage(user_id: int, usage: dict[str, Any]) -> None:
    prompt = max(0, int(usage.get("prompt_tokens") or 0))
    completion = max(0, int(usage.get("completion_tokens") or 0))
    total = max(0, int(usage.get("total_tokens") or prompt + completion))
    async with async_session_maker() as session:
        user = await session.get(User, user_id, with_for_update=True)
        if user is None:
            return
        refresh_user_windows(user)
        user.input_tokens_used += prompt
        user.output_tokens_used += completion
        user.total_tokens_used += total
        user.five_hour_tokens_used += total
        user.weekly_tokens_used += total
        await session.commit()


async def list_conversations(user_id: int) -> list[Conversation]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())


async def create_conversation_record(
    *,
    user_id: int,
    title: str,
    model_name: str,
    knowledge_base_id: int | None,
    rag_enabled: bool,
    retrieval_mode: str,
    max_retrieval_tokens: int,
) -> Conversation:
    async with async_session_maker() as session:
        item = Conversation(
            user_id=user_id,
            title=title,
            model_name=model_name,
            knowledge_base_id=knowledge_base_id,
            rag_enabled=rag_enabled,
            retrieval_mode=retrieval_mode,
            max_retrieval_tokens=max_retrieval_tokens,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


async def get_owned_conversation(
    conversation_id: int, user_id: int
) -> Conversation | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()


async def update_owned_conversation(
    conversation_id: int, user_id: int, changes: dict[str, Any]
) -> Conversation | None:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
            .with_for_update()
        )
        item = result.scalar_one_or_none()
        if item is None:
            return None
        for field, value in changes.items():
            setattr(item, field, value)
        item.updated_at = utcnow()
        await session.commit()
        await session.refresh(item)
        return item


async def delete_owned_conversation(conversation_id: int, user_id: int) -> bool:
    async with async_session_maker() as session:
        result = await session.execute(
            delete(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        await session.commit()
        return bool(result.rowcount)


async def list_messages(conversation_id: int) -> list[Message]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id)
        )
        return list(result.scalars().all())


async def add_message(
    *,
    conversation_id: int,
    role: str,
    content: str,
    rag_context: dict[str, Any] | None = None,
) -> Message:
    async with async_session_maker() as session:
        item = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            rag_context=rag_context,
        )
        session.add(item)
        conversation = await session.get(
            Conversation, conversation_id, with_for_update=True
        )
        if conversation is None:
            raise LookupError("会话不存在")
        conversation.updated_at = utcnow()
        await session.commit()
        await session.refresh(item)
        return item
