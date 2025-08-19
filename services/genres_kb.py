# services/genres_kb.py
# -----------------------------------------------------------------------------
# Music4all · Base curada de géneros + utilitários de geneaologia/summary
# -----------------------------------------------------------------------------
from typing import List, Dict, Set, Tuple
from collections import deque

# ======================
# Aliases / nomes canónicos (inclui variações PT/EN)
# ======================
ALIASES: Dict[str, str] = {
    # variações comuns
    "r&b": "Rhythm and Blues",
    "rock & roll": "Rock and Roll",
    "rock n roll": "Rock and Roll",
    "rock ’n’ roll": "Rock and Roll",
    "prog rock": "Progressive Rock",
    "rock progressivo": "Progressive Rock",
    "synthpop": "Synth-pop",
    "dance pop": "Dance-pop",
    "doo wop": "Doo-wop",
    "britpop": "Britpop",
    "art pop": "Art Pop",
    "power pop": "Power Pop",
    "post punk": "Post-punk",
    "hard rock": "Hard Rock",
    "blues rock": "Blues Rock",
    "new wave": "New Wave",
    "country blues": "Country Blues",
    "classico": "Classical",
    "eletrónica": "Electronic",
    "electronica": "Electronic",
    "hip hop": "Hip Hop",
    "hip-hop": "Hip Hop",
    "latino": "Latin",
    "latina": "Latin",
    "reggae": "Reggae",
}

def canonical_name(name: str) -> str:
    """Converte um nome para a forma canónica usando ALIASES."""
    key = (name or "").strip()
    low = key.lower()
    return ALIASES.get(low, key)

def _mk_list(items: List[str]) -> str:
    return ", ".join(items) if items else "—"

# ======================
# Blocos curados (resumo editorial por género)
# ======================
# BLURBS: Dict[str, Dict] = {
#     # --- Raiz e primeira geração ---
#     "Blues": {
#         "period": "finais séc. XIX – anos 1920",
#         "regions": ["Sul dos EUA", "Mississippi Delta", "Chicago (era elétrica)"],
#         "characteristics": [
#             "forma 12 compassos", "escala blues", "call-and-response",
#             "improvisação", "timbre vocal expressivo"
#         ],
#         "notes": ("Eletrificação em Chicago → R&B e Rock. "
#                   "‘Blues’ liga-se a ‘blue devils’ (melancolia)."),
#     },
#     "Country Blues": {
#         "period": "anos 1910–1930",
#         "regions": ["Sul rural dos EUA"],
#         "characteristics": ["voz e guitarra solo", "improvisação rítmico-harmónica"],
#         "notes": "Uma das primeiras cristalizações regionais do Blues.",
#     },
#     "Rhythm and Blues": {
#         "period": "anos 1940–1950",
#         "regions": ["EUA (cidades)"],
#         "characteristics": ["backbeat forte", "metais", "vocais com ‘gospel feel’"],
#         "notes": "Charneira entre Blues e Rock & Roll; diálogo com Soul e Gospel.",
#     },
#     "Rock and Roll": {
#         "period": "c. 1954–1960 (primeira vaga)",
#         "regions": ["EUA"],
#         "characteristics": ["backbeat 2/4", "12-compassos herdado", "vocais energéticos"],
#         "notes": "Fusão de R&B e Country; canal de passagem do Blues para a música popular juvenil.",
#     },
#     "Country": {
#         "period": "anos 1920–1940",
#         "regions": ["EUA (Sul/Appalachia)"],
#         "characteristics": ["harmonia simples", "narrativa", "instrumentação acústica"],
#         "notes": "Em cruza com R&B origina o Rock and Roll (via Rockabilly).",
#     },
#     "Gospel": {
#         "period": "anos 1920–1940",
#         "regions": ["EUA"],
#         "characteristics": ["vocais corais", "chamadas-respostas", "harmonia diatónica"],
#         "notes": "Fonte vocal para R&B, Soul e Pop de matriz Motown.",
#     },

