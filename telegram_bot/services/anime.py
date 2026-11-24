"""Hybrid ani-cli wrapper for anime search (fzf shim) and isolated single-episode downloads."""
import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path
from ..config import (
    ANI_CLI_BIN,
    ANI_CLI_SEARCH_TIMEOUT_SECONDS,
    ANI_CLI_TIMEOUT_SECONDS,
    ANIME_MAX_EPISODE,
)
from .drive import sanitize_error

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".ts", ".avi", ".mov", ".m4v"}
_TEMP_SUFFIXES = (".part", ".tmp", ".ytdl", ".aria2")
VALID_QUALITIES = ("360", "720", "1080", "best")


class AnimeCliUnavailableError(RuntimeError):
    """Raised when the ani-cli binary is not found in PATH."""


def is_ani_cli_available() -> str | None:
    """Return resolved path to ani-cli executable if installed, else None."""
    return shutil.which(ANI_CLI_BIN)


def parse_anime_command_args(args: list[str]) -> tuple[str, int | None, str | None]:
    """
    Parse `/anime <title> [-e <episode>]` arguments.
    Returns (query, episode_or_none, error_message_or_none).
    Rejects bulk ranges (e.g. 1-5, 1,2) and out-of-range episodes.
    """
    if not args:
        return "", None, "Usage: /anime <title> [-e <episode>]"

    query_parts: list[str] = []
    episode: int | None = None
    idx = 0
    while idx < len(args):
        token = args[idx].strip()
        if token in ("-e", "--episode"):
            if idx + 1 >= len(args):
                return "", None, "Provide a single episode number after -e (example: /anime frieren -e 1)."
            ep_raw = args[idx + 1].strip()
            ep_val, err = _parse_single_episode(ep_raw)
            if err:
                return "", None, err
            episode = ep_val
            idx += 2
            continue
        query_parts.append(token)
        idx += 1

    query = " ".join(part for part in query_parts if part).strip()
    if not query:
        return "", None, "Usage: /anime <title> [-e <episode>]"
    return query, episode, None


def _parse_single_episode(raw: str) -> tuple[int | None, str | None]:
    if any(sep in raw for sep in ("-", ",", ":", " ")):
        return None, "Bulk episode ranges are not allowed. Provide a single episode number."
    if not raw.isdigit():
        return None, "Episode must be a positive integer."
    ep = int(raw)
    if ep < 1 or ep > ANIME_MAX_EPISODE:
        return None, f"Episode must be between 1 and {ANIME_MAX_EPISODE}."
    return ep, None


def sanitize_title(title: str) -> str:
    cleaned = _ANSI_ESCAPE_RE.sub("", title or "").strip()
    cleaned = _UNSAFE_FILENAME_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:80] or "Anime"


def build_clean_anime_filename(title: str, episode: int, quality: str, extension: str) -> str:
    """Format output filename as `<Title> - Ep <ep> (<quality>).<ext>`."""
    safe_title = sanitize_title(title)
    q = (quality or "720").lower().rstrip("p")
    quality_label = "Best" if q == "best" else f"{q}p"
    ext = extension if extension.startswith(".") else f".{extension}"
    return f"{safe_title} - Ep {episode} ({quality_label}){ext}"


def _clean_captured_titles(raw_text: str, max_results: int = 5) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    for line in raw_text.splitlines():
        cleaned = _ANSI_ESCAPE_RE.sub("", line).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        results.append(cleaned)
        if len(results) >= max_results:
            break
    return results


