"""Menu com teclado e alternativa numerada para terminais simples."""
import os
import sys

try:
    import curses
except ImportError:
    curses = None


class Cancelled(Exception):
    """Saída solicitada pelo usuário."""


def _plain(options, msg):
    print(msg)
    for index, option in enumerate(options, 1):
        print(f"  {index}. {option}")
    print("  0. Sair")
    while True:
        value = input("Escolha um número: ").strip()
        if value.lower() in {"0", "q", "sair"}:
            raise Cancelled
        if value.isdecimal() and 1 <= int(value) <= len(options):
            return options[int(value) - 1]
        print("Opção inválida. Digite um dos números acima.")


def _screen(screen, options, msg):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.keypad(True)
    current = 0
    labels = [*options, "Sair"]
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 4 or width < 12:
            raise curses.error("Terminal pequeno")
        visible = height - 2
        start = max(0, current - visible + 1)

        def draw(row, text, attr=0):
            try:
                screen.addnstr(row, 0, str(text), width - 1, attr)
            except curses.error:
                pass  # Caracteres largos podem ocupar mais de uma coluna.

        draw(0, msg, curses.A_BOLD)
        for row, index in enumerate(range(start, min(len(labels), start + visible)), 1):
            draw(row, labels[index], curses.A_REVERSE if index == current else 0)
        draw(height - 1, "↑/↓ ou j/k • Enter • q: sair")
        screen.refresh()
        key = screen.getch()
        if key in (ord("q"), 27):
            raise Cancelled
        if key in (curses.KEY_UP, ord("k")):
            current = (current - 1) % len(labels)
        elif key in (curses.KEY_DOWN, ord("j")):
            current = (current + 1) % len(labels)
        elif key in (10, 13, curses.KEY_ENTER):
            if current == len(options):
                raise Cancelled
            return options[current]


def menu(opts, msg="Escolha uma opção:"):
    options = list(opts)
    if not options:
        raise ValueError("Nenhum resultado disponível. Tente outra busca ou fonte.")
    if curses and sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("TERM", "dumb") != "dumb":
        try:
            return curses.wrapper(_screen, options, msg)
        except curses.error:
            pass
    return _plain(options, msg)