#     # --- Pop & derivados ---
#     "Traditional Pop": {
#         "period": "décadas de 1930–1950",
#         "regions": ["EUA", "Reino Unido"],
#         "characteristics": ["canção padrão (Tin Pan Alley)", "arranjos orquestrais", "crooners"],
#         "notes": "Base melódica e estrutural para baladas pop do pós-guerra.",
#     },
#     "Doo-wop": {
#         "period": "anos 1950–início 1960",
#         "regions": ["EUA"],
#         "characteristics": ["harmonias vocais em bloco", "padrões I–vi–IV–V", "onomatopeias ‘doo-wop’"],
#         "notes": "Ponte vocal entre R&B e Pop/rock inicial.",
#     },
#     "Soul": {
#         "period": "anos 1960",
#         "regions": ["EUA (Detroit, Memphis)"],
#         "characteristics": ["vocais gospelizados", "seção rítmica marcada", "metais"],
#         "notes": "Cruza R&B com Gospel; origina variantes como Motown.",
#     },
#     "Motown": {
#         "period": "anos 1960",
#         "regions": ["Detroit (EUA)"],
#         "characteristics": ["groove dançável", "arranjos polidos", "hooks fortes"],
#         "notes": "Estética que define muito do Pop dos 60s.",
#     },
#     "Pop": {
#         "period": "desde finais dos 1950s (consolidação nos 1960s) até hoje",
#         "regions": ["Global"],
#         "characteristics": ["estrutura verso–refrão", "melodias/hook marcantes",
#                             "produção de estúdio", "duração radio-friendly"],
#         "notes": ("Herda de Rock & Roll e R&B, mas também de Traditional Pop/Tin Pan Alley e Doo-wop; "
#                   "ao longo das décadas absorve Soul, Disco, Eletrónica e Hip-hop."),
#     },
#     "Pop Rock": {
#         "period": "meados 1960s →",
#         "regions": ["EUA", "Reino Unido"],
#         "characteristics": ["guitarras com ênfase melódica", "refrões cativantes"],
#         "notes": "Interseção direta entre Pop e Rock; base para Power Pop e Britpop.",
#     },
#     "Power Pop": {
#         "period": "final 1960s–1970s",
#         "regions": ["EUA", "Reino Unido"],
#         "characteristics": ["harmonias vocais", "guitarras brilhantes", "refrões fortes"],
#         "notes": "Derivado melódico de Pop Rock (The Who/Beatles como matriz).",
#     },
#     "Art Pop": {
#         "period": "1960s →",
#         "regions": ["Reino Unido", "Europa"],
#         "characteristics": ["estética conceptual", "produção experimental", "ênfase autoral"],
#         "notes": "Ponto de contacto entre Pop e Art Rock.",
#     },

