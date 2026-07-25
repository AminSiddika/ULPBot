import os
import re
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.config import settings
from src.database.engine import get_db
from src.database.repos.log import get_stats
from src.database.repos.user import get_or_create_user, is_admin
from src.utils.logger import logger

router = Router()

ITEMS_PER_PAGE = 8


async def _check_admin(message: types.Message) -> bool:
    user_doc = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    admin = await is_admin(user_doc, settings.owner_id, settings.admin_ids_set)
    if not admin:
        await message.answer("⛔ You are not authorized to use this command.")
        return False
    return True


@router.message(Command("add"))
async def cmd_add(message: types.Message) -> None:
    if not await _check_admin(message):
        return

    if not message.reply_to_message or not message.reply_to_message.document:
        await message.answer(
            "📤 <b>Usage:</b> Reply to a .txt file with /add to upload it as a database.\n\n"
            "Supported: .txt files with one ULP record per line."
        )
        return

    doc = message.reply_to_message.document
    if not doc.file_name or not doc.file_name.endswith(".txt"):
        await message.answer("❌ Only <b>.txt</b> files are accepted.")
        return

    progress_msg = await message.answer(f"📥 Downloading <b>{doc.file_name}</b>...")

    file_obj = await message.bot.get_file(doc.file_id)
    dest_path = Path(settings.data_dir) / doc.file_name

    await message.bot.download_file(file_obj.file_path, str(dest_path))
    file_size = dest_path.stat().st_size

    from src.services.cache import cache_delete
    await cache_delete("search:*")

    await progress_msg.edit_text(
        f"✅ Database added: <b>{doc.file_name}</b>\n"
        f"Size: <b>{_format_size(file_size)}</b>\n"
        f"Path: <code>data/{doc.file_name}</code>\n\n"
        f"ℹ️ Search cache cleared.",
    )
    logger.info(f"Admin {message.from_user.id} added DB: {doc.file_name} ({file_size} bytes)")


@router.message(Command("files"))
async def cmd_files(message: types.Message, command: CommandObject) -> None:
    if not await _check_admin(message):
        return

    page = 0
    args = command.args
    if args:
        try:
            page = max(0, int(args.strip()))
        except ValueError:
            pass

    data_path = Path(settings.data_dir)
    files: list[Path] = sorted(data_path.glob("*.txt"))

    if not files:
        await message.answer("📭 No database files found in <code>data/</code>.")
        return

    total_pages = (len(files) - 1) // ITEMS_PER_PAGE
    page = min(page, total_pages)

    start = page * ITEMS_PER_PAGE
    chunk = files[start : start + ITEMS_PER_PAGE]

    lines = [f"📁 <b>Database Files</b> (page {page + 1}/{total_pages + 1})\n"]
    for i, fp in enumerate(chunk, 1):
        size = fp.stat().st_size
        lines.append(f"{start + i}. <code>{fp.name}</code> — {_format_size(size)}")

    builder = InlineKeyboardBuilder()
    for fp in chunk:
        builder.button(text=f"🗑 {fp.name[:20]}", callback_data=f"db_del:{fp.name}")
    builder.adjust(1)

    nav_builder = InlineKeyboardBuilder()
    if page > 0:
        nav_builder.button(text="⬅️ Prev", callback_data=f"files_pg:{page - 1}")
    if page < total_pages:
        nav_builder.button(text="Next ➡️", callback_data=f"files_pg:{page + 1}")
    nav_builder.adjust(2)

    await message.answer("\n".join(lines), reply_markup=builder.as_markup())
    if nav_builder._buttons:
        await message.answer("Navigate:", reply_markup=nav_builder.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("files_pg:"))
