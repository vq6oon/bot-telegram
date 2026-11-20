import unittest
from types import SimpleNamespace
from unittest.mock import patch

from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler
from telegram_bot import app as application

class ApplicationWiringTests(unittest.TestCase):
    def test_build_application_preserves_handler_order_and_patterns(self):
        handlers = []
        fake = SimpleNamespace(add_handler=handlers.append)
        class Builder:
            concurrent_limit = None
            def concurrent_updates(self, limit):
                self.concurrent_limit = limit
                return self
            def token(self, *_): return self
            def request(self, *_): return self
            def build(self): return fake
        builder = Builder()
        with patch.object(application, "configure_logging"), \
             patch.object(application, "HTTPXRequest"), \
             patch.object(application, "ApplicationBuilder", return_value=builder):
            application.build_application()
        actual = []
        for handler in handlers:
            if isinstance(handler, CommandHandler):
                actual.append(("command", sorted(handler.commands)[0], None))
            elif isinstance(handler, CallbackQueryHandler):
                actual.append(("callback", handler.callback.__name__, handler.pattern.pattern))
            elif isinstance(handler, MessageHandler):
                actual.append(("message", handler.callback.__name__, str(handler.filters)))
        expected_commands = ["start", "lapor", "rules", "shorten", "convert", "yt", "ig", "id", "github", "uptime", "clearcache", "whois", "list", "cleardrive", "checkdrive", "upload"]
        self.assertEqual([x[1] for x in actual if x[0] == "command"], expected_commands)
        self.assertEqual([x[1] for x in actual if x[0] == "callback"], ["menu_callback_handler", "start_callback_handler", "tiktok_callback_handler", "yt_callback_handler", "clear_drive_callback"])
        self.assertEqual([x[1] for x in actual if x[0] == "message"], ["handle_laporan_balasan", "handle_message", "handle_message"])
        self.assertEqual(builder.concurrent_limit, 8)
        self.assertEqual(len(handlers), 24)
        self.assertEqual(handlers[5].callback.__name__, handlers[23].callback.__name__)
        self.assertEqual(str(handlers[5].filters), str(handlers[23].filters))

    def test_entrypoint_only_loads_environment_and_starts_bot(self):
        from pathlib import Path
        import ast
        tree = ast.parse((Path(__file__).resolve().parents[1] / "bot.py").read_text())
        imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)]
        self.assertEqual([(node.module, [alias.name for alias in node.names]) for node in imports], [("telegram_bot.app", ["main"])])
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertEqual([call.func.id for call in calls], ["main"])
        self.assertFalse(any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in tree.body))
        self.assertFalse(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "chdir" for node in ast.walk(tree)))
if __name__ == "__main__":
    unittest.main()
