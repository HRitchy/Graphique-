# app_mcp_n8n_fixed.py
# Streamlit: n8n MCP (HTTP/SSE) -> 3 tools Google Sheets ("1","2","3") -> 3 graphiques
# Usage: streamlit run app_mcp_n8n_fixed.py

import json
import requests
import pandas as pd
import streamlit as st
from typing import Any, Dict, List, Tuple

# ---- Config par défaut adaptée à votre workflow n8n ----
DEFAULT_TOOL_1 = "1"  # Variation Journalière (gid=0) selon votre JSON
DEFAULT_TOOL_2 = "2"  # Moyenne Mobile (gid=45071720)
DEFAULT_TOOL_3 = "3"  # RSI (gid=372876708)

# Candidats de chemins d'appel rencontrés sur des serveurs MCP n8n
CALL_PATH_CANDIDATES = [
    "/call", "/tool", "/invoke", "/run", "/tools/call", "/tool/call", "/respond"
]

# Variantes de payload (name/tool/toolName × arguments/args)
PAYLOAD_SHAPES = [
    lambda tool, args: {"name": tool, "arguments": args},
    lambda tool, args: {"tool": tool, "arguments": args},
    lambda tool, args: {"toolName": tool, "arguments": args},
    lambda tool, args: {"name": tool, "args": args},
    lambda tool, args: {"tool": tool, "args": args},
    lambda tool, args: {"toolName": tool, "args": args},
]

# Dans votre cas, les tools n8n sont pré-paramétrés => pas d'arguments nécessaires.
EMPTY_ARGS: Dict[str, Any] = {}

def sse_to_base(sse_url: str) -> str:
    if not sse_url:
        raise ValueError("URL SSE manquante.")
    return sse_url[:-4] if sse_url.endswith("/sse") else sse_url.rstrip("/")

def join_url(base: str, path: str) -> str:
    return base.rstrip("/") + path

def list_tools(base: str, headers: Dict[str, str]) -> Tuple[str, List[str], Dict[str,int]]:
    """
    Tente GET {base}/tools et renvoie (path, tools, codes).
    n8n standard expose souvent /tools à la racine du même préfixe.
    """
    url = join_url(base, "/tools")
    codes = {}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        codes["/tools"] = r.status_code
        tools = []
        if r.ok:
            j = r.json()
            if isinstance(j, dict) and "tools" in j and isinstance(j["tools"], list):
                for t in j["tools"]:
                    if isinstance(t, dict) and "name" in t:
                        tools.append(str(t["name"]))
            return "/tools", tools, codes
    except requests.RequestException:
        codes["/tools"] = -1
    return "", [], codes

def try_call(base: str, headers: Dict[str,str], tool_name: str, args: Dict[str,Any]) -> Tuple[str, Dict[str,Any], Any]:
    """
    Essaie toutes les combinaisons (CALL_PATH_CANDIDATES × PAYLOAD_SHAPES) jusqu'au succès.
    Renvoie (chemin utilisé, payload utilisé, réponse JSON).
    """
    last_err = None
    for path in CALL_PATH_CANDIDATES:
        url = join_url(base, path)
        for make_payload in PAYLOAD_SHAPES:
            payload = make_payload(tool_name, args)
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=45)
                if r.status_code == 404:
                    last_err = requests.HTTPError(f"404 for {url}")
                    continue
                r.raise_for_status()
                return path, payload, r.json()
            except Exception as e:
                last_err = e
                continue
    raise RuntimeError(f"Echec d'appel MCP pour tool '{tool_name}'. Dernière erreur: {last_err}")

def rows_to_df(payload: Any) -> pd.DataFrame:
    """
    Adapte au format n8n: souvent { result: { rows|data|values: [[...],[...]] } } ou liste brute.
    """
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

def plot_rsi(df: pd.DataFrame):
    st.subheader("RSI – court / moyen / long")
    if not {"date","close"}.issubset(df.columns):
        st.error("Colonnes requises: date, close")
        return
    aliases_long = ["long terme","long","long_terme","rsi long","rsi_long"]
    rsi_cols = [c for c in ["court","moyen"] + aliases_long if c in df.columns]
    st.line_chart(df[["date","close"]].sort_values("date").set_index("date"))
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
st.set_page_config(page_title="n8n MCP → Google Sheets → Graphiques", layout="wide")
st.title("n8n MCP → Google Sheets → Graphiques (tools pré-paramétrés)")

with st.sidebar:
    st.header("Serveur MCP")
    sse_url = st.text_input(
        "URL SSE MCP",
        value="https://n8n.srv874064.hstgr.cloud/mcp-test/e9a73f19-4553-4823-9b1a-edea1540a25c/sse",
        placeholder="https://.../mcp-test/<UUID>/sse"
    )
    bearer = st.text_input("Bearer token (optionnel)", type="password")
    st.caption("La base HTTP est déduite en retirant /sse à la fin.")

    st.markdown("---")
    st.subheader("Noms des tools (n8n)")
    tool_1 = st.text_input("Tool pour Variation", value=DEFAULT_TOOL_1)
    tool_2 = st.text_input("Tool pour Moyennes Mobiles", value=DEFAULT_TOOL_2)
    tool_3 = st.text_input("Tool pour RSI", value=DEFAULT_TOOL_3)

    st.markdown("---")
    if st.button("Lister les outils"):
        try:
            base = sse_to_base(sse_url)
            headers = {"Content-Type": "application/json"}
            if bearer:
                headers["Authorization"] = f"Bearer {bearer}"
            path, tools, codes = list_tools(base, headers)
            st.info(f"Codes HTTP /tools: {codes}")
            st.success(f"Chemin: {path or 'indisponible'} — Outils détectés: {tools or 'aucun'}")
        except Exception as e:
            st.exception(e)

if st.button("Charger & tracer"):
    try:
        base = sse_to_base(sse_url)
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"

        # Appels: tools sans arguments (pré-paramétrés dans n8n)
        path1, payload1, resp1 = try_call(base, headers, tool_1, EMPTY_ARGS)
        path2, payload2, resp2 = try_call(base, headers, tool_2, EMPTY_ARGS)
        path3, payload3, resp3 = try_call(base, headers, tool_3, EMPTY_ARGS)

        df1 = normalize(rows_to_df(resp1))  # Variation
        df2 = normalize(rows_to_df(resp2))  # MM
        df3 = normalize(rows_to_df(resp3))  # RSI

        st.success("Données chargées via MCP.")
        with st.expander("Diagnostic des appels"):
            st.write({
                "Variation": {"path": path1, "payload": payload1},
                "MM": {"path": path2, "payload": payload2},
                "RSI": {"path": path3, "payload": payload3},
            })

        st.markdown("## Graphiques")
        plot_variation(df1)
        plot_mm(df2)
        plot_rsi(df3)

        with st.expander("Aperçu tables"):
            st.write("Variation (head)"); st.dataframe(df1.head(20))
            st.write("MM (head)");        st.dataframe(df2.head(20))
            st.write("RSI (head)");       st.dataframe(df3.head(20))

    except Exception as e:
        st.exception(e)