#     # --- Rock & proximidades ---
#     "Rock": {
#         "period": "desde 1960s",
#         "regions": ["Global"],
#         "characteristics": ["secção rítmica forte", "guitarras", "ênfase em bandas"],
#         "notes": "Abrange múltiplos ramos descendentes: Hard Rock, Psych, Prog, Punk, etc.",
#     },
#     "British Blues": {
#         "period": "c. 1963–1968",
#         "regions": ["Reino Unido"],
#         "characteristics": ["adaptação elétrica do Chicago Blues", "guitarra virtuosa"],
#         "notes": "Catalisou Blues Rock/Hard Rock (Cream, Yardbirds, Led Zeppelin).",
#     },
#     "Blues Rock": {
#         "period": "meados 1960s →",
#         "regions": ["Reino Unido", "EUA"],
#         "characteristics": ["riffs de blues amplificados", "improvisação de guitarra"],
#         "notes": "Ponte direta do Blues (especialmente linha britânica) para o Hard Rock.",
#     },
#     "Hard Rock": {
#         "period": "final 1960s–1970s",
#         "regions": ["Reino Unido", "EUA"],
#         "characteristics": ["riffs pesados", "drums marcantes", "vocais potentes"],
#         "notes": "Consolida-se a partir de Blues Rock e Psych; tangencia o Heavy Metal.",
#     },
#     "Heavy Metal": {
#         "period": "final 1960s–1970s",
#         "regions": ["Reino Unido", "EUA"],
#         "characteristics": ["guitarras distorcidas", "riffs pesados", "potência sonora"],
#         "notes": "Desdobra-se em inúmeras variantes; mantém raízes em Hard/Blues Rock.",
#     },
#     "Garage Rock": {
#         "period": "meados 1960s",
#         "regions": ["EUA"],
#         "characteristics": ["crueza sonora", "energia juvenil", "estruturas simples"],
#         "notes": "Antepassado direto do Punk Rock.",
#     },
#     "Psychedelic Rock": {
#         "period": "c. 1966–1969",
#         "regions": ["São Francisco", "Reino Unido"],
#         "characteristics": ["texturas experimentais", "efeitos/feedback", "canções longas"],
#         "notes": "Ponte para o Art/Progressive Rock.",
#     },
#     "Art Rock": {
#         "period": "final 1960s–1970s",
#         "regions": ["Reino Unido", "Europa"],
#         "characteristics": ["conceitos artísticos", "experimentos formais", "estúdio como instrumento"],
#         "notes": "Alimenta o Prog e dialoga com Art Pop.",
#     },
#     "Progressive Rock": {
#         "period": "c. 1968–1977; revival 1990s→",
#         "regions": ["Reino Unido", "Europa"],
#         "characteristics": [
#             "suites", "assinaturas ímpares", "harmonia modal/tonal mista",
#             "álbuns conceptuais", "virtuosismo instrumental"
#         ],
#         "notes": ("Expande Psych/Art Rock e dialoga com o Jazz; mantém raízes no Blues via rock britânico. "
#                   "Influenciou neo-prog e prog metal."),
#     },
#     "Punk Rock": {
#         "period": "meados 1970s",
#         "regions": ["Reino Unido", "EUA"],
#         "characteristics": ["andamentos rápidos", "estética DIY", "agressividade"],
#         "notes": "Reacção crua ao rock mainstream; dá origem a Post-punk e New Wave.",
#     },
#     "Post-punk": {
#         "period": "final 1970s–início 1980s",
#         "regions": ["Reino Unido", "Europa"],
#         "characteristics": ["experimentação rítmica", "texturas sombrias", "influência eletrónica"],
#         "notes": "Laboratório para Alternative Rock e fusões com eletrónica.",
#     },
#     "New Wave": {
#         "period": "final 1970s–1980s",
#         "regions": ["Reino Unido", "EUA"],
#         "characteristics": ["sensibilidade pop", "produção mais limpa", "uso de sintetizadores"],
#         "notes": "Deriva do Punk mas com ênfase pop/electro; origina o Synth-pop.",
#     },

