import streamlit as st

def render_filters(default_q: str=""):
    q = st.text_input("Pesquisa no Spotify", value=default_q, placeholder="ex.: artist:radiohead year:1997")
    col1, col2, col3 = st.columns(3)
    with col1:
        limit = st.selectbox("Resultados por página", [10, 20, 30, 50], index=1)
    with col2:
        market = st.selectbox("País", ["PT","US","GB","BR","ES"], index=0)
    with col3:
        explicit = st.checkbox("Incluir explícitas", value=True)
    return q, limit, market, explicit
