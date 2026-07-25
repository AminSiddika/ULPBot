import secrets
import string
from datetime import datetime, timedelta, timezone

from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config import settings
from src.database.engine import get_db
from src.database.repos.user import (
    FREE_SEARCH_LIMIT,
    get_or_create_user,
    get_user,
    is_admin,
    is_premium,
    is_registered,
    register_user,
    set_premium,
)
from src.utils.logger import logger

router = Router()

FREE_SEARCH_LIMIT_CONST = 10


@router.message(Command("register"))
async def cmd_register(message: types.Message) -> None:
    user_id = message.from_user.id

    db = get_db()
    doc = await db.users.find_one({"user_id": user_id})
    if doc and doc.get("is_registered"):
        await message.answer("✅ You are already registered!\nUse /userinfo to check your status.")
        return

    await register_user(user_id)

    builder = InlineKeyboardBuilder()
    builder.button(text="📋 User Info", callback_data="userinfo")

    await message.answer(
        "✅ <b>Registration Successful!</b>\n\n"
        f"🎁 You have <b>{FREE_SEARCH_LIMIT_CONST} free searches</b>.\n"
        f"🔑 Use /redeem to upgrade to premium.\n"
        f"ℹ️ /userinfo to check your usage.",
        reply_markup=builder.as_markup(),
    )
    logger.info(f"User {user_id} registered")


@router.message(Command("redeem"))
async def cmd_redeem(message: types.Message, command: CommandObject) -> None:
    user_id = message.from_user.id

    key = command.args.strip() if command.args else ""
    if not key:
        await message.answer("⚠️ Usage: <code>/redeem KEY</code>\n\nRedeem a premium key to unlock unlimited searches.")
        return

    doc = await get_user(user_id)
    if not doc or not doc.get("is_registered"):
        await message.answer("⚠️ You must /register first.")
        return

    db = get_db()
    key_doc = await db.premium_keys.find_one({"key": key.upper(), "used": False})

    if key_doc is None:
        await message.answer("❌ Invalid or already used key.")
        return

    duration_seconds = key_doc.get("duration_seconds", 0)
    duration = timedelta(seconds=duration_seconds)

    await set_premium(user_id, duration)
    await db.premium_keys.update_one(
        {"key": key.upper()},
        {"$set": {"used": True, "used_by": user_id, "used_at": datetime.now(timezone.utc)}},
    )

    expiry = datetime.now(timezone.utc) + duration
    await message.answer(
        f"🎉 <b>Premium Activated!</b>\n\n"
        f"Expires: <b>{expiry.strftime('%Y-%m-%d %H:%M UTC')}</b>\n"
        f"Duration: <b>{_format_duration(duration_seconds)}</b>\n\n"
        f"Enjoy unlimited searches!"
    )
    logger.info(f"User {user_id} redeemed key {key} for {_format_duration(duration_seconds)}")


@router.message(Command("userinfo"))
async def cmd_userinfo(message: types.Message) -> None:
    user_id = message.from_user.id

    doc = await get_user(user_id)
    if doc is None:
        await message.answer("⚠️ Use /start first, then /register.")
        return

    registered = doc.get("is_registered", False)
    premium = await is_premium(user_id)
    search_count = doc.get("search_count", 0)
    created = doc.get("created_at")
    premium_expiry = doc.get("premium_expiry")
    role = doc.get("role", "user")

    lines = [f"👤 <b>User Info</b>\n"]
    lines.append(f"ID: <code>{user_id}</code>")
    lines.append(f"Role: <b>{role.upper()}</b>")

    if registered:
        lines.append(f"Registered: ✅")
        reg_time = doc.get("registered_at")
        if reg_time:
            lines.append(f"Since: {_format_ts(reg_time)}")
    else:
        lines.append(f"Registered: ❌ (use /register)")

    if premium:
        lines.append(f"Premium: ⭐ <b>ACTIVE</b>")
        if premium_expiry:
            lines.append(f"Expires: {_format_ts(premium_expiry)}")
    else:
        remaining = max(0, FREE_SEARCH_LIMIT_CONST - search_count)
        lines.append(f"Premium: ❌")
        lines.append(f"Free searches: <b>{remaining}/{FREE_SEARCH_LIMIT_CONST}</b>")
        if remaining == 0:
            lines.append(f"\n⚠️ <b>Limit reached!</b> Use /redeem to upgrade.")

    if created:
        lines.append(f"Joined: {_format_ts(created)}")

    await message.answer("\n".join(lines))


@router.callback_query(lambda c: c.data == "userinfo")
async def on_userinfo_callback(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id
    doc = await get_user(user_id)
    if doc is None:
        await callback.answer("Register first with /register", show_alert=True)
        return

    premium = await is_premium(user_id)
    search_count = doc.get("search_count", 0)
    premium_expiry = doc.get("premium_expiry")

    lines = [f"👤 <b>User Info</b>\n"]
    lines.append(f"ID: <code>{user_id}</code>")
    if premium:
        lines.append(f"Premium: ⭐ ACTIVE")
        if premium_expiry:
            lines.append(f"Expires: {_format_ts(premium_expiry)}")
    else:
        remaining = max(0, FREE_SEARCH_LIMIT_CONST - search_count)
        lines.append(f"Free searches: <b>{remaining}/{FREE_SEARCH_LIMIT_CONST}</b>")
        if remaining == 0:
            lines.append(f"\n⚠️ Limit reached. /redeem to upgrade.")

    await callback.message.edit_text("\n".join(lines))
    await callback.answer()


def _format_duration(seconds: int) -> str:
    if seconds < 120:
        return f"{seconds}s"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    mins = (seconds % 3600) // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    secs = seconds % 60
    if secs and not days:
        parts.append(f"{secs}s")
    return " ".join(parts) if parts else f"{seconds}s"


def _format_ts(ts) -> str:
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M UTC")
    return str(ts)
