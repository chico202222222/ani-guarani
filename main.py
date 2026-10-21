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
from watchlist import add_to_watchlist, in_watchlist, read_watchlist, remove_from_watchlist


def status(message):
    color = sys.stderr.isatty() and "NO_COLOR" not in os.environ
    print(f"\033[36m{message}\033[0m" if color else message, file=sys.stderr, flush=True)


ADD_LABEL = "Adicionar à lista para assistir"
REMOVE_LABEL = "Remover da lista para assistir"


def open_saved(anime, saved_sources, episode_idx):
    """Prepara um anime salvo (histórico ou lista) usando só as fontes habilitadas."""
    sources = [(urls, source) for urls, source in saved_sources if source in rep.sources]
    if not sources:
        raise RuntimeError("Este anime não tem fontes habilitadas no histórico. Habilite uma fonte salva ou faça uma nova busca.")
    num_episodes = max(len(urls) for urls, source in sources)
    if episode_idx >= num_episodes:
        raise RuntimeError("O episódio salvo não está disponível nas fontes habilitadas. Habilite a fonte original ou faça uma nova busca.")
    rep.anime_episodes_urls[anime] = sources
    return num_episodes


def choose_from_watchlist():
    """Menu da lista para assistir; devolve (título, fontes, episódio inicial) ou None."""
    saved = read_watchlist()
    if not saved:
        status("Sua lista para assistir está vazia. Use -q ANIME --add-watchlist para adicionar.")
        return None
    history = read_history()
    labels = {}
    for title in saved:
        progress = f"último episódio: {history[title][1] + 1}" if title in history else "não iniciado"
        labels[f"{title} ({progress})"] = title
    while True:
        selected = labels[menu(list(labels), "Sua lista para assistir:")]
        if menu(["Assistir", "Remover da lista"], selected) == "Assistir":
            return selected, saved[selected], history[selected][1] if selected in history else 0
        remove_from_watchlist(selected)
        status(f"Removido da lista: {selected}")
        labels = {label: title for label, title in labels.items() if title != selected}
        if not labels:
            status("Sua lista para assistir está vazia.")
            return None


def toggle_watchlist(anime, sources):
    try:
        if in_watchlist(anime):
            remove_from_watchlist(anime)
            status(f"Removido da lista para assistir: {anime}")
        else:
            add_to_watchlist(anime, sources)
            status(f"Adicionado à lista para assistir: {anime}")
    except (OSError, RuntimeError) as exc:
        logging.warning("Não foi possível atualizar a lista para assistir: %s", exc)


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
        num_episodes = open_saved(selected_anime, history_sources, episode_idx)
    elif getattr(args, "watchlist", False):
        chosen = choose_from_watchlist()
        if chosen is None:
            return
        selected_anime, history_sources, episode_idx = chosen
        num_episodes = open_saved(selected_anime, history_sources, episode_idx)
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
        if getattr(args, "add_watchlist", False):
            if add_to_watchlist(selected_anime, rep.anime_episodes_urls[selected_anime]):
                status(f"Adicionado à lista para assistir: {selected_anime}")
            else:
                status(f"Já estava na lista (fontes atualizadas): {selected_anime}")
            return
        labels = [f"{index + 1}. {title}" for index, title in enumerate(episodes)]
        episode_idx = labels.index(menu(labels, "Escolha o episódio:"))
        num_episodes = len(episodes)
        history_sources = rep.anime_episodes_urls[selected_anime]
    while True:
        status(f"Resolvendo player: {selected_anime} — episódio {episode_idx + 1}/{num_episodes}…")
        play_error = None
        played = False
        for player_url in rep.search_players(selected_anime, episode_idx + 1):
            try:
                play_video(player_url, args.debug)
                played = True
                break
            except (RuntimeError, ValueError) as exc:
                play_error = exc
                logging.warning("Fonte falhou, tentando a próxima: %s", exc)
        if not played:
            raise play_error
        try:
            # A restrição --source afeta a reprodução, não apaga fontes do histórico.
            save_history(selected_anime, episode_idx, history_sources)
        except (OSError, RuntimeError) as exc:
            logging.warning("Não foi possível salvar o histórico: %s", exc)
        while True:
            opts = []
            if episode_idx + 1 < num_episodes:
                opts.append("Próximo")
            if episode_idx > 0:
                opts.append("Anterior")
            try:
                listed = in_watchlist(selected_anime)
            except RuntimeError as exc:
                logging.warning("Lista para assistir indisponível: %s", exc)
                listed = None
            if listed is not None:
                opts.append(REMOVE_LABEL if listed else ADD_LABEL)
            if not opts:
                status("Fim dos episódios disponíveis.")
                return
            selected = menu(opts, "O que quer fazer agora?")
            if selected in (ADD_LABEL, REMOVE_LABEL):
                toggle_watchlist(selected_anime, history_sources)
                continue
            break
        episode_idx += 1 if selected == "Próximo" else -1


def cli(argv=None):
    parser = argparse.ArgumentParser(prog="ani-guarani", description="Busque e assista a animes em português pelo terminal.")
    parser.add_argument("--query", "-q", help="termo de busca (use aspas para várias palavras)")
    parser.add_argument("--debug", "-d", action="store_true", help="mostrar diagnóstico detalhado, sem alterar a busca")
    parser.add_argument("--continue-watching", "--continue_watching", "-c", action="store_true", help="retomar o último episódio assistido")
    parser.add_argument("--watchlist", "-l", action="store_true", help="abrir a lista para assistir")
    parser.add_argument("--add-watchlist", "-a", action="store_true", help="com -q: salvar o anime escolhido na lista para assistir, sem reproduzir")
    parser.add_argument("--source", action="append", choices=["animefire", "animesonlinecc", "animesonlinecloud"], help="limitar fonte (pode repetir)")
    args = parser.parse_args(argv)
    if args.query is not None and args.continue_watching:
        parser.error("--query não pode ser combinado com --continue-watching")
    if args.watchlist and (args.query is not None or args.continue_watching or args.add_watchlist):
        parser.error("--watchlist não pode ser combinado com --query, --continue-watching ou --add-watchlist")
    if args.add_watchlist and args.continue_watching:
        parser.error("--add-watchlist não pode ser combinado com --continue-watching")
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
