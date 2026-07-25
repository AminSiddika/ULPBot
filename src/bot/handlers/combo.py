import os
from datetime import datetime

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.database.repos.log import log_usage
from src.services.cache import check_rate_limit
from src.services.search import SORT_KEYS, count_estimate, generate_combo_file
from src.utils.logger import logger

router = Router()

FORMATS_ORDER = ["mail:pass", "user:pass", "number:pass", "raw"]
FORMATS_MAP = {
    "mail:pass": "mail_pass",
    "user:pass": "user_pass",
    "number:pass": "number_pass",
    "password_only": "password_only",
    "login_only": "login_only",
    "raw": "raw",
}
SORT_OPTIONS = ["none", "url", "login", "password", "domain", "email"]

_options_store: dict[str, dict] = {}


def _opts_key(user_id: int, keyword: str) -> str:
    return f"{user_id}:{keyword.lower()}"


def _get_opts(user_id: int, keyword: str) -> dict:
    key = _opts_key(user_id, keyword)
    if key not in _options_store:
        _options_store[key] = {
            "dedup": False,
            "lowercase": False,
            "sort": "none",
            "delimiter": ":",
        }
    return _options_store[key]


def _set_opt(user_id: int, keyword: str, option: str, value: str) -> None:
    opts = _get_opts(user_id, keyword)
    if option == "dedup" or option == "lowercase":
        opts[option] = value == "1"
    elif option == "sort":
        opts["sort"] = value
    elif option == "delimiter":
        opts["delimiter"] = value
    _options_store[_opts_key(user_id, keyword)] = opts


def _opts_text(opts: dict) -> str:
    return (
        f"Sort: <b>{opts['sort']}</b> | "
        f"Dedup: <b>{'✅' if opts['dedup'] else '❌'}</b> | "
        f"Lower: <b>{'✅' if opts['lowercase'] else '❌'}</b> | "
        f"Delim: <code>{opts['delimiter']}</code>"
    )


@router.message(Command("cmb"))
async def cmd_cmb(message: types.Message) -> None:
    user_id = message.from_user.id

    limited = await check_rate_limit(user_id, limit=10, window=300)
    if limited:
        await message.answer("⏳ Combo generation is rate-limited. Try again in 5 minutes.")
        return

    parts = message.text.split(" ", 1)
    keyword = parts[1].strip() if len(parts) > 1 else ""
    if not keyword:
        await message.answer(
            "⚠️ Usage: <code>/cmb keyword [--sort=KEY] [--dedup] [--lower] [--delim=CHAR]</code>\n\n"
            "Quick CLI flags also supported:\n"
            "  <code>/cmb netflix --sort=domain --dedup --lower</code>\n\n"
            "Example: <code>/cmb netflix</code>",
        )
        return

    opts = _parse_cli_flags(keyword)
    keyword_clean = opts.pop("_keyword", keyword)
    _options_store[_opts_key(user_id, keyword_clean)] = opts

    est, total = await count_estimate(keyword_clean)
    est_label = est if est < 50 else f"50+"
    opts = _get_opts(user_id, keyword_clean)

    builder = InlineKeyboardBuilder()
    for fmt in FORMATS_ORDER:
        builder.button(text=fmt, callback_data=f"cmb_f:{keyword_clean[:24]}:{fmt}")
    builder.button(text="🔐 Passwords only", callback_data=f"cmb_f:{keyword_clean[:24]}:password_only")
    builder.button(text="👤 Logins only", callback_data=f"cmb_f:{keyword_clean[:24]}:login_only")
    builder.adjust(2, 2, 2)

    builder2 = InlineKeyboardBuilder()
    builder2.button(text="⚙️ Options", callback_data=f"cmb_opt_menu:{keyword_clean[:24]}")

    await message.answer(
        f"📦 <b>Combo Generation</b>\n"
        f"Keyword: <code>{keyword_clean}</code>\n"
        f"Estimated matches: <b>~{est_label}</b> of {total} scanned\n"
        f"{_opts_text(opts)}\n\n"
        f"Select output format:",
        reply_markup=builder.as_markup(),
    )
    await message.answer("Configure:", reply_markup=builder2.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("cmb_opt_menu:"))
