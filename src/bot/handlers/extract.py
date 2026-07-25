import asyncio
import os
import random
import shlex

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.database.repos.log import log_usage
from src.services.cache import cache_get, cache_set, check_cooldown, check_rate_limit
from src.services.search import SORT_KEYS, search_ulp

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

USAGE = (
    "⚠️ Usage: <code>/extract [format] [keyword] [--sort=KEY] [--file=name.txt]</code>\n\n"
    "Formats: mail:pass, user:pass, number:pass, raw\n"
    "Sort keys: url, login, password, domain, email, none\n\n"
    "Example: <code>/extract mail:pass gmail --sort=email --file=db1.txt</code>"
)


def _parse_args(text: str) -> tuple[str, str, str | None, str | None]:
    parts = shlex.split(text)[1:] if len(shlex.split(text)) > 1 else []
    if len(parts) < 2:
        return "", "", None, None

    fmt_key = parts[0].lower()
    keyword_parts: list[str] = []
    sort_by: str | None = None
    file_filter: str | None = None

    for part in parts[1:]:
        if part.startswith("--sort="):
            val = part.split("=", 1)[1]
            if val in SORT_KEYS or val == "none":
                sort_by = val
        elif part.startswith("--file="):
            file_filter = part.split("=", 1)[1]
        else:
            keyword_parts.append(part)

    return fmt_key, " ".join(keyword_parts), sort_by, file_filter


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


@router.message(Command("extract"))
async def cmd_extract(message: types.Message) -> None:
    user_id = message.from_user.id

    limited = await check_rate_limit(user_id, limit=15, window=60)
    if limited:
        await message.answer("⏳ Rate limit exceeded. Please wait a moment.")
        return

    fmt_key, keyword, sort_by, file_filter = _parse_args(message.text)

    if not fmt_key or not keyword:
        await message.answer(USAGE)
        return

    if fmt_key not in FORMATS:
        await message.answer(f"❌ Unknown format: <b>{fmt_key}</b>\nValid: mail:pass, user:pass, number:pass, raw")
        return

    full_key = f"{fmt_key}:{keyword}"
    on_cooldown = await check_cooldown(user_id, full_key)
    if on_cooldown:
        await message.answer(f"⏳ You just searched <code>{fmt_key} {keyword}</code>. Wait 30s before repeating.")
        return

    format_type = FORMATS[fmt_key]
    cache_key = f"search:extract:{fmt_key}:{keyword.lower()}:{sort_by or 'none'}:{file_filter or 'all'}:{MAX_RESULTS}"

    cached = await cache_get(cache_key)
    if cached is not None:
        results, total = cached
        await _send_paginated(message, fmt_key, keyword, results, total, sort_by, file_filter, 0)
        await log_usage(user_id, "extract", full_key, len(results))
        return

    spinner_label = f"Extracting <b>{fmt_key}</b> for: <b>{keyword}</b>" + (f" (sorted: {sort_by})" if sort_by and sort_by != "none" else "") + (f" [file: {file_filter}]" if file_filter else "")
    progress_msg = await message.answer(f"🔍 {spinner_label}...")
    task = await _start_spinner(progress_msg, spinner_label)

    results, total = await search_ulp(
        keyword, max_results=MAX_RESULTS, format_type=format_type, sort_by=sort_by, file_filter=file_filter
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
        await progress_msg.edit_text(f"❌ No {fmt_key} matches for: <b>{keyword}</b>")
        await log_usage(user_id, "extract", full_key, 0)
        return

    await cache_set(cache_key, (results, total), ttl=300)
    await log_usage(user_id, "extract", full_key, len(results))
    await _send_paginated(message, fmt_key, keyword, results, total, sort_by, file_filter, 0, edit_msg=progress_msg)


async def _send_paginated(
    message: types.Message,
    fmt_key: str,
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

    header = f"📤 Extracted <b>{fmt_key}</b> for: <b>{keyword}</b>{suffix}\nTotal: {len(results)}/{total} · Page {page + 1}/{total_pages}\n<pre>"
    body = "\n".join(chunk)
    footer = "</pre>"
    full_text = header + body + footer

    if len(full_text) > MAX_RESPONSE_LENGTH or len(results) > MAX_INLINE_LINES:
        await _send_as_file(message, fmt_key, keyword, results, total, suffix, edit_msg)
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

    for cache_prefix in ["mail_pass", "user_pass", "number_pass", "raw", None]:
        if cache_prefix is None:
            continue
        for marker in ("Extracted ", "Results for "):
            if marker in text:
                await callback.answer("Cache expired. Please search again.", show_alert=True)
                return

    from src.services.cache import get_redis
    r = get_redis()
    keys = await r.keys("search:extract:*")
    if not keys:
        await callback.answer("Cache expired. Please search again.", show_alert=True)
        return

    for key in keys:
        cached = await cache_get(key)
        if cached is None:
            continue
        results, total = cached
        total_pages = max(1, (len(results) - 1) // PAGE_SIZE + 1)
        page_clamped = min(max(page, 0), total_pages - 1)
        start = page_clamped * PAGE_SIZE
        chunk = results[start : start + PAGE_SIZE]

        header = text[:text.find("<pre>")] if "<pre>" in text else f"📤 Results\n"
        header_parts = header.split("· Page ")
        if len(header_parts) > 1:
            header = header_parts[0].rstrip() + f" · Page {page_clamped + 1}/{total_pages}\n<pre>"
        else:
            header += f"Total: {len(results)}/{total} · Page {page_clamped + 1}/{total_pages}\n<pre>"

        body = "\n".join(chunk)
        full_text = header + body + "</pre>"

        builder = InlineKeyboardBuilder()
        if page_clamped > 0:
            builder.button(text="⬅️ Prev", callback_data=f"ext_pg:{page_clamped - 1}")
        builder.button(text=f"📄 {page_clamped + 1}/{total_pages}", callback_data="ext_noop")
        if page_clamped < total_pages - 1:
            builder.button(text="Next ➡️", callback_data=f"ext_pg:{page_clamped + 1}")
        builder.adjust(3)

        await callback.message.edit_text(full_text, reply_markup=builder.as_markup())
        await callback.answer()
        return


async def _send_as_file(
    message: types.Message,
    fmt_key: str,
    keyword: str,
    results: list[str],
    total: int,
    suffix: str,
    edit_msg: types.Message | None = None,
) -> None:
    filename = f"extract_{fmt_key.replace(':', '_')}_{keyword[:15].replace('/', '_')}_{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=6))}.txt"
    filepath = f"/tmp/{filename}"

    with open(filepath, "w") as f:
        f.write("\n".join(results))

    caption = f"📤 Extracted <b>{fmt_key}</b> for: <b>{keyword}</b>{suffix}\nTotal: <b>{len(results)}/{total}</b>\n\n💾 Served as file (too large for inline display)."

    if edit_msg:
        await edit_msg.delete()

    await message.answer_document(FSInputFile(filepath), caption=caption)

    try:
        os.remove(filepath)
    except OSError:
        pass
