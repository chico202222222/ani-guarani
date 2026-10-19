"""Interface de linha de comando do ani-guarani."""
import argparse
import logging
import os
import sys

import loader
from history import read_history, save_history
from menu import Cancelled, menu
from repository import rep
from video_player import play_video


def status(message):
    color = sys.stderr.isatty() and "NO_COLOR" not in os.environ
    print(f"\033[36m{message}\033[0m" if color else message, file=sys.stderr, flush=True)


def main(args):
    rep.sources.clear()
    loader.load_plugins({"pt-br"}, args.source)
    if not rep.sources:
        raise RuntimeError("Nenhuma fonte carregada. Instale requirements.txt e confira os avisos acima.")
    if args.continue_watching:
        data = read_history()
        if not data:
            status("Você ainda não tem histórico. Busque um anime com -q.")
            return
        titles = {f"{title} (último episódio: {entry[1] + 1})": title for title, entry in data.items()}
        selected_anime = titles[menu(list(titles), "Continue assistindo:")]
        history_sources, episode_idx = data[selected_anime]
        sources = [(urls, source) for urls, source in history_sources if source in rep.sources]
        if not sources:
            raise RuntimeError("Este anime não tem fontes habilitadas no histórico. Habilite uma fonte salva ou faça uma nova busca.")
        num_episodes = max(len(urls) for urls, source in sources)
        if episode_idx >= num_episodes:
            raise RuntimeError("O episódio salvo não está disponível nas fontes habilitadas. Habilite a fonte original ou faça uma nova busca.")
        rep.anime_episodes_urls[selected_anime] = sources
    else:
        query = (args.query if args.query is not None else input("Pesquise anime: ")).strip()
        if not query:
            raise ValueError("Informe um termo de busca, por exemplo: ani-guarani -q Naruto.")
        status("Buscando animes nas fontes disponíveis…")
        rep.search_anime(query)
        selected_anime = menu(rep.get_anime_titles(), "Escolha o anime:")
        status("Carregando episódios…")
        rep.search_episodes(selected_anime)
        episodes = rep.get_episode_list(selected_anime)
        labels = [f"{index + 1}. {title}" for index, title in enumerate(episodes)]
        episode_idx = labels.index(menu(labels, "Escolha o episódio:"))
        num_episodes = len(episodes)
        history_sources = rep.anime_episodes_urls[selected_anime]
    while True:
        status(f"Resolvendo player: {selected_anime} — episódio {episode_idx + 1}/{num_episodes}…")
        player_url = rep.search_player(selected_anime, episode_idx + 1)
        play_video(player_url, args.debug)
        try:
            # A restrição --source afeta a reprodução, não apaga fontes do histórico.
            save_history(selected_anime, episode_idx, history_sources)
        except (OSError, RuntimeError) as exc:
            logging.warning("Não foi possível salvar o histórico: %s", exc)
        opts = []
        if episode_idx + 1 < num_episodes:
            opts.append("Próximo")
        if episode_idx > 0:
            opts.append("Anterior")
        if not opts:
            status("Fim dos episódios disponíveis.")
            return
        selected = menu(opts, "O que quer fazer agora?")
        episode_idx += 1 if selected == "Próximo" else -1


def cli(argv=None):
    parser = argparse.ArgumentParser(prog="ani-guarani", description="Busque e assista a animes em português pelo terminal.")
    parser.add_argument("--query", "-q", help="termo de busca (use aspas para várias palavras)")
    parser.add_argument("--debug", "-d", action="store_true", help="mostrar diagnóstico detalhado, sem alterar a busca")
    parser.add_argument("--continue-watching", "--continue_watching", "-c", action="store_true", help="retomar o último episódio assistido")
    parser.add_argument("--source", action="append", choices=["animefire", "animesonlinecc"], help="limitar fonte (pode repetir)")
    args = parser.parse_args(argv)
    if args.query is not None and args.continue_watching:
        parser.error("--query não pode ser combinado com --continue-watching")
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING, format="%(levelname)s: %(message)s")
    try:
        main(args)
        return 0
    except (Cancelled, EOFError):
        status("Até a próxima!")
        return 0
    except KeyboardInterrupt:
        status("Operação interrompida.")
        return 130
    except Exception as exc:
        if args.debug:
            logging.exception("Falha na execução")
        else:
            print(f"Erro: {exc}\nUse --debug para detalhes.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(cli())
