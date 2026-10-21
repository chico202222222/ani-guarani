import io
import logging
import time
import unittest
from unittest.mock import patch

import progress
from progress import Loading
from repository import Repository


class FakeTty(io.StringIO):
    encoding = "utf-8"

    def isatty(self):
        return True


class LoadingTests(unittest.TestCase):
    def test_non_tty_prints_message_once_without_control_codes(self):
        stream = io.StringIO()
        with Loading("Buscando…", stream):
            time.sleep(0.15)
        self.assertEqual(stream.getvalue(), "Buscando…\n")

    def test_dumb_terminal_is_not_animated(self):
        stream = FakeTty()
        with patch.dict(progress.os.environ, {"TERM": "dumb"}):
            with Loading("Buscando…", stream):
                pass
        self.assertEqual(stream.getvalue(), "Buscando…\n")

    def test_tty_animates_and_restores_the_cursor(self):
        stream = FakeTty()
        with patch.object(progress, "FRAME_SECONDS", 0.01), Loading("Buscando…", stream):
            time.sleep(0.15)
        out = stream.getvalue()
        self.assertTrue(out.startswith("\033[?25l"))
        self.assertTrue(out.endswith("\r\033[K\033[?25h"))
        self.assertIn("Buscando…", out)
        self.assertGreater(out.count("\r\033[K"), 3)

    def test_error_inside_block_still_cleans_up(self):
        stream = FakeTty()
        with self.assertRaises(ValueError):
            with Loading("x", stream):
                raise ValueError
        self.assertTrue(stream.getvalue().endswith("\033[?25h"))

    def test_determinate_bar_fills_to_the_reported_fraction(self):
        loading = Loading("x", FakeTty())
        loading.color = False
        loading.update(2, 4)
        for _ in range(200):
            frame = loading._frame()
        self.assertIn(" 50%", frame)
        self.assertIn(" 2/4", frame)

    def test_progress_never_goes_backwards_or_past_100(self):
        loading = Loading("x", FakeTty())
        loading.update(4, 4)
        shown = []
        for _ in range(300):
            loading._frame()
            shown.append(loading._shown)
        self.assertEqual(shown, sorted(shown))
        self.assertEqual(shown[-1], 1.0)

    def test_ascii_fallback_without_utf8(self):
        stream = FakeTty()
        stream.encoding = "ascii"
        loading = Loading("x", stream)
        loading.color = False
        self.assertTrue(loading._frame().isascii())

    def test_long_message_is_truncated_to_the_terminal(self):
        loading = Loading("a" * 500, FakeTty())
        loading.color = False
        with patch.object(progress.shutil, "get_terminal_size", return_value=progress.os.terminal_size((60, 20))):
            self.assertLessEqual(len(loading._frame()), 60)

    def test_log_warning_clears_the_bar_line_first(self):
        stream = FakeTty()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            with Loading("x", stream):
                logging.warning("fonte caiu")
            self.assertNotIn("emit", handler.__dict__)
        finally:
            root.removeHandler(handler)
        self.assertIn("\r\033[KWARNING: fonte caiu\n", stream.getvalue())


class RepositoryProgressTests(unittest.TestCase):
    def test_run_reports_each_finished_source(self):
        repo = Repository()
        calls = []
        repo.progress = lambda done, total: calls.append((done, total))

        def boom():
            raise RuntimeError("falhou")

        repo._run([("a", lambda: None, ()), ("b", boom, ()), ("c", lambda: None, ())])
        self.assertEqual(calls, [(0, 3), (1, 3), (2, 3), (3, 3)])


if __name__ == "__main__":
    unittest.main()
