import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from history import read_history, save_history
from loader import get_resource_path
from menu import Cancelled, menu
from repository import Repository
from video_player import play_video
import main


class HistoryTests(unittest.TestCase):
    def test_first_save_and_update(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "nested" / "history.json"
            sources = [(["https://example.org/1", "https://example.org/2"], "test")]
            save_history("A", 0, sources, path)
            save_history("A", 1, sources, path)
            self.assertTrue(path.is_file())
            self.assertEqual(read_history(path)["A"][1], 1)
            self.assertEqual(len(list(path.parent.iterdir())), 1)

    def test_corrupt_history_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "history.json"
            path.write_text("broken")
            with self.assertRaises(RuntimeError):
                save_history("A", 0, [], path)
            self.assertEqual(path.read_text(), "broken")

    def test_invalid_index(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "history.json"
            path.write_text(json.dumps({"A": [[[['url'], 'source']], 5]}))
            with self.assertRaises(RuntimeError):
                read_history(path)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.rep = Repository()

    def test_instances_do_not_reset_each_other(self):
        self.rep.add_anime("A", "url", "test")
        Repository()
        self.assertEqual(self.rep.get_anime_titles(), ["A"])

    def test_empty_sources(self):
        with self.assertRaises(RuntimeError):
            self.rep.search_anime("A")

    def test_episode_cache_and_longest_list(self):
        self.rep.add_episode_list("A", ["1"], ["u1"], "a")
        self.rep.add_episode_list("A", ["1", "2"], ["u1", "u2"], "b")
        self.rep.search_episodes("A")
        self.assertEqual(self.rep.get_episode_list("A"), ["1", "2"])

    def test_failed_source_does_not_hide_success(self):
        class Broken:
            @staticmethod
            def search_player_src(url, container, event):
                raise ValueError("offline")

        class Good:
            @staticmethod
            def search_player_src(url, container, event):
                container.append("https://example.org/video")

        self.rep.sources = {"bad": Broken, "good": Good}
        self.rep.anime_episodes_urls["A"] = [(["url"], "bad"), (["url"], "good")]
        with self.assertLogs("repository", level="WARNING"):
            self.assertEqual(self.rep.search_player("A", 1), "https://example.org/video")

    def test_invalid_player_does_not_cancel_good_source(self):
        for invalid in ("blob:https://example.org/id", "https:", "https://[broken", "", 42):
            with self.subTest(invalid=invalid):
                invalid_finished = Event()
                test = self

                class Invalid:
                    @staticmethod
                    def search_player_src(url, container, event):
                        container.append(invalid)
                        invalid_finished.set()

                class Good:
                    @staticmethod
                    def search_player_src(url, container, event):
                        test.assertTrue(invalid_finished.wait(2))
                        test.assertFalse(event.is_set())
                        container.append("https://example.org/video")

                self.rep.sources = {"bad": Invalid, "good": Good}
                self.rep.anime_episodes_urls["A"] = [(["url"], "bad"), (["url"], "good")]
                with self.assertLogs("repository", level="WARNING"):
                    self.assertEqual(self.rep.search_player("A", 1), "https://example.org/video")

    def test_only_invalid_player_fails_without_setting_event(self):
        events = []

        class Invalid:
            @staticmethod
            def search_player_src(url, container, event):
                events.append(event)
                container.append("blob:https://example.org/id")

        self.rep.sources = {"bad": Invalid}
        self.rep.anime_episodes_urls["A"] = [(["url"], "bad")]
        with self.assertLogs("repository", level="WARNING"):
            with self.assertRaisesRegex(RuntimeError, "Nenhum player encontrado"):
                self.rep.search_player("A", 1)
        self.assertFalse(events[0].is_set())

    def test_no_player(self):
        with self.assertRaises(RuntimeError):
            self.rep.search_player("unknown", 1)

    def test_do_not_merge_seasons(self):
        self.rep.add_anime("Anime Season 1", "a", "a")
        self.rep.add_anime("Anime Season 2", "b", "b")
        self.assertEqual(len(self.rep.get_anime_titles()), 2)


class CliTests(unittest.TestCase):
    def test_menu_does_not_modify_options(self):
        options = ["A", "B"]
        with patch("menu.curses", None), patch("builtins.input", side_effect=["bad", "2"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(menu(options), "B")
        self.assertEqual(options, ["A", "B"])

    def test_menu_cancel_and_empty(self):
        with self.assertRaises(ValueError):
            menu([])
        with patch("menu.curses", None), patch("builtins.input", return_value="0"), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(Cancelled):
                menu(["A"])

    def test_help_without_plugins(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
            main.cli(["--help"])
        self.assertEqual(result.exception.code, 0)

    def test_resource_path_is_absolute(self):
        self.assertTrue(Path(get_resource_path("plugins")).is_absolute())

    def test_player_rejects_options_and_local_files(self):
        for value in ["--script=evil", "file:///etc/passwd", "javascript:alert(1)", "https:"]:
            with self.assertRaises(ValueError):
                play_video(value)

    def test_player_failure(self):
        with patch("video_player.shutil.which", return_value="/bin/mpv"), patch("video_player.subprocess.run") as run:
            run.return_value.returncode = 1
            with self.assertRaises(RuntimeError):
                play_video("https://example.org/video")
            self.assertEqual(run.call_args.args[0][-2:], ["--", "https://example.org/video"])


if __name__ == "__main__":
    unittest.main()
