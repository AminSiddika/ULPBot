from aiogram import Router, types
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.database.repos.log import log_usage
from src.services.cache import cache_get
from src.services.search import search_ulp

router = Router()

MAX_RESULTS = 100

VERSION = "3.3"


@router.message(Command("ping"))
async def cmd_ping(message: types.Message) -> None:
    import time
    t0 = time.monotonic()
    db_ok = False
    redis_ok = False

    try:
        from src.database.engine import get_db
        await get_db().command("ping")
        db_ok = True
    except Exception:
        pass

    try:
        from src.services.cache import get_redis
        await get_redis().ping()
        redis_ok = True
    except Exception:
        pass

    elapsed = (time.monotonic() - t0) * 1000

    await message.answer(
        f"🏓 <b>Pong!</b>\n"
        f"Version: <b>{VERSION}</b>\n"
        f"Latency: <b>{elapsed:.0f}ms</b>\n"
        f"MongoDB: {'✅' if db_ok else '❌'}\n"
        f"Redis: {'✅' if redis_ok else '❌'}"
    )


@router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject) -> None:
    deep_arg = command.args.strip() if command.args else ""

    if deep_arg:
        await _handle_deep_link(message, deep_arg)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Channel", url="https://t.me/ulpbotchannel")

    kb = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="🔍 /ulp"), types.KeyboardButton(text="📤 /extract"), types.KeyboardButton(text="📦 /cmb")],
            [types.KeyboardButton(text="👤 /userinfo"), types.KeyboardButton(text="📜 /history"), types.KeyboardButton(text="❓ /help")],
        ],
        resize_keyboard=True,
    )

    await message.answer(
        "🤖 <b>ULP Bot v4</b>\n\n"
        "Search ULP databases, extract combos, and generate custom combo files.\n\n"
        "Commands:\n"
        "/cmds — List all commands\n"
        "/ulp keyword — Search ULP database\n"
        "/extract format keyword — Extract specific format\n"
        "/cmb keyword — Generate combo file\n\n"
        "Tip: Share links like <code>t.me/bot?start=outlook</code> to auto-search!\n\n"
        "Use /help for detailed information.",
        reply_markup=kb,
    )


async def _handle_deep_link(message: types.Message, arg: str) -> None:
    keyword = arg.strip()

    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Channel", url="https://t.me/ulpbotchannel")

    await message.answer(
        f"🤖 <b>ULP Bot v3</b>\n\n"
        f"Auto-searching for: <b>{keyword}</b>...\n\n"
        f"Use /help for detailed information.",
        reply_markup=builder.as_markup(),
    )

    progress_msg = await message.answer(f"🔍 Searching for: <b>{keyword}</b>...")
    results, total = await search_ulp(keyword, max_results=MAX_RESULTS)

    if not results:
        await progress_msg.edit_text(f"❌ No results for: <b>{keyword}</b>")
        return

    await log_usage(message.from_user.id, "ulp", keyword, len(results))

    chunks: list[str] = []
    current = f"🔍 Results for: <b>{keyword}</b>\nTotal: {len(results)}/{total}\n<pre>"
    for line in results:
        if len(current) + len(line) + 10 > 3800:
            current += "</pre>"
            chunks.append(current)
            current = "<pre>"
        current += line + "\n"
    current += "</pre>"
    chunks.append(current)

    await progress_msg.edit_text(chunks[0])
    for chunk in chunks[1:]:
        await message.answer(chunk)