#     # --- Funk/Disco/Eletrónica & outros eixos ---
#     "Funk": {
#         "period": "meados 1960s–1970s",
#         "regions": ["EUA"],
#         "characteristics": ["groove sincopado", "baixo marcante", "seção de sopros"],
#         "notes": "Base rítmica para Disco e para vertentes de Pop dançável.",
#     },
#     "Disco": {
#         "period": "meados–final 1970s",
#         "regions": ["EUA", "Europa"],
#         "characteristics": ["quatro por quatro dançável", "cordas/metais", "produção polida"],
#         "notes": "Alimenta o Dance-pop e a música eletrónica de pista.",
#     },
#     "Electronic": {
#         "period": "1950s →",
#         "regions": ["Europa", "Global"],
#         "characteristics": ["síntese sonora", "drum machines", "programação"],
#         "notes": "Umbrella para synth-based; influencia Pop, New Wave e Dance-pop.",
#     },
#     "Synth-pop": {
#         "period": "final 1970s–1980s",
#         "regions": ["Reino Unido", "Europa"],
#         "characteristics": ["sintetizadores proeminentes", "drum machines", "produção eletrónica"],
#         "notes": "Deriva de New Wave/Eletrónica dentro do ecossistema Pop.",
#     },
#     "Dance-pop": {
#         "period": "1980s →",
#         "regions": ["Global"],
#         "characteristics": ["andamento dançável", "estrutura pop", "produção club-oriented"],
#         "notes": "Fusão Pop com Disco/Eletrónica.",
#     },
#     "Britpop": {
#         "period": "1990s",
#         "regions": ["Reino Unido"],
#         "characteristics": ["melodia e canção", "referências pop britânicas", "guitarras"],
#         "notes": "Deriva de Pop Rock/Alternative com ênfase britânica.",
#     },
#     # (podes ir acrescentando mais blocos aqui)
#}
BLURBS = {
    # --- Roots / first generation ---
    "Blues": {
        "period": "late 19th c. – 1920s",
        "regions": ["US South", "Mississippi Delta", "Chicago (electric era)"],
        "characteristics": [
            "12-bar form", "blues scale", "call-and-response",
            "improvisation", "expressive vocal timbre"
        ],
        "notes": "Chicago electrification fed R&B and Rock."
    },
    "Country Blues": {
        "period": "1910s–1930s",
        "regions": ["Rural US South"],
        "characteristics": ["voice + solo guitar", "loose rhythm/harmony", "improvised phrasing"],
        "notes": "One of the earliest regional crystallisations of the Blues."
    },
    "Rhythm and Blues": {
        "period": "1940s–1950s",
        "regions": ["Urban US"],
        "characteristics": ["strong backbeat", "horn sections", "gospel-tinged vocals"],
        "notes": "Bridge from Blues to Rock ’n’ Roll; cross-talk with Soul and Gospel."
    },
    "Rock and Roll": {
        "period": "c. 1954–1960 (first wave)",
        "regions": ["US"],
        "characteristics": ["2/4 backbeat", "12-bar inheritance", "energetic vocals"],
        "notes": "Fusion of R&B and Country; youth-driven popular music channel."
    },
    "Country": {
        "period": "1920s–1940s",
        "regions": ["US (South/Appalachia)"],
        "characteristics": ["simple harmony", "narrative lyrics", "acoustic instrumentation"],
        "notes": "Crosses with R&B → Rock ’n’ Roll (via Rockabilly)."
    },
    "Gospel": {
        "period": "1920s–1940s",
        "regions": ["US"],
        "characteristics": ["choir-style vocals", "call-and-response", "diatonic harmony"],
        "notes": "Vocal source for R&B, Soul and Pop (Motown)."
    },

    # --- Pop & satellites ---
    "Traditional Pop": {
        "period": "1930s–1950s",
        "regions": ["US", "UK"],
        "characteristics": ["Tin Pan Alley songcraft", "orchestral arrangements", "crooner vocals"],
        "notes": "Melodic/structural base for post-war pop ballads."
    },
    "Doo-wop": {
        "period": "1950s–early 1960s",
        "regions": ["US"],
        "characteristics": ["block vocal harmonies", "I–vi–IV–V patterns", "nonsense syllables"],
        "notes": "Vocal bridge from R&B to early Pop/Rock."
    },
    "Soul": {
        "period": "1960s",
        "regions": ["US (Detroit, Memphis)"],
        "characteristics": ["gospel-inflected vocals", "tight rhythm section", "horns"],
        "notes": "R&B × Gospel; yields variants such as Motown."
    },
    "Motown": {
        "period": "1960s",
        "regions": ["Detroit (US)"],
        "characteristics": ["danceable groove", "polished arrangements", "strong hooks"],
        "notes": "Aesthetics that defined much of 60s Pop."
    },
    "Pop": {
        "period": "late 1950s/1960s → present",
        "regions": ["Global"],
        "characteristics": ["verse–chorus form", "memorable hooks", "studio production", "radio-friendly length"],
        "notes": "Inherits from Rock ’n’ Roll & R&B and absorbs Soul, Disco, Electronic and Hip-hop over time."
    },
    "Pop Rock": {
        "period": "mid-1960s →",
        "regions": ["US", "UK"],
        "characteristics": ["guitars with melodic focus", "catchy choruses"],
        "notes": "Direct intersection of Pop and Rock; basis for Power Pop and Britpop."
    },
    "Power Pop": {
        "period": "late 1960s–1970s",
        "regions": ["US", "UK"],
        "characteristics": ["stacked harmonies", "bright guitars", "strong refrains"],
        "notes": "Melodic offshoot of Pop Rock (Beatles/Who lineage)."
    },
    "Art Pop": {
        "period": "1960s →",
        "regions": ["UK", "Europe"],
        "characteristics": ["conceptual aesthetics", "experimental production", "authorial focus"],
        "notes": "Contact point between Pop and Art Rock."
    },

    # --- Rock & neighbours ---
    "Rock": {
        "period": "since 1960s",
        "regions": ["Global"],
        "characteristics": ["strong rhythm section", "guitars", "band-centric performance"],
        "notes": "Umbrella for Hard Rock, Psychedelic, Prog, Punk, etc."
    },
    "British Blues": {
        "period": "c. 1963–1968",
        "regions": ["UK"],
        "characteristics": ["electric Chicago-style rework", "guitar virtuosity"],
        "notes": "Catalysed Blues Rock/Hard Rock (Cream, Yardbirds, Led Zeppelin)."
    },
    "Blues Rock": {
        "period": "mid-1960s →",
        "regions": ["UK", "US"],
        "characteristics": ["amplified blues riffs", "guitar improvisation"],
        "notes": "Direct bridge from Blues (esp. British line) to Hard Rock."
    },
    "Hard Rock": {
        "period": "late 1960s–1970s",
        "regions": ["UK", "US"],
        "characteristics": ["heavy riffs", "pounding drums", "power vocals"],
        "notes": "Consolidates from Blues Rock and Psychedelic; borders Heavy Metal."
    },
    "Heavy Metal": {
        "period": "late 1960s–1970s",
        "regions": ["UK", "US"],
        "characteristics": ["distorted guitars", "dense riffs", "high-volume aesthetics"],
        "notes": "Splits into many substyles; roots in Hard/Blues Rock."
    },
    "Garage Rock": {
        "period": "mid-1960s",
        "regions": ["US"],
        "characteristics": ["raw sound", "youthful energy", "simple structures"],
        "notes": "Direct ancestor of Punk Rock."
    },
    "Psychedelic Rock": {
        "period": "c. 1966–1969",
        "regions": ["San Francisco", "UK"],
        "characteristics": ["experimental textures", "effects/feedback", "extended forms"],
        "notes": "Bridge to Art/Progressive Rock."
    },
    "Art Rock": {
        "period": "late 1960s–1970s",
        "regions": ["UK", "Europe"],
        "characteristics": ["art concepts", "formal experiments", "studio as instrument"],
        "notes": "Feeds Prog and dialogues with Art Pop."
    },
    "Progressive Rock": {
        "period": "c. 1968–1977; revival 1990s →",
        "regions": ["UK", "Europe"],
        "characteristics": [
            "suites/long forms", "odd meters", "modal/tonal mix",
            "concept albums", "instrumental virtuosity"
        ],
        "notes": "Expands Psychedelic/Art Rock and cross-fertilises with Jazz; influenced neo-prog and prog metal."
    },
    "Punk Rock": {
        "period": "mid-1970s",
        "regions": ["UK", "US"],
        "characteristics": ["fast tempi", "DIY aesthetics", "aggression"],
        "notes": "Raw reaction to mainstream rock; spawns Post-punk and New Wave."
    },
    "Post-punk": {
        "period": "late 1970s–early 1980s",
        "regions": ["UK", "Europe"],
        "characteristics": ["rhythmic experimentation", "darker textures", "electronic influence"],
        "notes": "Laboratory for Alternative Rock and electro fusions."
    },
    "New Wave": {
        "period": "late 1970s–1980s",
        "regions": ["UK", "US"],
        "characteristics": ["pop sensibility", "cleaner production", "use of synthesizers"],
        "notes": "Derives from Punk with pop/electro emphasis; leads to Synth-pop."
    },

    # --- Funk / Disco / Electronic & beyond ---
    "Funk": {
        "period": "mid-1960s–1970s",
        "regions": ["US"],
        "characteristics": ["syncopated groove", "prominent bass", "horn sections"],
        "notes": "Rhythmic base for Disco and dance-oriented Pop."
    },
    "Disco": {
        "period": "mid- to late 1970s",
        "regions": ["US", "Europe"],
        "characteristics": ["four-on-the-floor", "strings/horns", "polished production"],
        "notes": "Feeds Dance-pop and electronic club music."
    },
    "Electronic": {
        "period": "1950s →",
        "regions": ["Europe", "Global"],
        "characteristics": ["sound synthesis", "drum machines", "programming"],
        "notes": "Umbrella for synth-based styles; influences Pop, New Wave, Dance-pop."
    },
    "Synth-pop": {
        "period": "late 1970s–1980s",
        "regions": ["UK", "Europe"],
        "characteristics": ["prominent synths", "drum machines", "electronic production"],
        "notes": "Offshoot of New Wave/Electronic within the Pop ecosystem."
    },
    "Dance-pop": {
        "period": "1980s →",
        "regions": ["Global"],
        "characteristics": ["danceable tempo", "pop song form", "club-oriented production"],
        "notes": "Pop fused with Disco/Electronic."
    },
    "Britpop": {
        "period": "1990s",
        "regions": ["UK"],
        "characteristics": ["melodic focus", "British pop references", "guitars"],
        "notes": "Derivative of Pop Rock/Alternative with British emphasis."
    },
}

