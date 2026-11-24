import logging
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from telegram.request import HTTPXRequest
from .config import BOT_TOKEN
from .logging_setup import configure_logging
from .handlers import admin, drive, general, media, reports
from .services import drive as drive_service, media as media_service

def build_application():
    configure_logging()
    request = HTTPXRequest(connect_timeout=30, read_timeout=300, write_timeout=300)
    app = ApplicationBuilder().token(BOT_TOKEN).request(request).concurrent_updates(8).build()
    app.add_handler(CommandHandler('start', general.start))
    app.add_handler(CallbackQueryHandler(general.menu_callback_handler, pattern='^open_menu_commands$'))
    app.add_handler(CallbackQueryHandler(general.start_callback_handler, pattern='^back_to_main$'))
    app.add_handler(CommandHandler('lapor', reports.lapor))
    app.add_handler(MessageHandler(filters.REPLY & ~filters.COMMAND, reports.handle_laporan_balasan))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, media.handle_message))
    app.add_handler(CommandHandler('rules', general.rules))
    app.add_handler(CommandHandler('shorten', general.shorten))
    app.add_handler(CallbackQueryHandler(media.tiktok_callback_handler, pattern='^tt\\|'))
    app.add_handler(CommandHandler('convert', media.convert))
    app.add_handler(CommandHandler('yt', media.download_youtube_command))
    app.add_handler(CommandHandler('ytm', media.download_youtube_music_command))
    app.add_handler(CommandHandler('ig', media.download_instagram_command))
    app.add_handler(CommandHandler('status', media.active_downloads_status))
    app.add_handler(CallbackQueryHandler(media.yt_callback_handler, pattern='^yt\\|'))
    app.add_handler(CommandHandler('id', general.get_id))
    app.add_handler(CommandHandler('github', general.github_command))
    app.add_handler(CommandHandler('uptime', admin.uptime))
    app.add_handler(CommandHandler('clearcache', admin.clearcache))
    app.add_handler(CommandHandler('whois', admin.whois))
    app.add_handler(CommandHandler('list', drive.list_drive_files))
    app.add_handler(CommandHandler('cleardrive', drive.clear_drive))
    app.add_handler(CommandHandler('checkdrive', drive.check_drive))
    app.add_handler(CommandHandler('upload', drive.upload))
    app.add_handler(CallbackQueryHandler(drive.clear_drive_callback, pattern='^(confirm_clear_drive|cancel_clear_drive)$'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, media.handle_message))
    return app

def main():
    app = build_application()
    logging.info("Bot aktif bos...")
    app.run_polling()
