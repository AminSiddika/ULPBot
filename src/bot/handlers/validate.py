import asyncio
from pathlib import Path

from aiogram import Router, types
from aiogram.filters import Command

from src.config import settings
from src.database.repos.user import get_or_create_user, is_admin

router = Router()


async def _check_admin(message: types.Message) -> bool:
    user_doc = await get_or_create_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    admin = await is_admin(user_doc, settings.owner_id, settings.admin_ids_set)
    if not admin:
        await message.answer("⛔ You are not authorized to use this command.")
        return False
    return True


@router.message(Command("validate"))
async def cmd_validate(message: types.Message) -> None:
    if not await _check_admin(message):
        return

    data_path = Path(settings.data_dir)
    files = sorted(data_path.glob("*.txt"))

    if not files:
        await message.answer("📭 No database files found in <code>data/</code>.")
        return

    progress_msg = await message.answer("🔍 Validating database files...")
    report_lines = ["📋 <b>Database Validation Report</b>\n"]

    for fp in files:
        total_lines = 0
        valid_lines = 0
        malformed = 0
        empty_lines = 0

        try:
            with open(fp, "r", errors="replace") as f:
                for line in f:
                    total_lines += 1
                    stripped = line.strip()
                    if not stripped:
                        empty_lines += 1
                        continue
                    parts = stripped.split(":", 2)
                    if len(parts) == 3 and parts[0] and parts[1] and parts[2]:
                        valid_lines += 1
                    else:
                        malformed += 1
        except Exception as e:
            report_lines.append(f"❌ <code>{fp.name}</code> — read error: {e}")
            continue

        status = "✅" if malformed == 0 else "⚠️"
        report_lines.append(
            f"{status} <code>{fp.name}</code> — {total_lines} lines | "
            f"valid: {valid_lines} | malformed: {malformed} | empty: {empty_lines}"
            + (f" ({malformed/max(1,total_lines)*100:.1f}% bad)" if malformed > 0 else "")
        )

    if len(report_lines) > 20:
        report = "\n".join(report_lines[:20]) + f"\n\n... and {len(report_lines) - 21} more files."
    else:
        report = "\n".join(report_lines)

    await progress_msg.edit_text(report[:4000])

    total_files = len(files)
    await message.answer(
        f"✅ <b>Validation complete.</b>\n"
        f"Files scanned: <b>{total_files}</b>\n"
        f"Tip: Use /files to manage individual databases."
    )
