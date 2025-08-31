# app_mcp_http.py
# Streamlit app spécifique: MCP (SSE/HTTP) -> Google Sheets -> 3 graphiques
# Usage: streamlit run app_mcp_http.py

import json
import requests
import pandas as pd
import streamlit as st
from typing import List, Dict, Any, Optional

DEFAULT_TOOL_CANDIDATES = [
    "sheets.values.get",
    "google_sheets.read",
    "sheets.read_sheet",
    "sheets.get_values",
    "google_sheets_get_values",
]

def sse_to_http_base(sse_url: str) -> str:
    if not sse_url:
        raise ValueError("URL SSE manquante.")
    if not sse_url.endswith("/sse"):
        return sse_url.rstrip("/")
    return sse_url.rsplit("/", 1)[0]

def discover_tools(base_url: str, headers: Dict[str, str]) -> List[str]:
    tools = []
    try:
        resp = requests.get(base_url.rstrip("/") + "/tools", headers=headers, timeout=20)
        if resp.ok:
            j = resp.json()
            if isinstance(j, dict) and "tools" in j and isinstance(j["tools"], list):
                for t in j["tools"]:
                    if isinstance(t, dict) and "name" in t:
                        tools.append(str(t["name"]))
    except Exception:
        pass
    return tools

def choose_tool(available: List[str], candidates: List[str], forced: Optional[str]) -> str:
    if forced:
        return forced
    for cand in candidates:
        if cand in (available or []):
            return cand
    return candidates[0]

def call_tool(base_url: str, tool_name: str, args: Dict[str, Any], headers: Dict[str, str]) -> Any:
    url = base_url.rstrip("/") + "/call"
    payload = {"name": tool_name, "arguments": args}
    resp = requests.post(url, json=payload, headers=headers, timeout=40)
    resp.raise_for_status()
    return resp.json()

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
    header = rows[0] if all(isinstance(h, str) for h in rows[0]) else None
    body = rows[1:] if header else rows
    return pd.DataFrame(body, columns=header if header else None)

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [str(c).strip().lower() for c in d.columns]
    if "date" in d.columns:
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
    for c in d.columns:
        if c != "date":
            d[c] = pd.to_numeric(d[c], errors="ignore")
    return d

def plot_rsi(df: pd.DataFrame):
    st.subheader("RSI – court / moyen / long")
    needed = ["date", "close"]
    for col in needed:
        if col not in df.columns:
            st.error(f"Colonne manquante pour RSI: {col}")
            return
    aliases_long = ["long terme", "long", "long_terme", "rsi long", "rsi_long"]
    rsi_cols = []
    for name in ["court", "moyen"] + aliases_long:
        if name in df.columns and name not in rsi_cols:
            rsi_cols.append(name)

    base = df[["date", "close"]].sort_values("date")
    st.line_chart(base.set_index("date"))

    if rsi_cols:
        st.line_chart(df[["date"] + rsi_cols].set_index("date").sort_values("date"))
    else:
        st.info("Colonnes RSI non trouvées (court/moyen/long).")

def plot_variation(df: pd.DataFrame):
    st.subheader("Variation journalière (%)")
    if "date" not in df.columns or "variation_pct" not in df.columns:
        st.error("Colonnes requises: date, variation_pct")
        return
    d2 = df[["date", "variation_pct"]].sort_values("date")
    st.line_chart(d2.set_index("date"))

def plot_mm(df: pd.DataFrame):
    st.subheader("Moyennes mobiles (MM50 / MM200) & Cours")
    needed = ["date", "close", "mm50", "mm200"]
    for col in needed:
        if col not in df.columns:
            st.error(f"Colonne manquante pour MM: {col}")
            return
    d2 = df[needed].sort_values("date")
    st.line_chart(d2.set_index("date"))

# ================= UI Streamlit =================

st.set_page_config(page_title="MCP (HTTP) → Google Sheets → Graphiques", layout="wide")
st.title("MCP (HTTP) → Google Sheets → Graphiques")

with st.sidebar:
    st.header("Serveur MCP (SSE/HTTP)")
    sse_url = st.text_input("URL SSE MCP", placeholder="https://.../mcp-test/.../sse")
    bearer = st.text_input("Bearer token (optionnel)", type="password")
    st.caption("La base HTTP sera déduite de l'URL SSE (remplacement de /sse par la base).")
    st.markdown("---")
    forced_tool = st.text_input("Nom exact de l'outil (optionnel)", placeholder="ex: google_sheets.read")

st.markdown("### Paramètres des 3 feuilles Google Sheets")
col1, col2, col3 = st.columns(3)
with col1:
    st.markdown("**Feuille 1 – RSI**")
    ssid_1 = st.text_input("Spreadsheet ID (RSI)")
    sheet_1 = st.text_input("Nom de la feuille (RSI)", value="RSI")
with col2:
    st.markdown("**Feuille 2 – Variation journalière**")
    ssid_2 = st.text_input("Spreadsheet ID (Variation)")
    sheet_2 = st.text_input("Nom de la feuille (Variation)", value="VARIATION JOURNALIERE")
with col3:
    st.markdown("**Feuille 3 – Moyennes mobiles**")
    ssid_3 = st.text_input("Spreadsheet ID (MM)")
    sheet_3 = st.text_input("Nom de la feuille (MM)", value="MOYENNE MOBILE")

run = st.button("Charger & tracer")

if run:
    try:
        base = sse_to_http_base(sse_url)
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"

        available = discover_tools(base, headers)
        chosen_tool = choose_tool(available, DEFAULT_TOOL_CANDIDATES, forced_tool if forced_tool else None)
        st.caption(f"Outil sélectionné: **{chosen_tool}** (disponibles: {', '.join(available) if available else 'inconnus'})")

        def fetch(spreadsheet_id, sheet_name):
            args = {"spreadsheet_id": spreadsheet_id, "sheet": sheet_name}
            payload = call_tool(base, chosen_tool, args, headers)
            return rows_to_df(payload)

        df1 = fetch(ssid_1, sheet_1)
        df2 = fetch(ssid_2, sheet_2)
        df3 = fetch(ssid_3, sheet_3)

        df1n = normalize_columns(df1)
        df2n = normalize_columns(df2)
        df3n = normalize_columns(df3)

        st.success("Données chargées.")
        with st.expander("Aperçu RSI"):
            st.dataframe(df1n.head(20))
        with st.expander("Aperçu Variation"):
            st.dataframe(df2n.head(20))
        with st.expander("Aperçu MM"):
            st.dataframe(df3n.head(20))

        st.markdown("## Graphiques")
        plot_rsi(df1n)
        plot_variation(df2n)
        plot_mm(df3n)

    except Exception as e:
        st.exception(e)
