from datetime import datetime, timezone

from src.database.engine import get_db


async def log_usage(
    user_id: int,
    command: str,
    keyword: str | None = None,
    result_count: int = 0,
) -> None:
    db = get_db()
    await db.usage_logs.insert_one({
        "user_id": user_id,
        "command": command,
        "keyword": keyword,
        "result_count": result_count,
        "created_at": datetime.now(timezone.utc),
    })


async def get_stats() -> dict:
    db = get_db()
    total_users = await db.users.count_documents({})
    total_queries = await db.usage_logs.count_documents({})

    pipeline = [
        {"$group": {"_id": "$command", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    top_commands = await db.usage_logs.aggregate(pipeline).to_list(5)

    return {
        "total_users": total_users,
        "total_queries": total_queries,
        "top_commands": [(doc["_id"], doc["count"]) for doc in top_commands],
    }


async def get_user_history(
    user_id: int,
    limit: int = 20,
    command: str | None = None,
) -> list[dict]:
    db = get_db()
    query: dict = {"user_id": user_id}
    if command:
        query["command"] = command
    cursor = (
        db.usage_logs.find(query, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    return [doc async for doc in cursor]


async def clear_user_history(user_id: int) -> int:
    db = get_db()
    result = await db.usage_logs.delete_many({"user_id": user_id})
    return result.deleted_count
