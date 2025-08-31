# app_gsheet_direct_altair_prod.py
# Streamlit + Altair — Lecture directe Google Sheets (CSV) -> 3 graphiques
# Mode production : pas de sidebar, IDs figés, fond sombre (via config.toml)

import io
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import streamlit as st
import altair as alt

# ========= Paramètres figés (votre fichier/onglets) =========
SHEET_ID = "1C3ATTbCfnqT-Hx1gqHCA1wLv0Wl9RDrtVn1CgV2P6EY"
GID_VARIATION = 0              # VARIATION JOURNALIÈRE
GID_MM        = 45071720       # MOYENNE MOBILE
GID_RSI       = 372876708      # RSI

# ========= Utilitaires =========
def csv_export_url(sheet_id: str, gid: int) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

@st.cache_data(show_spinner=False, ttl=600)
def fetch_csv_as_df(url: str, timeout: int = 30) -> pd.DataFrame:
    r = requests.get(url, timeout=timeout); r.raise_for_status()
    return pd.read_csv(io.StringIO(r.content.decode("utf-8", errors="replace")))

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))

def normalize_name(s: str) -> str:
    x = strip_accents(str(s)).lower().strip()
    x = re.sub(r"[^\w]+", "_", x); x = re.sub(r"_+", "_", x).strip("_")
    return x

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy(); d.columns = [normalize_name(c) for c in d.columns]; return d

