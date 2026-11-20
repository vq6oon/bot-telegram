import os
import requests
import yt_dlp
import logging

def yt_progress_hook(d):
    if d['status'] == 'downloading' and context and status_msg:
        downloaded = d.get('downloaded_bytes', 0)
        total = d.get('total_bytes') or d.get('total_bytes_estimate', 1)
        bar = generate_progress_bar(downloaded, total)
        print(f"Progress: {downloaded}/{total}")

        try:
            asyncio.run_coroutine_threadsafe(
                status_msg.edit_text(f"📥 Mengunduh...\n{bar}"),
                context.application.loop
            )
        except Exception as e:
            logging.warning(f"[yt_dlp] Gagal update progress: {e}")

def generate_progress_bar(downloaded: int, total: int, length: int = 20):
    if total == 0:
        return "[----------] 0%"
    progress = int(length * downloaded / total)
    bar = "█" * progress + "─" * (length - progress)
    percent = downloaded / total * 100
    return f"[{bar}] {percent:.1f}%"

async def download_file_with_progress(context, url, filename, chat_id):
    msg = await context.bot.send_message(chat_id, text="⬇️ Sedang mengunduh...")
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 1024 * 32
            with open(filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            bar = generate_progress_bar(downloaded, total)
                            try:
                                await msg.edit_text(f"📁 Mengunduh...{bar}")
                            except:
                                pass
        await msg.edit_text("✅ Unduhan selesai.")
        return True
    except Exception as e:
        await msg.edit_text(f"❌ Gagal mengunduh: {e}")
        return False

def download_youtube(url: str, mode: str = "video", resolution: str = None, music: bool = False):
    try:
        out_dir = "youtube-dump"
        os.makedirs(out_dir, exist_ok=True)
        if mode == "audio":
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": f"{out_dir}/%(uploader)s - %(title).50s.%(ext)s" if music else f"{out_dir}/%(title).50s.%(ext)s",
                "quiet": True,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            }
        else:
            res_filter = f"[height={resolution}]" if resolution else ""
            ydl_opts = {
                "format": f"bestvideo{res_filter}+bestaudio/best",
                "outtmpl": f"{out_dir}/%(title).50s_{resolution or 'best'}.%(ext)s",
                "merge_output_format": "mp4",
                "quiet": True,
                "noplaylist": True,
                "postprocessors": [{
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }],
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            ext = ".mp3" if mode == "audio" else ".mp4"
            if not filepath.endswith(ext):
                filepath = os.path.splitext(filepath)[0] + ext
            title = f"{info.get('uploader', '')} - {info.get('title', '')}" if music else info.get("title", "YouTube")
            return filepath, title
    except Exception as e:
        logging.error(f"YouTube download error: {e}")
        return None