# ======================
# Relações curadas (grafo PAI -> FILHO)
# ======================
_KB_UP: Dict[str, Set[str]] = {
    "Rock and Roll": {"Rhythm and Blues", "Country", "Blues"},
    "Soul": {"Rhythm and Blues", "Gospel", "Blues"},
    "Motown": {"Soul", "Rhythm and Blues", "Gospel"},
    "Pop": {"Rock and Roll", "Rhythm and Blues", "Traditional Pop", "Doo-wop", "Soul"},

    "Rock": {"Rock and Roll", "Rhythm and Blues", "Blues", "Country"},
    "British Blues": {"Blues"},
    "Blues Rock": {"Blues", "British Blues"},
    "Hard Rock": {"Blues Rock", "Psychedelic Rock", "British Blues"},
    "Heavy Metal": {"Hard Rock"},
    "Psychedelic Rock": {"Rock", "Blues Rock"},
    "Art Rock": {"Psychedelic Rock", "Rock"},
    "Progressive Rock": {"Psychedelic Rock", "Art Rock", "Jazz"},
    "Pop Rock": {"Pop", "Rock"},
    "Power Pop": {"Pop Rock"},
    "Garage Rock": {"Rock and Roll"},
    "Punk Rock": {"Garage Rock", "Rock and Roll"},
    "Post-punk": {"Punk Rock", "Art Rock", "Electronic"},
    "New Wave": {"Punk Rock", "Pop", "Disco", "Electronic"},

    "Funk": {"Rhythm and Blues", "Soul"},
    "Disco": {"Funk", "Soul"},
    "Synth-pop": {"New Wave", "Electronic", "Pop"},
    "Dance-pop": {"Pop", "Disco", "Electronic"},

    "Britpop": {"Pop Rock", "Alternative Rock"},
}

