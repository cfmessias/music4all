#!/usr/bin/env python3
import argparse, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent

# Mapa de substituições (strings simples)
SUBS = {
    # views -> novos módulos
    "from views.spotify.results import": "from views.spotify.results import",
    "import views.spotify.results":       "import views.spotify.results",

    "from views.spotify.page import":     "from views.spotify.page import",
    "import views.spotify.page":          "import views.spotify.page",

    "from views.spotify.helpers import":  "from views.spotify.helpers import",
    "import views.spotify.helpers":       "import views.spotify.helpers",

    "from views.spotify.wiki_info import": "from views.spotify.wiki_info import",
    "import views.spotify.wiki_info":      "import views.spotify.wiki_info",

    # relativo dentro de views/spotify
    "from .components.legacy_ui import":            "from .components.legacy_ui import",
    "from views.spotify.components.legacy_ui import":       "from views.spotify.components.legacy_ui import",
    "import views.spotify.components.legacy_ui":            "import views.spotify.components.legacy_ui",

    # services soltos -> package services/spotify
    "from services.spotify.auth import":        "from services.spotify.auth import",
    "import services.spotify.auth":             "import services.spotify.auth",

    "from services.spotify.lookup import":       "from services.spotify.lookup import",
    "import services.spotify.lookup":            "import services.spotify.lookup",

    "from services.spotify.radio import":        "from services.spotify.radio import",
    "import services.spotify.radio":             "import services.spotify.radio",

    "from services.spotify.push import":         "from services.spotify.push import",
    "import services.spotify.push":              "import services.spotify.push",

    "from services.spotify.session_push import": "from services.spotify.session_push import",
    "import services.spotify.session_push":      "import services.spotify.session_push",

    "from services.spotify.genres import":       "from services.spotify.genres import",
    "import services.spotify.genres":            "import services.spotify.genres",

    # novos helpers
    "from services.spotify.search import":       "from services.spotify.search import",
    "import services.spotify.search":            "import services.spotify.search",

    "from services.spotify.albums import":       "from services.spotify.albums import",
    "import services.spotify.albums":            "import services.spotify.albums",

    # core antigo renomeado
    "from services.spotify.core import":         "from services.spotify.core import",
    "import services.spotify.core":              "import services.spotify.core",
    
    # --- RELATIVOS dentro de views/spotify ---
    "from .results import":  "from .results import",
    "from .page import":     "from .page import",
    "from .helpers import":  "from .helpers import",
    "from .wiki_info import":"from .wiki_info import",
    
    "from . import results":  "from . import results",
    "from . import page":     "from . import page",
    "from . import helpers":  "from . import helpers",
    "from . import wiki_info":"from . import wiki_info",
    
    # módulo UI legado
    "from .components.legacy_ui import":        "from .components.legacy_ui import",
    "from .components import legacy_ui as spotify_ui":       "from .components import legacy_ui as spotify_ui",
    
    # --- ABSOLUTOS variante 'views.spotify.<mod>' ---
    "from views.spotify.results import": "from views.spotify.results import",
    "from views.spotify.page import":    "from views.spotify.page import",
    "from views.spotify.helpers import": "from views.spotify.helpers import",
    "from views.spotify.wiki_info import":"from views.spotify.wiki_info import",
    
    "from views.spotify import results": "from views.spotify import results",
    "from views.spotify import page":    "from views.spotify import page",
    "from views.spotify import helpers": "from views.spotify import helpers",
    "from views.spotify import wiki_info":"from views.spotify import wiki_info",
    
    "import views.spotify.results": "import views.spotify.results",
    "import views.spotify.page":    "import views.spotify.page",
    "import views.spotify.helpers": "import views.spotify.helpers",
    "import views.spotify.wiki_info":"import views.spotify.wiki_info",
    
    # UI legado absoluto
    "from views.spotify.components.legacy_ui import":         "from views.spotify.components.legacy_ui import",
    "import views.spotify.components.legacy_ui":              "import views.spotify.components.legacy_ui",
    "from views.spotify.components import legacy_ui as spotify_ui": "from views.spotify.components import legacy_ui as spotify_ui",

}

def should_edit(path: pathlib.Path) -> bool:
    if path.suffix != ".py":
        return False
    # ignora .git, venvs, caches, dist, build
    p = str(path)
    for skip in ("/.git/", "/.venv/", "/venv/", "/env/", "__pycache__", "/build/", "/dist/"):
        if skip in p.replace("\\", "/"):
            return False
    return True

def apply_subs(text: str) -> tuple[str, int]:
    count = 0
    for old, new in SUBS.items():
        if old in text:
            c = text.count(old)
            text = text.replace(old, new)
            count += c
    return text, count

def main():
    ap = argparse.ArgumentParser(description="Atualiza imports para a nova árvore spotify views/services")
    ap.add_argument("--apply", action="store_true", help="Grava alterações (por omissão é dry-run)")
    args = ap.parse_args()

    changed_files = 0
    total_repls = 0
    for path in ROOT.rglob("*.py"):
        if not should_edit(path):
            continue
        src = path.read_text(encoding="utf-8")
        dst, n = apply_subs(src)
        if n > 0:
            changed_files += 1
            total_repls += n
            print(f"[{path}] {n} substituição(ões)")
            if args.apply:
                path.write_text(dst, encoding="utf-8")

    if changed_files == 0:
        print("Nenhuma alteração necessária.")
    else:
        print(f"Ficheiros alterados: {changed_files} | Substituições: {total_repls}")
        if not args.apply:
            print("Dry-run concluído. Execute com --apply para gravar.")

if __name__ == "__main__":
    main()
