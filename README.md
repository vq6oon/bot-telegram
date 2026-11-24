# Lamp1on-Bot (Telegram)

Telegram bot for media downloads and Google Drive storage. Built with `python-telegram-bot` v20+ async handlers, `yt-dlp`, and the Drive v3 API. Menu version string: `v1.5.0`.

## Requirements

- Python 3.10 or newer (the code uses `str | None` annotations; verified on 3.11)
- `ffmpeg` on `PATH` — yt-dlp extracts MP3 and muxes MP4
- Packages from `requirements.txt`: `python-telegram-bot`, `requests`, `yt-dlp`, `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`, `Pillow`

## Install and run

```bash
git clone git@github.com:vq6oon/bot-telegram.git
cd bot-telegram
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then fill BOT_TOKEN, OWNER_ID, ...
.venv/bin/python bot.py
```

`bot.py` is a four-line entry point that calls `main()` in `telegram_bot/app.py`. Run it from the repository root: `/start` opens `assets/v1.5.png` by relative path.

`build_application()` configures logging, builds the application with `HTTPXRequest(connect_timeout=30, read_timeout=300, write_timeout=300)` and `concurrent_updates(8)`, then registers every handler before `run_polling()`.

Logs go to `bot-activity.log` plus stderr, format `[%Y-%m-%d %H:%M:%S] [LEVEL] message`; `httpx`, `telegram.bot`, and `apscheduler` loggers are pinned to WARNING.

## Configuration

`telegram_bot/config.py` loads `.env` from the repository root with `os.environ.setdefault`, so real environment variables win.

| Variable | Default | Used for |
| --- | --- | --- |
| `BOT_TOKEN` | empty (required) | Telegram bot token |
| `OWNER_ID` | `0` | Admin commands: `/uptime`, `/clearcache`, `/whois`, `/cleardrive`; also always added to the Drive whitelist |
| `GROUP_LAPOR_ID` | `0` | Chat that receives `/lapor` reports |
| `GITHUB_LINK` | empty | Reply text of `/github` |
| `DRIVE_FOLDER_ID` | empty | Target Drive folder; when empty the bot searches for or creates `DRIVE_FOLDER_NAME` |
| `DRIVE_FOLDER_NAME` | `Bot-Uploads` | Folder name to find or create |
| `DRIVE_ALLOWED_USER_IDS` | empty | Comma-separated Telegram IDs allowed to use `/upload`, `/list`, `/checkdrive` |
| `DRIVE_CLEANUP_THRESHOLD_GB` | `14` | Storage usage that triggers auto-cleanup; clamped to at least 1 |
| `DRIVE_MAX_CONCURRENT_UPLOADS` | `2` | Semaphore size for `/upload` |

`UPLOAD_TOKEN` and `CHANNEL_ID` in `.env.example` are only read by the standalone `uploader.py`, not by the bot. `COOLDOWN_SECONDS = 30` and `MAX_TELEGRAM_FILE_SIZE = 50 MiB` are constants; the cooldown is no longer applied — updates are handled independently.

## Commands

Registered in `telegram_bot/app.py`, listed in `telegram_bot/menus/commands.py`.

| Command | Handler | Behavior |
| --- | --- | --- |
| `/start` | `general.start` | Sends `assets/v1.5.png` with the welcome caption and a "Daftar Perintah Bot" button |
| `/github` | `general.github_command` | Replies with `GITHUB_LINK` |
| `/rules` | `general.rules` | Usage rules |
| `/id` | `general.get_id` | Telegram ID, username, full name |
| `/shorten <url>` | `general.shorten` | TinyURL shortlink |
| `/lapor` | `reports.lapor` | Asks for a report with `ForceReply`; the reply is forwarded to `GROUP_LAPOR_ID` |
| `/convert <name>` | `media.convert` | Reply to a video: downloads it, converts to `converted/<name>.mp3` with ffmpeg, sends audio, or uploads to Drive above 50 MiB |
| `/yt <link>` | `media.download_youtube_command` | Shows an inline keyboard: 360p / 720p / 1080p, MP3, Subtitle (only when `id`/`en`/`es` subtitles exist), Cancel |
| `/ytm <link>` | `media.download_youtube_music_command` | Requires a `music.youtube.com` host; downloads MP3, title becomes `uploader - title` |
| `/ig <link>` | `media.download_instagram_command` | Downloads the best Instagram/Reels media with yt-dlp (mp4 merge) |
| `/upload` | `drive.upload` | Reply to a document to store it in Drive (whitelist, semaphore, temp file) |
| `/list` | `drive.list_drive_files` | 20 newest files with links plus quota (whitelist) |
| `/checkdrive` | `drive.check_drive` | Free / total Drive space (whitelist) |
| `/cleardrive` | `drive.clear_drive` | Owner only; inline confirm, then deletes every file in the folder |
| `/uptime`, `/clearcache`, `/whois <id>` | `admin` | Owner only; uptime uses `BOT_START`, `/clearcache` removes `youtube-dump`, `ig-dump`, `subs` |

Plain text that is not a command goes to `media.handle_message`, which routes by URL:

- `youtube.com` / `youtu.be` — `music.youtube.com` links download MP3 immediately, everything else shows the format keyboard
- links containing `tiktok.com` — metadata from `tikwm.com`; photo posts are sent as a private album (max 10 photos), video/audio as a private keyboard
- `instagram.com` — Instagram download
- anything else — "Link tidak dikenali"