def to_datetime_safe(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")

def to_numeric_safe(s: pd.Series) -> pd.Series:
    if s.dtype == object:
        s2 = s.astype(str).str.replace(r"\s", "", regex=True).str.replace(",", ".", regex=False).str.replace("%", "", regex=False)
        return pd.to_numeric(s2, errors="coerce")
    return pd.to_numeric(s, errors="coerce")

def find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = set(df.columns)
    for c in candidates:
        n = normalize_name(c)
        if n in cols: return n
    for ncol in df.columns:
        for c in candidates:
            if normalize_name(c) in ncol: return ncol
    return None

def date_range_label(df: pd.DataFrame, date_col: str = "date") -> Tuple[str, str]:
    d2 = df[df[date_col].notna()]
    if d2.empty: return "?", "?"
    return (d2[date_col].min().strftime("%Y-%m-%d"), d2[date_col].max().strftime("%Y-%m-%d"))

def last_non_nan(s: pd.Series) -> Optional[float]:
    try: return s.dropna().iloc[-1]
    except Exception: return None

# ========= Parsing spécifique rendements =========
def parse_returns_decimal(series: pd.Series) -> pd.Series:
    s_obj = series.astype(str)
    has_pct = s_obj.str.contains("%", na=False)
    s_clean = s_obj.str.replace(r"\s", "", regex=True).str.replace(",", ".", regex=False).str.replace("%", "", regex=False)
    s_num = pd.to_numeric(s_clean, errors="coerce")
    s_num = s_num.where(~has_pct, s_num / 100.0)
    q95 = s_num.abs().quantile(0.95)
    if pd.notna(q95) and q95 > 1.0:  # valeurs en %
        s_num = s_num / 100.0
    return s_num

# ========= Chargements & validations =========
def load_variation(df_raw: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    msgs: List[str] = []
    d = normalize_columns(df_raw)
    c_date = "date" if "date" in d.columns else find_column(d, ["date", "jour", "datetime"])
    c_var  = find_column(d, ["variation_pct", "variation", "variation_journaliere", "rendement", "return"])
    if not c_date or not c_var:
        raise ValueError("VARIATION: colonnes requises introuvables (date + variation_pct/variation).")
    out = d[[c_date, c_var]].rename(columns={c_date: "date", c_var: "variation_pct"})
    out["date"] = to_datetime_safe(out["date"])
    out["variation_pct"] = parse_returns_decimal(out["variation_pct"])
    if (out["variation_pct"].abs() > 0.5).any():
        msgs.append("Outliers détectés (> ±50% jour/jour) — non filtrés (spécification).")
    return out, msgs

def load_mm(df_raw: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    msgs: List[str] = []
    d = normalize_columns(df_raw)
    c_date  = "date" if "date" in d.columns else find_column(d, ["date", "jour", "datetime"])
    c_close = find_column(d, ["close", "cours", "price", "close_price"])
    c_mm50  = find_column(d, ["mm50", "ma50", "sma50"])
    c_mm200 = find_column(d, ["mm200", "ma200", "sma200"])
    if not all([c_date, c_close, c_mm50, c_mm200]):
        raise ValueError("MM: colonnes requises introuvables (date, close, mm50, mm200).")
    out = d[[c_date, c_close, c_mm50, c_mm200]].rename(columns={c_date:"date", c_close:"close", c_mm50:"mm50", c_mm200:"mm200"})
    out["date"] = to_datetime_safe(out["date"])
    for c in ["close","mm50","mm200"]:
        out[c] = to_numeric_safe(out[c])
    return out, msgs

def load_rsi(df_raw: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    msgs: List[str] = []
    d = normalize_columns(df_raw)
    c_date  = "date" if "date" in d.columns else find_column(d, ["date", "jour", "datetime"])
    c_close = find_column(d, ["close", "cours", "price", "close_price"])
    c_court = find_column(d, ["court", "rsi_court", "rsi_short", "rsi7", "rsi_7"])
    c_moyen = find_column(d, ["moyen", "rsi_moyen", "rsi14", "rsi_14"])
    c_long  = find_column(d, ["long_terme", "long", "rsi_long", "rsi28", "rsi_28", "rsi_long_terme", "longterme"])
    if not c_date or not c_close:
        raise ValueError("RSI: colonnes minimales introuvables (date + close).")
    out = d[[c_date, c_close]].rename(columns={c_date:"date", c_close:"close"})
    out["date"] = to_datetime_safe(out["date"])
    if c_court: out["court"] = to_numeric_safe(d[c_court])
    if c_moyen: out["moyen"] = to_numeric_safe(d[c_moyen])
    if c_long:  out["long_terme"] = to_numeric_safe(d[c_long])
    return out, msgs

# ========= Insights (1 ligne) =========
def insight_rsi_line(df: pd.DataFrame) -> str:
    def zone(v: Optional[float]) -> str:
        if v is None or np.isnan(v): return "n.d."
        if v >= 70: return "surachat"
        if v <= 30: return "survente"
        return "neutre"
    last_date = df["date"].dropna().max()
    rc = last_non_nan(df.get("court", pd.Series(dtype=float)))
    rm = last_non_nan(df.get("moyen", pd.Series(dtype=float)))
    rl = last_non_nan(df.get("long_terme", pd.Series(dtype=float)))
    dstr = last_date.date() if pd.notna(last_date) else "n.d."
    rc_s = "n.d." if rc is None or np.isnan(rc) else f"{rc:.2f}"
    rm_s = "n.d." if rm is None or np.isnan(rm) else f"{rm:.2f}"
    rl_s = "n.d." if rl is None or np.isnan(rl) else f"{rl:.2f}"
    return f"Dernier point {dstr} — Court {rc_s}: {zone(rc)}, Moyen {rm_s}: {zone(rm)}, Long {rl_s}: {zone(rl)}."

def insight_variation_line(df: pd.DataFrame, has_outliers: bool) -> str:
    pos_pct = 100.0 * (df["variation_pct"] > 0).mean()
    base = f"Série centrée autour de 0 — {pos_pct:.0f}% de jours positifs."
    if has_outliers: base += " Outliers ±50% détectés."
    return base

def insight_mm_line(df: pd.DataFrame) -> str:
    last_date = df["date"].dropna().max()
    last = df[df["date"] == last_date].iloc[-1] if pd.notna(last_date) else df.iloc[-1]
    config = "haussière" if last["mm50"] > last["mm200"] else "baissière"
    rel_close = "au-dessus" if (last["close"] > max(last["mm50"], last["mm200"])) else ("au-dessous" if (last["close"] < min(last["mm50"], last["mm200"])) else "entre")
    dstr = last_date.date() if pd.notna(last_date) else "n.d."
    return f"Dernier point {dstr} — config MM {config}, cours {rel_close} des MM."

# ========= Charts Altair (fond transparent) =========
def chart_rsi(df: pd.DataFrame) -> alt.Chart:
    df2 = df.dropna(subset=["date"]).sort_values("date").copy()
    dmin, dmax = date_range_label(df2, "date")
    title = f"RSI (court, moyen, long) — {dmin} à {dmax}"

    long_cols = []
    if "court" in df2.columns: long_cols.append(("court","Court"))
    if "moyen" in df2.columns: long_cols.append(("moyen","Moyen"))
    if "long_terme" in df2.columns: long_cols.append(("long_terme","Long Terme"))
    if not long_cols:
        raise ValueError("RSI: aucune colonne court/moyen/long détectée.")

    melted = pd.melt(df2, id_vars=["date"], value_vars=[c for c,_ in long_cols], var_name="serie", value_name="valeur")
    label_map = {src:lab for src,lab in long_cols}; melted["serie"] = melted["serie"].map(label_map)

    base = alt.Chart(melted).encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("valeur:Q", title="RSI", scale=alt.Scale(domain=[0,100])),
        color=alt.Color("serie:N", title="Horizon"),
        tooltip=[alt.Tooltip("date:T"), alt.Tooltip("serie:N"), alt.Tooltip("valeur:Q", format=".2f")]
    )
    lines = base.mark_line()
    h30 = alt.Chart(pd.DataFrame({"y":[30]})).mark_rule(strokeDash=[4,4]).encode(y="y:Q")
    h70 = alt.Chart(pd.DataFrame({"y":[70]})).mark_rule(strokeDash=[4,4]).encode(y="y:Q")

    last_points = melted.sort_values("date").groupby("serie").tail(1)
    labels = alt.Chart(last_points).mark_text(align="left", dx=6).encode(
        x="date:T", y="valeur:Q", text=alt.Text("label:N")
    ).transform_calculate(label="datum.serie + ': ' + format(datum.valeur, '.2f')")

    return (lines + h30 + h70 + labels).properties(title=title, width="container", height=350).configure_view(stroke=None).configure(background=None)

def chart_variation(df: pd.DataFrame, msgs: List[str]) -> alt.Chart:
    df2 = df.dropna(subset=["date", "variation_pct"]).sort_values("date").copy()
    dmin, dmax = date_range_label(df2, "date")
    title = f"Variation journalière (rendements) — {dmin} à {dmax}"

    line = alt.Chart(df2).mark_line().encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("variation_pct:Q", title="Rendement quotidien (décimal)"),
        tooltip=[alt.Tooltip("date:T"), alt.Tooltip("variation_pct:Q", format=".4f")]
    )
    zero_rule = alt.Chart(pd.DataFrame({"y":[0.0]})).mark_rule().encode(y="y:Q")

    return (line + zero_rule).properties(title=title, width="container", height=350).configure_view(stroke=None).configure(background=None)

def chart_mm(df: pd.DataFrame) -> alt.Chart:
    df2 = df.dropna(subset=["date"]).sort_values("date").copy()
    melted = pd.melt(df2, id_vars=["date"], value_vars=["close","mm50","mm200"], var_name="serie", value_name="valeur")
    label_map = {"close":"Cours (Close)", "mm50":"MM50", "mm200":"MM200"}; melted["serie"] = melted["serie"].map(label_map)

    line = alt.Chart(melted).mark_line().encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("valeur:Q", title="Prix"),
        color=alt.Color("serie:N", title="Série"),
        tooltip=[alt.Tooltip("date:T"), alt.Tooltip("serie:N"), alt.Tooltip("valeur:Q", format=".2f")]
    )

    return line.properties(title="Cours vs MM50 vs MM200", width="container", height=350).configure_view(stroke=None).configure(background=None)

# ========= App (sans sidebar) =========
st.set_page_config(page_title="Google Sheets → Graphiques (Altair, Dark)", layout="wide")

# Nettoyage UI (menu/footer)
st.markdown("""
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
/* Optionnel : réduire la marge du header */
header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

st.title("Tableaux de bord — Google Sheets (lecture directe)")
st.caption("Rendu figé — source et onglets prédéfinis. Fond sombre via configuration.")

# Chargement des 3 feuilles (toutes les lignes)
err_any = False
try:
    df_var_raw = fetch_csv_as_df(csv_export_url(SHEET_ID, GID_VARIATION))
    df_var, msgs_var = load_variation(df_var_raw)
except Exception as e:
    err_any = True; df_var = None
    st.error(f"[02_Rendements] Erreur de lecture/normalisation : {e}")

try:
    df_mm_raw = fetch_csv_as_df(csv_export_url(SHEET_ID, GID_MM))
    df_mm, _ = load_mm(df_mm_raw)
except Exception as e:
    err_any = True; df_mm = None
    st.error(f"[03_Prix_MM50] Erreur de lecture/normalisation : {e}")

try:
    df_rsi_raw = fetch_csv_as_df(csv_export_url(SHEET_ID, GID_RSI))
    df_rsi, _ = load_rsi(df_rsi_raw)
except Exception as e:
    err_any = True; df_rsi = None
    st.error(f"[01_RSI] Erreur de lecture/normalisation : {e}")

# Graphiques (3 sections)
st.markdown("---")
st.subheader("01_RSI")
if df_rsi is not None and not df_rsi.empty:
    st.altair_chart(chart_rsi(df_rsi), use_container_width=True)
    st.caption(insight_rsi_line(df_rsi))
else:
    st.info("RSI indisponible.")

st.markdown("---")
st.subheader("02_Rendements")
if df_var is not None and not df_var.empty:
    st.altair_chart(chart_variation(df_var, msgs_var), use_container_width=True)
    has_outliers = any("Outliers" in m for m in msgs_var)
    st.caption(insight_variation_line(df_var, has_outliers))
    for m in msgs_var:
        if "Outliers" in m: st.info(m)
else:
    st.info("Rendements indisponibles.")

st.markdown("---")
st.subheader("03_Prix_MM50")
if df_mm is not None and not df_mm.empty:
    st.altair_chart(chart_mm(df_mm), use_container_width=True)
    st.caption(insight_mm_line(df_mm))
else:
    st.info("Moyennes mobiles indisponibles.")
