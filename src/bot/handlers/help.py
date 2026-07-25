from aiogram import Router, types
from aiogram.filters import Command

router = Router()


@router.message(Command("help", "cmds"))
async def cmd_help(message: types.Message) -> None:
    await message.answer(
        "📋 <b>Available Commands</b>\n\n"
        "<b>━━ Public Commands ━━</b>\n"
        "/start — Welcome message\n"
        "/help — This help message\n"
        "/cmds — List all commands\n"
        "/ulp <b>[keyword]</b> — Search ULP database\n"
        "/extract <b>[format] [keyword]</b> — Extract specific format\n"
        "/cmb <b>[keyword] [options]</b> — Generate combo file\n"
        "/history <b>[cmd]</b> — View search history\n\n"
        "<b>━━ Admin Commands ━━</b>\n"
        "/add — Upload DB files (reply to .txt)\n"
        "/files — Browse & manage database files\n"
        "/clean — DB stats & cleanup tools\n"
        "/stats — Usage statistics\n"
        "/validate — Validate DB lines for errors\n"
        "/merge — Merge all DBs into one deduped file\n"
        "/export — Export all DBs as ZIP\n"
        "/broadcast — Send message to all users\n"
        "/ban <b>[id]</b> — Ban a user\n"
        "/unban <b>[id]</b> — Unban a user\n"
        "/users <b>[page]</b> — List registered users\n\n"
        "<b>━━ Owner Only ━━</b>\n"
        "/promote <b>[id]</b> — Promote to admin\n"
        "/demote <b>[id]</b> — Demote to user\n\n"
        "<b>━━ Formats ━━</b>\n"
        "mail:pass, user:pass, number:pass, raw\n"
        "password_only, login_only (combo only)\n\n"
        "<b>━━ Combo Options ━━</b>\n"
        "--dedup, --lower, --delim=CHAR\n"
        "(or use inline buttons for interactive setup)\n\n"
        "<b>━━ Examples ━━</b>\n"
        "/ulp outlook\n"
        "/extract mail:pass gmail.com\n"
        "/cmb netflix --dedup --lower\n"
        "/history ulp\n"
        "t.me/bot?start=outlook  ← deep link auto-search",
    )
