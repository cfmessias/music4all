#!/usr/bin/env bash
set -euo pipefail

echo "→ Preparar pastas alvo…"
mkdir -p views/spotify/components
mkdir -p services/spotify

# usamos git mv se estiver num repo git
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then MV="git mv"; else MV="mv"; fi

move () {
  local SRC="$1"; local DST="$2"
  if [ -f "$SRC" ]; then
    echo "✓ mover $SRC → $DST"
    mkdir -p "$(dirname "$DST")"
    eval $MV "\"$SRC\"" "\"$DST\""
  else
    echo "· (ignorar) $SRC não existe"
  fi
}

# ---- VIEWS (já em views/spotify/*.py) -> renomear para nomes limpos
move "views/spotify/spotify_results.py"    "views/spotify/results.py"
move "views/spotify/spotify_page.py"       "views/spotify/page.py"
move "views/spotify/spotify_helpers.py"    "views/spotify/helpers.py"
move "views/spotify/spotify_wiki_info.py"  "views/spotify/wiki_info.py"
move "views/spotify/spotify_ui.py"         "views/spotify/components/legacy_ui.py"

# ---- SERVICES (ficheiros na raiz de services/) -> services/spotify/
move "services/spotify_oauth.py"        "services/spotify/auth.py"
move "services/spotify_lookup.py"       "services/spotify/lookup.py"
move "services/spotify_radio.py"        "services/spotify/radio.py"
move "services/spotify_push.py"         "services/spotify/push.py"
move "services/spotify_session_push.py" "services/spotify/session_push.py"
move "services/spotify_genres.py"       "services/spotify/genres.py"

# ---- __init__.py do package services/spotify (reexporta API + core)
echo "→ escrever services/spotify/__init__.py"
cat > services/spotify/__init__.py <<'PY'
"""Namespace Spotify (serviços). Re-exporta API pública para compatibilidade."""
__all__ = []
def _reexport(modname: str) -> None:
    try:
        module = __import__(f"{__name__}.{modname}", fromlist=["*"])
        for k, v in module.__dict__.items():
            if not k.startswith("_"):
                globals()[k] = v
                __all__.append(k)
    except Exception:
        pass

# inclui 'core' (era o antigo services/spotify.py) + restantes módulos
for _m in ["core","auth","client","errors","models","mappers","queries",
           "search","albums","radio","genres","lookup","push","session_push"]:
    _reexport(_m)
del _reexport
PY

# ---- __init__ das views
[ -f views/spotify/__init__.py ] || echo '"""UI da área Spotify."""' > views/spotify/__init__.py
[ -f views/spotify/components/__init__.py ] || echo '"""Componentes Spotify."""' > views/spotify/components/__init__.py

echo "✔ Terminado. Agora actualiza imports se necessário e corre a app."
