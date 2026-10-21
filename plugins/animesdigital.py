import re
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from typing import ClassVar
from urllib.parse import quote_plus, urljoin, urlsplit

from bs4 import BeautifulSoup

from loader import PluginInterface
from repository import rep
from .utils import BLOGGER_USER_AGENT, fetch_page, find_anivideo_src

BASE_URL = "https://animesdigital.org"
HEADERS = {"User-Agent": BLOGGER_USER_AGENT}
MAX_EPISODE_PAGES = 100
_EPISODE = re.compile(r"Epis[óo]dio\s+(\d+(?:\.\d+)?)", re.IGNORECASE)
_PAGE = re.compile(r"/page/(\d+)/?$")


def _fetch(url):
    return fetch_page(url, HEADERS)


def _number(label):
    match = _EPISODE.search(label)
    try:
        return Decimal(match[1]) if match else None
    except InvalidOperation:
        return None


def _episodes(soup, page_url):
    found = []
    for card in soup.select(".item_ep a[href]"):
        label = (card.select_one(".title_anime") or card).get_text(" ", strip=True)
        found.append((label, urljoin(page_url, card["href"].strip())))
    return found


class AnimesDigital(PluginInterface):
    languages: ClassVar[list[str]] = ["pt-br"]
    name = "animesdigital"
    priority = 20

    @staticmethod
    def search_anime(query):
        # O site redireciona /?s= para /pesquisa/<termo>/.
        html, page_url = _fetch(BASE_URL + "/?s=" + quote_plus(query.strip()))
        soup = BeautifulSoup(html, "html.parser")
        for item in soup.select(".itemA"):
            anchor = item.select_one("a[href]")
            title = item.select_one(".title_anime")
            if anchor is None or title is None:
                continue
            title = title.get_text(" ", strip=True)
            if title:
                rep.add_anime(f"{title} [AnimesDigital]", urljoin(page_url, anchor["href"].strip()),
                              AnimesDigital.name)

    @staticmethod
    def search_episodes(anime, url, params):
        html, page_url = _fetch(url)
        soup = BeautifulSoup(html, "html.parser")
        found = _episodes(soup, page_url)
        last = max((int(match[1]) for anchor in soup.select(".content-pagination a[href]")
                    if (match := _PAGE.search(urlsplit(anchor["href"]).path))), default=1)
        base = page_url.split("?")[0].rstrip("/") + "/"
        pages = [f"{base}page/{number}/" for number in range(2, min(last, MAX_EPISODE_PAGES) + 1)]
        if pages:
            with ThreadPoolExecutor(max_workers=min(8, len(pages))) as pool:
                for extra_html, extra_url in pool.map(_fetch, pages):
                    found += _episodes(BeautifulSoup(extra_html, "html.parser"), extra_url)
        entries, seen = [], set()
        for label, episode_url in found:
            if episode_url not in seen:
                seen.add(episode_url)
                number = _number(label)
                entries.append((number is None, number or Decimal(0), label, episode_url))
        if not entries:
            raise RuntimeError("AnimesDigital: nenhum episódio encontrado.")
        # O site lista do mais novo para o mais antigo.
        entries.sort(key=lambda entry: entry[:2])
        titles = [f"Episódio {entry[1]:g}" if not entry[0] else entry[2] for entry in entries]
        rep.add_episode_list(anime, titles, [entry[3] for entry in entries], AnimesDigital.name)

    @staticmethod
    def search_player_src(url, container, event):
        find_anivideo_src(url, container, event, "AnimesDigital")


def load(languages_dict):
    if any(language in languages_dict for language in AnimesDigital.languages):
        rep.register(AnimesDigital)  # pyright: ignore[reportArgumentType]
