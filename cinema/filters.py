import pandas as pd

def parse_year_filter(txt: str):
    if not txt or not str(txt).strip():
        return ("none", None)
    s = str(txt).strip()
    if "-" in s:
        a, b = s.split("-", 1)
        try:
            a, b = int(a.strip()), int(b.strip())
            if a > b: a, b = b, a
            return ("range", (a, b))
        except Exception:
            return ("none", None)
    try:
        return ("exact", int(s))
    except Exception:
        return ("none", None)

def apply_filters(section: str, df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)

    def contains(col, val):
        return df[col].astype(str).str.contains(str(val), case=False, na=False)

    if filters.get("title"):
        m &= contains("title", filters["title"])
    if section == "Movies" and filters.get("director"):
        m &= contains("director", filters["director"])
    if section == "Series" and filters.get("creator"):
        m &= contains("creator", filters["creator"])
    if section == "Soundtracks" and filters.get("artist"):
        m &= contains("artist", filters["artist"])

    gen = filters.get("genre")
    if gen and gen != "All":
        m &= df["genre"].fillna("").astype(str).str.strip().str.casefold().eq(str(gen).strip().casefold())

    if section == "Movies":
        w = filters.get("watched")
        if w in ("Yes", "No"):
            m &= df["watched"].fillna(False) == (w == "Yes")

    mode, val = parse_year_filter(filters.get("year", ""))
    if mode != "none":
        col = "year" if "year" in df.columns else "year_start"
        coln = pd.to_numeric(df[col], errors="coerce")
        if mode == "exact":
            m &= (coln == val)
        else:
            a, b = val
            m &= coln.between(a, b, inclusive="both")

    mr = filters.get("min_rating")
    if mr is not None and mr > 0:
        m &= (pd.to_numeric(df["rating"], errors="coerce") >= mr)

    out = df[m].copy()
    if "rating" in out.columns:
        out = out.sort_values(by=["rating","title"], ascending=[False,True], na_position="last")
    else:
        out = out.sort_values(by=["title"], ascending=True)
    return out
