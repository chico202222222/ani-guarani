from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By

from loader import PluginInterface
from repository import rep
from .utils import fetch_page, find_player_src


class AnimesOnlineCC(PluginInterface):
    languages = ["pt-br"]
    name = "animesonlinecc"
    priority = 10

    @staticmethod
    def search_anime(query):
        url = "https://animesonlinecc.to/search/" + "+".join(
            quote(word, safe="") for word in query.split()
        )
        html, base_url = fetch_page(url)
        soup = BeautifulSoup(html, "html.parser")
        entries = []
        for div in soup.find_all("div", class_="data"):
            anchor = div.select_one("h3 a[href]")
            if anchor is None:
                continue
            title = anchor.get_text(strip=True)
            href = anchor["href"].strip()
            if title and href:
                anime_url = urljoin(base_url, href)
                entries.append((title, anime_url))
                rep.add_anime(title, anime_url, AnimesOnlineCC.name)

        # The former ThreadPool.apply calls also processed seasons sequentially.
        for title, anime_url in entries:
            html, _ = fetch_page(anime_url)
            soup = BeautifulSoup(html, "html.parser")
            num_seasons = len(soup.find_all("div", class_="se-c"))
            for n in range(2, num_seasons + 1):
                rep.add_anime(title + " Season " + str(n), anime_url, AnimesOnlineCC.name, n)

    @staticmethod
    def search_episodes(anime, url, season):
        html, base_url = fetch_page(url)
        soup = BeautifulSoup(html, "html.parser")
        seasons = soup.find_all("ul", class_="episodios")
        season_number = 1 if season is None else season
        if type(season_number) is not int or not 1 <= season_number <= len(seasons):
            raise ValueError(
                f"Invalid season {season_number!r} for {anime!r} at {url}: "
                f"found {len(seasons)} seasons"
            )
        titles, urls = [], []
        for div in seasons[season_number - 1].find_all("div", class_="episodiotitle"):
            anchor = div.find("a", href=True)
            if anchor is None:
                continue
            title = anchor.get_text(strip=True)
            href = anchor["href"].strip()
            if title and href:
                titles.append(title)
                urls.append(urljoin(base_url, href))
        rep.add_episode_list(anime, titles, urls, AnimesOnlineCC.name)

    @staticmethod
    def search_player_src(url_episode, container, event):
        find_player_src(url_episode, container, event, AnimesOnlineCC.name, (
            (By.XPATH, "/html/body/div[1]/div[2]/div[2]/div[2]/div[1]/div[1]/div[1]/iframe"),
        ))


def load(languages_dict):
    if any(language in languages_dict for language in AnimesOnlineCC.languages):
        rep.register(AnimesOnlineCC)
