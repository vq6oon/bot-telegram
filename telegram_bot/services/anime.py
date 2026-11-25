"""Hybrid ani-cli wrapper for anime search (fzf shim) and isolated single-episode downloads."""
import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
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
_EPISODE_ONLY_RE = re.compile(r"^\d+(?:\.\d+)?$")
_TITLE_EPISODE_RE = re.compile(r"\((\d+)\s+episodes?\)\s*$", re.IGNORECASE)
_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".ts", ".avi", ".mov", ".m4v"}
_SUBTITLE_EXTENSIONS = {".vtt", ".srt", ".ass", ".ssa"}
_TEMP_SUFFIXES = (".part", ".tmp", ".ytdl", ".aria2")
VALID_QUALITIES = ("360", "720", "1080", "best")


class AnimeCliUnavailableError(RuntimeError):
    """Raised when the ani-cli binary is not found in PATH."""


class AnimeNotFoundError(LookupError):
    """Raised when ani-cli reports zero search matches."""


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


def _strip_ani_cli_list_numbers(lines: list[str]) -> list[str]:
    if len(lines) < 2:
        return lines
    stripped: list[str] = []
    for idx, line in enumerate(lines, start=1):
        prefix = str(idx)
        if not line.startswith(prefix):
            return lines
        rest = line[len(prefix):]
        if not rest or rest[0] not in (" ", "\t"):
            return lines
        title = rest.strip()
        if not title:
            return lines
        stripped.append(title)
    return stripped


def _clean_captured_titles(raw_text: str, max_results: int = 5) -> list[str]:
    non_empty = [
        cleaned
        for line in raw_text.splitlines()
        if (cleaned := _ANSI_ESCAPE_RE.sub("", line).strip())
    ]
    if not non_empty:
        return []
    if all(_EPISODE_ONLY_RE.match(item) for item in non_empty):
        return non_empty[:max_results]
    return _strip_ani_cli_list_numbers(non_empty)[:max_results]


def _write_executable_shim(path: str, script: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(script)
    try:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def _build_shim_env(shim_dir: str, *, capture_fzf: bool) -> tuple[dict[str, str], str | None]:
    # Always shadow mpv at the front of PATH so ani-cli never launches a GUI player.
    _write_executable_shim(os.path.join(shim_dir, "mpv"), "#!/bin/sh\nexit 0\n")

    capture_file: str | None = None
    if capture_fzf:
        capture_file = os.path.join(shim_dir, "captured.txt")
        _write_executable_shim(
            os.path.join(shim_dir, "fzf"),
            "#!/bin/sh\ncat > \"$ANI_CLI_CAPTURE_FILE\"\nexit 1\n",
        )
    elif not shutil.which("fzf"):
        _write_executable_shim(os.path.join(shim_dir, "fzf"), "#!/bin/sh\nhead -n 1\n")

    env = os.environ.copy()
    env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '')}"
    env["ANI_CLI_PLAYER"] = "mpv"
    if capture_file:
        env["ANI_CLI_CAPTURE_FILE"] = capture_file
    return env, capture_file


def _collect_proc_output(proc) -> str:
    return " ".join(
        part.strip()
        for part in (getattr(proc, "stderr", ""), getattr(proc, "stdout", ""))
        if part
    )


def search_anime(query: str, max_results: int = 5) -> list[str]:
    """
    Capture up to `max_results` titles from ani-cli using a temporary fzf + player shim.
    Raises AnimeNotFoundError on explicit zero-result responses, and returns [] on fallback.
    """
    ani_bin = is_ani_cli_available()
    if not ani_bin:
        raise AnimeCliUnavailableError(f"'{ANI_CLI_BIN}' is not installed on this server.")

    with tempfile.TemporaryDirectory(prefix="anicli-shim-") as shim_dir:
        env, capture_file = _build_shim_env(shim_dir, capture_fzf=True)

        try:
            proc = subprocess.run(
                [ani_bin, "-d", query],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=ANI_CLI_SEARCH_TIMEOUT_SECONDS,
                env=env,
                check=False,
            )
        except Exception as err:
            logging.warning("[ANIME] Search shim failed for '%s': %s", query, sanitize_error(err))
            return []

        raw = ""
        if capture_file and os.path.isfile(capture_file):
            try:
                raw = Path(capture_file).read_text(encoding="utf-8", errors="replace")
            except OSError as err:
                logging.warning("[ANIME] Failed to read captured search results: %s", sanitize_error(err))
                return []

        titles = _clean_captured_titles(raw, max_results=max_results)
        if titles:
            # Single search match skips the title menu in ani-cli and pipes episode numbers to fzf.
            if all(_EPISODE_ONLY_RE.match(item) for item in titles):
                logging.info("[ANIME] Single search match for '%s'; defaulting to #1", query)
                return []
            return titles

        output = _collect_proc_output(proc)
        if "no results found" in output.lower():
            raise AnimeNotFoundError(f"No anime found for '{query}'.")
        if output or getattr(proc, "returncode", 0) != 0:
            logging.warning(
                "[ANIME] Search returned no list for '%s' (code=%s): %s",
                query,
                getattr(proc, "returncode", "?"),
                sanitize_error(RuntimeError(output[:200] or "empty output")),
            )
        return []


