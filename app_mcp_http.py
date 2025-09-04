# app_gsheet_finance.py
# Streamlit : lecture directe Google Sheets (CSV) -> conseil financier

import io
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import streamlit as st

DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1C3ATTbCfnqT-Hx1gqHCA1wLv0Wl9RDrtVn1CgV2P6EY/edit?gid=0#gid=0"
GID_VARIATION = 0
GID_MM        = 45071720

GID_RSI       = 372876708

# ---------- Utils ----------
def extract_spreadsheet_id(url_or_id: str) -> str:
    m = re.search(r"/d/([a-zA-Z0-9-_]+)/", url_or_id)
    return m.group(1) if m else url_or_id.strip()

def csv_export_url(sheet_id: str, gid: int) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

def fetch_csv_as_df(url: str, timeout: int = 30) -> pd.DataFrame:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    content = r.content.decode("utf-8", errors="replace")
    return pd.read_csv(io.StringIO(content))

def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))

def normalize_name(s: str) -> str:
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
    """Conversion générique (coerce) hors cas spécial Variation_Pct."""
    if s.dtype == object:
        s2 = s.astype(str).str.replace(r"\s", "", regex=True)
        s2 = s2.str.replace(",", ".", regex=False)
        s2 = s2.str.replace("%", "", regex=False)
        return pd.to_numeric(s2, errors="coerce")
    return pd.to_numeric(s, errors="coerce")

