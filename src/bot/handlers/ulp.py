import asyncio
import json
import os
import random
import shlex
import time

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.database.repos.log import log_usage
from src.services.cache import (
    cache_get,
    cache_set,
    check_cooldown,
    check_rate_limit,
    get_redis,
    store_search_page,
)
from src.services.search import SORT_KEYS, search_ulp
from src.utils.logger import logger

router = Router()

MAX_RESULTS = 1000
MAX_RESPONSE_LENGTH = 3800
MAX_INLINE_LINES = 50
PAGE_SIZE = 30

SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

USAGE = (
    "⚠️ Usage: <code>/ulp keyword [--sort=KEY] [--file=name.txt]</code>\n\n"
    "Sort keys: url, login, password, domain, email, none\n"
    "Example: <code>/ulp outlook --sort=domain --file=db1.txt</code>"
)


def _parse_args(text: str) -> tuple[str, str | None, str | None]:
    keyword_parts: list[str] = []
    sort_by: str | None = None
    file_filter: str | None = None
    raw_parts = shlex.split(text)[1:] if len(shlex.split(text)) > 1 else []

    for part in raw_parts:
        if part.startswith("--sort="):
            val = part.split("=", 1)[1]
            if val in SORT_KEYS or val == "none":
                sort_by = val
        elif part.startswith("--file="):
            file_filter = part.split("=", 1)[1]
        else:
            keyword_parts.append(part)

    return " ".join(keyword_parts), sort_by, file_filter


async def _start_spinner(message: types.Message, text: str) -> asyncio.Task:
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


@router.message(Command("ulp"))
async def cmd_ulp(message: types.Message) -> None:
    user_id = message.from_user.id

    limited = await check_rate_limit(user_id, limit=15, window=60)
    if limited:
        await message.answer("⏳ Rate limit exceeded. Please wait a moment.")
        return

    keyword, sort_by, file_filter = _parse_args(message.text)
    if not keyword:
        await message.answer(USAGE)
        return

    on_cooldown = await check_cooldown(user_id, keyword)
    if on_cooldown:
        await message.answer(f"⏳ You just searched <code>{keyword}</code>. Wait 30s before repeating the same keyword.")
        return

    cache_key = f"search:ulp:{keyword.lower()}:{sort_by or 'none'}:{file_filter or 'all'}:{MAX_RESULTS}"

    cached = await cache_get(cache_key)
    if cached is not None:
        results, total = cached
        await _send_paginated(message, keyword, results, total, sort_by, file_filter, 0)
        await log_usage(user_id, "ulp", keyword, len(results))
        return

    spinner_label = f"Searching: <b>{keyword}</b>" + (f" (sorted: {sort_by})" if sort_by and sort_by != "none" else "") + (f" [file: {file_filter}]" if file_filter else "")
    progress_msg = await message.answer(f"🔍 {spinner_label}...")
    task = await _start_spinner(progress_msg, spinner_label)

    results, total = await search_ulp(
        keyword, max_results=MAX_RESULTS, sort_by=sort_by, file_filter=file_filter
    )

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    if total == -1:
        await progress_msg.edit_text("❌ <b>ripgrep</b> not installed on server. Contact admin.")
        return

    if not results:
        await progress_msg.edit_text(f"❌ No results for: <b>{keyword}</b>")
        await log_usage(user_id, "ulp", keyword, 0)
        return

    await cache_set(cache_key, (results, total), ttl=300)
    await log_usage(user_id, "ulp", keyword, len(results))
    await _send_paginated(message, keyword, results, total, sort_by, file_filter, 0, edit_msg=progress_msg)


