import asyncio
import math
from datetime import datetime

from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config import settings
from src.database.repos.user import (
    UserRole,
    ban_user,
    get_all_user_ids,
    get_or_create_user,
    get_users_page,
    is_admin,
    set_user_role,
    unban_user,
)
from src.utils.logger import logger

router = Router()

PER_PAGE = 10
BROADCAST_BATCH = 30
BROADCAST_DELAY = 0.05


async def _check_admin(message: types.Message) -> bool:
    user_doc = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    admin = await is_admin(user_doc, settings.owner_id, settings.admin_ids_set)
    if not admin:
        await message.answer("⛔ You are not authorized.")
        return False
    return True


@router.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message) -> None:
    if not await _check_admin(message):
        return

    if not message.reply_to_message or not message.reply_to_message.text:
        await message.answer(
            "📢 <b>Usage:</b> Reply to a message with <code>/broadcast</code> to send it to all users.\n\n"
            "Optional: <code>/broadcast pinned</code> to send without notification."
        )
        return

    args = message.text.split()
    silent = "pinned" in args or "silent" in args

    reply = message.reply_to_message
    user_ids = await get_all_user_ids(skip_banned=True)
    total = len(user_ids)

    if total == 0:
        await message.answer("📭 No users registered.")
        return

    status_msg = await message.answer(f"📢 Broadcasting to <b>{total}</b> users...\nProgress: 0/{total}")

    sent = 0
    failed = 0

    for i in range(0, total, BROADCAST_BATCH):
        batch = user_ids[i : i + BROADCAST_BATCH]
        tasks = [
            _safe_send(message.bot, uid, reply, disable_notification=silent)
            for uid in batch
        ]
        results = await asyncio.gather(*tasks)
        sent += sum(1 for r in results if r)
        failed += sum(1 for r in results if not r)

        if i + BROADCAST_BATCH < total:
            progress = min(i + BROADCAST_BATCH, total)
            try:
                await status_msg.edit_text(
                    f"📢 Broadcasting to <b>{total}</b> users...\nProgress: {progress}/{total}"
                )
            except Exception:
                pass
            await asyncio.sleep(BROADCAST_DELAY)

    await status_msg.edit_text(
        f"✅ Broadcast complete\n"
        f"Total: <b>{total}</b>\n"
        f"Sent: <b>{sent}</b>\n"
        f"Failed: <b>{failed}</b>"
    )
    logger.info(f"Admin {message.from_user.id} broadcast to {sent}/{total} users")


async def _safe_send(bot, user_id: int, msg: types.Message, **kwargs) -> bool:
    try:
        await msg.copy_to(chat_id=user_id, **kwargs)
        return True
    except Exception:
        return False


@router.message(Command("ban"))
async def cmd_ban(message: types.Message, command: CommandObject) -> None:
    if not await _check_admin(message):
        return

    target_id = await _resolve_user_id(message, command)
    if target_id is None:
        return

    if target_id == settings.owner_id:
        await message.answer("⛔ Cannot ban the owner.")
        return

    if await ban_user(target_id):
        await message.answer(f"🚫 User <code>{target_id}</code> has been <b>banned</b>.")
        logger.info(f"Admin {message.from_user.id} banned user {target_id}")
    else:
        await message.answer(f"⚠️ User <code>{target_id}</code> not found.")


@router.message(Command("unban"))
async def cmd_unban(message: types.Message, command: CommandObject) -> None:
    if not await _check_admin(message):
        return

    target_id = await _resolve_user_id(message, command)
    if target_id is None:
        return

    if await unban_user(target_id):
        await message.answer(f"✅ User <code>{target_id}</code> has been <b>unbanned</b>.")
        logger.info(f"Admin {message.from_user.id} unbanned user {target_id}")
    else:
        await message.answer(f"⚠️ User <code>{target_id}</code> not found.")


@router.message(Command("promote"))
async def cmd_promote(message: types.Message, command: CommandObject) -> None:
    if message.from_user.id != settings.owner_id:
        await message.answer("⛔ Only the bot owner can promote users.")
        return

    target_id = await _resolve_user_id(message, command)
    if target_id is None:
        return

    if await set_user_role(target_id, UserRole.ADMIN):
        await message.answer(f"⭐ User <code>{target_id}</code> promoted to <b>admin</b>.")
        logger.info(f"Owner promoted user {target_id} to admin")
    else:
        await message.answer(f"⚠️ User <code>{target_id}</code> not found.")


@router.message(Command("demote"))
async def cmd_demote(message: types.Message, command: CommandObject) -> None:
    if message.from_user.id != settings.owner_id:
        await message.answer("⛔ Only the bot owner can demote users.")
        return

    target_id = await _resolve_user_id(message, command)
    if target_id is None:
        return

    if await set_user_role(target_id, UserRole.USER):
        await message.answer(f"⬇️ User <code>{target_id}</code> demoted to <b>user</b>.")
        logger.info(f"Owner demoted user {target_id} to user")
    else:
        await message.answer(f"⚠️ User <code>{target_id}</code> not found.")


@router.message(Command("users"))
async def cmd_users(message: types.Message, command: CommandObject) -> None:
    if not await _check_admin(message):
        return

    page = 0
    if command.args:
        try:
            page = max(0, int(command.args.strip()))
        except ValueError:
            pass

    users, total = await get_users_page(page=page, per_page=PER_PAGE)
    total_pages = max(1, math.ceil(total / PER_PAGE))
    page = min(page, total_pages - 1)

    lines = [f"👥 <b>Registered Users</b> (total: {total})\n"]
    lines.append(f"Page {page + 1}/{total_pages}\n")
    for u in users:
        name = u.get("first_name", "Unknown")
        uid = u.get("user_id", "—")
        role = u.get("role", "user")
        ban = "🚫" if u.get("is_banned") else ""
        lines.append(f"<code>{uid}</code> {name} [{role}] {ban}")

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Prev", callback_data=f"users_pg:{page - 1}")
    builder.button(text=f"📄 {page + 1}/{total_pages}", callback_data="users_noop")
    if page < total_pages - 1:
        builder.button(text="Next ➡️", callback_data=f"users_pg:{page + 1}")
    builder.adjust(3)

    await message.answer("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("users_pg:"))
async def on_users_page(callback: types.CallbackQuery) -> None:
    page = int(callback.data.split(":")[1])
    users, total = await get_users_page(page=page, per_page=PER_PAGE)
    total_pages = max(1, math.ceil(total / PER_PAGE))
    page = min(max(page, 0), total_pages - 1)

    lines = [f"👥 <b>Registered Users</b> (total: {total})\n"]
    lines.append(f"Page {page + 1}/{total_pages}\n")
    for u in users:
        name = u.get("first_name", "Unknown")
        uid = u.get("user_id", "—")
        role = u.get("role", "user")
        ban = "🚫" if u.get("is_banned") else ""
        lines.append(f"<code>{uid}</code> {name} [{role}] {ban}")

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Prev", callback_data=f"users_pg:{page - 1}")
    builder.button(text=f"📄 {page + 1}/{total_pages}", callback_data="users_noop")
    if page < total_pages - 1:
        builder.button(text="Next ➡️", callback_data=f"users_pg:{page + 1}")
    builder.adjust(3)

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
    await callback.answer()


async def _resolve_user_id(message: types.Message, command: CommandObject) -> int | None:
    if command.args and command.args.strip().isdigit():
        return int(command.args.strip())
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    await message.answer("⚠️ Usage: <code>/command user_id</code> or reply to a user's message.")
    return None
