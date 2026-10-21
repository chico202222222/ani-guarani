"""Lista "para assistir": animes salvos com suas fontes, independente do histórico."""
import json
from pathlib import Path

from history import history_path, validate_sources, write_json_atomic


def watchlist_path():
    # Fica ao lado do histórico para compartilhar o mesmo diretório de estado.
    return history_path().with_name("watchlist.json")


def read_watchlist(path=None):
    path = Path(path) if path is not None else watchlist_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("objeto JSON esperado")
        for title, sources in data.items():
            if not isinstance(title, str) or not title.strip():
                raise ValueError("título inválido")
            validate_sources(sources)
        return data
    except (ValueError, OSError) as exc:
        raise RuntimeError(f"Não foi possível ler {path}: {exc}. Preserve ou renomeie o arquivo para iniciar outra lista.") from exc


def add_to_watchlist(anime, sources, path=None):
    """Adiciona (ou atualiza as fontes de) um anime. Retorna False se já estava na lista."""
    path = Path(path) if path is not None else watchlist_path()
    data = read_watchlist(path)
    validate_sources(sources)
    added = anime not in data
    data[anime] = sources
    write_json_atomic(path, data)
    return added


def remove_from_watchlist(anime, path=None):
    """Remove um anime da lista. Retorna False se ele não estava nela."""
    path = Path(path) if path is not None else watchlist_path()
    data = read_watchlist(path)
    if anime not in data:
        return False
    del data[anime]
    write_json_atomic(path, data)
    return True


def in_watchlist(anime, path=None):
    return anime in read_watchlist(path)
