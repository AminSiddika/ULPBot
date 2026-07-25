import asyncio
import os
import random

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.database.repos.log import log_usage
from src.services.cache import cache_get, cache_set, check_cooldown, check_rate_limit
from src.services.search import search_ulp

router = Router()

FORMATS = {
    "mail:pass": "mail_pass",
    "email:pass": "mail_pass",
    "user:pass": "user_pass",
    "number:pass": "number_pass",
    "raw": None,
}

MAX_RESULTS = 1000
MAX_RESPONSE_LENGTH = 3800
MAX_INLINE_LINES = 50
PAGE_SIZE = 30

SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _start_spinner(message: types.Message, text: str) -> asyncio.Task:
    async def spin():
        i = 0
        while True:
            try:
                await message.edit_text(f"{SPINNER[i % len(SPINNER)]} {text}")
                i += 1
                await asyncio.sleep(0.8)
            except Exception:
                break
    return asyncio.create_task(spin())


@router.message(Command("extract"))
async def cmd_extract(message: types.Message) -> None:
    user_id = message.from_user.id

    limited = await check_rate_limit(user_id, limit=15, window=60)
    if limited:
        await message.answer("⏳ Rate limit exceeded. Please wait a moment.")
        return

    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        await message.answer(
            "⚠️ Usage: <code>/extract [format] [keyword]</code>\n\n"
            "Formats: mail:pass, user:pass, number:pass, raw\n\n"
            "Example: <code>/extract mail:pass gmail.com</code>",
        )
        return

    fmt_key = parts[1].lower()
    keyword = parts[2].strip()

    if fmt_key not in FORMATS:
        await message.answer(f"❌ Unknown format: <b>{fmt_key}</b>\nValid: mail:pass, user:pass, number:pass, raw")
        return

    full_key = f"{fmt_key}:{keyword}"
    on_cooldown = await check_cooldown(user_id, full_key)
    if on_cooldown:
        await message.answer(f"⏳ You just searched <code>{fmt_key} {keyword}</code>. Wait 30s before repeating.")
        return

    format_type = FORMATS[fmt_key]
    cache_key = f"search:extract:{fmt_key}:{keyword.lower()}:{MAX_RESULTS}"

    cached = await cache_get(cache_key)
    if cached is not None:
        results, total = cached
        await _send_paginated(message, fmt_key, keyword, results, total, 0)
        await log_usage(user_id, "extract", full_key, len(results))
        return

    progress_msg = await message.answer(f"⠋ Extracting <b>{fmt_key}</b> for: <b>{keyword}</b>...")
    task = _start_spinner(progress_msg, f"Extracting <b>{fmt_key}</b> for: <b>{keyword}</b>")

    results, total = await search_ulp(keyword, max_results=MAX_RESULTS, format_type=format_type)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    if total == -1:
        await progress_msg.edit_text("❌ <b>ripgrep</b> not installed on server. Contact admin.")
        return

    if not results:
        await progress_msg.edit_text(f"❌ No {fmt_key} matches for: <b>{keyword}</b>")
        await log_usage(user_id, "extract", full_key, 0)
        return

    await cache_set(cache_key, (results, total), ttl=300)
    await log_usage(user_id, "extract", full_key, len(results))
    await _send_paginated(message, fmt_key, keyword, results, total, 0, edit_msg=progress_msg)