def fetch_anime_episodes(query: str, index: int, dub: bool = False) -> list[int]:
    """
    Probe available episode numbers for a specific ani-cli result index without downloading.
    Returns sorted unique integer episode numbers, or [] if unavailable / single-match.
    """
    ani_bin = is_ani_cli_available()
    if not ani_bin:
        return []

    safe_index = max(1, int(index))
    cmd = [ani_bin, "-S", str(safe_index)]
    if dub:
        cmd.append("--dub")
    cmd.append(query)

    with tempfile.TemporaryDirectory(prefix="anicli-ep-shim-") as shim_dir:
        env, capture_file = _build_shim_env(shim_dir, capture_fzf=True)
        try:
            subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=min(ANI_CLI_SEARCH_TIMEOUT_SECONDS, 15),
                env=env,
                check=False,
            )
        except Exception as err:
            logging.warning("[ANIME] Episode probe failed for '%s' (#%s): %s", query, safe_index, sanitize_error(err))
            return []

        if not capture_file or not os.path.isfile(capture_file):
            return []

        try:
            raw = Path(capture_file).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

    lines = [
        cleaned
        for line in raw.splitlines()
        if (cleaned := _ANSI_ESCAPE_RE.sub("", line).strip())
    ]
    if not lines or not all(_EPISODE_ONLY_RE.match(item) for item in lines):
        return []

    episodes = sorted({int(float(item)) for item in lines if int(float(item)) >= 1})
    return episodes


def _parse_title_episode_count(title: str) -> tuple[str, int | None]:
    match = _TITLE_EPISODE_RE.search(title)
    if not match:
        return title, None
    count = int(match.group(1))
    clean_title = title[:match.start()].strip() or title
    return clean_title, count if count >= 1 else None


def search_anime_with_episodes(query: str, max_results: int = 5) -> list[dict]:
    """
    Search titles via ani-cli and attach known total episode counts.
    Returns list of {'title': str, 'episodes': int | None}.
    """
    titles = search_anime(query, max_results=max_results)
    if not titles:
        return []

    entries: list[dict] = []
    missing_indices: list[int] = []
    for idx, raw_title in enumerate(titles, start=1):
        clean_title, count = _parse_title_episode_count(raw_title)
        entries.append({"title": clean_title, "episodes": count})
        if count is None:
            missing_indices.append(idx)

    if missing_indices:
        with ThreadPoolExecutor(max_workers=len(missing_indices)) as pool:
            futures = {idx: pool.submit(fetch_anime_episodes, query, idx) for idx in missing_indices}
            for idx, fut in futures.items():
                try:
                    eps = fut.result()
                    if eps:
                        entries[idx - 1]["episodes"] = max(eps)
                except Exception:
                    pass

    return entries


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


def _find_subtitle_file(job_dir: str) -> str | None:
    root = Path(job_dir)
    if not root.is_dir():
        return None
    subs = [
        item
        for item in root.rglob("*")
        if item.is_file()
        and item.suffix.lower() in _SUBTITLE_EXTENSIONS
        and item.stat().st_size > 0
    ]
    if not subs:
        return None
    best = max(subs, key=lambda p: p.stat().st_size)
    return str(best)


def _run_ffmpeg_mux(ffmpeg_bin: str, video_path: str, sub_path: str, out_path: str, sub_codec: str) -> bool:
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        video_path,
        "-i",
        sub_path,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-map",
        "1:0",
        "-c",
        "copy",
        "-c:s",
        sub_codec,
        "-metadata:s:s:0",
        "language=eng",
        out_path,
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=ANI_CLI_TIMEOUT_SECONDS,
            check=False,
        )
        return proc.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0
    except Exception as err:
        logging.warning("[ANIME] ffmpeg mux failed (%s): %s", sub_codec, sanitize_error(err))
        return False


def _mux_softsub_if_present(video_path: str, job_dir: str) -> str:
    """Embed external .vtt/.srt/.ass subtitle track into the video when present."""
    sub_path = _find_subtitle_file(job_dir)
    if not sub_path:
        return video_path

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        logging.warning("[ANIME] Softsub found (%s) but ffmpeg is missing; skipping mux.", Path(sub_path).name)
        return video_path

    src = Path(video_path)
    mp4_target = str(src.with_name(f"{src.stem}_muxed.mp4"))
    if src.suffix.lower() in {".mp4", ".m4v", ".mov"} and _run_ffmpeg_mux(ffmpeg_bin, video_path, sub_path, mp4_target, "mov_text"):
        logging.info("[ANIME] Auto-muxed softsub %s into %s", Path(sub_path).name, Path(mp4_target).name)
        return mp4_target

    mkv_target = str(src.with_name(f"{src.stem}_muxed.mkv"))
    mkv_codec = "srt" if Path(sub_path).suffix.lower() == ".vtt" else "copy"
    if _run_ffmpeg_mux(ffmpeg_bin, video_path, sub_path, mkv_target, mkv_codec):
        logging.info("[ANIME] Auto-muxed softsub %s into %s", Path(sub_path).name, Path(mkv_target).name)
        return mkv_target

    logging.warning("[ANIME] Softsub auto-mux failed for %s; returning raw video.", Path(sub_path).name)
    return video_path


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

    with tempfile.TemporaryDirectory(prefix="anicli-dl-shim-") as shim_dir:
        env, _ = _build_shim_env(shim_dir, capture_fzf=False)
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
                detail = _collect_proc_output(proc)
                logging.warning(
                    "[ANIME] ani-cli exited %s for '%s' ep %s: %s",
                    proc.returncode,
                    query,
                    safe_episode,
                    sanitize_error(RuntimeError(detail[:200] or "no output")),
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

    final_video = _mux_softsub_if_present(downloaded, job_dir)
    ext = Path(final_video).suffix or ".mp4"
    clean_name = build_clean_anime_filename(title or query, safe_episode, q, ext)
    return final_video, clean_name, job_dir
