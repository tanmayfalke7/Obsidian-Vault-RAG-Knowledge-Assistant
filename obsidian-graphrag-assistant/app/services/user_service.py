"""User CRUD operations."""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import User, AccessRequest
from app.core.security import hash_password, verify_password


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    result = await db.execute(
        select(User)
        .options(selectinload(User.documents), selectinload(User.folders))
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username.lower()))
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    email: str,
    username: str,
    full_name: str,
    password: str,
    is_admin: bool = False,
) -> User:
    user = User(
        email=email.lower().strip(),
        username=username.lower().strip(),
        full_name=full_name.strip(),
        hashed_password=hash_password(password),
        is_admin=is_admin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    user = await get_user_by_email(db, email)
    if user is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def increment_query_count(db: AsyncSession, user: User) -> User:
    user.ai_queries_used += 1
    await db.commit()
    await db.refresh(user)
    return user


async def update_user_limits(
    db: AsyncSession,
    user: User,
    max_documents: int | None = None,
    max_ai_queries: int | None = None,
) -> User:
    if max_documents is not None:
        user.max_documents = max_documents
    if max_ai_queries is not None:
        user.max_ai_queries = max_ai_queries
    await db.commit()
    await db.refresh(user)
    return user


async def get_all_users(db: AsyncSession) -> list[User]:
    result = await db.execute(
        select(User)
        .options(selectinload(User.documents))
        .order_by(User.created_at.desc())
    )
    return list(result.scalars().all())


async def get_pending_access_requests(db: AsyncSession) -> list[AccessRequest]:
    result = await db.execute(
        select(AccessRequest)
        .options(selectinload(AccessRequest.user))
        .where(AccessRequest.status == "pending")
        .order_by(AccessRequest.created_at.desc())
    )
    return list(result.scalars().all())


async def create_access_request(
    db: AsyncSession,
    user: User,
    request_type: str,
    requested_amount: int,
    reason: str | None,
) -> AccessRequest:
    req = AccessRequest(
        user_id=user.id,
        request_type=request_type,
        requested_amount=requested_amount,
        reason=reason,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req


async def resolve_access_request(
    db: AsyncSession,
    request_id: str,
    status: str,  # "approved" | "rejected"
    admin_note: str | None,
    resolved_by: str,
) -> AccessRequest | None:
    from datetime import datetime, timezone
    result = await db.execute(
        select(AccessRequest)
        .options(selectinload(AccessRequest.user))
        .where(AccessRequest.id == request_id)
    )
    req = result.scalar_one_or_none()
    if req is None:
        return None

    req.status = status
    req.admin_note = admin_note
    req.resolved_by = resolved_by
    req.resolved_at = datetime.now(timezone.utc)

    # If approved, update user limits
    if status == "approved":
        if req.request_type == "more_queries":
            req.user.max_ai_queries += req.requested_amount
        elif req.request_type == "more_documents":
            req.user.max_documents += req.requested_amount

    await db.commit()
    await db.refresh(req)
    return req


async def update_profile(
    db: AsyncSession,
    user: User,
    full_name: str | None = None,
    new_password: str | None = None,
) -> User:
    if full_name:
        user.full_name = full_name.strip()
    if new_password:
        user.hashed_password = hash_password(new_password)
    await db.commit()
    await db.refresh(user)
    return user
