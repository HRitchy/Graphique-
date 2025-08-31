# app_mcp_locked.py
# Streamlit: MCP (HTTP/SSE) -> google_sheets.read -> 3 graphiques
# Usage: streamlit run app_mcp_locked.py

import json
import requests
import pandas as pd
import streamlit as st
from typing import Any, Dict, List

TOOL_NAME = "google_sheets.read"

def sse_to_http_base(sse_url: str) -> str:
    if not sse_url:
        raise ValueError("URL SSE manquante.")
    return sse_url[:-4] if sse_url.endswith("/sse") else sse_url.rstrip("/")

def call_tool(base_url: str, headers: Dict[str, str], args: Dict[str, Any]) -> Any:
    url = base_url.rstrip("/") + "/call"
    payload = {"name": TOOL_NAME, "arguments": args}
    r = requests.post(url, json=payload, headers=headers, timeout=45)
    r.raise_for_status()
    return r.json()

def rows_to_df(payload: Any) -> pd.DataFrame:
    rows = None
    if isinstance(payload, dict):
        data = payload.get("result", payload)
        if isinstance(data, dict):
            rows = data.get("rows") or data.get("data") or data.get("values")
        elif isinstance(data, list):
            rows = data
    elif isinstance(payload, list):
        rows = payload
    if rows is None:
        raise RuntimeError(f"Réponse inattendue: {payload}")
    if not rows:
        return pd.DataFrame()
    header = rows[0] if isinstance(rows[0], list) and all(isinstance(h, str) for h in rows[0]) else None
    body = rows[1:] if header else rows
    return pd.DataFrame(body, columns=header if header else None)

def normalize(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [str(c).strip().lower() for c in d.columns]
    if "date" in d.columns:
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
    for c in d.columns:
        if c != "date":
            d[c] = pd.to_numeric(d[c], errors="ignore")
    return d

def try_fetch_sheet(base: str, headers: Dict[str, str], spreadsheet_id: str, sheet_name: str) -> pd.DataFrame:
    """
    Essaie plusieurs signatures usuelles de google_sheets.read :
    - {spreadsheet_id, sheet}
    - {spreadsheetId, sheet}
    - {spreadsheet_id, range}
    - {spreadsheetId, range}
    - {id, sheet} / {id, range}
    - {spreadsheet_id, sheet_name}
    - {spreadsheetId, sheetName}
    """
    arg_variants: List[Dict[str, Any]] = [
        {"spreadsheet_id": spreadsheet_id, "sheet": sheet_name},
        {"spreadsheetId": spreadsheet_id, "sheet": sheet_name},
        {"spreadsheet_id": spreadsheet_id, "range": sheet_name},
        {"spreadsheetId": spreadsheet_id, "range": sheet_name},
        {"id": spreadsheet_id, "sheet": sheet_name},
        {"id": spreadsheet_id, "range": sheet_name},
        {"spreadsheet_id": spreadsheet_id, "sheet_name": sheet_name},
        {"spreadsheetId": spreadsheet_id, "sheetName": sheet_name},
    ]
    last_err = None
    for args in arg_variants:
        try:
            payload = call_tool(base, headers, args)
            return rows_to_df(payload)
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"google_sheets.read a échoué avec toutes les variantes. Dernière erreur: {last_err}")

def plot_rsi(df: pd.DataFrame):
    st.subheader("RSI – court / moyen / long")
    needed = ["date", "close"]
    for c in needed:
        if c not in df.columns:
            st.error(f"Colonne manquante pour RSI: {c}")
            return
    aliases_long = ["long terme", "long", "long_terme", "rsi long", "rsi_long"]
    rsi_cols = [c for c in ["court", "moyen"] + aliases_long if c in df.columns]
    st.line_chart(df[["date", "close"]].sort_values("date").set_index("date"))
    if rsi_cols:
        st.line_chart(df[["date"] + rsi_cols].sort_values("date").set_index("date"))
    else:
        st.info("Colonnes RSI non trouvées (court/moyen/long).")

def plot_variation(df: pd.DataFrame):
    st.subheader("Variation journalière (%)")
    if not {"date", "variation_pct"}.issubset(df.columns):
        st.error("Colonnes requises: date, variation_pct")
        return
    st.line_chart(df[["date", "variation_pct"]].sort_values("date").set_index("date"))

def plot_mm(df: pd.DataFrame):
    st.subheader("Moyennes mobiles (MM50 / MM200) & Cours")
    needed = ["date", "close", "mm50", "mm200"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        st.error(f"Colonnes manquantes pour MM: {', '.join(missing)}")
        return
    st.line_chart(df[needed].sort_values("date").set_index("date"))

# ================= UI =================
st.set_page_config(page_title="MCP → google_sheets.read → Graphiques", layout="wide")
st.title("MCP (HTTP/SSE) → google_sheets.read → Graphiques")

with st.sidebar:
    st.header("Serveur MCP")
    sse_url = st.text_input("URL SSE MCP", value="", placeholder="https://.../mcp-test/.../sse")
    bearer = st.text_input("Bearer token (optionnel)", type="password")
    st.caption("La base HTTP est déduite en retirant le suffixe /sse.")

st.markdown("### Paramètres des 3 feuilles")
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("**Feuille 1 – RSI**")
    ssid1 = st.text_input("Spreadsheet ID (RSI)")
    sh1 = st.text_input("Nom de la feuille (RSI)", value="RSI")
with c2:
    st.markdown("**Feuille 2 – Variation journalière**")
    ssid2 = st.text_input("Spreadsheet ID (Variation)")
    sh2 = st.text_input("Nom de la feuille (Variation)", value="VARIATION JOURNALIERE")
with c3:
    st.markdown("**Feuille 3 – Moyennes mobiles**")
    ssid3 = st.text_input("Spreadsheet ID (MM)")
    sh3 = st.text_input("Nom de la feuille (MM)", value="MOYENNE MOBILE")

if st.button("Charger & tracer"):
    try:
        base = sse_to_http_base(sse_url)
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"

        df1 = try_fetch_sheet(base, headers, ssid1, sh1)
        df2 = try_fetch_sheet(base, headers, ssid2, sh2)
        df3 = try_fetch_sheet(base, headers, ssid3, sh3)

        df1, df2, df3 = normalize(df1), normalize(df2), normalize(df3)

        st.success("Données chargées.")
        with st.expander("Aperçu RSI"):
            st.dataframe(df1.head(20))
        with st.expander("Aperçu Variation"):
            st.dataframe(df2.head(20))
        with st.expander("Aperçu MM"):
            st.dataframe(df3.head(20))

        st.markdown("## Graphiques")
        plot_rsi(df1)
        plot_variation(df2)
        plot_mm(df3)

    except Exception as e:
        st.exception(e)


