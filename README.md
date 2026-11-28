# Kamui-Bot

Telegram bot for downloading YouTube, Instagram, TikTok media and anime, plus Google Drive file management. Built with `python-telegram-bot` (async), `yt-dlp`, `ffmpeg`/`ffprobe`, `ani-cli`, and Google Drive API v3. Menu version: `v3.0.0`.

## Requirements

- Python 3.10 or newer (`str | None` type syntax)
- `ffmpeg` and `ffprobe` on `PATH` (audio extraction, MP4 muxing, video resolution probing, anime sub muxing)
- Node.js or Deno on `PATH` (`yt-dlp` JS runtime for YouTube extraction)
- Python packages in `requirements.txt`: `python-telegram-bot`, `requests`, `yt-dlp[default]`, `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`, `Pillow`

## Setup and Run

```bash
git clone git@github.com:vq6oon/bot-telegram.git
cd bot-telegram
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

1. Fill in `.env` (at minimum `BOT_TOKEN`).
2. Generate `token.json` from `credentials.json`:
   ```bash
   python get_token.py
   ```
   `get_token.py` defaults to `https://www.googleapis.com/auth/drive.file`. If your bot must manage an existing Drive folder not created or opened by this app, run it with `--full-drive-access`, which grants access to all Drive files; back up the existing `token.json` first because reauthorization replaces it. For OAuth on a VPS, keep the script running and forward its callback port from your computer, for example `ssh -N -L 8765:127.0.0.1:8765 <user>@<host>`, then open the printed authorization URL locally.
3. Optional for age-restricted or bot-checked YouTube videos: place Netscape-format cookies in `cookies.txt` (or set `YTDLP_COOKIES_FILE`).
4. Start the bot from the repository root (`bot.py` runs `telegram_bot.app.main()`):
   ```bash
   python bot.py
   ```

Group usage note: Telegram bots default to Group Privacy Mode ON, which hides `reply_to_message` when members reply to non-bot messages with `/upload`. Disable `/setprivacy` in `@BotFather` (then remove and re-add the bot to the group) or grant the bot group admin status.

Logs write to both `bot-activity.log` and stderr using `[%Y-%m-%d %H:%M:%S] [LEVEL] message`; `httpx`, `telegram.bot`, and `apscheduler` stay at `WARNING`.

## Configuration

`telegram_bot/config.py` loads `<repo>/.env` via `os.environ.setdefault`, so process environment variables take precedence.

| Variable | Default | Purpose |
| --- | --- | --- |
| `BOT_TOKEN` | empty (required) | Telegram bot token |
| `OWNER_ID` | `0` | Owner ID for `/uptime`, `/clearcache`, `/whois`, `/cleardrive`; always included in Drive whitelist |
| `GITHUB_LINK` | empty | Reply URL returned by `/github` |
| `DRIVE_FOLDER_ID` | empty | Target Drive folder ID; when unset, looks up or creates `DRIVE_FOLDER_NAME` |
| `DRIVE_FOLDER_NAME` | `Bot-Uploads` | Folder name used when `DRIVE_FOLDER_ID` is empty |
| `DRIVE_ALLOWED_USER_IDS` | empty | Comma-separated Telegram user IDs allowed to run `/upload`, `/list`, `/checkdrive` (deprecated - commands are now public) |
| `DRIVE_CLEANUP_THRESHOLD_GB` | `14.0` | Storage quota threshold (min `1.0`) that triggers oldest-file auto-cleanup |
| `DRIVE_MAX_CONCURRENT_UPLOADS` | `2` | Per-loop semaphore cap for Drive uploads (min `1`) |
| `DRIVE_UPLOAD_CHUNK_SIZE_MB` | `8` | Resumable upload chunk size in MB (min `1`) |
| `DRIVE_HTTP_TIMEOUT_SECONDS` | `180` | Socket timeout per Drive HTTP call (min `30`) |
| `DRIVE_UPLOAD_MAX_RETRIES` | `5` | Chunk retry limit on transient network/HTTP errors (min `1`) |
| `MAX_CONCURRENT_DOWNLOADS` | `3` | Per-loop semaphore cap for concurrent YouTube jobs (min `1`) |
| `DOWNLOAD_RATELIMIT_KBPS` | `0` | Optional `yt-dlp` bandwidth limit in KB/s (`0` = unlimited) |
| `YTDLP_COOKIES_FILE` / `COOKIE_FILE_PATH` | `<repo>/cookies.txt` | Path to YouTube cookies file |
| `TELEGRAM_API_BASE_URL` | `https://api.telegram.org/bot` | Telegram Bot API endpoint; override for a local Bot API server |
| `TELEGRAM_FILE_BASE_URL` | `https://api.telegram.org/file/bot` | Telegram file endpoint; override for a local Bot API server |
| `MAX_TELEGRAM_DOWNLOAD_SIZE` | `20971520` | Telegram download limit in bytes; set `0` only with local Bot API server |

