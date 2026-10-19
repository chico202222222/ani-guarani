import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main
from menu import Cancelled
from repository import Repository


class ResumeTests(unittest.TestCase):
    def run_resume(self, sources, index, menu, repository):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(main, "rep", repository))
        stack.enter_context(patch.object(main.loader, "load_plugins", side_effect=lambda *args: repository.sources.update({"animefire": object()})))
        stack.enter_context(patch.object(main, "read_history", return_value={"Anime": [sources, index]}))
        stack.enter_context(patch.object(main, "menu", side_effect=menu))
        player = stack.enter_context(patch.object(repository, "search_player", return_value="https://example.org/video"))
        play = stack.enter_context(patch.object(main, "play_video"))
        save = stack.enter_context(patch.object(main, "save_history"))
        stack.enter_context(patch.object(main, "status"))
        args = SimpleNamespace(source=["animefire"], continue_watching=True, debug=False)
        return args, player, play, save

    def test_disabled_source_does_not_offer_extra_episodes(self):
        sources = [(["one"], "animefire"), (["one", "two"], "animesonlinecc")]
        repository = Repository()
        calls = []

        def choose(options, message):
            calls.append(options)
            return options[0]

        args, player, play, save = self.run_resume(sources, 0, choose, repository)
        main.main(args)
        self.assertEqual(len(calls), 1)  # Sem menu Próximo no único episódio habilitado.
        self.assertEqual(repository.anime_episodes_urls["Anime"], sources[:1])
        player.assert_called_once_with("Anime", 1)
        play.assert_called_once()
        save.assert_called_once_with("Anime", 0, sources)  # Preserva fontes desabilitadas no disco.

    def test_saved_episode_unavailable_has_clear_error(self):
        sources = [(["one"], "animefire"), (["one", "two"], "animesonlinecc")]
        args, player, play, save = self.run_resume(sources, 1, lambda opts, msg: opts[0], Repository())
        with self.assertRaisesRegex(RuntimeError, "episódio salvo não está disponível"):
            main.main(args)
        player.assert_not_called()
        play.assert_not_called()
        save.assert_not_called()

    def test_no_enabled_history_source_has_clear_error(self):
        args, player, play, save = self.run_resume([(["one"], "animesonlinecc")], 0, lambda opts, msg: opts[0], Repository())
        with self.assertRaisesRegex(RuntimeError, "não tem fontes habilitadas"):
            main.main(args)
        player.assert_not_called()
        save.assert_not_called()

    def test_next_previous_only_use_enabled_source_length(self):
        sources = [(["one", "two"], "animefire"), (["one", "two", "three"], "animesonlinecc")]
        calls = []

        def choose(options, message):
            calls.append(options)
            if len(calls) == 1:
                return options[0]
            if len(calls) == 2:
                return "Próximo"
            if len(calls) == 3:
                return "Anterior"
            raise Cancelled

        args, player, play, save = self.run_resume(sources, 0, choose, Repository())
        with self.assertRaises(Cancelled):
            main.main(args)
        self.assertEqual(calls[1:], [["Próximo"], ["Anterior"], ["Próximo"]])
        self.assertEqual([call.args[1] for call in player.call_args_list], [1, 2, 1])

    def test_manga_flags_are_rejected(self):
        for flag in ("--manga", "-m"):
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                main.cli([flag])
            self.assertEqual(result.exception.code, 2)

    def test_help_is_anime_only(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as result:
            main.cli(["--help"])
        self.assertEqual(result.exception.code, 0)
        self.assertNotIn("--manga", output.getvalue())


if __name__ == "__main__":
    unittest.main()