Callback buttons: `open_menu_commands`, `back_to_main`, `yt|…`, `tt|…`, `confirm_clear_drive`, `cancel_clear_drive`. YouTube URLs are stored in `bot_data[f"yt_{token}"]` with a 12-hex-character token to stay inside Telegram's 64-byte `callback_data` limit. TikTok entries live in `user_data` keyed `tt_<8 chars>` and record `owner_id`, so only the person who sent the link can press the button.

## Media and Drive flow

Files up to `MAX_TELEGRAM_FILE_SIZE` (50 MiB) go back through Telegram; anything larger is uploaded to Drive because the Bot API caps downloads at 50 MB.

- `media._upload_media_to_drive(file_path, title, status_msg)` is the single Drive path for media. It edits the status message, runs `upload_to_drive` and `get_drive_usage` inside `asyncio.to_thread` so the event loop is not blocked, and edits the message again with the link and free space. Errors are logged through `sanitize_error` and answered with a generic message.
- YouTube video downloads that hit `telegram.error.TimedOut` while sending also fall back to a Drive upload.
- Temporary files live in `youtube-dump/`, `ig-dump/`, `subs/`, `converted/`, or `tempfile.mkstemp` for TikTok, and are removed in `finally` blocks.
- `/upload` writes the Telegram download to a `NamedTemporaryFile` created next to `handlers/drive.py`, so a Windows temp directory cannot break the rename-free upload, then deletes it in `finally`.
- `DRIVE_MAX_CONCURRENT_UPLOADS` limits simultaneous `/upload` runs through an `asyncio.Semaphore`.

## Drive service

`telegram_bot/services/drive.py`:

- Token path is fixed to `<repo>/token.json`. Missing, unreadable, expired-without-refresh, or rejected tokens raise `GoogleDriveAuthError`, which every handler turns into "run `get_token.py`" advice.
- Refresh happens under a `threading.Lock` because uploads run in worker threads. The refreshed token is written to a temp file in the same directory with mode `0o600`, `fsync`ed, then `os.replace`d over `token.json`.
- `upload_to_drive(path, folder_id=None, custom_name=None)` rejects a missing source path before any API call, uses `MediaFileUpload(..., resumable=True)`, and updates an existing same-name file instead of creating a duplicate with stale content. Setting public `anyone/reader` permission is best effort; a failure is logged, not raised.
- `auto_cleanup_drive` runs after each upload: when `storageQuota.usage` reaches `DRIVE_CLEANUP_THRESHOLD_BYTES` it deletes the oldest files in the target folder (`orderBy=createdTime`) until usage drops below the threshold.
- `clear_drive_files_sync` and `auto_cleanup_drive` re-list the first page after every delete pass instead of following page tokens, so shifting pagination cannot skip files; both stop when a page is empty or nothing could be deleted.
- `sanitize_error` redacts bearer tokens, `access_token`/`refresh_token`/`client_secret`/`api_key` values, query-string tokens, and Windows paths before logging or replying.
- Folder and file names are escaped for Drive query syntax by `_escape_drive_query`.

`get_token.py` requests `https://www.googleapis.com/auth/drive.file`. That scope only covers files the client created or opened; to manage a folder that already exists, change `SCOPES` to `https://www.googleapis.com/auth/drive` before running it. The script performs the OAuth flow, writes `token.json` atomically, and sets mode `0o600`.

## Project layout

```
bot.py                      entry point
get_token.py                OAuth flow, writes token.json
uploader.py                 separate helper bot: forwards documents to CHANNEL_ID using UPLOAD_TOKEN
ig_scraper.py               Playwright Instagram scraper, unused by the bot (playwright is not in requirements.txt)
requirements.txt            runtime dependencies
telegram_bot/app.py         application builder, handler registration
telegram_bot/config.py      env loading and constants
telegram_bot/state.py       BOT_START, START_IMAGE_FILE_ID, user_cooldowns
telegram_bot/logging_setup.py
telegram_bot/handlers/      general, media, drive, admin, reports
telegram_bot/services/      drive, media (yt-dlp), tiktok, subtitles
telegram_bot/menus/         welcome and command captions
tests/                      unittest suites
assets/                     banners referenced by /start and /info
```

Runtime directories created on demand: `youtube-dump/`, `ig-dump/`, `subs/`, `converted/`, `temp_upload/`. `token.json`, `credentials.json`, `.env`, `*.log`, and `__pycache__` are gitignored.

## Tests

```bash
.venv/bin/python -m unittest \
  tests.test_drive_service tests.test_drive_handler tests.test_media_commands \
  tests.test_menu_modules tests.test_refactor tests.test_tiktok_concurrency \
  tests.test_tiktok_isolation tests.test_tiktok_photo_privacy tests.test_ytm_command
```

26 tests, no network. They cover token refresh and atomic `0o600` writes, same-name replacement, pagination-safe cleanup, missing source paths, the `/upload` worker-thread path with temp-file cleanup, URL host validation, yt-dlp option building, handler registration order, menu contents, TikTok per-user isolation and DM-only photo delivery, and the `/ytm` flow. `tests/` has no `__init__.py`, so `python -m unittest discover -s tests` fails with "Start directory is not importable" — list the modules explicitly.

## Notes

- The `filters.TEXT & ~filters.COMMAND` message handler is registered twice in `app.py`; the second registration is unreachable.
- `/start` caches the uploaded photo in `START_IMAGE_FILE_ID` at module level, so the Back button only works after a `/start` in the same process.
- `uploader.py` expects `temp_upload/` to exist and a channel ID; `ig_scraper.py` would need `playwright` and browsers installed.
- Never commit `.env`, `credentials.json`, or `token.json`.