_KB_DOWN: Dict[str, Set[str]] = {
    "Blues": {"Rhythm and Blues", "Jazz", "Country Blues", "British Blues", "Blues Rock"},
    "Country": {"Rockabilly"},
    "Rhythm and Blues": {"Rock and Roll", "Soul", "Doo-wop", "Funk"},
    "Rock and Roll": {"Rock", "Pop", "Garage Rock", "Rockabilly"},
    "Rock": {"Hard Rock", "Blues Rock", "Psychedelic Rock", "Art Rock", "Punk Rock", "Pop Rock", "Progressive Rock"},
    "British Blues": {"Blues Rock", "Hard Rock"},
    "Blues Rock": {"Hard Rock"},
    "Hard Rock": {"Heavy Metal"},
    "Soul": {"Motown", "Funk", "Disco"},
    "Motown": {"Pop"},
    "Pop": {"Pop Rock", "Art Pop", "Synth-pop", "Dance-pop", "Teen Pop"},
    "Pop Rock": {"Power Pop", "Britpop"},
    "Punk Rock": {"Post-punk", "New Wave", "Hardcore Punk"},
    "New Wave": {"Synth-pop"},
    "Psychedelic Rock": {"Progressive Rock"},
    "Progressive Rock": {"Neo-progressive Rock", "Progressive Metal"},
    "Funk": {"Disco"},
    "Disco": {"Dance-pop"},
    "Electronic": {"Synth-pop", "Dance-pop"},
}

