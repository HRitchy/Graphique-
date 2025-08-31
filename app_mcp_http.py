# app_gsheet_direct.py
# Streamlit : lit directement un Google Sheets (export CSV) et trace 3 graphiques
# Usage : streamlit run app_gsheet_direct.py

import re
import io
import sys
import csv
import unicodedata
from typing import Any, Dict, List

import requests
import pandas as pd
import streamlit as st

# =========================
# Config par défaut (adaptée à votre fichier)
# =========================
DEFAULT_SPREADSHEET_URL = (
    "https://docs.google.com/spreadsheets/d/1C3ATTbCfnqT-Hx1gqHCA1wLv0Wl9RDrtVn1CgV2P6EY/edit?gid=0#gid=0"
)
GID_VARIATION = 0
GID_MM = 45071720
GID_RSI = 372876708

# =========================
# Utilitaires
# =========================
def extract_spreadsheet_id(url_or_id: str) -> str:
    """
    Accepte soit un ID brut, soit une URL Google Sheets.
    Renvoie l'ID (entre /d/<ID>/).
    """
    m = re.search(r"/d/([a-zA-Z0-9-_]+)/", url_or_id)
    if m:
        return m.group(1)
    return url_or_id.strip()

def csv_export_url(sheet_id: str, gid: int) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

def fetch_csv_as_df(url: str, timeout: int = 30) -> pd.DataFrame:
    """
    Télécharge l'export CSV ; gère séparateur virgule.
    """
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    content = resp.content.decode("utf-8", errors="replace")
    # Pandas lit directement le CSV ; si besoin, on peut ajuster l'encodage/dialecte
    df = pd.read_csv(io.StringIO(content))
    return df