async def on_files_page(callback: types.CallbackQuery) -> None:
    page = int(callback.data.split(":")[1])

    data_path = Path(settings.data_dir)
    files: list[Path] = sorted(data_path.glob("*.txt"))
    total_pages = (len(files) - 1) // ITEMS_PER_PAGE
    page = min(max(page, 0), total_pages)

    start = page * ITEMS_PER_PAGE
    chunk = files[start : start + ITEMS_PER_PAGE]

    lines = [f"📁 <b>Database Files</b> (page {page + 1}/{total_pages + 1})\n"]
    for i, fp in enumerate(chunk, 1):
        size = fp.stat().st_size
        lines.append(f"{start + i}. <code>{fp.name}</code> — {_format_size(size)}")

    builder = InlineKeyboardBuilder()
    for fp in chunk:
        builder.button(text=f"🗑 {fp.name[:20]}", callback_data=f"db_del:{fp.name}")
    builder.adjust(1)

    nav_builder = InlineKeyboardBuilder()
    if page > 0:
        nav_builder.button(text="⬅️ Prev", callback_data=f"files_pg:{page - 1}")
    if page < total_pages:
        nav_builder.button(text="Next ➡️", callback_data=f"files_pg:{page + 1}")
    nav_builder.adjust(2)

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
    if nav_builder._buttons:
        await callback.message.answer("Navigate:", reply_markup=nav_builder.as_markup())
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("db_del:"))
async def on_delete_file(callback: types.CallbackQuery) -> None:
    filename = callback.data.split(":", 1)[1]
    filepath = Path(settings.data_dir) / filename

    if not filepath.exists():
        await callback.answer("File not found", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Yes, Delete", callback_data=f"db_del_confirm:{filename}")
    builder.button(text="❌ Cancel", callback_data="db_del_cancel")
    builder.adjust(2)

    await callback.message.edit_text(
        f"⚠️ <b>Confirm Delete</b>\n\nFile: <code>{filename}</code>\nSize: <b>{_format_size(filepath.stat().st_size)}</b>\n\nThis action <b>cannot</b> be undone.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("db_del_confirm:"))
async def on_delete_confirm(callback: types.CallbackQuery) -> None:
    filename = callback.data.split(":", 1)[1]
    filepath = Path(settings.data_dir) / filename

    if not filepath.exists():
        await callback.answer("File already deleted", show_alert=True)
        await callback.message.delete()
        return

    size = filepath.stat().st_size
    filepath.unlink()

    from src.services.cache import cache_delete
    await cache_delete("search:*")

    await callback.message.edit_text(
        f"✅ Deleted: <code>{filename}</code> ({_format_size(size)})\nℹ️ Search cache cleared."
    )
    await callback.answer("Deleted", show_alert=True)
    logger.info(f"Admin {callback.from_user.id} deleted DB: {filename}")


@router.callback_query(lambda c: c.data == "db_del_cancel")
async def on_delete_cancel(callback: types.CallbackQuery) -> None:
    await callback.message.delete()
    await callback.answer("Cancelled")


@router.message(Command("clean"))
async def cmd_clean(message: types.Message) -> None:
    if not await _check_admin(message):
        return

    data_path = Path(settings.data_dir)
    files = list(data_path.glob("*.txt"))
    total_size = sum(f.stat().st_size for f in files)

    dl_path = Path(settings.downloads_dir)
    dl_files = list(dl_path.glob("*"))
    dl_size = sum(f.stat().st_size for f in dl_files if f.is_file())

    text = (
        f"🧹 <b>Database Stats</b>\n\n"
        f"📁 Files: <b>{len(files)}</b>\n"
        f"💾 Total size: <b>{_format_size(total_size)}</b>\n"
        f"📂 Downloads: <b>{len(dl_files)} items</b> ({_format_size(dl_size)})\n\n"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Clean Downloads", callback_data="clean_dl")
    if files:
        builder.button(text="📋 List All DBs", callback_data="clean_list")
    builder.adjust(1)

    await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(lambda c: c.data == "clean_dl")
async def on_clean_downloads(callback: types.CallbackQuery) -> None:
    if not await _check_admin(callback.message):
        await callback.answer("Unauthorized", show_alert=True)
        return

    dl_path = Path(settings.downloads_dir)
    count = 0
    for fp in dl_path.iterdir():
        if fp.is_file():
            fp.unlink()
            count += 1

    await callback.answer(f"Cleaned {count} files", show_alert=True)
    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ Downloads folder cleaned ({count} files removed)."
    )
    logger.info(f"Admin {callback.from_user.id} cleaned downloads: {count} files")


@router.callback_query(lambda c: c.data == "clean_list")
async def on_clean_list(callback: types.CallbackQuery) -> None:
    data_path = Path(settings.data_dir)
    files = sorted(data_path.glob("*.txt"))

    lines = ["📋 <b>All Database Files:</b>\n"]
    for i, fp in enumerate(files, 1):
        size = fp.stat().st_size
        lines.append(f"{i}. <code>{fp.name}</code> — {_format_size(size)}")

    await callback.message.answer("\n".join(lines[:50]))
    await callback.answer()


@router.message(Command("merge"))
async def cmd_merge(message: types.Message) -> None:
    if not await _check_admin(message):
        return

    data_path = Path(settings.data_dir)
    files = sorted(data_path.glob("*.txt"))

    if len(files) < 2:
        await message.answer("⚠️ Need at least 2 database files to merge.")
        return

    progress_msg = await message.answer(f"🔀 Merging <b>{len(files)}</b> files...")

    import time
    seen: set[str] = set()
    total_lines = 0
    unique_lines = 0

    master_path = data_path / f"merged_{int(time.time())}.txt"

    with open(master_path, "w") as out:
        for fp in files:
            with open(fp, "r", errors="replace") as fh:
                for line in fh:
                    total_lines += 1
                    stripped = line.strip().lower()
                    if stripped and stripped not in seen:
                        seen.add(stripped)
                        out.write(line.strip() + "\n")
                        unique_lines += 1

    size = master_path.stat().st_size
    dupes = total_lines - unique_lines

    await progress_msg.edit_text(
        f"✅ <b>Merge Complete</b>\n\n"
        f"Files merged: <b>{len(files)}</b>\n"
        f"Total lines: <b>{total_lines}</b>\n"
        f"Unique lines: <b>{unique_lines}</b>\n"
        f"Duplicates removed: <b>{dupes}</b>\n"
        f"Output: <code>data/{master_path.name}</code>\n"
        f"Size: <b>{_format_size(size)}</b>\n\n"
        f"ℹ️ Search cache cleared."
    )

    from src.services.cache import cache_delete
    await cache_delete("search:*")


@router.message(Command("export"))
async def cmd_export(message: types.Message) -> None:
    if not await _check_admin(message):
        return

    import zipfile

    data_path = Path(settings.data_dir)
    files = sorted(data_path.glob("*.txt"))

    if not files:
        await message.answer("📭 No database files to export.")
        return

    progress_msg = await message.answer(f"📦 Packaging <b>{len(files)}</b> files...")

    zip_path = Path("/tmp/ulpbot_export.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in files:
            zf.write(fp, fp.name)

    zip_size = zip_path.stat().st_size

    if zip_size > 50 * 1024 * 1024:
        await progress_msg.edit_text(f"❌ Export too large ({_format_size(zip_size)}). Max: 50 MB. Consider /merge first.")
        zip_path.unlink()
        return

    await message.answer_document(
        FSInputFile(str(zip_path)),
        caption=(
            f"📦 <b>Database Export</b>\n"
            f"Files: <b>{len(files)}</b>\n"
            f"Total size: <b>{_format_size(sum(f.stat().st_size for f in files))}</b>\n"
            f"Compressed: <b>{_format_size(zip_size)}</b>"
        ),
    )

    zip_path.unlink()
    await progress_msg.delete()
    logger.info(f"Admin {message.from_user.id} exported {len(files)} DB files")


@router.message(Command("genkey"))
async def cmd_genkey(message: types.Message, command: CommandObject) -> None:
    if not await _check_admin(message):
        return

    arg = command.args.strip().lower() if command.args else ""
    if not arg:
        await message.answer(
            "🔑 <b>Generate Premium Keys</b>\n\n"
            "Usage: <code>/genkey [amount] [duration]</code>\n\n"
            "Duration formats:\n"
            "  <code>30min</code> — 30 minutes\n"
            "  <code>7d</code> — 7 days\n"
            "  <code>1m</code> — 1 month (30 days)\n"
            "  <code>1y</code> — 1 year (365 days)\n\n"
            "Examples:\n"
            "  <code>/genkey 10min</code> — single 10-min key\n"
            "  <code>/genkey 3 7d</code> — 3 keys, each 7 days\n"
            "  <code>/genkey 1m</code> — single 1-month key"
        )
        return

    args = arg.split()
    duration_str = args[-1]
    quantity = 1

    if len(args) >= 2 and args[0].isdigit():
        try:
            quantity = min(int(args[0]), 100)
            duration_str = args[1]
        except ValueError:
            pass

    duration_seconds = _parse_duration(duration_str)
    if duration_seconds is None or duration_seconds <= 0:
        await message.answer(f"❌ Invalid duration: <code>{duration_str}</code>\nUse: 30min, 7d, 1m, 1y")
        return

    keys = []
    db = get_db()
    now = datetime.now(timezone.utc)

    for _ in range(quantity):
        key = _generate_key()
        await db.premium_keys.insert_one({
            "key": key,
            "duration_seconds": duration_seconds,
            "used": False,
            "used_by": None,
            "used_at": None,
            "created_by": message.from_user.id,
            "created_at": now,
        })
        keys.append(key)

    duration_label = _format_duration(duration_seconds)
    if quantity == 1:
        lines = [
            f"🔑 <b>Premium Key Generated</b>\n",
            f"Key: <code>{keys[0]}</code>",
            f"Duration: <b>{duration_label}</b>",
            f"\nRedeem: <code>/redeem {keys[0]}</code>",
        ]
    else:
        lines = [f"🔑 <b>{quantity} Premium Keys Generated</b>\n"]
        lines.append(f"Duration each: <b>{duration_label}</b>\n")
        for i, k in enumerate(keys, 1):
            lines.append(f"{i}. <code>/redeem {k}</code>")
        if len(lines) > 30:
            lines = lines[:30] + [f"\n... and {quantity - 30} more"]

    await message.answer("\n".join(lines))
    logger.info(f"Admin {message.from_user.id} generated {quantity} premium key(s) for {duration_label}")


@router.message(Command("keys"))
async def cmd_keys(message: types.Message) -> None:
    if not await _check_admin(message):
        return

    db = get_db()
    total = await db.premium_keys.count_documents({})
    unused_count = await db.premium_keys.count_documents({"used": False})
    used_count = total - unused_count

    cursor = db.premium_keys.find().sort("created_at", -1).limit(20)
    keys_list = [doc async for doc in cursor]

    lines = [
        f"🔑 <b>Premium Keys</b>\n",
        f"Total: {total} | Unused: <b>{unused_count}</b> | Used: {used_count}\n",
    ]

    for k in keys_list:
        used = "✅" if k.get("used") else "⏳"
        dur = _format_duration(k.get("duration_seconds", 0))
        uid = f" | user: {k['used_by']}" if k.get("used_by") else ""
        lines.append(f"{used} <code>{k['key']}</code> — {dur}{uid}")

    if len(lines) > 25:
        lines = lines[:25] + [f"\n... showing last 20 of {total} keys"]
    await message.answer("\n".join(lines))


@router.message(Command("premium_users"))
async def cmd_premium_users(message: types.Message) -> None:
    if not await _check_admin(message):
        return

    db = get_db()
    from datetime import timezone as tz
    now = __import__("datetime").datetime.now(tz.utc)
    cursor = db.users.find({"is_premium": True}).sort("premium_expiry", 1).limit(30)
    users = [doc async for doc in cursor]

    if not users:
        await message.answer("📭 No premium users found.")
        return

    lines = [f"⭐ <b>Premium Users</b> ({len(users)})\n"]
    for u in users:
        uid = u.get("user_id", "—")
        name = u.get("first_name", "Unknown")
        exp = u.get("premium_expiry")
        if isinstance(exp, __import__("datetime").datetime):
            if exp < now:
                lines.append(f"❌ <code>{uid}</code> {name} — <b>EXPIRED</b>")
            else:
                days = (exp - now).days
                lines.append(f"⭐ <code>{uid}</code> {name} — {exp.strftime('%Y-%m-%d')} ({days}d left)")
        else:
            lines.append(f"⭐ <code>{uid}</code> {name} — no expiry")

    if len(lines) > 30:
        lines = lines[:30] + [f"\n... and {len(users) - 30} more"]
    await message.answer("\n".join(lines))


@router.message(Command("reset"))
async def cmd_reset(message: types.Message, command: CommandObject) -> None:
    if not await _check_admin(message):
        return

    target_id = None
    if command.args and command.args.strip().isdigit():
        target_id = int(command.args.strip())
    elif message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id

    if target_id is None:
        await message.answer("⚠️ Usage: <code>/reset user_id</code> or reply to a user's message.")
        return

    db = get_db()
    result = await db.users.update_one(
        {"user_id": target_id},
        {"$set": {"search_count": 0, "updated_at": __import__("datetime").datetime.now(timezone.utc)}},
    )
    if result.modified_count:
        await message.answer(f"✅ Search count reset for user <code>{target_id}</code>.")
        logger.info(f"Admin {message.from_user.id} reset search count for user {target_id}")
    else:
        await message.answer(f"⚠️ User <code>{target_id}</code> not found.")


@router.message(Command("stats"))
async def cmd_stats(message: types.Message) -> None:
    if not await _check_admin(message):
        return

    stats = await get_stats()

    lines = [
        "📊 <b>Bot Statistics</b>\n",
        f"👥 Registered users: <b>{stats['total_users']}</b>",
        f"🔍 Total queries: <b>{stats['total_queries']}</b>",
    ]
    if stats["top_commands"]:
        lines.append("\n📈 <b>Top Commands:</b>")
        for cmd, cnt in stats["top_commands"]:
            lines.append(f"  /{cmd} — <b>{cnt}</b>")

    await message.answer("\n".join(lines))


def _generate_key(length: int = 16) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "ULP-" + "-".join(
        "".join(secrets.choice(alphabet) for _ in range(4))
        for _ in range(length // 4)
    )


def _parse_duration(s: str) -> int | None:
    s = s.strip().lower()
    match = re.match(r"^(\d+)\s*(min|d|day|days|m|month|months|y|year|years)$", s)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    match unit:
        case "min":
            return value * 60
        case "d" | "day" | "days":
            return value * 86400
        case "m" | "month" | "months":
            return value * 30 * 86400
        case "y" | "year" | "years":
            return value * 365 * 86400
    return None


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
    return " ".join(parts) if parts else f"{seconds}s"


def _format_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"