`TELEGRAM_API_BASE_URL` and `TELEGRAM_FILE_BASE_URL` default to Telegram's hosted Bot API. Set both to the matching URLs for a local Bot API server. `MAX_TELEGRAM_DOWNLOAD_SIZE` defaults to `20971520` bytes (`20 MiB`); set it to `0` only when using a local Bot API server, which can download files without size limit. Hosted Bot API bots cannot use `/upload` to fetch this 2.9 GB file; enable a local Bot API server first. `MAX_TELEGRAM_FILE_SIZE` (`50 MB` bot send limit) remains unchanged. `UPLOAD_TOKEN` and `CHANNEL_ID` in `.env.example` belong only to the standalone `uploader.py` script.

## Commands

All media downloads require explicit commands; plain chat messages and uncommanded links are ignored.

| Command | Handler | Behavior |
| --- | --- | --- |
| `/start` | `general.start` | Sends a welcome greeting and points users to `/menu` |
| `/menu` | `general.menu` | Sends menu banner and public command caption. `/menu --admin` (owner only) sends the admin caption with owner commands |
| `/changelog` | `changelog.changelog` | Shows 15 recent git commits with conventional commit formatting |
| `/github` | `general.github_command` | Replies with `GITHUB_LINK` |
| `/contributor` | `general.contributor` | Lists bot contributors from `menus/contributors.py` |
| `/rules` | `general.rules` | Displays usage rules |
| `/id` | `general.get_id` | Replies with user ID, username, and full name |
| `/shorten <url>` | `general.shorten` | Shortens an `http`/`https` URL via TinyURL |
| `/yt <link>` | `media.download_youtube_command` | Queries available video tiers (`360p`, `480p`, `720p`, `1080p`, or `Best`) from `formats`, plus `MP3` and `Subtitle` (`id`/`en`/`es` if present) |
| `/ytm <link>` | `media.download_youtube_music_command` | Downloads `music.youtube.com` audio as MP3 titled `uploader - title` |
| `/ig <link>` | `media.download_instagram_command` | Downloads Instagram posts/Reels merged to MP4 |
| `/tt <link>` | `media.download_tiktok_command` | Fetches TikTok media via `tikwm.com`; sends photo albums (up to 10) or video/audio picker to the requester's DM |
| `/anime <title> [-e <ep>]` | `anime.download_anime_command` | Search anime via `ani-cli`, show episode counts, auto-mux subtitles with `ffmpeg` |
| `/status` | `media.active_downloads_status` | Lists active queued, downloading, or uploading jobs |
| `/convert` | `media.convert` | Reply to a video (`<= 20 MB`) to extract MP3 audio via `ffmpeg` |
| `/upload` | `drive.upload` | **Public.** Reply to any media (`document`, `video`, `audio`, `animation`, `voice`, `video_note`, `photo`), cross-chat `external_reply`, or send captioned media (`/upload`) up to `20 MB` |
| `/list` | `drive.list_drive_files` | **Public.** Lists 20 newest Drive files and quota usage |
| `/checkdrive` | `drive.check_drive` | **Public.** Reports Drive storage usage and total |
| `/cleardrive` | `drive.clear_drive` | Owner only. Inline confirmation before deleting all files in the Drive folder |
| `/uptime`, `/clearcache`, `/whois <id>` | `admin` | Owner only. Process uptime, local cache cleanup (`youtube-dump`, `ig-dump`, `subs`), and Telegram user lookup |

