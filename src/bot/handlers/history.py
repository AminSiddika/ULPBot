from datetime import datetime, timezone

from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.database.repos.log import clear_user_history, get_user_history

router = Router()


@router.message(Command("history"))
async def cmd_history(message: types.Message, command: CommandObject) -> None:
    user_id = message.from_user.id

    filter_cmd = None
    if command.args:
        arg = command.args.strip().lower().lstrip("/")
        if arg in ("ulp", "extract", "cmb", "all"):
            filter_cmd = None if arg == "all" else arg

    history = await get_user_history(user_id, limit=20, command=filter_cmd)

    if not history:
        await message.answer("📭 No search history found.\nUse <code>/ulp</code>, <code>/extract</code>, or <code>/cmb</code> to build history.")
        return

    lines = [f"📜 <b>Search History</b> ({'all' if not filter_cmd else filter_cmd})\n"]
    for h in history:
        cmd = h.get("command", "?")
        kw = h.get("keyword", "—") or "—"
        count = h.get("result_count", 0)
        ts = h.get("created_at")
        if isinstance(ts, datetime):
            ts_str = ts.strftime("%m-%d %H:%M")
        else:
            ts_str = "—"
        lines.append(f"/{cmd} <code>{kw}</code> → {count} results · {ts_str}")

    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Clear History", callback_data="hist_clear")
    if filter_cmd:
        builder.button(text="📋 Show All", callback_data="hist_all")

    await message.answer("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(lambda c: c.data == "hist_clear")
async def on_clear_history(callback: types.CallbackQuery) -> None:
    count = await clear_user_history(callback.from_user.id)
    await callback.answer(f"Cleared {count} entries", show_alert=True)
    await callback.message.edit_text(f"🗑 Search history cleared ({count} entries removed).")


@router.callback_query(lambda c: c.data == "hist_all")
async def on_show_all_history(callback: types.CallbackQuery) -> None:
    history = await get_user_history(callback.from_user.id, limit=20)
    lines = ["📜 <b>Search History</b> (all)\n"]
    for h in history:
        cmd = h.get("command", "?")
        kw = h.get("keyword", "—") or "—"
        count = h.get("result_count", 0)
        ts = h.get("created_at")
        if isinstance(ts, datetime):
            ts_str = ts.strftime("%m-%d %H:%M")
        else:
            ts_str = "—"
        lines.append(f"/{cmd} <code>{kw}</code> → {count} results · {ts_str}")

    builder = InlineKeyboardBuilder()
    builder.button(text="🗑 Clear History", callback_data="hist_clear")

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
    await callback.answer()
