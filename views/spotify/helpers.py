# views/spotify_helpers.py
import streamlit as st

def reset_spotify_filters():
    """
    Limpa filtros, paginações, seleções e painéis abertos.
    Deixa a app no estado inicial (inputs vazios e página = 1).
    """
    s = st.session_state

    # filtros básicos
    s["name_input"] = ""
    s["genre_input"] = ""            # selectbox
    s["genre_free_input"] = ""

    # query e estado de resultados
    s["query"] = ""
    s["deep_items"] = None

    # paginação
    s["page"] = 1
    s["page_input"] = 1

    # painéis/álbuns abertos
    s["open_albums_for"] = None
    s["albums_data"] = None

    # checkboxes de faixas e seleção de álbum (prefixos)
    for k in list(s.keys()):
        if k.startswith("chk_") or k.startswith("selected_album_id_"):
            s.pop(k, None)

    # qualquer outra paginação/estado antigo que possas ter usado
    for k in ("spotify_csv_page", "spotify_csv_ps"):
        s.pop(k, None)

    # # rerun compatível com versões antigas/novas do Streamlit
    # try:
    #     st.rerun()
    # except AttributeError:
    #     st.experimental_rerun()
    return True