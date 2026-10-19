from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By

from loader import PluginInterface
from repository import rep
from .utils import fetch_page, find_player_src


class AnimeFire(PluginInterface):
    languages = ["pt-br"]
    name = "animefire"

    @staticmethod
    def search_anime(query):
        url = "https://animefire.plus/pesquisar/" + quote("-".join(query.split()), safe="")
        html, base_url = fetch_page(url)
        soup = BeautifulSoup(html, "html.parser")
        target_class = "col-6 col-sm-4 col-md-3 col-lg-2 mb-1 minWDanime divCardUltimosEps"
        for div in soup.find_all("div", class_=target_class):
            if "title" not in div.attrs:
                continue
            anchor = div.select_one("article a[href]")
            heading = div.find("h3", class_="animeTitle")
            if anchor is None or heading is None:
                continue
            title = heading.get_text(strip=True)
            href = anchor["href"].strip()
            if title and href:
                rep.add_anime(title, urljoin(base_url, href), AnimeFire.name)

    @staticmethod
    def search_episodes(anime, url, params):
        html, base_url = fetch_page(url)
        soup = BeautifulSoup(html, "html.parser")
        titles, urls = [], []
        for anchor in soup.find_all("a", class_="lEp epT divNumEp smallbox px-2 mx-1 text-left d-flex"):
            title = anchor.get_text(strip=True)
            href = anchor.get("href", "").strip()
            if title and href:
                titles.append(title)
                urls.append(urljoin(base_url, href))
        rep.add_episode_list(anime, titles, urls, AnimeFire.name)

    @staticmethod
    def search_player_src(url_episode, container, event):
        find_player_src(url_episode, container, event, AnimeFire.name, (
            (By.ID, "my-video_html5_api"),
            (By.XPATH, "/html/body/div[2]/div[2]/div/div[1]/div[1]/div/div/div[2]/div[4]/iframe"),
        ))


def load(languages_dict):
    if any(language in languages_dict for language in AnimeFire.languages):
        rep.register(AnimeFire)
