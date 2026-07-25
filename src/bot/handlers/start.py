from aiogram import Router, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()


@router.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Channel", url="https://t.me/ulpbotchannel")

    await message.answer(
        "🤖 <b>ULP Bot v2</b>\n\n"
        "Search ULP databases, extract combos, and generate custom combo files.\n\n"
        "Commands:\n"
        "/cmds — List all commands\n"
        "/ulp keyword — Search ULP database\n"
        "/extract format keyword — Extract specific format\n"
        "/cmb keyword — Generate combo file\n\n"
        "Use /help for detailed information.",
        reply_markup=builder.as_markup(),
    )
