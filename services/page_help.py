# services/page_help.py
from __future__ import annotations
import streamlit as st

HELP: dict[str, dict[str, str]] = {
    "spotify": {
        "EN": ("**Search artists, albums or tracks.** Use filters if available and toggle "
               "**Audio previews** to hear 30-second snippets. Click a result for details."),
        "PT": ("**Pesquise artistas, álbuns ou faixas.** Use os filtros (se existirem) e ative "
               "**Audio previews** para ouvir excertos de 30 s. Clique num resultado para detalhes."),
    },
    "wikipedia": {
        "EN": ("**Type a term** to fetch a concise summary from Wikipedia. "
               "Follow the links to open the full article."),
        "PT": ("**Escreva um termo** para obter um resumo da Wikipedia. "
               "Use as ligações para abrir o artigo completo."),
    },
    "genres": {
        "EN": ("**Search a genre** to see a curated description and related styles. "
               "Use the page links to jump to **Genealogy** or **Influence map**."),
        "PT": ("**Pesquise um género** para ver uma descrição curada e estilos relacionados. "
               "Use as ligações da página para ir para a **Genealogy** ou **Influence map**."),
    },
    "playlists": {
        "EN": ("**Build playlists** from selected seeds (genres, artists, tracks). "
               "Adjust options and export to Spotify if connected."),
        "PT": ("**Crie playlists** a partir de sementes (géneros, artistas, faixas). "
               "Ajuste as opções e exporte para o Spotify se estiver ligado."),
    },
    "genealogy": {
        "EN": ("**Type a genre** and set the map depth. "
               "Choose the branch level-by-level and toggle **Show only the selected branch** to isolate it."),
        "PT": ("**Escreva um género** e defina a profundidade do mapa. "
               "Escolha o ramo nível a nível e ative **Show only the selected branch** para o isolar."),
    },
    "influence_map": {
        "EN": ("**Choose the start genre** and **depth** to draw downstream influences. "
               "Use **Levels up** to include ancestors; switch data source when available."),
        "PT": ("**Escolha o género inicial** e a **profundidade** para desenhar as influências a jusante. "
               "Use **Levels up** para incluir ancestrais; altere a fonte de dados quando existir."),
    },
    "explore": {
    "EN": ("Search a genre, set the map depth and pick the branch level-by-level. "
           "Toggle **Show only the selected branch** to isolate it."),
    "PT": ("Pesquise um género, defina a profundidade do mapa e escolha o ramo nível a nível. "
           "Ative **Show only the selected branch** para o isolar."),
    },

}

def show_page_help(page_key: str, lang: str | None = None, icon: str = "❓") -> None:
    lang = (lang or st.session_state.get("lang") or "EN").upper()
    if page_key not in HELP:
        return

    col_spacer, col_icon = st.columns([0.93, 0.07])
    with col_icon:
        # Usa popover se existir; caso contrário, expander
        if hasattr(st, "popover"):
            with st.popover(icon, help="Help / Ajuda", use_container_width=True):
                st.markdown(f"**EN** — {HELP[page_key]['EN']}")
                st.markdown("---")
                st.markdown(f"**PT** — {HELP[page_key]['PT']}")
        else:
            with st.expander(icon + " Help / Ajuda", expanded=False):
                st.markdown(f"**EN** — {HELP[page_key]['EN']}")
                st.markdown("---")
                st.markdown(f"**PT** — {HELP[page_key]['PT']}")
