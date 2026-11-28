"""Generate Google Drive OAuth2 token.json using Desktop App credentials."""
import argparse
import os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

# Least-privilege default: only files this app created or opened.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FULL_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"

BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"
CALLBACK_PORT = 8765


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Generate Google Drive OAuth2 token.json.")
    parser.add_argument(
        "--full-drive-access",
        action="store_true",
        help="request full Drive access for folders created outside this app",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=CALLBACK_PORT,
        help=f"local OAuth callback port (default: {CALLBACK_PORT}; forward it over SSH on a VPS)",
    )
    args = parser.parse_args(argv)

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    if not CREDENTIALS_FILE.exists():
        print(f"Error: '{CREDENTIALS_FILE.name}' not found in {BASE_DIR}")
        print("Save your OAuth client credentials from Google Cloud Console as credentials.json.")
        return

    scopes = [FULL_DRIVE_SCOPE] if args.full_drive_access else SCOPES

    print("Starting Google Drive OAuth2 flow...")
    print(f"Scope: {', '.join(scopes)}")
    if args.full_drive_access:
        print("Full Drive access requested: this grants access to all files in your Drive.")
    print(f"Callback listens on localhost:{args.port}.")
    print(f"On a VPS, first run locally: ssh -N -L {args.port}:127.0.0.1:{args.port} <user>@<host>")
    print("Authorize in your browser when the URL appears below.")

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), scopes)
    # offline access + prompt=consent forces Google to issue a refresh token
    creds = flow.run_local_server(
        host="localhost",
        bind_addr="127.0.0.1",
        port=args.port,
        open_browser=False,
        access_type="offline",
        prompt="consent",
    )

    temp_file = TOKEN_FILE.with_suffix(".tmp")
    try:
        with open(temp_file, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
            token.flush()
            os.fsync(token.fileno())
        os.chmod(temp_file, 0o600)
        os.replace(temp_file, TOKEN_FILE)
        try:
            os.chmod(TOKEN_FILE, 0o600)
        except OSError:
            pass
    except Exception:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass
        raise

    print(f"Token saved to: {TOKEN_FILE.name}")
    print("Google Drive integration is ready.")


if __name__ == "__main__":
    main()
