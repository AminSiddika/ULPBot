import enum
from datetime import datetime, timezone
from typing import Any

from src.database.engine import get_db
from src.utils.logger import logger


class UserRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    USER = "user"


async def get_or_create_user(
    user_id: int,
    username: str | None,
    first_name: str,
) -> dict[str, Any]:
    db = get_db()
    doc = await db.users.find_one({"user_id": user_id})

    if doc is None:
        doc = {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "role": UserRole.USER.value,
            "is_banned": False,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        await db.users.insert_one(doc)
        return doc

    if doc.get("username") != username or doc.get("first_name") != first_name:
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "username": username,
                "first_name": first_name,
                "updated_at": datetime.now(timezone.utc),
            }},
        )
        doc["username"] = username
        doc["first_name"] = first_name

    return doc


async def is_admin(user: dict[str, Any], owner_id: int, admin_ids: set[int]) -> bool:
    db = get_db()
    if user["user_id"] == owner_id:
        if user.get("role") != UserRole.OWNER.value:
            await db.users.update_one(
                {"user_id": user["user_id"]},
                {"$set": {"role": UserRole.OWNER.value}},
            )
        return True
    if user["user_id"] in admin_ids:
        if user.get("role") != UserRole.ADMIN.value:
            await db.users.update_one(
                {"user_id": user["user_id"]},
                {"$set": {"role": UserRole.ADMIN.value}},
            )
        return True
    return False


async def ban_user(user_id: int) -> bool:
    db = get_db()
    result = await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"is_banned": True, "updated_at": datetime.now(timezone.utc)}},
    )
    return result.modified_count > 0


async def unban_user(user_id: int) -> bool:
    db = get_db()
    result = await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"is_banned": False, "updated_at": datetime.now(timezone.utc)}},
    )
    return result.modified_count > 0


async def is_banned(user_id: int) -> bool:
    db = get_db()
    doc = await db.users.find_one({"user_id": user_id, "is_banned": True})
    return doc is not None


async def get_all_user_ids(skip_banned: bool = True) -> list[int]:
    db = get_db()
    query: dict[str, Any] = {}
    if skip_banned:
        query["is_banned"] = {"$ne": True}
    cursor = db.users.find(query, {"user_id": 1})
    return [doc["user_id"] async for doc in cursor]


async def get_users_page(page: int = 0, per_page: int = 10) -> tuple[list[dict[str, Any]], int]:
    db = get_db()
    total = await db.users.count_documents({})
    cursor = db.users.find().sort("created_at", -1).skip(page * per_page).limit(per_page)
    users = [doc async for doc in cursor]
    return users, total


async def set_user_role(user_id: int, role: UserRole) -> bool:
    db = get_db()
    result = await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"role": role.value, "updated_at": datetime.now(timezone.utc)}},
    )
    return result.modified_count > 0