async def on_options_menu(callback: types.CallbackQuery) -> None:
    keyword = callback.data.split(":", 1)[1]
    opts = _get_opts(callback.from_user.id, keyword)

    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🗂 Dedup: {'✅' if opts['dedup'] else '❌'}",
        callback_data=f"cmb_opt:{keyword}:dedup:{0 if opts['dedup'] else 1}",
    )
    builder.button(
        text=f"🔡 Lowercase: {'✅' if opts['lowercase'] else '❌'}",
        callback_data=f"cmb_opt:{keyword}:lowercase:{0 if opts['lowercase'] else 1}",
    )
    builder.adjust(1)

    sort_builder = InlineKeyboardBuilder()
    current_sort = opts.get("sort", "none")
    for s in SORT_OPTIONS:
        prefix = "✅ " if s == current_sort else ""
        sort_builder.button(text=f"{prefix}{s}", callback_data=f"cmb_opt:{keyword}:sort:{s}")
    sort_builder.adjust(3)

    delim_builder = InlineKeyboardBuilder()
    for d in [":", "|", ";", "-", "/"]:
        current = "✅ " if opts.get("delimiter", ":") == d else ""
        delim_builder.button(text=f"{current}{d}", callback_data=f"cmb_opt:{keyword}:delimiter:{d}")
    delim_builder.adjust(5)

    b = InlineKeyboardBuilder()
    b.button(text="🔙 Back", callback_data=f"cmb_back:{keyword}")

    await callback.message.edit_text(
        f"⚙️ <b>Combo Options</b>\n\n{_opts_text(opts)}\n\nToggle settings below:",
        reply_markup=builder.as_markup(),
    )
    await callback.message.answer("📊 Sort by:", reply_markup=sort_builder.as_markup())
    await callback.message.answer("🔗 Delimiter:", reply_markup=delim_builder.as_markup())
    await callback.message.answer("Done configuring:", reply_markup=b.as_markup())
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("cmb_opt:"))
async def on_option_toggle(callback: types.CallbackQuery) -> None:
    _, keyword, option, value = callback.data.split(":", 3)
    _set_opt(callback.from_user.id, keyword, option, value)
    opts = _get_opts(callback.from_user.id, keyword)
    await callback.answer(f"{option} = {value}")
    await callback.message.edit_text(
        f"⚙️ <b>Combo Options</b>\n\n{_opts_text(opts)}",
        reply_markup=callback.message.reply_markup,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cmb_back:"))
async def on_back_to_main(callback: types.CallbackQuery) -> None:
    keyword = callback.data.split(":", 1)[1]
    opts = _get_opts(callback.from_user.id, keyword)
    est, total = await count_estimate(keyword)
    est_label = est if est < 50 else "50+"

    builder = InlineKeyboardBuilder()
    for fmt in FORMATS_ORDER:
        builder.button(text=fmt, callback_data=f"cmb_f:{keyword[:24]}:{fmt}")
    builder.button(text="🔐 Passwords only", callback_data=f"cmb_f:{keyword[:24]}:password_only")
    builder.button(text="👤 Logins only", callback_data=f"cmb_f:{keyword[:24]}:login_only")
    builder.adjust(2, 2, 2)

    builder2 = InlineKeyboardBuilder()
    builder2.button(text="⚙️ Options", callback_data=f"cmb_opt_menu:{keyword[:24]}")

    await callback.message.edit_text(
        f"📦 <b>Combo Generation</b>\n"
        f"Keyword: <code>{keyword}</code>\n"
        f"Estimated matches: <b>~{est_label}</b> of {total} scanned\n"
        f"{_opts_text(opts)}\n\n"
        f"Select output format:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("cmb_f:"))
async def on_combo_format_chosen(callback: types.CallbackQuery) -> None:
    _, keyword, fmt_key = callback.data.split(":", 2)
    opts = _get_opts(callback.from_user.id, keyword)

    await callback.answer(f"Generating {fmt_key} with current options...")
    await callback.message.edit_text(
        f"⏳ Generating <b>{fmt_key}</b> for: <b>{keyword}</b>\n"
        f"{_opts_text(opts)}\n\n"
        f"Please wait..."
    )

    format_type = FORMATS_MAP.get(fmt_key, "raw")
    filepath, count = await generate_combo_file(
        keyword,
        format_type=format_type,
        sort_by=opts["sort"] if opts["sort"] != "none" else None,
        dedup=opts["dedup"],
        lowercase=opts["lowercase"],
        delimiter=opts["delimiter"],
    )

    await log_usage(callback.from_user.id, "cmb", f"{fmt_key}:{keyword}", count)

    if count == 0:
        await callback.message.edit_text(f"❌ No results found for: <b>{keyword}</b>")
        return

    opt_lines = []
    if opts["dedup"]:
        opt_lines.append("✅ Dedup")
    if opts["lowercase"]:
        opt_lines.append("🔡 Lowercased")
    if opts["sort"] != "none":
        opt_lines.append(f"📊 Sorted by: {opts['sort']}")
    if opts["delimiter"] != ":":
        opt_lines.append(f"🔗 Delimiter: {opts['delimiter']}")
    opt_text = " | ".join(opt_lines) if opt_lines else "—"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    caption = (
        f"📦 <b>Combo Generated</b>\n"
        f"Format: <b>{fmt_key}</b>\n"
        f"Keyword: <b>{keyword}</b>\n"
        f"Count: <b>{count}</b>\n"
        f"Options: {opt_text}\n"
        f"Date: <b>{timestamp}</b>"
    )

    await callback.message.answer_document(FSInputFile(filepath), caption=caption)
    await callback.message.delete()

    try:
        os.remove(filepath)
    except OSError:
        logger.warning(f"Failed to remove temp file: {filepath}")

    del _options_store[_opts_key(callback.from_user.id, keyword)]


def _parse_cli_flags(text: str) -> dict:
    import shlex
    parts = shlex.split(text)
    keyword_parts: list[str] = []
    opts: dict = {"dedup": False, "lowercase": False, "sort": "none", "delimiter": ":"}

    for p in parts:
        if p == "--dedup":
            opts["dedup"] = True
        elif p == "--lower":
            opts["lowercase"] = True
        elif p.startswith("--sort="):
            val = p.split("=", 1)[1]
            if val in SORT_KEYS or val == "none":
                opts["sort"] = val
        elif p.startswith("--delim="):
            val = p.split("=", 1)[1]
            if len(val) == 1:
                opts["delimiter"] = val
        else:
            keyword_parts.append(p)

    opts["_keyword"] = " ".join(keyword_parts)
    return opts
