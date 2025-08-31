# app_gsheet_direct_v2.py
# Streamlit : lit directement un Google Sheets (export CSV) et produit 3 graphiques conformes au cahier des charges
# Usage : streamlit run app_gsheet_direct_v2.py

import re
import io
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import requests
import pandas as pd
import numpy as np
import streamlit as st
import matplotlib.pyplot as plt
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter

# =========================
# Paramètres par défaut (votre fichier + onglets)
# =========================
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1C3ATTbCfnqT-Hx1gqHCA1wLv0Wl9RDrtVn1CgV2P6EY/edit?gid=0#gid=0"
GID_VARIATION = 0              # "VARIATION JOURNALIÈRE"
GID_MM        = 45071720       # "MOYENNE MOBILE"
GID_RSI       = 372876708      # "RSI"

# =========================
# Utilitaires
# =========================
def extract_spreadsheet_id(url_or_id: str) -> str:
    """Accepte un ID brut ou une URL Google Sheets ; renvoie l'ID (entre /d/<ID>/)."""
    m = re.search(r"/d/([a-zA-Z0-9-_]+)/", url_or_id)
    if m:
        return m.group(1)
    return url_or_id.strip()

def csv_export_url(sheet_id: str, gid: int) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

def fetch_csv_as_df(url: str, timeout: int = 30) -> pd.DataFrame:
    """Télécharge l'export CSV complet (toutes les lignes)."""
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    content = resp.content.decode("utf-8", errors="replace")
    return pd.read_csv(io.StringIO(content))

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))

def normalize_name(s: str) -> str:
    """Normalise les libellés : minuscules, sans accents, non-alphanum -> '_'."""
    x = strip_accents(str(s)).lower().strip()
    x = re.sub(r"[^\w]+", "_", x)
    x = re.sub(r"_+", "_", x).strip("_")
    return x

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [normalize_name(c) for c in d.columns]
    return d