def normalize_types(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if "date" in d.columns:
        d["date"] = to_datetime_safe(d["date"])
    for c in d.columns:
        if c != "date":
            d[c] = to_numeric_safe(d[c])
    return d

def find_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = set(df.columns)
    for c in candidates:
        n = normalize_name(c)
        if n in cols:
            return n
    for ncol in df.columns:
        for c in candidates:
            if normalize_name(c) in ncol:
                return ncol
    return None

def date_range_label(df: pd.DataFrame, date_col: str = "date") -> Tuple[str, str]:
    d2 = df[df[date_col].notna()]
    if d2.empty:
        return "?", "?"
    return (d2[date_col].min().strftime("%Y-%m-%d"),
            d2[date_col].max().strftime("%Y-%m-%d"))

def last_non_nan(s: pd.Series) -> Optional[float]:
    try:
        return s.dropna().iloc[-1]
    except Exception:
        return None

# ---------- Spécifique rendements ----------
def parse_returns_decimal(series: pd.Series) -> pd.Series:
    """
    Convertit robustement une série de rendements potentiellement saisis en :
    - décimal (0.0123), ou
    - pourcentage ('1.23%', '1,23%', '1.23', '1,23' voulant dire 1.23%)
    Règles:
      1) on divise par 100 uniquement si:
         - la valeur contenait explicitement '%', OU
         - l'échelle détectée est 'en pourcents' (quantile 95% > 1.0)
      2) sinon on laisse en décimal.
    """
    s_obj = series.astype(str)

    # Marqueurs de pourcent
    has_pct = s_obj.str.contains("%", na=False)

    # Nettoyage basique
    s_clean = s_obj.str.replace(r"\s", "", regex=True)
    s_clean = s_clean.str.replace(",", ".", regex=False)
    s_clean = s_clean.str.replace("%", "", regex=False)

    s_num = pd.to_numeric(s_clean, errors="coerce")

    # Cas explicite '%'
    s_num = s_num.where(~has_pct, s_num / 100.0)

    # Heuristique d'échelle: si la majorité des valeurs > 1, on considère que c'était des pourcents
    q95 = s_num.abs().quantile(0.95)
    if pd.notna(q95) and q95 > 1.0:
        s_num = s_num / 100.0

    return s_num

# ---------- Chargement/validation ----------
def load_variation(df_raw: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    msgs: List[str] = []
    d = normalize_columns(df_raw)
    # ne pas convertir tout de suite en numérique : on traite la colonne rendement avec parse_returns_decimal
    c_date = "date" if "date" in d.columns else find_column(d, ["date", "jour", "datetime"])
    c_var  = find_column(d, ["variation_pct", "variation", "variation_journaliere", "rendement", "return"])
    if not c_date or not c_var:
        raise ValueError("Colonnes requises introuvables pour Variation (date + variation_pct/variation).")

    out = d[[c_date, c_var]].rename(columns={c_date: "date", c_var: "variation_pct"})
    out["date"] = to_datetime_safe(out["date"])
    out["variation_pct"] = parse_returns_decimal(out["variation_pct"])

    if (out["variation_pct"].abs() > 0.5).any():
        msgs.append("Outliers détectés (> ±50% jour/jour) — non filtrés, conformément aux spécifications.")
    return out, msgs

def load_mm(df_raw: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    msgs: List[str] = []
    d = normalize_types(normalize_columns(df_raw))
    c_date = "date" if "date" in d.columns else find_column(d, ["date", "jour", "datetime"])
    c_close = find_column(d, ["close", "cours", "price", "close_price"])
    c_mm50  = find_column(d, ["mm50", "ma50", "sma50"])
    c_mm200 = find_column(d, ["mm200", "ma200", "sma200"])
    if not all([c_date, c_close, c_mm50, c_mm200]):
        raise ValueError("Colonnes requises introuvables pour MM (date, close, mm50, mm200).")
    out = d[[c_date, c_close, c_mm50, c_mm200]].rename(columns={
        c_date: "date", c_close: "close", c_mm50: "mm50", c_mm200: "mm200"
    })
    return out, msgs

def load_rsi(df_raw: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    msgs: List[str] = []
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

# ---------- Insights (1 ligne) ----------
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
    if has_outliers:
        base += " Outliers ±50% détectés."
    return base

def insight_mm_line(df: pd.DataFrame) -> str:
    last_date = df["date"].dropna().max()
    last = df[df["date"] == last_date].iloc[-1] if pd.notna(last_date) else df.iloc[-1]
    config = "haussière" if last["mm50"] > last["mm200"] else "baissière"
    rel_close = (
        "au-dessus" if (last["close"] > max(last["mm50"], last["mm200"]))
        else ("au-dessous" if (last["close"] < min(last["mm50"], last["mm200"])) else "entre")
    )
    dstr = last_date.date() if pd.notna(last_date) else "n.d."
    return f"Dernier point {dstr} — config MM {config}, cours {rel_close} des MM."

# ---------- Conseil financier ----------
def generate_financial_advice(
    df_rsi: Optional[pd.DataFrame],
    df_mm: Optional[pd.DataFrame],
    df_var: Optional[pd.DataFrame],
    msgs_var: List[str],
) -> str:
    lines: List[str] = []
    if df_rsi is not None and not df_rsi.empty:
        lines.append(insight_rsi_line(df_rsi))
    if df_var is not None and not df_var.empty:
        has_outliers = any("Outliers" in m for m in msgs_var)
        lines.append(insight_variation_line(df_var, has_outliers))
    if df_mm is not None and not df_mm.empty:
        lines.append(insight_mm_line(df_mm))

    recs: List[str] = []
    if df_rsi is not None and not df_rsi.empty:
        rsi_val = last_non_nan(df_rsi.get("moyen", pd.Series(dtype=float)))
        if rsi_val is not None:
            if rsi_val > 70:
                recs.append(
                    "RSI en zone de surachat — envisager une vente ou prise de bénéfices."
                )
            elif rsi_val < 30:
                recs.append(
                    "RSI en zone de survente — possibilité d'achat."
                )
            else:
                recs.append("RSI neutre — pas de signal clair.")

    if df_mm is not None and not df_mm.empty:
        last = df_mm.sort_values("date").iloc[-1]
        if last["mm50"] > last["mm200"] and last["close"] > last["mm50"]:
            recs.append(
                "Tendance haussière confirmée par les moyennes mobiles — biais acheteur."
            )
        elif last["mm50"] < last["mm200"] and last["close"] < last["mm50"]:
            recs.append(
                "Tendance baissière, cours sous les moyennes — prudence ou vente."
            )
        else:
            recs.append(
                "Situation mitigée autour des moyennes mobiles — attendre un signal plus clair."
            )

    if not recs:
        recs.append("Données insuffisantes pour établir une recommandation.")

    lines.append("")
    lines.append("Recommandation :")
    lines.extend(recs)
    return "\n".join(lines)

# ---------- App ----------
st.set_page_config(
    page_title="Google Sheets → Conseil financier",
    layout="wide",
)

st.markdown(
    """
    <style>
    .main .block-container{padding-top:1rem;padding-left:0.5rem;padding-right:0.5rem;}
    .vega-bindings input, .mark-text { font-size: 12px !important; }
    body { background-color:#fff; color:#000; }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("Google Sheets → Conseil financier (analyse technique)")

with st.expander("Configuration"):
    st.header("Source")
    url_or_id = st.text_input("URL ou ID du Google Sheets", value=DEFAULT_SHEET_URL)
    st.caption("Le document doit être accessible en lecture.")
    st.markdown("---")
    st.header("gid des onglets")
    gid_var = st.number_input("gid — VARIATION JOURNALIÈRE", value=GID_VARIATION, step=1)
    gid_mm  = st.number_input("gid — MOYENNE MOBILE", value=GID_MM, step=1)
    gid_rsi = st.number_input("gid — RSI", value=GID_RSI, step=1)

if st.button("Analyser les données"):
    try:
        sheet_id = extract_spreadsheet_id(url_or_id)
    except Exception as e:
        st.error(f"Extraction ID Google Sheets impossible : {e}")
        st.stop()

    # Variation
    df_var = None; msgs_var: List[str] = []
    try:
        url_var = csv_export_url(sheet_id, int(gid_var))
        df_var_raw = fetch_csv_as_df(url_var)
        df_var, msgs_var = load_variation(df_var_raw)
    except Exception as e:
        st.error(f"[02_Rendements] Erreur : {e}")

    # MM
    df_mm = None
    try:
        url_mm = csv_export_url(sheet_id, int(gid_mm))
        df_mm_raw = fetch_csv_as_df(url_mm)
        df_mm, _ = load_mm(df_mm_raw)
    except Exception as e:
        st.error(f"[03_Prix_MM50] Erreur : {e}")

    # RSI
    df_rsi = None
    try:
        url_rsi = csv_export_url(sheet_id, int(gid_rsi))
        df_rsi_raw = fetch_csv_as_df(url_rsi)
        df_rsi, _ = load_rsi(df_rsi_raw)
    except Exception as e:
        st.error(f"[01_RSI] Erreur : {e}")

    st.markdown("---")
    st.markdown("## Conseil financier")
    advice = generate_financial_advice(df_rsi, df_mm, df_var, msgs_var)
    st.write(advice)
