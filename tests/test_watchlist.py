import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from menu import Cancelled
from repository import Repository
from watchlist import add_to_watchlist, in_watchlist, read_watchlist, remove_from_watchlist, watchlist_path

SOURCES = [(["ep1", "ep2", "ep3"], "animesonlinecloud"), (["ep1", "ep2"], "animefire")]


class WatchlistStorageTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.path = Path(self.root.name) / "state" / "watchlist.json"

    def test_missing_file_is_empty(self):
        self.assertEqual(read_watchlist(self.path), {})
        self.assertFalse(in_watchlist("A", self.path))

    def test_add_remove_roundtrip_keeps_order_and_sources(self):
        self.assertTrue(add_to_watchlist("B", SOURCES, self.path))
        self.assertTrue(add_to_watchlist("A", SOURCES[:1], self.path))
        self.assertFalse(add_to_watchlist("B", SOURCES[:1], self.path))  # já existia: atualiza
        data = read_watchlist(self.path)
        self.assertEqual(list(data), ["B", "A"])
        self.assertEqual(data["B"], [[["ep1", "ep2", "ep3"], "animesonlinecloud"]])  # atualizada na 2ª chamada
        self.assertTrue(remove_from_watchlist("B", self.path))
        self.assertFalse(remove_from_watchlist("B", self.path))
        self.assertEqual(list(read_watchlist(self.path)), ["A"])

    def test_invalid_sources_are_rejected_before_writing(self):
        for bad in ([], [[[], "x"]], [[["a"], 3]], "texto"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                add_to_watchlist("A", bad, self.path)
        self.assertFalse(self.path.exists())

    def test_corrupt_file_is_reported_not_overwritten(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{ruim", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Não foi possível ler"):
            add_to_watchlist("A", SOURCES, self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{ruim")

    def test_wrong_shape_is_reported(self):
        self.path.parent.mkdir(parents=True)
        for payload in ([], {"A": []}, {"A": [[["x"], "s", 1]]}, {"": [[["x"], "s"]]}):
            self.path.write_text(json.dumps(payload), encoding="utf-8")
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                read_watchlist(self.path)

    def test_default_path_is_next_to_history(self):
        from history import history_path
        self.assertEqual(watchlist_path().parent, history_path().parent)


class WatchlistFlowTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.dir = Path(self.root.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.repo = Repository()
        self.history = {}
        patches = {
            "rep": self.repo,
            "read_history": lambda: self.history,
            "save_history": lambda *a: None,
            "status": lambda m: self.messages.append(m),
        }
        self.messages = []
        for name, value in patches.items():
            self.stack.enter_context(patch.object(main, name, value))
        for name, func in (("read_watchlist", read_watchlist), ("add_to_watchlist", add_to_watchlist),
                           ("remove_from_watchlist", remove_from_watchlist), ("in_watchlist", in_watchlist)):
            self.stack.enter_context(patch.object(main, name, lambda *a, f=func: f(*a, path=self.dir / "w.json")))
        self.stack.enter_context(patch.object(main.loader, "load_plugins", side_effect=lambda *a: self.repo.sources.update(
            {"animesonlinecloud": object(), "animefire": object()})))
        self.play = self.stack.enter_context(patch.object(main, "play_video"))
        self.stack.enter_context(patch.object(self.repo, "search_players", side_effect=lambda *a: iter(["https://example.org/v"])))

    def args(self, **kw):
        base = dict(source=None, continue_watching=False, debug=False, watchlist=False, add_watchlist=False, query="Naruto")
        return SimpleNamespace(**{**base, **kw})

    def fake_search(self, title="Naruto"):
        def search_anime(query):
            self.repo.anime_episodes_urls[title] = SOURCES
        self.stack.enter_context(patch.object(self.repo, "search_anime", side_effect=search_anime))
        self.stack.enter_context(patch.object(self.repo, "get_anime_titles", return_value=[title]))
        self.stack.enter_context(patch.object(self.repo, "search_episodes"))
        self.stack.enter_context(patch.object(self.repo, "get_episode_list", return_value=["1", "2", "3"]))

    def test_add_flag_saves_without_playing(self):
        self.fake_search()
        with patch.object(main, "menu", side_effect=lambda opts, msg: opts[0]):
            main.main(self.args(add_watchlist=True))
        self.play.assert_not_called()
        self.assertEqual(list(read_watchlist(self.dir / "w.json")), ["Naruto"])
        # Repetir não duplica e informa que apenas atualizou as fontes.
        with patch.object(main, "menu", side_effect=lambda opts, msg: opts[0]):
            main.main(self.args(add_watchlist=True))
        self.assertEqual(list(read_watchlist(self.dir / "w.json")), ["Naruto"])
        self.assertTrue(any("Já estava na lista" in message for message in self.messages))

    def test_toggle_from_post_play_menu_adds_then_removes(self):
        self.fake_search()
        seen = []

        answers_post = iter([main.ADD_LABEL, main.REMOVE_LABEL])

        def choose_all(options, message):
            if message in ("Escolha o anime:", "Escolha o episódio:"):
                return options[0]
            seen.append(list(options))
            try:
                return next(answers_post)
            except StopIteration:
                raise Cancelled

        with patch.object(main, "menu", side_effect=choose_all), self.assertRaises(Cancelled):
            main.main(self.args())
        self.assertEqual(seen[0], ["Próximo", main.ADD_LABEL])
        self.assertEqual(seen[1], ["Próximo", main.REMOVE_LABEL])
        self.assertEqual(seen[2], ["Próximo", main.ADD_LABEL])
        self.assertEqual(read_watchlist(self.dir / "w.json"), {})
        self.assertEqual(self.play.call_count, 1)  # alternar a lista não reproduz de novo

    def test_watchlist_menu_shows_progress_and_plays_from_history(self):
        add_to_watchlist("Naruto", SOURCES, self.dir / "w.json")
        add_to_watchlist("Bleach", SOURCES, self.dir / "w.json")
        self.history = {"Naruto": [SOURCES, 1]}
        labels = []

        def choose(options, message):
            if message == "Sua lista para assistir:":
                labels.extend(options)
                return options[0]
            if message == "Naruto":
                return "Assistir"
            raise Cancelled

        with patch.object(main, "menu", side_effect=choose), self.assertRaises(Cancelled):
            main.main(self.args(watchlist=True, query=None))
        self.assertEqual(labels, ["Naruto (último episódio: 2)", "Bleach (não iniciado)"])
        # Retoma do episódio salvo no histórico (índice 1 => episódio 2).
        self.repo.search_players.assert_called_once_with("Naruto", 2)
        self.play.assert_called_once()

    def test_remove_from_watchlist_menu_until_empty(self):
        add_to_watchlist("Naruto", SOURCES, self.dir / "w.json")

        def choose(options, message):
            return "Remover da lista" if message == "Naruto" else options[0]

        with patch.object(main, "menu", side_effect=choose):
            main.main(self.args(watchlist=True, query=None))
        self.assertEqual(read_watchlist(self.dir / "w.json"), {})
        self.play.assert_not_called()
        self.assertIn("Sua lista para assistir está vazia.", self.messages)

    def test_empty_watchlist_does_not_open_menu(self):
        with patch.object(main, "menu", side_effect=AssertionError("menu não deve abrir")):
            main.main(self.args(watchlist=True, query=None))
        self.assertTrue(any("vazia" in message for message in self.messages))

    def test_watchlist_respects_enabled_sources(self):
        add_to_watchlist("Naruto", [(["a"], "animefire")], self.dir / "w.json")
        self.repo.sources.clear()
        with patch.object(main.loader, "load_plugins", side_effect=lambda *a: self.repo.sources.update({"animesonlinecloud": object()})), \
                patch.object(main, "menu", side_effect=lambda opts, msg: "Assistir" if msg == "Naruto" else opts[0]), \
                self.assertRaisesRegex(RuntimeError, "não tem fontes habilitadas"):
            main.main(self.args(watchlist=True, query=None, source=["animesonlinecloud"]))

    def test_cli_rejects_conflicting_flags(self):
        for argv in (["-l", "-q", "x"], ["-l", "-c"], ["-l", "-a"], ["-a", "-c"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                main.cli(argv)
            self.assertEqual(result.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
