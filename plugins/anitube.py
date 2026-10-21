import re
from typing import ClassVar
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from loader import PluginInterface
from repository import AUDIOS, rep
from .utils import BLOGGER_USER_AGENT, anivideo_stream, fetch_page, find_anivideo_src

BASE_URL = "https://www.anitube.zip"
HEADERS = {"User-Agent": BLOGGER_USER_AGENT}
_SUFFIX = re.compile(r"\s*[–-]\s*Todos\s+(?:os\s+)?Epis[óo]dios\s*$", re.IGNORECASE)


def _fetch(url):
    return fetch_page(url, HEADERS)


class AniTube(PluginInterface):
    languages: ClassVar[list[str]] = ["pt-br"]
    name = "anitube"
    priority = 25

    @staticmethod
    def search_anime(query):
        html, page_url = _fetch(BASE_URL + "/?s=" + quote_plus(query.strip()))
        soup = BeautifulSoup(html, "html.parser")
        for item in soup.select(".aniItem"):
            anchor = item.select_one("a[href]")
            name = item.select_one(".aniItemNome")
            if anchor is None or name is None:
                continue
            title = _SUFFIX.sub("", name.get_text(" ", strip=True))
            # A etiqueta do cartão (Legendado/Dublado/Filme) é mais confiável que o título.
            tag = item.select_one(".aniCC")
            tag = tag.get_text(strip=True).casefold() if tag else ""
            if title:
                rep.add_anime(f"{title} [AniTube]", urljoin(page_url, anchor["href"].strip()),
                              AniTube.name, audio=[tag] if tag in AUDIOS else None)

    @staticmethod
    def search_episodes(anime, url, params):
        html, page_url = _fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        titles, urls = [], []
        for anchor in soup.select(".pagAniListaContainer a[href]"):
            title = anchor.get_text(" ", strip=True)
            episode_url = urljoin(page_url, anchor["href"].strip())
            if title and episode_url not in urls:
                titles.append(title)
                urls.append(episode_url)
        if not urls and any(anivideo_stream(urljoin(page_url, frame["src"]))
                            for frame in soup.select("iframe[src]")):
            # Filmes/OVAs: a própria página já é o player.
            titles, urls = ["Filme"], [page_url]
        if not urls:
            raise RuntimeError("AniTube: nenhum episódio encontrado.")
        rep.add_episode_list(anime, titles, urls, AniTube.name)

    @staticmethod
    def search_player_src(url, container, event):
        find_anivideo_src(url, container, event, "AniTube")


def load(languages_dict):
    if any(language in languages_dict for language in AniTube.languages):
        rep.register(AniTube)  # pyright: ignore[reportArgumentType]
