# views/genres/css.py
STYLE = """
/* =================== Breadcrumbs (tamanho normal) =================== */
.breadcrumbs div.stButton > button{
    width: 100%;
    background-color: #f0f2f6 !important;
    border-color: #d9d9d9 !important;
    box-shadow: none !important;
    min-height: 36px !important;
    padding: 0.50rem 0.90rem !important;
    line-height: 1.25rem !important;
}
.breadcrumbs div.stButton > button[disabled]{
    background-color: #e6e9ef !important;
    border-color: #bfc3c9 !important;
    font-weight: 600;
}

/* =================== Branch list — ULTRA-COMPACT =================== */
/* reduz os gaps entre colunas/linhas do layout gerado pelo Streamlit */
.branches [data-testid="stHorizontalBlock"]{
    gap: .15rem !important;
    margin: 0 !important;
}
.branches [data-testid="stVerticalBlock"]{
    gap: .10rem !important;
    margin: 0 !important;
}

/* zera padding/margens internas dos content wrappers das colunas */
.branches [data-testid="column"] > div{
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    margin-top: 0 !important;
    margin-bottom: 0 !important;
}

/* botão em si — mata o min-height nativo e encolhe o padding */
.branches div.stButton > button,
.branches button[kind],
.branches button[data-testid="baseButton-secondary"],
.branches button[data-testid="baseButton-primary"]{
    min-height: 0 !important;
    height: 26px !important;              /* altura alvo do botão */
    padding: .15rem .45rem !important;    /* controla a “altura visual” */
    line-height: 1 !important;
    font-size: .90rem !important;
    border-radius: 10px !important;
}

/* remove margens dos <p> que vêm do markdown (evita altura extra) */
.branches [data-testid="stMarkdownContainer"] p{
    margin: 0 !important;
}

/* wrapper do st.button também tem margem vertical — reduzida aqui */
.branches div.stButton{
    margin: .06rem 0 !important;
}

/* =================== Slider mais compacto =================== */
div[data-testid="stSlider"] > label { margin-bottom: 0.10rem !important; }
div[data-testid="stSlider"] > div  { padding-top: 0 !important; padding-bottom: 0 !important; }
div[data-testid="stTickBar"]       { margin-top: 0.15rem !important; }
"""
