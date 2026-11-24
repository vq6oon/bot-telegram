import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram_bot.handlers import anime as anime_handler
from telegram_bot.services import anime as anime_service


class AnimeServiceTests(unittest.TestCase):
    def test_parse_args_supports_title_and_single_episode(self):
        query, ep, err = anime_service.parse_anime_command_args(["frieren", "beyond", "-e", "12"])
        self.assertIsNone(err)
        self.assertEqual(query, "frieren beyond")
        self.assertEqual(ep, 12)

        query2, ep2, err2 = anime_service.parse_anime_command_args(["one", "piece"])
        self.assertIsNone(err2)
        self.assertEqual(query2, "one piece")
        self.assertIsNone(ep2)

    def test_parse_args_rejects_bulk_ranges_and_invalid_episodes(self):
        for bad_args in (
            [],
            ["frieren", "-e"],
            ["frieren", "-e", "1-5"],
            ["frieren", "-e", "1,2"],
            ["frieren", "-e", "0"],
            ["frieren", "-e", "abc"],
        ):
            with self.subTest(bad_args=bad_args):
                _, _, err = anime_service.parse_anime_command_args(bad_args)
                self.assertIsNotNone(err)

    def test_build_clean_anime_filename(self):
        self.assertEqual(
            anime_service.build_clean_anime_filename("Frieren: Journey?", 3, "720", ".mp4"),
            "Frieren Journey - Ep 3 (720p).mp4",
        )
        self.assertEqual(
            anime_service.build_clean_anime_filename("Naruto", 1, "best", "mkv"),
            "Naruto - Ep 1 (Best).mkv",
        )

    def test_search_anime_captures_fzf_shim_and_strips_ansi(self):
        def fake_run(cmd, **kwargs):
            self.assertIn("-d", cmd)
            capture = kwargs["env"]["ANI_CLI_CAPTURE_FILE"]
            shim_dir = kwargs["env"]["PATH"].split(os.pathsep)[0]
            self.assertTrue(os.path.isfile(os.path.join(shim_dir, "mpv")))
            self.assertTrue(os.path.isfile(os.path.join(shim_dir, "fzf")))
            Path(capture).write_text(
                "\x1b[32mFrieren (28 episodes)\x1b[0m\nFrieren Dub\nTitle 3\nTitle 4\nTitle 5\nTitle 6\n",
                encoding="utf-8",
            )
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            return SimpleNamespace(returncode=1, stdout="", stderr="")

        with patch.object(anime_service, "is_ani_cli_available", return_value="/usr/bin/ani-cli"), \
             patch.object(anime_service.shutil, "which", return_value=None), \
             patch.object(anime_service.subprocess, "run", side_effect=fake_run):
            results = anime_service.search_anime("frieren", max_results=5)

        self.assertEqual(len(results), 5)
        self.assertEqual(results[0], "Frieren (28 episodes)")

    def test_search_anime_raises_not_found_and_ignores_episode_only_capture(self):
        not_found = SimpleNamespace(returncode=1, stdout="No results found!\n", stderr="")
        with patch.object(anime_service, "is_ani_cli_available", return_value="/usr/bin/ani-cli"), \
             patch.object(anime_service.subprocess, "run", return_value=not_found):
            with self.assertRaises(anime_service.AnimeNotFoundError):
                anime_service.search_anime("aldi makan bakso")

        def single_match_run(cmd, **kwargs):
            Path(kwargs["env"]["ANI_CLI_CAPTURE_FILE"]).write_text("1\n2\n3\n", encoding="utf-8")
            return SimpleNamespace(returncode=1, stdout="", stderr="")

        with patch.object(anime_service, "is_ani_cli_available", return_value="/usr/bin/ani-cli"), \
             patch.object(anime_service.subprocess, "run", side_effect=single_match_run):
            self.assertEqual(anime_service.search_anime("exact single match"), [])

    def test_search_anime_strips_ani_cli_list_numbers_without_dropping_duplicates(self):
        def numbered_run(cmd, **kwargs):
            Path(kwargs["env"]["ANI_CLI_CAPTURE_FILE"]).write_text(
                "1 Witch on the Holy Night\n2 Witch on the Holy Night\n3 86\n",
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=1, stdout="", stderr="")

        with patch.object(anime_service, "is_ani_cli_available", return_value="/usr/bin/ani-cli"), \
             patch.object(anime_service.subprocess, "run", side_effect=numbered_run):
            results = anime_service.search_anime("witch", max_results=5)

        self.assertEqual(
            results,
            ["Witch on the Holy Night", "Witch on the Holy Night", "86"],
        )

    def test_download_anime_passes_noninteractive_flags_and_returns_file(self):
        captured_cmd = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            out_dir = kwargs["env"]["ANI_CLI_DOWNLOAD_DIR"]
            out_file = Path(out_dir) / "raw_video.mp4"
            out_file.write_bytes(b"video-data")
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp_cwd:
            old_cwd = os.getcwd()
            os.chdir(tmp_cwd)
            try:
                with patch.object(anime_service, "is_ani_cli_available", return_value="/usr/bin/ani-cli"), \
                     patch.object(anime_service.subprocess, "run", side_effect=fake_run):
                    res = anime_service.download_anime(
                        "frieren", index=2, episode=4, quality="1080", dub=True, title="Frieren", job_id="job1"
                    )
                self.assertIsNotNone(res)
                filepath, clean_name, job_dir = res
                self.assertTrue(os.path.isfile(filepath))
                self.assertEqual(clean_name, "Frieren - Ep 4 (1080p).mp4")
                self.assertTrue(job_dir.endswith(os.path.join("anime-dump", "job1")))
                self.assertEqual(
                    captured_cmd,
                    ["/usr/bin/ani-cli", "-d", "-S", "2", "-e", "4", "-q", "1080", "--dub", "frieren"],
                )
            finally:
                os.chdir(old_cwd)


class AnimeHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_guards_missing_ani_cli(self):
        msg = SimpleNamespace(reply_text=AsyncMock(), message_id=10)
        update = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=1, username="u", first_name="U"))
        context = SimpleNamespace(args=["frieren"], bot_data={})

        with patch.object(anime_handler, "is_ani_cli_available", return_value=None):
            await anime_handler.download_anime_command(update, context)

        msg.reply_text.assert_awaited_once()
        self.assertIn("not installed", msg.reply_text.await_args.args[0])

    async def test_command_reports_no_anime_found(self):
        status = SimpleNamespace(edit_text=AsyncMock())
        msg = SimpleNamespace(reply_text=AsyncMock(return_value=status), message_id=10)
        update = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=1, username="u", first_name="U"))
        context = SimpleNamespace(args=["aldi", "makan", "bakso"], bot_data={})

        with patch.object(anime_handler, "is_ani_cli_available", return_value="/usr/bin/ani-cli"), \
             patch.object(anime_handler, "search_anime", side_effect=anime_handler.AnimeNotFoundError("none")):
            await anime_handler.download_anime_command(update, context)

        status.edit_text.assert_awaited_once()
        self.assertIn("No anime found", status.edit_text.await_args.args[0])

    async def test_callback_enforces_owner_lock(self):
        query = SimpleNamespace(
            data="anime|go||tok1234567",
            from_user=SimpleNamespace(id=999, username="intruder", first_name="Bad"),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
        context = SimpleNamespace(bot_data={"anime_tok1234567": {"owner_id": 111, "title": "Frieren"}})

        await anime_handler.anime_callback_handler(update, context)

        query.answer.assert_awaited_once()
        self.assertTrue(query.answer.await_args.kwargs.get("show_alert"))
        query.edit_message_text.assert_not_awaited()

    async def test_callback_routes_large_file_to_drive_and_cleans_up_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            job_dir = os.path.join(tmp_dir, "job_cleanup")
            os.makedirs(job_dir, exist_ok=True)
            fake_video = os.path.join(job_dir, "ep1.mp4")
            Path(fake_video).write_bytes(b"x" * 1024)

            status_msg = SimpleNamespace(edit_text=AsyncMock(), delete=AsyncMock(), chat_id=55)
            query = SimpleNamespace(
                data="anime|go||tok1234567",
                from_user=SimpleNamespace(id=111, username="owner", first_name="Owner"),
                message=SimpleNamespace(chat_id=55),
                answer=AsyncMock(),
                edit_message_text=AsyncMock(return_value=status_msg),
            )
            update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
            context = SimpleNamespace(
                bot=SimpleNamespace(send_document=AsyncMock()),
                bot_data={
                    "anime_tok1234567": {
                        "query": "frieren",
                        "results": ["Frieren"],
                        "owner_id": 111,
                        "owner_tag": "@owner",
                        "index": 1,
                        "title": "Frieren",
                        "dub": False,
                        "quality": "720",
                        "episode": 1,
                        "reply_to_message_id": 77,
                    }
                },
            )

            with patch.object(anime_handler, "MAX_TELEGRAM_FILE_SIZE", 512), \
                 patch.object(anime_handler, "download_anime", return_value=(fake_video, "Frieren - Ep 1 (720p).mp4", job_dir)), \
                 patch.object(anime_handler, "_upload_and_notify_drive", new=AsyncMock(return_value="https://drive.google.com/file/d/abc/view")) as mock_upload:
                await anime_handler.anime_callback_handler(update, context)

            mock_upload.assert_awaited_once()
            self.assertFalse(os.path.exists(job_dir))


if __name__ == "__main__":
    unittest.main()
