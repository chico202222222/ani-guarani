"""Banner de abertura em ASCII art (gato dormindo, de Felix Lee)."""
import os
import sys

GATO = r'''
      |\      _,,,---,,_
ZZZzz /,`.-'`'    -.  ;-;;,_
     |,4-  ) )-,_. ,\ (  `'-'
    '---''(_/--'  `-'\_)  Felix Lee <flee@cse.psu.edu>
'''

TITLE = "ani-guarani"
SUBTITLE = "Busque e assista a animes pelo terminal"


def banner(stream=None):
    """Mostra o banner uma vez, só em terminal interativo."""
    stream = stream or sys.stderr
    if not stream.isatty():
        return
    color = "NO_COLOR" not in os.environ
    art, title = GATO.strip("\n"), f"{TITLE}\n{SUBTITLE}"
    if color:
        art, title = f"\033[33m{art}\033[0m", f"\033[1m{TITLE}\033[0m\n\033[2m{SUBTITLE}\033[0m"
    print(f"{art}\n\n{title}\n", file=stream, flush=True)
