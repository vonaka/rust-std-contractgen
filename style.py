import colorama


def init():
    colorama.init()


def red(s: str):
    return colorama.Fore.RED + s + colorama.Style.RESET_ALL


def green(s: str):
    return colorama.Fore.GREEN + s + colorama.Style.RESET_ALL


def blue(s: str):
    return colorama.Fore.BLUE + s + colorama.Style.RESET_ALL


def yellow(s: str):
    return colorama.Fore.YELLOW + s + colorama.Style.RESET_ALL


def magenta(s: str):
    return colorama.Fore.MAGENTA + s + colorama.Style.RESET_ALL
