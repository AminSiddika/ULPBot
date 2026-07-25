import asyncio
import os
import random
import string
from pathlib import Path

import aiofiles

from src.config import settings
from src.utils.logger import logger


def _extract_section(line: str, format_type: str) -> str | None:
    parts = line.strip().split(":", 2)
    if len(parts) < 3:
        return None
    url, login, password = parts

    match format_type:
        case "mail_pass" | "email_pass":
            if "@" in login and login.count("@") == 1 and "." in login.split("@", 1)[1]:
                return f"{login}:{password}"
        case "user_pass":
            if "@" not in login and not login.replace("-", "").isascii():
                return None
            if "@" not in login:
                return f"{login}:{password}"
        case "number_pass":
            login_clean = login.replace("-", "").replace("+", "").replace(" ", "")
            if login_clean.isdigit() and len(login_clean) >= 7:
                return f"{login}:{password}"
        case "password_only":
            return password
        case "login_only":
            return login
        case _:
            return line.strip()
    return None


def _parse_parts(line: str) -> tuple[str, str, str]:
    parts = line.strip().split(":", 2)
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return "", parts[0], parts[1]
    return "", "", parts[0] if parts else ""


def _get_domain(url: str) -> str:
    dom = url.lower()
    for prefix in ("https://", "http://"):
        if dom.startswith(prefix):
            dom = dom[len(prefix):]
    dom = dom.split("/")[0]
    dom = dom.removeprefix("www.")
    return dom


SORT_KEYS = {
    "url": lambda x: _parse_parts(x)[0].lower(),
    "login": lambda x: _parse_parts(x)[1].lower(),
    "password": lambda x: _parse_parts(x)[2].lower(),
    "domain": lambda x: _get_domain(_parse_parts(x)[0]),
    "email": lambda x: (
        _parse_parts(x)[1].split("@", 1)[1].lower()
        if "@" in _parse_parts(x)[1]
        else _parse_parts(x)[1].lower()
    ),
}


def sort_results(results: list[str], sort_by: str) -> list[str]:
    key_fn = SORT_KEYS.get(sort_by)
    if key_fn is None:
        return results
    return sorted(results, key=key_fn)


def dedup_results(results: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for r in results:
        h = r.strip().lower()
        if h not in seen:
            seen.add(h)
            unique.append(r)
    return unique


def lowercase_results(results: list[str]) -> list[str]:
    return [r.lower() for r in results]


async def search_ulp(
    keyword: str,
    max_results: int = 1000,
    format_type: str | None = None,
    sort_by: str | None = None,
    file_filter: str | None = None,
) -> tuple[list[str], int]:
    data_path = Path(settings.data_dir)
    if not data_path.exists() or not any(data_path.glob("*.txt")):
        return [], 0

    if file_filter:
        db_files = [data_path / file_filter] if (data_path / file_filter).exists() else []
    else:
        db_files = sorted(data_path.glob("*.txt"))

    results: list[str] = []
    total_found = 0

    for db_file in db_files:
        if total_found >= max_results:
            break
        try:
            proc = await asyncio.create_subprocess_exec(
                "rg",
                "-i",
                "-F",
                keyword,
                str(db_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

            if proc.returncode not in (0, 1):
                logger.warning(f"ripgrep failed on {db_file}: {stderr.decode()}")
                continue

            for line in stdout.decode(errors="replace").strip().split("\n"):
                if not line:
                    continue
                total_found += 1
                if total_found > max_results:
                    break

                entry = line.split(":", 1)[-1] if ":" in line else line
                if format_type:
                    extracted = _extract_section(entry, format_type)
                    if extracted:
                        results.append(extracted)
                else:
                    results.append(entry.strip())

        except TimeoutError:
            logger.warning(f"ripgrep timeout on {db_file} for keyword: {keyword}")
        except FileNotFoundError:
            logger.error("ripgrep (rg) not found. Install it with: apt install ripgrep")
            return [], -1

    results = results[:max_results]

    if sort_by and sort_by != "none":
        results = sort_results(results, sort_by)

    return results, total_found


async def generate_combo_file(
    keyword: str,
    format_type: str = "raw",
    max_results: int = 50000,
    sort_by: str | None = None,
    dedup: bool = False,
    lowercase: bool = False,
    delimiter: str = ":",
) -> tuple[str, int]:
    results, total = await search_ulp(
        keyword,
        max_results=max_results,
        format_type=format_type if format_type not in ("password_only", "login_only") else "raw",
        sort_by=sort_by,
    )

    if format_type in ("password_only", "login_only"):
        processed = []
        for r in results:
            extracted = _extract_section(r, format_type)
            if extracted:
                processed.append(extracted)
        results = processed
    elif format_type and format_type != "raw":
        processed = []
        for r in results:
            parts = r.split(":", 1)
            if len(parts) == 2:
                processed.append(parts[0] + delimiter + parts[1])
        if processed:
            results = processed

    if dedup:
        results = dedup_results(results)
    if lowercase:
        results = lowercase_results(results)

    filename = f"combo_{keyword[:20].replace('/', '_')}_{_random_id()}.txt"
    filepath = Path(settings.downloads_dir) / filename

    async with aiofiles.open(filepath, "w") as f:
        await f.write("\n".join(results))

    return str(filepath), len(results)


async def count_estimate(
    keyword: str,
    format_type: str | None = None,
) -> tuple[int, int]:
    results, total = await search_ulp(keyword, max_results=50, format_type=None)
    if format_type and format_type != "raw":
        count = sum(
            1
            for r in results
            if _extract_section(r, format_type) is not None
        )
    else:
        count = len(results)
    return count, total


def _random_id(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))
