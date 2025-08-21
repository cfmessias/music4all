#!/usr/bin/env bash
set -euo pipefail

echo "→ Preparar pastas alvo…"
mkdir -p views/spotify/components
mkdir -p services/spotify

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then MV="git mv"; else MV="mv"; fi

move_found () {
  local SRC="$1"; local DST="$2"
  # caso exacto
  if [ -f "$SRC" ]; then
    echo "✓ mover $SRC → $DST"
    mkdir -p "$(dirname "$DST")"
    eval $MV "\"$SRC\"" "\"$DST\""
    return
  fi
  # procurar pelo nome em todo o repo (ignorar .git)
  local B="$(basename "$SRC")"
  local CAND
  mapfile -t CAND < <(find . -type f -name "$B" | grep -v "/\.git/" || true)
  if [ "${#CAND[@]}" -eq 0 ]; then
    echo "· não encontrado: $SRC (procurei por $B)"
    return
  fi
  if [ "${#CAND[@]}" -gt 1 ]; then
    echo "⚠ múltiplos candidatos para $B:"
    printf '   - %s\n' "${CAND[@]}"
    echo "   (ignorado para evitar erro)"
    return
  fi
  echo "✓ mover ${CAND[0]} → $DST"
  mkdir -p "$(dirname "$DST")"
  eval $MV "\"${CAND[0]}\"" "\"$DST\""
}

# ---- MOVES views (qualquer sítio → estrutura nova) ----
move_found "views/spotify_results.py"   "views/spotify/results.py"
move_found "views/spotify_page.py"      "views/spotify/page.py"
move_found "views/spotify_helpers.py"   "views/spotify/helpers.py"
move_found "views/spotify_wiki_info.py" "views/spotify/wiki_info.py"
move_found "views/spotify_ui.py"        "views/spotify/components/legacy_ui.py"

# Também cobre o caso em que já estão debaixo de views/spotify/ com prefixo "spotify_"
move_found "views/spotify/spotify_results.py"   "views/spotify/results.py"
move_found "views/spotify/spotify_page.py"      "views/spotify/page.py"
move_found "views/spotify/spotify_helpers.py"   "views/spotify/helpers.py"
move_found "views/spotify/spotify_wiki_info.py" "views/spotify/wiki_info.py"
move_found "views/spotify/spotify_ui.py"        "views/spotify/components/legacy_ui.py"

# ---- MOVES services (ficheiros soltos → services/spotify/) ----
move_found "services/spotify_oauth.py"        "services/spotify/auth.py"
move_found "services/spotify_lookup.py"       "services/spotify/lookup.py"
move_found "services/spotify_radio.py"        "services/spotify/radio.py"
move_found "services/spotify_push.py"         "services/spotify/push.py"
move_found "services/spotify_session_push.py" "services/spotify/session_push.py"
move_found "services/spotify_genres.py"       "services/spotify/genres.py"
move_found "services/spotify_search.py"       "services/spotify/search.py"
move_found "services/spotify_albums.py"       "services/spotify/albums.py"

echo "→ Criar __init__.py e shims…"
mkdir -p views/spotify/components services/spotify

# __init__ spotify services (reexport)
cat > services/spotify/__init__.py <<'PY'
"""Namespace Spotify (serviços). Re-exporta módulos comuns para compatibilidade."""
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
for _m in ["core","auth","client","errors","models","mappers","queries","search",
           "albums","radio","genres","lookup","push","session_push"]:
    _reexport(_m)
del _reexport
PY

# __init__ views
[ -f views/spotify/__init__.py ] || echo '"""UI da área Spotify."""' > views/spotify/__init__.py
[ -f views/spotify/components/__init__.py ] || echo '"""Componentes Spotify."""' > views/spotify/components/__init__.py

# Shims de compat
[ -f services/spotify_search.py ] || echo 'from services.spotify.search import *'  > services/spotify_search.py
[ -f services/spotify_albums.py ] || echo 'from services.spotify.albums import *' > services/spotify_albums.py
[ -f views/spotify_results.py ]   || echo 'from views.spotify.results import *'   > views/spotify_results.py

echo "✔ Terminado."
