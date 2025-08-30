# cinema/config.py
from __future__ import annotations
from pathlib import Path

# CSV separator (o teu projeto usa ';')
SEP = ";"

# Diretório base: mesmo diretório deste módulo
BASE_DIR = Path(__file__).resolve().parent

# Caminhos dos CSVs (ficam no mesmo diretório do módulo)
FILES = {
    "Movies":      BASE_DIR / "movies.csv",
    "Series":      BASE_DIR / "series.csv",
    "Soundtracks": BASE_DIR / "soundtracks.csv",
}

# Esquema base dos CSVs
SCHEMA = {
    "Movies": [
        "id", "title", "director", "year", "genre",
        "streaming", "rating", "notes",
        "watched", "watched_date"
    ],
    # Series agora tem uma linha por temporada → inclui 'season'
    "Series": [
        "id", "title", "creator", "season", "year_start", "year_end", "genre",
        "streaming", "rating", "notes",
        "watched", "watched_date"
    ],
    "Soundtracks": [
        "id", "title", "artist", "year", "genre", "subgenre",
        "rating", "notes", "related_movie_id", "related_series_id"
    ],
}

# Ficheiro(s) de géneros (PT por omissão)
GENRE_FILES = [
    BASE_DIR / "generos_cinema_selectbox.csv",
    # Se um dia tiveres EN: BASE_DIR / "generos_cinema_selectbox_en.csv",
]
