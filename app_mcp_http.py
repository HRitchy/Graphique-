# app_mcp_locked_diag.py
# Streamlit: MCP (HTTP/SSE) -> google_sheets.read -> 3 graphiques (avec diagnostic endpoints/payload)
# Usage: streamlit run app_mcp_locked_diag.py

import json
import requests
import pandas as pd
import streamlit as st
from typing import Any, Dict, List, Tuple

TOOL_NAME = "google_sheets.read"

TOOLS_PATH_CANDIDATES = [
    "/tools", "/mcp/tools", "/tooling/tools"
]

CALL_PATH_CANDIDATES = [
    "/call", "/tool", "/invoke", "/run", "/tools/call", "/tool/call", "/respond"
]

PAYLOAD_SHAPES = [
    lambda tool, args: {"name": tool, "arguments": args},
    lambda tool, args: {"tool": tool, "arguments": args},
    lambda tool, args: {"toolName": tool, "arguments": args},
    lambda tool, args: {"name": tool, "args": args},
    lambda tool, args: {"tool": tool, "args": args},
    lambda tool, args: {"toolName": tool, "args": args},
]

ARG_VARIANTS = lambda spreadsheet_id, sheet_name: [
    {"spreadsheet_id": spreadsheet_id, "sheet": sheet_name},
    {"spreadsheetId": spreadsheet_id, "sheet": sheet_name},
    {"spreadsheet_id": spreadsheet_id, "range": sheet_name},
    {"spreadsheetId": spreadsheet_id, "range": sheet_name},
    {"id": spreadsheet_id, "sheet": sheet_name},
    {"id": spreadsheet_id, "range": sheet_name},
    {"spreadsheet_id": spreadsheet_id, "sheet_name": sheet_name},
    {"spreadsheetId": spreadsheet_id, "sheetName": sheet_name},
]

def sse_to_base(sse_url: str) -> str:
    if not sse_url:
        raise ValueError("URL SSE manquante.")
    return sse_url[:-4] if sse_url.endswith("/sse") else sse_url.rstrip("/")

def join_url(base: str, path: str) -> str:
    return base.rstrip("/") + path

def probe_tools(base: str, headers: Dict[str, str]) -> Tuple[str, List[str], Dict[str,int]]:
    """Essaie plusieurs chemins /tools et renvoie (chemin retenu ou '', liste outils, dict codes HTTP)."""
    http_codes = {}
    for p in TOOLS_PATH_CANDIDATES:
        url = join_url(base, p)
        try:
            r = requests.get(url, headers=headers, timeout=15)
            http_codes[p] = r.status_code
            if r.ok:
                j = r.json()
                tools = []
                if isinstance(j, dict) and "tools" in j and isinstance(j["tools"], list):
                    for t in j["tools"]:
                        if isinstance(t, dict) and "name" in t:
                            tools.append(str(t["name"]))
                return p, tools, http_codes
        except requests.RequestException as e:
            http_codes[p] = -1
    return "", [], http_codes

def try_call(base: str, headers: Dict[str,str], args: Dict[str,Any]) -> Tuple[str, Dict[str,Any], Any]:
    """Teste toutes les combinaisons (CALL_PATH_CANDIDATES × PAYLOAD_SHAPES) jusqu'à succès; renvoie (chemin, payload, réponse_json)."""
    last_err = None
    for path in CALL_PATH_CANDIDATES:
        url = join_url(base, path)
        for make_payload in PAYLOAD_SHAPES:
            payload = make_payload(TOOL_NAME, args)
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=45)
                if r.status_code == 404:
                    # Endpoint inexistant -> passe au chemin suivant
                    last_err = requests.HTTPError(f"404 for {url}")
                    continue
                r.raise_for_status()
                return path, payload, r.json()
            except Exception as e:
                last_err = e
                continue
    raise RuntimeError(f"Echec d'appel MCP. Dernière erreur: {last_err}")

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

def fetch_sheet(base: str, headers: Dict[str,str], ssid: str, sheet: str) -> Tuple[pd.DataFrame, str, Dict[str,Any]]:
    last_err = None
    for av in ARG_VARIANTS(ssid, sheet):
        try:
            path_used, payload_used, resp = try_call(base, headers, av)
            df = rows_to_df(resp)
            return df, path_used, payload_used
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"google_sheets.read a échoué avec toutes les variantes d'arguments. Dernière erreur: {last_err}")

def plot_rsi(df: pd.DataFrame):
    st.subheader("RSI – court / moyen / long")
    needed = ["date", "close"]
    miss = [c for c in needed if c not in df.columns]
    if miss:
        st.error(f"Colonnes manquantes pour RSI: {', '.join(miss)}")
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
    if not {"date","variation_pct"}.issubset(df.columns):
        st.error("Colonnes requises: date, variation_pct")
        return
    st.line_chart(df[["date","variation_pct"]].sort_values("date").set_index("date"))

def plot_mm(df: pd.DataFrame):
    st.subheader("Moyennes mobiles (MM50 / MM200) & Cours")
    needed = ["date","close","mm50","mm200"]
    miss = [c for c in needed if c not in df.columns]
    if miss:
        st.error(f"Colonnes manquantes pour MM: {', '.join(miss)}")
        return
    st.line_chart(df[needed].sort_values("date").set_index("date"))

# ====================== UI ======================
st.set_page_config(page_title="MCP → google_sheets.read (diag) → Graphiques", layout="wide")
st.title("MCP → google_sheets.read (diagnostic) → Graphiques")

with st.sidebar:
    st.header("Serveur MCP")
    sse_url = st.text_input("URL SSE MCP", value="", placeholder="https://.../mcp-test/.../sse")
    bearer = st.text_input("Bearer token (optionnel)", type="password")
    st.caption("La base HTTP est déduite en retirant le suffixe /sse.")
    st.markdown("---")
    test_btn = st.button("Tester les endpoints /tools")

st.markdown("### Paramètres des 3 feuilles Google Sheets")
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

if test_btn:
    try:
        base = sse_to_base(sse_url)
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        path_tools, tools, codes = probe_tools(base, headers)
        st.info(f"Résultats /tools: {codes}")
        if path_tools:
            st.success(f"Chemin /tools retenu: {path_tools} — Outils détectés: {tools or 'aucun'}")
        else:
            st.warning("Aucun endpoint /tools n'a répondu OK. Ce serveur peut ne pas exposer /tools en HTTP.")
    except Exception as e:
        st.exception(e)

if st.button("Charger & tracer"):
    try:
        base = sse_to_base(sse_url)
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"

        df1, path_used1, payload_used1 = fetch_sheet(base, headers, ssid1, sh1)
        df2, path_used2, payload_used2 = fetch_sheet(base, headers, ssid2, sh2)
        df3, path_used3, payload_used3 = fetch_sheet(base, headers, ssid3, sh3)

        df1, df2, df3 = normalize(df1), normalize(df2), normalize(df3)

        st.success("Données chargées.")
        with st.expander("Diagnostic: appels retenus"):
            st.write({"Feuille 1": {"path": path_used1, "payload": payload_used1},
                      "Feuille 2": {"path": path_used2, "payload": payload_used2},
                      "Feuille 3": {"path": path_used3, "payload": payload_used3}})

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
