import shlex

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import FSInputFile

from src.database.repos.log import log_usage
from src.services.cache import cache_get, cache_set, check_rate_limit
from src.services.search import SORT_KEYS, search_ulp, sort_results
from src.utils.logger import logger

router = Router()

MAX_RESULTS = 500
MAX_RESPONSE_LENGTH = 4000
MAX_INLINE_LINES = 50

USAGE = (
    "⚠️ Usage: <code>/ulp keyword [--sort=KEY]</code>\n\n"
    "Sort keys: url, login, password, domain, email, none\n"
    "Example: <code>/ulp outlook --sort=domain</code>"
)


def _parse_args(text: str) -> tuple[str, str | None]:
    keyword_parts: list[str] = []
    sort_by: str | None = None
    raw_parts = shlex.split(text)[1:] if len(shlex.split(text)) > 1 else []

    for part in raw_parts:
        if part.startswith("--sort="):
            val = part.split("=", 1)[1]
            if val in SORT_KEYS or val == "none":
                sort_by = val
        else:
            keyword_parts.append(part)

    keyword = " ".join(keyword_parts)
    return keyword, sort_by


@router.message(Command("ulp"))
async def cmd_ulp(message: types.Message) -> None:
    user_id = message.from_user.id

    limited = await check_rate_limit(user_id, limit=15, window=60)
    if limited:
        await message.answer("⏳ Rate limit exceeded. Please wait a moment.")
        return

    keyword, sort_by = _parse_args(message.text)
    if not keyword:
        await message.answer(USAGE)
        return

    cache_key = f"search:ulp:{keyword.lower()}:{sort_by or 'none'}:{MAX_RESULTS}"

    cached = await cache_get(cache_key)
    if cached is not None:
        results, total = cached
        await _send_results(message, keyword, results, total, sort_by)
        await log_usage(user_id, "ulp", keyword, len(results))
        return

    progress_msg = await message.answer(
        f"🔍 Searching for: <b>{keyword}</b>"
        + (f" (sorted by: {sort_by})" if sort_by and sort_by != "none" else "")
        + "..."
    )
    results, total = await search_ulp(keyword, max_results=MAX_RESULTS, sort_by=sort_by)

    if total == -1:
        await progress_msg.edit_text("❌ <b>ripgrep</b> not installed on server. Contact admin.")
        return

    if not results:
        await progress_msg.edit_text(f"❌ No results found for: <b>{keyword}</b>\nTotal scanned: {total}")
        await log_usage(user_id, "ulp", keyword, 0)
        return

    await cache_set(cache_key, (results, total), ttl=300)
    await log_usage(user_id, "ulp", keyword, len(results))
    await _send_results(message, keyword, results, total, sort_by, edit_msg=progress_msg)


async def _send_results(
    message: types.Message,
    keyword: str,
    results: list[str],
    total: int,
    sort_by: str | None = None,
    edit_msg: types.Message | None = None,
) -> None:
    suffix = f" (sorted by: {sort_by})" if sort_by and sort_by != "none" else ""
    if len(results) <= MAX_INLINE_LINES:
        await _send_as_messages(message, keyword, results, total, suffix, edit_msg)
    else:
        await _send_as_file(message, keyword, results, total, "ulp", suffix, edit_msg)


async def _send_as_messages(
    message: types.Message,
    keyword: str,
    results: list[str],
    total: int,
    suffix: str,
    edit_msg: types.Message | None = None,
) -> None:
    chunks: list[str] = []
    current = f"🔍 Results for: <b>{keyword}</b>{suffix}\nTotal: {len(results)}/{total} records\n<pre>"
    for line in results:
        if len(current) + len(line) + 10 > MAX_RESPONSE_LENGTH:
            current += "</pre>"
            chunks.append(current)
            current = "<pre>"
        current += line + "\n"
    current += "</pre>"
    chunks.append(current)

    if edit_msg:
        await edit_msg.edit_text(chunks[0])
    else:
        await message.answer(chunks[0])
    for chunk in chunks[1:]:
        await message.answer(chunk)


async def _send_as_file(
    message: types.Message,
    keyword: str,
    results: list[str],
    total: int,
    prefix: str,
    suffix: str,
    edit_msg: types.Message | None = None,
) -> None:
    import os
    import random
    import string as _str

    filename = f"{prefix}_{keyword[:20].replace('/', '_')}_{''.join(random.choices(_str.ascii_lowercase, k=6))}.txt"
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
