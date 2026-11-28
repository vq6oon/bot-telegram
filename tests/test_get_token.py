import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import get_token


class GetTokenTests(unittest.TestCase):
    def _run(self, argv, token_json):
        result = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials = Path(temp_dir, "credentials.json")
            credentials.write_text("{}", encoding="utf-8")
            token = Path(temp_dir, "token.json")
            flow = Mock()
            flow.run_local_server.return_value.to_json.return_value = token_json

            with patch.object(get_token, "CREDENTIALS_FILE", credentials), \
                 patch.object(get_token, "TOKEN_FILE", token), \
                 patch.object(get_token.InstalledAppFlow, "from_client_secrets_file", return_value=flow) as create_flow:
                get_token.main(argv)

            result["create_flow"] = create_flow
            result["flow"] = flow
            result["token_text"] = token.read_text(encoding="utf-8")
            result["token_mode"] = stat.S_IMODE(token.stat().st_mode)
            result["credentials"] = str(credentials)
        return result

    def test_default_scope_is_limited_to_drive_file(self):
        result = self._run([], '{"token":"fresh"}')

        result["create_flow"].assert_called_once_with(
            result["credentials"], ["https://www.googleapis.com/auth/drive.file"]
        )
        result["flow"].run_local_server.assert_called_once_with(
            host="localhost",
            bind_addr="127.0.0.1",
            port=get_token.CALLBACK_PORT,
            open_browser=False,
            access_type="offline",
            prompt="consent",
        )
        self.assertEqual(result["token_text"], '{"token":"fresh"}')
        if os.name != "nt":
            self.assertEqual(result["token_mode"], 0o600)

    def test_full_drive_access_is_opt_in_and_accepts_custom_port(self):
        result = self._run(["--full-drive-access", "--port", "9001"], '{"token":"wide"}')

        result["create_flow"].assert_called_once_with(
            result["credentials"], ["https://www.googleapis.com/auth/drive"]
        )
        kwargs = result["flow"].run_local_server.call_args.kwargs
        self.assertEqual(kwargs["port"], 9001)
        self.assertFalse(kwargs["open_browser"])
        self.assertEqual(result["token_text"], '{"token":"wide"}')

    def test_rejects_invalid_port_before_starting_oauth(self):
        with self.assertRaises(SystemExit):
            get_token.main(["--port", "0"])


if __name__ == "__main__":
    unittest.main()