async def _send_paginated(
    message: types.Message,
    fmt_key: str,
    keyword: str,
    results: list[str],
    total: int,
    page: int = 0,
    edit_msg: types.Message | None = None,
) -> None:
    total_pages = max(1, (len(results) - 1) // PAGE_SIZE + 1)
    page = min(max(page, 0), total_pages - 1)
    start = page * PAGE_SIZE
    chunk = results[start : start + PAGE_SIZE]

    header = f"📤 Extracted <b>{fmt_key}</b> for: <b>{keyword}</b>\nTotal: {len(results)}/{total} · Page {page + 1}/{total_pages}\n<pre>"
    body = "\n".join(chunk)
    full_text = header + body + "</pre>"

    if len(full_text) > MAX_RESPONSE_LENGTH or len(results) > MAX_INLINE_LINES:
        await _send_as_file(message, fmt_key, keyword, results, total, edit_msg)
        return

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Prev", callback_data=f"ext_pg:{page-1}")
    builder.button(text=f"📄 {page+1}/{total_pages}", callback_data="ext_noop")
    if page < total_pages - 1:
        builder.button(text="Next ➡️", callback_data=f"ext_pg:{page+1}")
    builder.adjust(3)

    if edit_msg:
        await edit_msg.edit_text(full_text, reply_markup=builder.as_markup())
    else:
        await message.answer(full_text, reply_markup=builder.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("ext_pg:"))
async def on_extract_page(callback: types.CallbackQuery) -> None:
    page = int(callback.data.split(":")[1])
    text = callback.message.text or ""

    keyword = _extract_keyword_from_text(text)
    if keyword is None:
        await callback.answer("Cache expired. Please search again.", show_alert=True)
        return

    fmt_key = _extract_fmt_from_text(text)
    if fmt_key is None:
        await callback.answer("Cache expired. Please search again.", show_alert=True)
        return

    cache_key = f"search:extract:{fmt_key}:{keyword.lower()}:{MAX_RESULTS}"
    cached = await cache_get(cache_key)
    if cached is None:
        await callback.answer("Cache expired. Please search again.", show_alert=True)
        return

    results, total = cached

    total_pages = max(1, (len(results) - 1) // PAGE_SIZE + 1)
    page = min(max(page, 0), total_pages - 1)
    start = page * PAGE_SIZE
    chunk = results[start : start + PAGE_SIZE]

    header = f"📤 Extracted <b>{fmt_key}</b> for: <b>{keyword}</b>\nTotal: {len(results)}/{total} · Page {page + 1}/{total_pages}\n<pre>"
    body = "\n".join(chunk)
    full_text = header + body + "</pre>"

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Prev", callback_data=f"ext_pg:{page-1}")
    builder.button(text=f"📄 {page+1}/{total_pages}", callback_data="ext_noop")
    if page < total_pages - 1:
        builder.button(text="Next ➡️", callback_data=f"ext_pg:{page+1}")
    builder.adjust(3)

    await callback.message.edit_text(full_text, reply_markup=builder.as_markup())
    await callback.answer()


async def _send_as_file(
    message: types.Message,
    fmt_key: str,
    keyword: str,
    results: list[str],
    total: int,
    edit_msg: types.Message | None = None,
) -> None:
    filename = f"extract_{fmt_key.replace(':', '_')}_{keyword[:15].replace('/', '_')}_{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=6))}.txt"
    filepath = f"/tmp/{filename}"

    with open(filepath, "w") as f:
        f.write("\n".join(results))

    caption = f"📤 Extracted <b>{fmt_key}</b> for: <b>{keyword}</b>\nTotal: <b>{len(results)}/{total}</b>\n\n💾 Served as file (too large for inline display)."

    if edit_msg:
        await edit_msg.delete()

    await message.answer_document(FSInputFile(filepath), caption=caption)

    try:
        os.remove(filepath)
    except OSError:
        pass


def _extract_keyword_from_text(text: str) -> str | None:
    if "<b>" not in text or "</b>" not in text:
        return None
    parts = text.split("<b>")
    if len(parts) < 3:
        return None
    kw_part = parts[2]
    end = kw_part.index("</b>") if "</b>" in kw_part else None
    if end is None:
        return None
    return kw_part[:end].split("\n")[0].strip()


def _extract_fmt_from_text(text: str) -> str | None:
    if "<b>" not in text or "</b>" not in text:
        return None
    parts = text.split("<b>")
    if len(parts) < 2:
        return None
    fmt_part = parts[1]
    end = fmt_part.index("</b>") if "</b>" in fmt_part else None
    if end is None:
        return None
    return fmt_part[:end].strip()
