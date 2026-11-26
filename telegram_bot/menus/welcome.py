"""Welcome text and command menu sections for /start and /menu."""

WELCOME_MESSAGE = (
    "Kamui-Bot · v3.0.0\n\n"
    "Welcome! Send a supported command to get started.\n"
    "Use /menu to view available commands.\n\n"
    "@vq6oon"
)

_BRAND = "Kamui-Bot · v3.0.0"
_HANDLE = "@vq6oon"

_INFO = (
    "› Info\n"
    "/start · welcome message\n"
    "/menu · show this menu\n"
    "/github · developer profile\n"
    "/contributor · bot contributors\n"
    "/changelog · recent changes\n"
    "/rules · usage rules\n"
    "/id · Telegram account ID\n"
)

_DOWNLOAD = (
    "› Download\n"
    "/yt <url> · YouTube video and format selection\n"
    "/ytm <url> · YouTube Music audio\n"
    "/ig <url> · Instagram media\n"
    "/tt <url> · TikTok media\n"
    "/anime <title> [-e <ep>] · search anime and choose episode\n"
)

_PUBLIC_DRIVE = (
    "› Drive\n"
    "/checkdrive · Drive storage status\n"
    "/list · list Drive files\n"
    "/upload · upload replied or captioned media\n"
)

_SEARCH = "› Search\n/shorten <url> · shorten URL\n"

_PUBLIC_TOOLS = (
    "› Tools\n"
    "/convert · extract MP3 from replied video\n"
    "/status · active download status\n"
)

_ADMIN_ONLY = (
    "› Admin\n"
    "/cleardrive · clear Drive folder\n"
    "/clearcache · clear media cache\n"
    "/uptime · bot uptime\n"
    "/whois <id> · Telegram user info\n"
)

MENU_CAPTION = "\n".join(
    [_BRAND, _INFO, _DOWNLOAD, _PUBLIC_DRIVE, _SEARCH, _PUBLIC_TOOLS, _HANDLE]
)

ADMIN_CAPTION = "\n".join([f"{_BRAND} · admin", _ADMIN_ONLY, _HANDLE])
