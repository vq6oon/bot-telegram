"""Generate Google Drive OAuth2 token.json using Desktop App credentials."""
import os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

# Scope: manage files created or opened by this app
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"


def main():
    if not CREDENTIALS_FILE.exists():
        print(f"Error: '{CREDENTIALS_FILE.name}' not found in {BASE_DIR}")
        print("Save your OAuth client credentials from Google Cloud Console as credentials.json.")
        return

    print("Starting Google Drive OAuth2 flow...")
    print(f"Scope: {SCOPES[0]}")
    print("Opening browser for authorization...")

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    # offline access + prompt=consent forces Google to issue a refresh token
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    temp_file = TOKEN_FILE.with_suffix(".tmp")
    try:
        with open(temp_file, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
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