def kb_neighbors(genre: str) -> Tuple[List[str], List[str]]:
    """Pais/filhos curados para o género (se existir)."""
    g = canonical_name(genre)
    parents = set(_KB_UP.get(g, set()))
    for p, childs in _KB_DOWN.items():
        if g in childs:
            parents.add(p)

    children = set(_KB_DOWN.get(g, set()))
    for c, ups in _KB_UP.items():
        if g in ups:
            children.add(c)

    parents.discard(g); children.discard(g)
    return sorted(parents, key=str.lower), sorted(children, key=str.lower)

def build_kb_graph(focus: str, down_depth: int = 2, up_levels: int = 1):
    """Cria um pequeno grafo a partir das relações curadas (para fallback/visuais)."""
    f = canonical_name(focus)

    nodes: Set[str] = set([f])
    links: List[Tuple[str, str, int]] = []

    # Descendentes (jusante)
    dq = deque([(f, 0)])
    seen_down = set([f])
    while dq:
        u, d = dq.popleft()
        if d >= down_depth:
            continue
        for v in sorted(_KB_DOWN.get(u, set())):
            nodes.update([u, v])
            links.append((u, v, 1))
            if v not in seen_down:
                seen_down.add(v)
                dq.append((v, d + 1))

    # Ancestrais (montante)
    aq = deque([(f, 0)])
    seen_up = set([f])

    def parents_of(x: str) -> Set[str]:
        ups = set(_KB_UP.get(x, set()))
        for p, childs in _KB_DOWN.items():
            if x in childs:
                ups.add(p)
        ups.discard(x)
        return ups

    while aq:
        u, d = aq.popleft()
        if d >= up_levels:
            continue
        for p in sorted(parents_of(u)):
            nodes.update([p, u])
            links.append((p, u, 1))  # pai -> filho
            if p not in seen_up:
                seen_up.add(p)
                aq.append((p, d + 1))

    def _key(n): return (0 if n == f else 1, n.lower())
    nodes = sorted(nodes, key=_key)
    return nodes, links

def genre_summary(genre: str, parents: List[str], children: List[str]) -> str:
    """Resumo Markdown combinando bloco curado (se existir) com pais/filhos fornecidos."""
    g = canonical_name(genre)
    block = BLURBS.get(g, {})
    period = block.get("period", "—")
    regions = block.get("regions", [])
    chars = block.get("characteristics", [])
    notes = block.get("notes", "")

    md = [f"### {g}",
          f"**Período:** {period}",
          f"**Áreas-chave:** {_mk_list(regions)}",
          f"**Características típicas:** {_mk_list(chars)}",
          "",
          "**Influências (montante):** " + (_mk_list(parents) if parents else "—"),
          "**Derivações (jusante):** " + (_mk_list(children) if children else "—")]
    if notes:
        md += ["", notes]
    if not block:
        md += ["", "_(Resumo automático; adiciona um bloco em `services/genres_kb.py` para melhorar.)_"]
    return "\n".join(md)