def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c)
    )

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Noms de colonnes en minuscule, accents retirés, espaces/%, etc. -> underscores.
    """
    d = df.copy()
    new_cols = []
    for c in d.columns:
        base = strip_accents(str(c)).lower().strip()
        base = re.sub(r"[^\w]+", "_", base)  # non-alphanum -> _
        base = re.sub(r"_+", "_", base).strip("_")
        new_cols.append(base)
    d.columns = new_cols
    return d

def to_datetime_safe(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")

def to_numeric_safe(s: pd.Series) -> pd.Series:
    # Remplace éventuels séparateurs de milliers/virgules décimales
    if s.dtype == object:
        s2 = s.astype(str).str.replace(r"\s", "", regex=True)
        # Convertit "12,34" -> "12.34" si présence de virgule mais pas de point
        s2 = s2.str.replace(",", ".", regex=False)
        # Retire un éventuel "%", mais ne convertit PAS en points si déjà décimal
        s2 = s2.str.replace("%", "", regex=False)
        return pd.to_numeric(s2, errors="ignore")
    return pd.to_numeric(s, errors="ignore")

def normalize_types(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    # Date
    for cand in ("date",):
        if cand in d.columns:
            d[cand] = to_datetime_safe(d[cand])
    # Numériques pour le reste
    for c in d.columns:
        if c != "date":
            d[c] = to_numeric_safe(d[c])
    return d

def pick_column(df: pd.DataFrame, candidates: List[str]) -> str | None:
    """
    Retourne la première colonne présente parmi 'candidates'.
    """
    for c in candidates:
        if c in df.columns:
            return c
    return None

# =========================
# Tracés
# =========================
def plot_variation(df: pd.DataFrame):
    st.subheader("Variation journalière (selon vos données)")
    # Colonnes possibles (souplesse sur les variantes d'intitulés)
    col_date = "date" if "date" in df.columns else pick_column(df, ["jour", "datetime"])
    col_var = pick_column(df, ["variation_pct", "variation", "variation_journaliere", "var_pct", "var"])
    if not col_date or not col_var:
        st.error("Colonnes requises introuvables pour Variation (attendu: date + variation_pct/variation).")
        st.dataframe(df.head(10))
        return
    d2 = df[[col_date, col_var]].dropna().sort_values(col_date)
    d2 = d2.set_index(col_date)
    st.line_chart(d2)

def plot_mm(df: pd.DataFrame):
    st.subheader("Moyennes mobiles (MM50 / MM200) & Cours")
    col_date = "date" if "date" in df.columns else pick_column(df, ["jour", "datetime"])
    col_close = pick_column(df, ["close", "cours", "price", "close_price"])
    col_mm50  = pick_column(df, ["mm50", "ma50", "sma50"])
    col_mm200 = pick_column(df, ["mm200", "ma200", "sma200"])
    missing = [n for n in [col_date, col_close, col_mm50, col_mm200] if n is None]
    if missing:
        st.error("Colonnes requises introuvables pour MM (attendu: date, close, mm50, mm200).")
        st.dataframe(df.head(10))
        return
    d2 = df[[col_date, col_close, col_mm50, col_mm200]].dropna().sort_values(col_date)
    d2 = d2.set_index(col_date)
    st.line_chart(d2)

def plot_rsi(df: pd.DataFrame):
    st.subheader("RSI – court / moyen / long (si dispo)")
    col_date = "date" if "date" in df.columns else pick_column(df, ["jour", "datetime"])
    col_close = pick_column(df, ["close", "cours", "price", "close_price"])
    # Variantes RSI
    c_short = pick_column(df, ["court", "rsi_court", "rsi_short", "rsi_7", "rsi7"])
    c_mid   = pick_column(df, ["moyen", "rsi_moyen", "rsi_14", "rsi14"])
    c_long  = pick_column(df, ["long_terme", "long", "rsi_long", "rsi_28", "rsi28"])
    if not col_date or not col_close:
        st.error("Colonnes minimales introuvables pour RSI (attendu: date + close).")
        st.dataframe(df.head(10))
        return

    base = df[[col_date, col_close]].dropna().sort_values(col_date).set_index(col_date)
    st.line_chart(base)

    rsi_cols = [c for c in [c_short, c_mid, c_long] if c]
    if rsi_cols:
        rsi_df = df[[col_date] + rsi_cols].dropna().sort_values(col_date).set_index(col_date)
        st.line_chart(rsi_df)
    else:
        st.info("Colonnes RSI spécifiques (court/moyen/long) non détectées — graphique du cours affiché.")

# =========================
# App
# =========================
st.set_page_config(page_title="Google Sheets → Graphiques (direct CSV)", layout="wide")
st.title("Google Sheets → Graphiques (lecture directe CSV)")

with st.sidebar:
    st.header("Paramètres")
    url_or_id = st.text_input("URL ou ID du Google Sheets", value=DEFAULT_SPREADSHEET_URL)
    gid_var = st.number_input("gid Variation", value=GID_VARIATION, step=1)
    gid_mm  = st.number_input("gid MM", value=GID_MM, step=1)
    gid_rsi = st.number_input("gid RSI", value=GID_RSI, step=1)
    st.caption("Astuce : l'ID est la partie entre /d/<ID>/ dans l'URL. Le gid est l'identifiant d'onglet (visible dans l'URL).")

if st.button("Charger & tracer"):
    try:
        sheet_id = extract_spreadsheet_id(url_or_id)

        # Téléchargements CSV (3 onglets)
        url_var = csv_export_url(sheet_id, int(gid_var))
        url_mm_ = csv_export_url(sheet_id, int(gid_mm))
        url_rsi_ = csv_export_url(sheet_id, int(gid_rsi))

        df_var = fetch_csv_as_df(url_var)
        df_mm  = fetch_csv_as_df(url_mm_)
        df_rsi = fetch_csv_as_df(url_rsi_)

        # Normalisation colonnes + types
        df_var = normalize_types(normalize_columns(df_var))
        df_mm  = normalize_types(normalize_columns(df_mm))
        df_rsi = normalize_types(normalize_columns(df_rsi))

        st.success("Données chargées depuis Google Sheets (export CSV).")

        with st.expander("Aperçu des données"):
            st.write("Variation (head)"); st.dataframe(df_var.head(20))
            st.write("MM (head)");        st.dataframe(df_mm.head(20))
            st.write("RSI (head)");       st.dataframe(df_rsi.head(20))

        st.markdown("## Graphiques")
        plot_variation(df_var)
        plot_mm(df_mm)
        plot_rsi(df_rsi)

    except Exception as e:
        st.exception(e)
