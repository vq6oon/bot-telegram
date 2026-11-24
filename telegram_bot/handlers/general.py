from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import os
import requests
import logging
from ..config import GITHUB_LINK

from ..state import START_IMAGE_FILE_ID
from ..menus.welcome import WELCOME_CAPTION
from ..menus.commands import COMMANDS_CAPTION


async def shorten(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Contoh penggunaan:\n/shorten https://youtube.com/...")

    url = context.args[0]

    if not url.startswith("http"):
        return await update.message.reply_text("Link tidak valid. Harus diawali dengan http atau https.")

    try:
        res = requests.get(f"https://tinyurl.com/api-create.php?url={url}", timeout=10)
        short_url = res.text
        await update.message.reply_text(f"Shortlink:\n{short_url}")
    except Exception as e:
        await update.message.reply_text(f"Gagal membuat shortlink: {e}")

async def github_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logging.info(f"[GITHUB] {get_user_info(user)} membuka GitHub")
    await update.message.reply_text(f"Ini link GitHub saya:\n{GITHUB_LINK}")

def get_user_info(user):
    return f"{user.id} (@{user.username or '-'} / {user.full_name})"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global START_IMAGE_FILE_ID
    image_path = os.path.join("assets", "v1.5.png")

    caption = WELCOME_CAPTION

    keyboard = [[InlineKeyboardButton("Daftar Perintah Bot", callback_data="open_menu_commands")]]

    try:
        with open(image_path, "rb") as photo:
            msg = await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            START_IMAGE_FILE_ID = msg.photo[-1].file_id

            user = update.effective_user
            logging.info(f"[START] {get_user_info(user)} membuka menu utama")

    except Exception as e:
        await update.message.reply_text(f"Gagal kirim gambar pembuka: {e}")
        user = update.effective_user
        logging.info(f"[START] {get_user_info(user)} membuka menu utama")

async def menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    logging.info(f"[MENU] {get_user_info(user)} membuka daftar perintah")

    caption = COMMANDS_CAPTION

    keyboard = [[InlineKeyboardButton("Kembali", callback_data="back_to_main")]]

    try:
        await query.edit_message_caption(
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        await query.edit_message_text(f"Gagal tampilkan menu perintah: {e}")

async def start_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global START_IMAGE_FILE_ID
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    logging.info(f"[BACK] {get_user_info(user)} kembali ke menu utama")

    if not START_IMAGE_FILE_ID:
        await query.edit_message_text("Gambar pembuka belum tersedia.")
        return

    caption = WELCOME_CAPTION

    keyboard = [[InlineKeyboardButton("Daftar Perintah Bot", callback_data="open_menu_commands")]]

    try:
        await context.bot.edit_message_media(
            media=InputMediaPhoto(media=START_IMAGE_FILE_ID, caption=caption, parse_mode=ParseMode.MARKDOWN),
            chat_id=query.message.chat.id,
            message_id=query.message.message_id,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logging.warning(f"[BACK] Gagal edit media: {e}")
        try:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=START_IMAGE_FILE_ID,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            logging.info(f"[BACK] {get_user_info(query.from_user)} fallback kirim ulang menu utama")
        except Exception as err:
            await query.edit_message_text(f"Gagal tampilkan menu utama: {err}")

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*Aturan Penggunaan Lamp1on-Bot:*\n\n"
        "1. Gunakan bot secara *wajar*, jangan spam link atau file.\n"
        "2. Link yang didukung: *YouTube, TikTok, Instagram*.\n"
        "3. File besar akan diunggah ke *Google Drive publik*.\n"
        "4. *Jangan unggah konten ilegal, pornografi, atau bajakan*.\n"
        "5. Bot dapat menghapus file lama jika Drive penuh.\n"
        "6. Gunakan /lapor jika ada bug atau kendala.\n\n"
        "Dengan menggunakan bot ini, kamu dianggap setuju dengan aturan di atas."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logging.info(f"[ID] {get_user_info(user)} melihat ID-nya")
    await update.message.reply_text(
        f"ID kamu: `{user.id}`\n"
        f"Username: @{user.username or '-'}\n"
        f"Nama: {user.full_name}",
        parse_mode=ParseMode.MARKDOWN
    )