def search_anime(query: str, max_results: int = 5) -> list[str]:
    """
    Capture up to `max_results` titles from ani-cli using a temporary fzf shim in PATH.
    Returns [] if capture fails so callers can fall back to `-S 1`.
    """
    ani_bin = is_ani_cli_available()
    if not ani_bin:
        raise AnimeCliUnavailableError(f"'{ANI_CLI_BIN}' is not installed on this server.")

    with tempfile.TemporaryDirectory(prefix="anicli-shim-") as shim_dir:
        capture_file = os.path.join(shim_dir, "captured.txt")
        fzf_path = os.path.join(shim_dir, "fzf")
        shim_script = "#!/bin/sh\ncat > \"$ANI_CLI_CAPTURE_FILE\"\nexit 1\n"
        with open(fzf_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(shim_script)
        try:
            os.chmod(fzf_path, os.stat(fzf_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass

        env = os.environ.copy()
        env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
        env["ANI_CLI_CAPTURE_FILE"] = capture_file

        try:
            subprocess.run(
                [ani_bin, query],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=ANI_CLI_SEARCH_TIMEOUT_SECONDS,
                env=env,
                check=False,
            )
        except Exception as err:
            logging.warning("[ANIME] Search shim failed for '%s': %s", query, sanitize_error(err))
            return []

        if not os.path.isfile(capture_file):
            return []

        try:
            raw = Path(capture_file).read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            logging.warning("[ANIME] Failed to read captured search results: %s", sanitize_error(err))
            return []

        return _clean_captured_titles(raw, max_results=max_results)


def _find_downloaded_file(job_dir: str) -> str | None:
    candidates: list[Path] = []
    fallback: list[Path] = []
    root = Path(job_dir)
    if not root.is_dir():
        return None

    for item in root.rglob("*"):
        if not item.is_file():
            continue
        name_lower = item.name.lower()
        if any(name_lower.endswith(suffix) for suffix in _TEMP_SUFFIXES):
            continue
        if item.stat().st_size <= 0:
            continue
        if item.suffix.lower() in _VIDEO_EXTENSIONS:
            candidates.append(item)
        else:
            fallback.append(item)

    pool = candidates or fallback
    if not pool:
        return None
    best = max(pool, key=lambda p: p.stat().st_size)
    return str(best)


def download_anime(
    query: str,
    index: int,
    episode: int,
    quality: str = "720",
    dub: bool = False,
    title: str | None = None,
    job_id: str | None = None,
) -> tuple[str, str, str] | None:
    """
    Download a single anime episode via non-interactive ani-cli into `anime-dump/<job_id>/`.
    Returns (filepath, clean_filename, job_dir) on success, or None on failure.
    Caller is responsible for removing `job_dir` in a `finally` block.
    """
    ani_bin = is_ani_cli_available()
    if not ani_bin:
        raise AnimeCliUnavailableError(f"'{ANI_CLI_BIN}' is not installed on this server.")

    safe_index = max(1, int(index))
    safe_episode = max(1, min(ANIME_MAX_EPISODE, int(episode)))
    q = (quality or "720").lower().rstrip("p")
    if q not in VALID_QUALITIES:
        q = "720"

    folder_id = job_id or uuid.uuid4().hex[:8]
    job_dir = os.path.abspath(os.path.join("anime-dump", folder_id))
    os.makedirs(job_dir, exist_ok=True)

    cmd = [ani_bin, "-d", "-S", str(safe_index), "-e", str(safe_episode), "-q", q]
    if dub:
        cmd.append("--dub")
    cmd.append(query)

    env = os.environ.copy()
    env["ANI_CLI_DOWNLOAD_DIR"] = job_dir

    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=ANI_CLI_TIMEOUT_SECONDS,
            env=env,
            cwd=job_dir,
            check=False,
        )
        if proc.returncode != 0:
            logging.warning(
                "[ANIME] ani-cli exited with code %s for query '%s' ep %s",
                proc.returncode,
                query,
                safe_episode,
            )
    except Exception as err:
        logging.error("[ANIME] ani-cli download failed: %s", sanitize_error(err))
        shutil.rmtree(job_dir, ignore_errors=True)
        return None

    downloaded = _find_downloaded_file(job_dir)
    if not downloaded:
        logging.error("[ANIME] No video file produced in isolated dump directory for '%s' ep %s", query, safe_episode)
        shutil.rmtree(job_dir, ignore_errors=True)
        return None

    ext = Path(downloaded).suffix or ".mp4"
    clean_name = build_clean_anime_filename(title or query, safe_episode, q, ext)
    return downloaded, clean_name, job_dir
