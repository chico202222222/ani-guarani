from contextlib import contextmanager
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import requests

from video_player import play_video


class ExtractorTests(unittest.TestCase):
    def test_prefers_extractor_beside_python_without_activating_venv(self):
        def which(name, **kwargs):
            if name == "mpv":
                return "/usr/bin/mpv"
            paths = kwargs["path"].split(os.pathsep)
            self.assertEqual(paths[0], str(Path("/project/.venv/bin/python").parent))
            return "/project/.venv/bin/yt-dlp"

        with patch("video_player.sys.executable", "/project/.venv/bin/python"), patch(
            "video_player.shutil.which", side_effect=which
        ), patch("video_player.subprocess.run") as run:
            run.return_value.returncode = 0
            play_video("https://www.blogger.com/video.g?token=example")
        self.assertIn("--script-opts=ytdl_hook-ytdl_path=/project/.venv/bin/yt-dlp", run.call_args.args[0])
        self.assertEqual(run.call_args.args[0][-2:], ["--", "https://www.blogger.com/video.g?token=example"])

    def test_missing_extractor_does_not_prevent_direct_video(self):
        with patch("video_player.shutil.which", side_effect=["/usr/bin/mpv", None]), patch(
            "video_player.subprocess.run"
        ) as run, self.assertLogs("video_player", level="WARNING"):
            run.return_value.returncode = 0
            play_video("https://example.org/video.mp4")
        self.assertEqual(run.call_args.args[0], ["mpv", "--fullscreen", "--cursor-autohide-fs-only", "--", "https://example.org/video.mp4"])

    def test_cloud_cdn_receives_referrer_only_for_exact_hosts(self):
        for host in ("aniplay.online", "mangas.cloud", "aniplay.online.evil.example", "example.org"):
            with self.subTest(host=host), patch("video_player.shutil.which", return_value="/usr/bin/tool"), patch(
                "video_player.subprocess.run"
            ) as run, patch("video_player.ensure_media_exists"):
                run.return_value.returncode = 0
                play_video(f"https://{host}/video.mp4")
                self.assertEqual("--referrer=https://animesonline.cloud/" in run.call_args.args[0], host in {"aniplay.online", "mangas.cloud"})

    def test_cdn_404_does_not_launch_mpv(self):
        for status in (404, 410):
            with self.subTest(status=status), patch("video_player.requests.get") as get, patch(
                "video_player.shutil.which", return_value="/usr/bin/tool"
            ), patch("video_player.subprocess.run") as run:
                get.return_value.__enter__.return_value.status_code = status
                with self.assertRaisesRegex(RuntimeError, f"HTTP {status}"):
                    play_video("https://mangas.cloud/Animes/Letra-N/Naruto/01.mp4")
                run.assert_not_called()
                self.assertEqual(get.call_args.kwargs["headers"]["Referer"], "https://animesonline.cloud/")
                self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_cdn_other_statuses_and_network_errors_still_reach_mpv(self):
        for outcome in (200, 206, 403, 500, requests.ConnectTimeout()):
            with self.subTest(outcome=outcome), patch("video_player.requests.get") as get, patch(
                "video_player.shutil.which", return_value="/usr/bin/tool"
            ), patch("video_player.subprocess.run") as run:
                if isinstance(outcome, Exception):
                    get.side_effect = outcome
                else:
                    get.return_value.__enter__.return_value.status_code = outcome
                run.return_value.returncode = 0
                play_video("https://aniplay.online/video.mp4")
                run.assert_called_once()

    def test_relay_is_alive_during_mpv_and_closed_after_failure(self):
        active = []

        @contextmanager
        def relay(url):
            active.append(True)
            try:
                yield "http://127.0.0.1:1234/token/master.m3u8"
            finally:
                active.pop()

        def run(command, **kwargs):
            self.assertTrue(active)
            self.assertIn("--ytdl=no", command)
            self.assertEqual(command[-1], "http://127.0.0.1:1234/token/master.m3u8")
            from types import SimpleNamespace
            return SimpleNamespace(returncode=2)

        with patch("video_player.animefire_stream", side_effect=relay), patch(
            "video_player.shutil.which", return_value="/usr/bin/tool"
        ), patch("video_player.subprocess.run", side_effect=run):
            with self.assertRaises(RuntimeError):
                play_video("https://akumast.net/i/example/h.jpg")
        self.assertFalse(active)

    def test_unavailable_manifest_does_not_launch_mpv(self):
        @contextmanager
        def relay(url):
            raise RuntimeError("AnimeFire: manifesto inicial: HTTP 404 (stream indisponível).")
            yield  # O contexto falha antes da reprodução.

        with patch("video_player.animefire_stream", side_effect=relay), patch(
            "video_player.shutil.which", return_value="/usr/bin/tool"
        ), patch("video_player.subprocess.run") as run:
            with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
                play_video("https://akumast.net/i/example/h.jpg")
        run.assert_not_called()

    def test_failure_explains_how_to_update_extractor(self):
        with patch("video_player.shutil.which", side_effect=["/usr/bin/mpv", "/project/.venv/bin/yt-dlp"]), patch(
            "video_player.subprocess.run"
        ) as run:
            run.return_value.returncode = 2
            with self.assertRaisesRegex(RuntimeError, "pip install --upgrade yt-dlp"):
                play_video("https://www.blogger.com/video.g?token=example")


if __name__ == "__main__":
    unittest.main()