async def _send_paginated(
    message: types.Message,
    keyword: str,
    results: list[str],
    total: int,
    sort_by: str | None = None,
    file_filter: str | None = None,
    page: int = 0,
    edit_msg: types.Message | None = None,
) -> None:
    total_pages = max(1, (len(results) - 1) // PAGE_SIZE + 1)
    page = min(max(page, 0), total_pages - 1)
    start = page * PAGE_SIZE
    chunk = results[start : start + PAGE_SIZE]

    suffix = ""
    if sort_by and sort_by != "none":
        suffix += f" · sorted: {sort_by}"
    if file_filter:
        suffix += f" · file: {file_filter}"

    header = f"🔍 Results for: <b>{keyword}</b>{suffix}\nTotal: {len(results)}/{total} · Page {page + 1}/{total_pages}\n<pre>"
    body = "\n".join(chunk)
    footer = "</pre>"

    full_text = header + body + footer

    if len(full_text) > MAX_RESPONSE_LENGTH or len(results) > MAX_INLINE_LINES:
        await _send_as_file(message, keyword, results, total, "ulp", suffix, edit_msg)
        return

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Prev", callback_data=f"ulp_pg:{page-1}")
    builder.button(text=f"📄 {page+1}/{total_pages}", callback_data="ulp_noop")
    if page < total_pages - 1:
        builder.button(text="Next ➡️", callback_data=f"ulp_pg:{page+1}")
    builder.adjust(3)

    if edit_msg:
        await edit_msg.edit_text(full_text, reply_markup=builder.as_markup())
    else:
        await message.answer(full_text, reply_markup=builder.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("ulp_pg:"))
async def on_ulp_page(callback: types.CallbackQuery) -> None:
    page = int(callback.data.split(":")[1])
    text = callback.message.text or callback.message.caption or ""

    keyword_match = None
    for marker in ("Results for: <b>", "Results for: "):
        if marker in text:
            start_idx = text.index(marker) + len(marker)
            end_idx = text.index("</b>", start_idx) if "</b>" in text[start_idx:] else text.index("\n", start_idx)
            keyword_match = text[start_idx:end_idx].strip()
            break

    if keyword_match is None:
        await callback.answer("Cache expired. Please search again.", show_alert=True)
        return

    keyword = keyword_match
    cache_key = None
    r = get_redis()
    keys = await r.keys(f"search:ulp:{keyword.lower()}:*")
    if keys:
        cache_key = keys[0]

    if cache_key is None:
        await callback.answer("Cache expired. Please search again.", show_alert=True)
        return

    cached = await cache_get(cache_key)
    if cached is None:
        await callback.answer("Cache expired. Please search again.", show_alert=True)
        return

    results, total = cached
    total_pages = max(1, (len(results) - 1) // PAGE_SIZE + 1)
    page = min(max(page, 0), total_pages - 1)
    start = page * PAGE_SIZE
    chunk = results[start : start + PAGE_SIZE]

    suffix = ""
    if "· sorted:" in text:
        suffix = " · sorted:" + text.split("· sorted:")[1].split("·")[0].strip() if "· sorted:" in text else ""

    header = f"🔍 Results for: <b>{keyword}</b>{suffix}\nTotal: {len(results)}/{total} · Page {page + 1}/{total_pages}\n<pre>"
    body = "\n".join(chunk)
    footer = "</pre>"
    full_text = header + body + footer

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Prev", callback_data=f"ulp_pg:{page-1}")
    builder.button(text=f"📄 {page+1}/{total_pages}", callback_data="ulp_noop")
    if page < total_pages - 1:
        builder.button(text="Next ➡️", callback_data=f"ulp_pg:{page+1}")
    builder.adjust(3)

    await callback.message.edit_text(full_text, reply_markup=builder.as_markup())
    await callback.answer()


async def _send_as_file(
    message: types.Message,
    keyword: str,
    results: list[str],
    total: int,
    prefix: str,
    suffix: str,
    edit_msg: types.Message | None = None,
) -> None:
    filename = f"{prefix}_{keyword[:20].replace('/', '_')}_{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=6))}.txt"
    filepath = f"/tmp/{filename}"

    with open(filepath, "w") as f:
        f.write("\n".join(results))

    caption = f"🔍 Results for: <b>{keyword}</b>{suffix}\nTotal: <b>{len(results)}/{total}</b> records\n\n💾 Served as file (too large for inline display)."

    if edit_msg:
        await edit_msg.delete()

    await message.answer_document(FSInputFile(filepath), caption=caption)

    try:
        os.remove(filepath)
    except OSError:
        pass
