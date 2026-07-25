import os
import random
import shlex
import string as _str

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import FSInputFile

from src.database.repos.log import log_usage
from src.services.cache import cache_get, cache_set, check_rate_limit
from src.services.search import SORT_KEYS, search_ulp

router = Router()

FORMATS = {
    "mail:pass": "mail_pass",
    "email:pass": "mail_pass",
    "user:pass": "user_pass",
    "number:pass": "number_pass",
    "raw": None,
}

MAX_RESULTS = 500
MAX_RESPONSE_LENGTH = 4000
MAX_INLINE_LINES = 50

USAGE = (
    "⚠️ Usage: <code>/extract [format] [keyword] [--sort=KEY]</code>\n\n"
    "Formats: mail:pass, user:pass, number:pass, raw\n"
    "Sort keys: url, login, password, domain, email, none\n\n"
    "Example: <code>/extract mail:pass gmail.com --sort=email</code>"
)


def _parse_args(text: str) -> tuple[str, str, str | None]:
    parts = shlex.split(text)[1:] if len(shlex.split(text)) > 1 else []
    if len(parts) < 2:
        return "", "", None

    fmt_key = parts[0].lower()
    keyword_parts: list[str] = []
    sort_by: str | None = None

    for part in parts[1:]:
        if part.startswith("--sort="):
            val = part.split("=", 1)[1]
            if val in SORT_KEYS or val == "none":
                sort_by = val
        else:
            keyword_parts.append(part)

    return fmt_key, " ".join(keyword_parts), sort_by


@router.message(Command("extract"))
async def cmd_extract(message: types.Message) -> None:
    user_id = message.from_user.id

    limited = await check_rate_limit(user_id, limit=15, window=60)
    if limited:
        await message.answer("⏳ Rate limit exceeded. Please wait a moment.")
        return

    fmt_key, keyword, sort_by = _parse_args(message.text)

    if not fmt_key or not keyword:
        await message.answer(USAGE)
        return

    if fmt_key not in FORMATS:
        await message.answer(f"❌ Unknown format: <b>{fmt_key}</b>\nValid: mail:pass, user:pass, number:pass, raw")
        return

    format_type = FORMATS[fmt_key]
    cache_key = f"search:extract:{fmt_key}:{keyword.lower()}:{sort_by or 'none'}:{MAX_RESULTS}"

    cached = await cache_get(cache_key)
    if cached is not None:
        results, total = cached
        await _send_results(message, fmt_key, keyword, results, total, sort_by)
        await log_usage(user_id, "extract", f"{fmt_key}:{keyword}", len(results))
        return

    suffix = f" (sorted by: {sort_by})" if sort_by and sort_by != "none" else ""
    progress_msg = await message.answer(f"🔍 Extracting <b>{fmt_key}</b> for: <b>{keyword}</b>{suffix}...")
    results, total = await search_ulp(keyword, max_results=MAX_RESULTS, format_type=format_type, sort_by=sort_by)

    if total == -1:
        await progress_msg.edit_text("❌ <b>ripgrep</b> not installed on server. Contact admin.")
        return

    if not results:
        await progress_msg.edit_text(
            f"❌ No {fmt_key} matches for: <b>{keyword}</b>\nTotal scanned: {total}"
        )
        await log_usage(user_id, "extract", f"{fmt_key}:{keyword}", 0)
        return

    await cache_set(cache_key, (results, total), ttl=300)
    await log_usage(user_id, "extract", f"{fmt_key}:{keyword}", len(results))
    await _send_results(message, fmt_key, keyword, results, total, sort_by, edit_msg=progress_msg)


async def _send_results(
    message: types.Message,
    fmt_key: str,
    keyword: str,
    results: list[str],
    total: int,
    sort_by: str | None = None,
    edit_msg: types.Message | None = None,
) -> None:
    suffix = f" (sorted by: {sort_by})" if sort_by and sort_by != "none" else ""
    if len(results) <= MAX_INLINE_LINES:
        await _send_as_messages(message, fmt_key, keyword, results, total, suffix, edit_msg)
    else:
        await _send_as_file(message, fmt_key, keyword, results, total, suffix, edit_msg)


async def _send_as_messages(
    message: types.Message,
    fmt_key: str,
    keyword: str,
    results: list[str],
    total: int,
    suffix: str,
    edit_msg: types.Message | None = None,
) -> None:
    chunks: list[str] = []
    current = (
        f"📤 Extracted <b>{fmt_key}</b> for: <b>{keyword}</b>{suffix}\n"
        f"Total: {len(results)}/{total}\n<pre>"
    )
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
    fmt_key: str,
    keyword: str,
    results: list[str],
    total: int,
    suffix: str,
    edit_msg: types.Message | None = None,
) -> None:
    filename = (
        f"extract_{fmt_key.replace(':', '_')}_"
        f"{keyword[:15].replace('/', '_')}_"
        f"{''.join(random.choices(_str.ascii_lowercase, k=6))}.txt"
    )
    filepath = f"/tmp/{filename}"

    with open(filepath, "w") as f:
        f.write("\n".join(results))

    caption = (
        f"📤 Extracted <b>{fmt_key}</b> for: <b>{keyword}</b>{suffix}\n"
        f"Total: <b>{len(results)}/{total}</b>\n\n"
        f"💾 Served as file (too large for inline display)."
    )

    if edit_msg:
        await edit_msg.delete()

    await message.answer_document(FSInputFile(filepath), caption=caption)

    try:
        os.remove(filepath)
    except OSError:
        pass
