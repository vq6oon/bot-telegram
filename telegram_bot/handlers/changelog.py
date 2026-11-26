"""Changelog command handler."""
import asyncio
import html
import logging
import re
import subprocess
from telegram import Update
from telegram.ext import ContextTypes
from ..config import BASE_DIR

REPO_ROOT = str(BASE_DIR)
_CONVENTIONAL_RE = re.compile(
    r"^(feat|fix|refactor|docs|test|chore|ci|perf)(?:\(([^)]+)\))?:\s*(.*)$"
)


def _get_message(update: Update):
    return getattr(update, "effective_message", None) or getattr(update, "message", None)


async def changelog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = _get_message(update)
    if not msg:
        return

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [
                "git",
                "log",
                "-15",
                "--pretty=format:%h %s",
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        await msg.reply_text("Timeout fetching changelog.")
        return
    except Exception as e:
        logging.error("Changelog error: %s", e)
        await msg.reply_text("Failed to fetch changelog.")
        return

    if result.returncode != 0:
        logging.error("Changelog git error (%s): %s", result.returncode, (result.stderr or "").strip())
        await msg.reply_text("Failed to fetch changelog.")
        return

    lines = result.stdout.strip().splitlines()
    if not lines or not lines[0]:
        await msg.reply_text("No commits found.")
        return

    formatted = []
    for line in lines:
        if not line:
            continue
        parts = line.split(" ", 1)
        safe_hash = html.escape(parts[0])
        if len(parts) < 2:
            formatted.append(f"• <code>{safe_hash}</code>")
            continue
        subject = parts[1]
        match = _CONVENTIONAL_RE.match(subject)
        if match:
            kind, scope, desc = match.groups()
            prefix = f"{kind}({scope})" if scope else kind
            formatted.append(
                f"• <code>{safe_hash}</code> <b>{html.escape(prefix)}</b>: {html.escape(desc)}"
            )
        else:
            formatted.append(f"• <code>{safe_hash}</code> {html.escape(subject)}")

    text = "Recent changes:\n\n" + "\n".join(formatted)
    await msg.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)