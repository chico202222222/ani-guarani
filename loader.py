"""Descoberta de plugins locais confiáveis, independente do diretório atual."""
import importlib
import logging
import sys
from abc import ABC, abstractmethod
from pathlib import Path


class PluginInterface(ABC):
    @staticmethod
    @abstractmethod
    def search_anime(query):
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def search_episodes(anime, url, params):
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def search_player_src(url, container, event):
        raise NotImplementedError


def get_resource_path(relative_path):
    return str(Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / relative_path)


def load_plugins(languages, plugins=None):
    available = {path.stem for path in Path(get_resource_path("plugins")).glob("*.py")
                 if path.stem not in {"__init__", "utils"}}
    selected = set(plugins) if plugins is not None else available
    unknown = selected - available
    if unknown:
        raise ValueError("Fontes desconhecidas: " + ", ".join(sorted(unknown)))
    for name in sorted(selected):
        try:
            importlib.import_module("plugins." + name).load(languages)
        except Exception as exc:
            logging.getLogger(__name__).warning("Não foi possível carregar %s: %s", name, exc)
