import asyncio
import os
import random

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.database.repos.log import log_usage
from src.database.repos.user import FREE_SEARCH_LIMIT, get_user, increment_search_count, is_premium
from src.services.cache import cache_get, cache_set
from src.services.search import search_ulp

router = Router()

MAX_RESULTS = 1000
MAX_RESPONSE_LENGTH = 3800
MAX_INLINE_LINES = 50
PAGE_SIZE = 30

SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
WARN_THRESHOLD = 5


@router.message(Command("ulp"))
async def cmd_ulp(message: types.Message) -> None:
    user_id = message.from_user.id

    if not await is_premium(user_id):
        count, ok = await increment_search_count(user_id)
        if not ok:
            remaining = max(0, FREE_SEARCH_LIMIT - count)
            await message.answer(
                f"⚠️ <b>Free search limit reached!</b>\n\n"
                f"You've used {count}/{FREE_SEARCH_LIMIT} free searches.\n"
                f"🔑 Use /redeem to upgrade to premium for unlimited searches."
            )
            return
        remaining = max(0, FREE_SEARCH_LIMIT - count)
        if remaining <= WARN_THRESHOLD:
            await message.answer(
                f"⚠️ <b>{remaining} search{'s' if remaining != 1 else ''} remaining!</b> "
                f"Used: {count}/{FREE_SEARCH_LIMIT}. "
                f"Use /redeem to upgrade.",
            )

    keyword = message.text.split(" ", 1)[-1].strip() if len(message.text.split(" ")) > 1 else ""
    if not keyword:
        await message.answer("⚠️ Usage: <code>/ulp keyword</code>\n\nExample: <code>/ulp outlook</code>")
        return

    cache_key = f"search:ulp:{keyword.lower()}:{MAX_RESULTS}"

    cached = await cache_get(cache_key)
    if cached is not None:
        results, total = cached
        await _send_paginated(message, keyword, results, total, 0)
        await log_usage(user_id, "ulp", keyword, len(results))
        return

    progress_msg = await message.answer(f"⠋ Searching: <b>{keyword}</b>...")
    task = _start_spinner(progress_msg, f"Searching: <b>{keyword}</b>")

    results, total = await search_ulp(keyword, max_results=MAX_RESULTS)

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

    footer = await _usage_footer(user_id)
    await _send_paginated(message, keyword, results, total, 0, edit_msg=progress_msg, footer=footer)


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


async def _send_paginated(
    message: types.Message,
    keyword: str,
    results: list[str],
    total: int,
    page: int = 0,
    edit_msg: types.Message | None = None,
    footer: str = "",
) -> None:
    total_pages = max(1, (len(results) - 1) // PAGE_SIZE + 1)
    page = min(max(page, 0), total_pages - 1)
    start = page * PAGE_SIZE
    chunk = results[start : start + PAGE_SIZE]

    header = f"🔍 Results for: <b>{keyword}</b>\nTotal: {len(results)}/{total} · Page {page + 1}/{total_pages}\n<pre>"
    body = "\n".join(chunk)
    full_text = header + body + "</pre>" + footer

    if len(full_text) > MAX_RESPONSE_LENGTH or len(results) > MAX_INLINE_LINES:
        await _send_as_file(message, keyword, results, total, edit_msg)
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
    text = callback.message.text or ""

    keyword = _extract_keyword_from_text(text)
    if keyword is None:
        await callback.answer("Cache expired. Please search again.", show_alert=True)
        return

    cache_key = f"search:ulp:{keyword.lower()}:{MAX_RESULTS}"
    cached = await cache_get(cache_key)
    if cached is None:
        await callback.answer("Cache expired. Please search again.", show_alert=True)
        return

    results, total = cached

    total_pages = max(1, (len(results) - 1) // PAGE_SIZE + 1)
    page = min(max(page, 0), total_pages - 1)
    start = page * PAGE_SIZE
    chunk = results[start : start + PAGE_SIZE]

    header = f"🔍 Results for: <b>{keyword}</b>\nTotal: {len(results)}/{total} · Page {page + 1}/{total_pages}\n<pre>"
    body = "\n".join(chunk)
    full_text = header + body + "</pre>"

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
    edit_msg: types.Message | None = None,
) -> None:
    filename = f"ulp_{keyword[:20].replace('/', '_')}_{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=6))}.txt"
    filepath = f"/tmp/{filename}"

    with open(filepath, "w") as f:
        f.write("\n".join(results))

    caption = f"🔍 Results for: <b>{keyword}</b>\nTotal: <b>{len(results)}/{total}</b> records\n\n💾 Served as file (too large for inline display)."

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
    start = text.index("<b>") + 3
    end = text.index("</b>", start)
    raw = text[start:end]
    return raw.split("\n")[0].strip()


async def _usage_footer(user_id: int) -> str:
    if await is_premium(user_id):
        return "\n\n⭐ Premium · unlimited searches"
    doc = await get_user(user_id)
    if doc is None:
        return ""
    used = doc.get("search_count", 0)
    remaining = max(0, FREE_SEARCH_LIMIT - used)
    return f"\n\n🔍 Free search: {remaining}/{FREE_SEARCH_LIMIT} remaining"