def to_datetime_safe(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")

def to_numeric_safe(s: pd.Series) -> pd.Series:
    # Gère "12 345", "12,34", "12.34", "5%" → 5 (on ne convertit pas en fraction ici)
    if s.dtype == object:
        s2 = s.astype(str).str.replace(r"\s", "", regex=True)
        s2 = s2.str.replace(",", ".", regex=False)
        s2 = s2.str.replace("%", "", regex=False)
        return pd.to_numeric(s2, errors="ignore")
    return pd.to_numeric(s, errors="ignore")

def normalize_types(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if "date" in d.columns:
        d["date"] = to_datetime_safe(d["date"])
    for c in d.columns:
        if c != "date":
            d[c] = to_numeric_safe(d[c])
    return d

def find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """Trouve la première colonne présente parmi 'candidates' après normalisation."""
    cols = set(df.columns)
    for c in candidates:
        n = normalize_name(c)
        if n in cols:
            return n
    # matching par similarité simple (contient):
    for ncol in df.columns:
        for c in candidates:
            if normalize_name(c) in ncol:
                return ncol
    return None

def date_range_label(df: pd.DataFrame, date_col: str = "date") -> Tuple[str, str]:
    d2 = df[df[date_col].notna()]
    if d2.empty:
        return "?", "?"
    mn = d2[date_col].min()
    mx = d2[date_col].max()
    return (mn.strftime("%Y-%m-%d"), mx.strftime("%Y-%m-%d"))

def last_non_nan(s: pd.Series) -> Optional[float]:
    try:
        return s.dropna().iloc[-1]
    except Exception:
        return None

# =========================
# Chargement & validation par feuille (robuste)
# =========================
def load_variation(df_raw: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """Retourne df normalisé pour Variation + messages (outliers, colonnes manquantes)."""
    msgs = []
    d = normalize_types(normalize_columns(df_raw))
    # Colonnes attendues (détection souple)
    c_date = "date" if "date" in d.columns else find_column(d, ["date", "jour", "datetime"])
    c_var  = find_column(d, ["variation_pct", "variation", "variation_journaliere", "rendement", "return"])
    missing = [x for x in ["date", "variation_pct"] if (x=="date" and not c_date) or (x=="variation_pct" and not c_var)]
    if missing:
        msgs.append(f"Colonnes manquantes/équivalents non trouvés: {', '.join(missing)}.")
        raise ValueError("; ".join(msgs))
    out = d[[c_date, c_var]].rename(columns={c_date: "date", c_var: "variation_pct"})
    # Outliers > ±50 % (décimal 0.5)
    if (out["variation_pct"].abs() > 0.5).any():
        msgs.append("Outliers détectés (> ±50% jour/jour) — non filtrés (conformément aux spécifications).")
    return out, msgs

def load_mm(df_raw: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    msgs = []
    d = normalize_types(normalize_columns(df_raw))
    c_date = "date" if "date" in d.columns else find_column(d, ["date", "jour", "datetime"])
    c_close = find_column(d, ["close", "cours", "price", "close_price"])
    c_mm50  = find_column(d, ["mm50", "ma50", "sma50"])
    c_mm200 = find_column(d, ["mm200", "ma200", "sma200"])
    required = {"date": c_date, "close": c_close, "mm50": c_mm50, "mm200": c_mm200}
    miss = [k for k, v in required.items() if v is None]
    if miss:
        msgs.append(f"Colonnes manquantes/équivalents non trouvés: {', '.join(miss)}.")
        raise ValueError("; ".join(msgs))
    out = d[[c_date, c_close, c_mm50, c_mm200]].rename(columns={
        c_date: "date", c_close: "close", c_mm50: "mm50", c_mm200: "mm200"
    })
    return out, msgs

def load_rsi(df_raw: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    msgs = []
    d = normalize_types(normalize_columns(df_raw))
    c_date  = "date" if "date" in d.columns else find_column(d, ["date", "jour", "datetime"])
    c_close = find_column(d, ["close", "cours", "price", "close_price"])
    c_court = find_column(d, ["court", "rsi_court", "rsi_short", "rsi7", "rsi_7"])
    c_moyen = find_column(d, ["moyen", "rsi_moyen", "rsi14", "rsi_14"])
    c_long  = find_column(d, ["long_terme", "long", "rsi_long", "rsi28", "rsi_28", "rsi_long_terme", "longterme"])
    if not c_date or not c_close:
        raise ValueError("Colonnes minimales introuvables pour RSI (date + close).")
    out = d[[c_date, c_close]].rename(columns={c_date: "date", c_close: "close"})
    if c_court: out["court"] = d[c_court]
    if c_moyen: out["moyen"] = d[c_moyen]
    if c_long:  out["long_terme"] = d[c_long]
    return out, msgs

# =========================
# Tracés (matplotlib, un graphique par figure)
# =========================
def format_date_axis(ax):
    locator = AutoDateLocator()
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(ConciseDateFormatter(locator))
    plt.setp(ax.get_xticklabels(), rotation=0, ha="center")

def insight_rsi(df: pd.DataFrame) -> str:
    def zone(v: Optional[float]) -> str:
        if v is None or np.isnan(v):
            return "n.d."
        if v >= 70: return "surachat"
        if v <= 30: return "survente"
        return "neutre"
    last_date = df["date"].dropna().max()
    rc = last_non_nan(df.get("court", pd.Series(dtype=float)))
    rm = last_non_nan(df.get("moyen", pd.Series(dtype=float)))
    rl = last_non_nan(df.get("long_terme", pd.Series(dtype=float)))
    return f"Dernier point {last_date.date() if pd.notna(last_date) else 'n.d.'} — Court {rc:.2f if rc is not None else float('nan')}: {zone(rc)}, Moyen {rm:.2f if rm is not None else float('nan')}: {zone(rm)}, Long {rl:.2f if rl is not None else float('nan')}: {zone(rl)}."

def insight_variation(df: pd.DataFrame, outlier_flag: bool) -> str:
    pos_pct = 100.0 * (df["variation_pct"] > 0).mean()
    base = f"Série centrée autour de 0 — {pos_pct:.0f}% de jours positifs."
    if outlier_flag:
        base += " Outliers ±50% détectés."
    return base

def insight_mm(df: pd.DataFrame) -> str:
    last_date = df["date"].dropna().max()
    last = df[df["date"] == last_date].iloc[-1] if pd.notna(last_date) else df.iloc[-1]
    config = "haussière" if last["mm50"] > last["mm200"] else "baissière"
    rel_close = "au-dessus" if (last["close"] > max(last["mm50"], last["mm200"])) else ("au-dessous" if (last["close"] < min(last["mm50"], last["mm200"])) else "entre")
    return f"Dernier point {last_date.date() if pd.notna(last_date) else 'n.d.'} — config MM {config}, cours {rel_close} des MM."

def plot_rsi(df: pd.DataFrame):
    df2 = df.dropna(subset=["date"]).sort_values("date")
    if df2.empty:
        st.error("Feuille RSI vide ou illisible.")
        return
    dmin, dmax = date_range_label(df2, "date")
    title = f"RSI (court, moyen, long) — {dmin} à {dmax}"

    fig, ax = plt.subplots(figsize=(10, 4.5))
    # Traces (si colonnes présentes)
    if "court" in df2.columns:
        ax.plot(df2["date"], df2["court"], label="Court")
    if "moyen" in df2.columns:
        ax.plot(df2["date"], df2["moyen"], label="Moyen")
    if "long_terme" in df2.columns:
        ax.plot(df2["date"], df2["long_terme"], label="Long Terme")

    ax.axhline(30, linestyle="--", linewidth=1)
    ax.axhline(70, linestyle="--", linewidth=1)
    ax.set_ylim(0, 100)
    ax.set_title(title)
    ax.set_ylabel("RSI")
    ax.legend(loc="best")
    format_date_axis(ax)

    # Annotations des dernières valeurs
    for col, lab in [("court", "Court"), ("moyen", "Moyen"), ("long_terme", "Long Terme")]:
        if col in df2.columns and df2[col].notna().any():
            x = df2["date"].iloc[-1]
            y = df2[col].dropna().iloc[-1]
            ax.annotate(f"{lab}: {y:.2f}", xy=(x, y), xytext=(8, 0),
                        textcoords="offset points", va="center")

    st.pyplot(fig, clear_figure=True)
    st.caption("01_RSI — " + insight_rsi(df2))

def plot_variation(df: pd.DataFrame, msgs: List[str]):
    df2 = df.dropna(subset=["date", "variation_pct"]).sort_values("date")
    if df2.empty:
        st.error("Feuille VARIATION JOURNALIÈRE vide ou illisible.")
        return
    dmin, dmax = date_range_label(df2, "date")
    title = f"Variation journalière (rendements) — {dmin} à {dmax}"

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(df2["date"], df2["variation_pct"], label="Rendements quotidiens")
    ax.axhline(0.0, linestyle="-", linewidth=1)
    ax.set_title(title)
    ax.set_ylabel("Rendement quotidien (décimal)")
    ax.legend(loc="best")
    format_date_axis(ax)

    st.pyplot(fig, clear_figure=True)
    outlier_flag = any("Outliers" in m for m in msgs)
    st.caption("02_Rendements — " + insight_variation(df2, outlier_flag))
    # Mention explicite (non bloquante) si outliers
    for m in msgs:
        if "Outliers" in m:
            st.info(m)

def plot_mm(df: pd.DataFrame):
    df2 = df.dropna(subset=["date"]).sort_values("date")
    if df2.empty:
        st.error("Feuille MOYENNE MOBILE vide ou illisible.")
        return

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(df2["date"], df2["close"], label="Cours (Close)")
    ax.plot(df2["date"], df2["mm50"], label="MM50")
    ax.plot(df2["date"], df2["mm200"], label="MM200")

    ax.set_title("Cours vs MM50 vs MM200")
    ax.set_ylabel("Prix")
    ax.legend(loc="best")
    format_date_axis(ax)

    st.pyplot(fig, clear_figure=True)
    st.caption("03_Prix_MM50 — " + insight_mm(df2))

# =========================
# App
# =========================
st.set_page_config(page_title="Google Sheets → Graphiques (direct CSV)", layout="wide")
st.title("Google Sheets → Graphiques (lecture directe CSV)")

with st.sidebar:
    st.header("Source")
    url_or_id = st.text_input("URL ou ID du Google Sheets", value=DEFAULT_SHEET_URL)
    st.caption("Assurez-vous que le document est lisible par lien (lecture publique).")
    st.markdown("---")
    st.header("GID des 3 onglets")
    gid_var = st.number_input("gid — Variation journalière", value=GID_VARIATION, step=1)
    gid_mm  = st.number_input("gid — Moyenne mobile", value=GID_MM, step=1)
    gid_rsi = st.number_input("gid — RSI", value=GID_RSI, step=1)

if st.button("Charger & produire les graphiques"):
    # On tente chaque feuille indépendamment ; en cas d'erreur, on continue.
    try:
        sheet_id = extract_spreadsheet_id(url_or_id)
    except Exception as e:
        st.error(f"Impossible d'extraire l'ID du Google Sheet : {e}")
        st.stop()

    # VARIATION
    try:
        url_var = csv_export_url(sheet_id, int(gid_var))
        df_var_raw = fetch_csv_as_df(url_var)
        df_var, msgs_var = load_variation(df_var_raw)
    except Exception as e:
        df_var = None
        st.error(f"[02_Rendements] Erreur de lecture/normalisation : {e}")

    # MM
    try:
        url_mm = csv_export_url(sheet_id, int(gid_mm))
        df_mm_raw = fetch_csv_as_df(url_mm)
        df_mm, msgs_mm = load_mm(df_mm_raw)
    except Exception as e:
        df_mm = None
        st.error(f"[03_Prix_MM50] Erreur de lecture/normalisation : {e}")

    # RSI
    try:
        url_rsi = csv_export_url(sheet_id, int(gid_rsi))
        df_rsi_raw = fetch_csv_as_df(url_rsi)
        df_rsi, msgs_rsi = load_rsi(df_rsi_raw)
    except Exception as e:
        df_rsi = None
        st.error(f"[01_RSI] Erreur de lecture/normalisation : {e}")

    st.markdown("---")
    st.markdown("## Graphiques")

    if df_rsi is not None:
        plot_rsi(df_rsi)
    if df_var is not None:
        plot_variation(df_var, msgs_var if df_var is not None else [])
    if df_mm is not None:
        plot_mm(df_mm)

    st.markdown("---")
    st.caption("Rendu : 3 graphiques distincts, légendes FR, police par défaut, dates lisibles. Pas de styles/palette exotiques.")
