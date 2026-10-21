import json
import logging
import subprocess
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait


logger = logging.getLogger(__name__)
REQUEST_TIMEOUT = (5, 20)
PAGE_LOAD_TIMEOUT = 30
PLAYER_TIMEOUT = 7
# O Blogger assina a URL de mídia para o User-Agent que abriu o player; o mpv
# precisa reutilizar exatamente este valor ao baixar do googlevideo.com.
BLOGGER_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"


def fetch_page(url, headers=None):
    kwargs = {"headers": headers} if headers else {}
    try:
        with requests.get(url, timeout=REQUEST_TIMEOUT, **kwargs) as response:
            response.raise_for_status()
            return response.text, response.url
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc


# Ordem de preferência dos itags do Blogger/YouTube: mp4 HD primeiro, 3GPP por último.
_ITAG_PREFERENCE = (37, 22, 59, 18, 43, 36, 17, 13)


def _itag_rank(url):
    itag = parse_qs(urlsplit(url).query).get("itag", [""])[0]
    try:
        return len(_ITAG_PREFERENCE) - _ITAG_PREFERENCE.index(int(itag))
    except ValueError:
        return 0


def resolve_blogger_player(url):
    parsed = urlsplit(url)
    if parsed.hostname not in {"blogger.com", "www.blogger.com"} or parsed.path != "/video.g":
        return url
    html, _ = fetch_page(url, {"User-Agent": BLOGGER_USER_AGENT})
    # O Blogger pode responder 200 com uma página de erro, sem mídia disponível.
    soup = BeautifulSoup(html, "html.parser")
    message = soup.select_one("main .Phuhlc")
    if message and message.get_text(" ", strip=True).casefold() == "video is unavailable":
        raise RuntimeError(
            "O Blogger informa 'Video is unavailable': este vídeo está indisponível. "
            "Tente outra fonte ou episódio; atualizar o yt-dlp não recupera o vídeo."
        )

    def media_url(value):
        if not isinstance(value, str):
            return False
        try:
            parts = urlsplit(value)
            host = parts.hostname or ""
            return (parts.scheme == "https" and host.endswith(".googlevideo.com")
                    and parts.path == "/videoplayback")
        except ValueError:
            return False

    def streams(value):
        # O novo Blogger serializa [URL, [itag]] dentro do atributo data-p.
        if isinstance(value, list):
            if len(value) == 2 and media_url(value[0]) and isinstance(value[1], list):
                yield value[0]
            else:
                for item in value:
                    yield from streams(item)

    for node in soup.select("c-wiz[data-p]"):
        payload = node["data-p"]
        if not payload.startswith("%.@."):
            continue
        try:
            data = json.loads("[" + payload[4:])
        except (ValueError, RecursionError):
            continue
        stream = max(streams(data), default=None, key=_itag_rank)
        if stream:
            return stream
    # Páginas antigas ou layouts desconhecidos continuam delegados ao yt-dlp.
    return url


def is_firefox_installed_as_snap():
    try:
        result = subprocess.run(
            ["snap", "list", "firefox"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f"Failed to check Firefox Snap installation: {exc}") from exc


def find_player_src(url, container, event, source, locators):
    if event.is_set():
        return

    driver = None
    try:
        options = FirefoxOptions()
        options.add_argument("--headless")
        try:
            if is_firefox_installed_as_snap():
                service = FirefoxService(executable_path="/snap/bin/geckodriver")
                driver = webdriver.Firefox(options=options, service=service)
            else:
                driver = webdriver.Firefox(options=options)
        except (WebDriverException, OSError) as exc:
            raise RuntimeError(f"Failed to start Firefox for {source}: {exc}") from exc

        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        driver.set_script_timeout(PAGE_LOAD_TIMEOUT)
        if event.is_set():
            return
        driver.get(url)
        player_error = None
        for locator in locators:
            if event.is_set():
                return
            try:
                visible = EC.visibility_of_all_elements_located(locator)
                elements = WebDriverWait(driver, PLAYER_TIMEOUT).until(
                    lambda browser: event.is_set() or visible(browser)
                )
            except TimeoutException:
                continue
            if event.is_set():
                return
            link = elements[0].get_property("src")
            if not isinstance(link, str) or not link.strip():
                continue
            # An iframe src is a player page, not necessarily a media stream.
            try:
                link = urljoin(driver.current_url, link.strip())
                parsed = urlsplit(link)
                if parsed.scheme not in ("http", "https") or not parsed.netloc:
                    continue
            except ValueError:
                continue
            if event.is_set():
                return
            try:
                link = resolve_blogger_player(link)
            except RuntimeError as exc:
                player_error = exc
                logger.warning("Player da fonte %s: %s", source, exc)
                continue
            if not event.is_set():
                container.append(link)
                event.set()
            return
        if not event.is_set():
            if player_error is not None:
                raise player_error
            raise RuntimeError(
                f"No visible player found in {source} at {url} with a valid HTTP(S) src; "
                f"tried selectors: {locators}"
            )
    except (WebDriverException, OSError) as exc:
        raise RuntimeError(f"Failed to inspect player in {source} at {url}: {exc}") from exc
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception as exc:
                # Cleanup must not hide the original lookup error or its result.
                logger.warning("Failed to close Firefox for %s at %s: %s", source, url, exc)
