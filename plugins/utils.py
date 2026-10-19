import logging
import subprocess
from urllib.parse import urljoin, urlsplit

import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait


logger = logging.getLogger(__name__)
REQUEST_TIMEOUT = (5, 20)
PAGE_LOAD_TIMEOUT = 30
PLAYER_TIMEOUT = 7


def fetch_page(url):
    try:
        with requests.get(url, timeout=REQUEST_TIMEOUT) as response:
            response.raise_for_status()
            return response.text, response.url
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc


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
        options = webdriver.FirefoxOptions()
        options.add_argument("--headless")
        try:
            if is_firefox_installed_as_snap():
                service = webdriver.FirefoxService(executable_path="/snap/bin/geckodriver")
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
            if not event.is_set():
                container.append(link)
                event.set()
            return
        if not event.is_set():
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