Inline callback prefixes: `yt|...` (locked to `owner_id`, 12-char hex token in `bot_data`), `tt|...` (locked to `owner_id`, 8-char ID in `user_data`), `anime|...`, `confirm_clear_drive`, and `cancel_clear_drive`.

## Media and Drive Architecture

- **Pre-download deduplication:** Before queuing `yt-dlp`, `yt_callback_handler` calls `find_cached_youtube_file()` to match `appProperties` (`yt_video_id`, `yt_mode`, `yt_res`) inside the target Drive folder. Hits return the existing Drive link immediately.
- **Resolution accuracy and filenames:** `extract_available_resolutions()` hides resolution buttons absent from video metadata (handling landscape, vertical Shorts, and ultrawide streams). After download, `probe_video_resolution()` verifies the output stream via `ffprobe` so fallbacks still produce accurate filenames (`<title> (<res>p).mp4` or `<title>.mp3`) and Drive cache metadata.
- **Scoped cookies:** `scoped_cookie_file()` copies `cookies.txt` to an isolated temporary file per `yt-dlp` call so concurrent downloads never corrupt shared cookies.
- **Anime subs auto-mux:** `ani-cli` downloads episodes with separate subtitle tracks; `mux_subtitles_ffmpeg()` burns them into MP4 via `ffmpeg` before sending.
- **Telegram vs. Drive routing:** Files `<= 50 MB` go directly to Telegram (`status.delete()` followed by the media message). Files `> 50 MB` (or direct sends failing with `BadRequest` / `TimedOut`) route to `_upload_and_notify_drive()`.
- **Fresh completion notices:** Both Drive media uploads and `/upload` use `deliver_fresh_message()` to post a new message at the bottom of the chat (replying to the requester's message when available) and remove the old progress status message.
- **Thread-safe Drive v3 transport:** `get_drive_service()` builds a fresh `AuthorizedHttp` + Drive v3 client per worker call with `DRIVE_HTTP_TIMEOUT_SECONDS`, strips HTTP `308` from `httplib2` `redirect_codes` so resumable chunks are not misread as missing redirects, refreshes expired tokens atomically (`0o600` + `os.replace`) under `_token_lock`, retries transient chunk errors with exponential backoff, and runs `auto_cleanup_drive()` after uploads.
- **Redaction:** `sanitize_error()` strips bearer tokens, JSON/query credentials, and local filesystem paths before logging or replying.

## Project Layout

```text
bot.py                               Entry point (calls telegram_bot.app.main)
get_token.py                         OAuth setup script writing token.json (0o600)
requirements.txt                     Python dependencies
uploader.py                          Standalone helper bot forwarding docs to CHANNEL_ID
ig_scraper.py                        Standalone Playwright scraper (not imported by bot)
assets/                              Menu banner image (`kamui.png` used by `/menu`)
telegram_bot/
  app.py                             ApplicationBuilder, timeouts, handler registration
  config.py                          .env loader and runtime constants
  logging_setup.py                   File + stderr logging configuration
  state.py                           BOT_START, user_cooldowns
  handlers/                          general, admin, changelog, drive, media
  menus/                             welcome.py, commands.py, contributors.py
  services/                          drive.py, job_tracker.py, media.py, subtitles.py, tiktok.py, anime.py
tests/                               Unit test suite (70 tests, offline)
```

Runtime temp directories (`youtube-dump/`, `ig-dump/`, `subs/`, `converted/`) and sensitive files (`.env`, `cookies.txt`, `credentials.json`, `token.json`, `bot-activity.log`) are excluded from version control.

## Tests

Run all unit tests offline:

```bash
python -m unittest discover -s tests -v
```

The unit tests cover Drive token refresh, atomic `0o600` writes, resumable upload updates and cleanup pagination, error redaction, `/upload` media/external-reply detection and fresh completion replies, YouTube resolution filtering, `ffprobe` fallback labeling, clean `<title> (<res>p).mp4` filenames, `/yt` + `/ytm` + `/tt` + `/anime` command isolation, welcome/menu behavior, changelog rendering, and handler registration order.