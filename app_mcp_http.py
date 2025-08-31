# app_mcp_custompath.py
# Streamlit: n8n MCP (SSE/HTTP) -> 3 tools -> 3 graphiques, avec chemin d'appel et payload configurables

import requests, pandas as pd, streamlit as st
from typing import Any, Dict, List

# Forms de payload supportées
def payload_name_arguments(tool, args): return {"name": tool, "arguments": args}
def payload_tool_arguments(tool, args): return {"tool": tool, "arguments": args}
def payload_toolName_arguments(tool, args): return {"toolName": tool, "arguments": args}
def payload_name_args(tool, args): return {"name": tool, "args": args}
def payload_tool_args(tool, args): return {"tool": tool, "args": args}
def payload_toolName_args(tool, args): return {"toolName": tool, "args": args}

PAYLOAD_SHAPES = {
    "name + arguments": payload_name_arguments,
    "tool + arguments": payload_tool_arguments,
    "toolName + arguments": payload_toolName_arguments,
    "name + args": payload_name_args,
    "tool + args": payload_tool_args,
    "toolName + args": payload_toolName_args,
}

def sse_to_base(sse_url: str) -> str:
    if not sse_url: raise ValueError("URL SSE manquante.")
    return sse_url[:-4] if sse_url.endswith("/sse") else sse_url.rstrip("/")

def list_tools(base: str, headers: Dict[str,str]):
    url = base.rstrip("/") + "/tools"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if not r.ok: return r.status_code, []
        j = r.json()
        tools = [t["name"] for t in j.get("tools", []) if isinstance(t, dict) and "name" in t]
        return r.status_code, tools
    except Exception:
        return -1, []

def call_tool(base: str, call_path: str, payload_fn, tool_name: str, args: Dict[str,Any], headers: Dict[str,str]):
    url = base.rstrip("/") + call_path
    r = requests.post(url, json=payload_fn(tool_name, args), headers=headers, timeout=45)
    r.raise_for_status()
    return r.json()

def rows_to_df(payload: Any) -> pd.DataFrame:
    rows = None
    if isinstance(payload, dict):
        data = payload.get("result", payload)
        if isinstance(data, dict): rows = data.get("rows") or data.get("data") or data.get("values")
        elif isinstance(data, list): rows = data
    elif isinstance(payload, list): rows = payload
    if rows is None: raise RuntimeError(f"Réponse inattendue: {payload}")
    if not rows: return pd.DataFrame()
    header = rows[0] if isinstance(rows[0], list) and all(isinstance(h, str) for h in rows[0]) else None
    body = rows[1:] if header else rows
    return pd.DataFrame(body, columns=header if header else None)

def normalize(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy(); d.columns = [str(c).strip().lower() for c in d.columns]
    if "date" in d.columns: d["date"] = pd.to_datetime(d["date"], errors="coerce")
    for c in d.columns:
        if c != "date": d[c] = pd.to_numeric(d[c], errors="ignore")
    return d

def plot_variation(df: pd.DataFrame):
    st.subheader("Variation journalière (%)")
    if not {"date","variation_pct"}.issubset(df.columns):
        st.error("Colonnes requises: date, variation_pct"); return
    st.line_chart(df[["date","variation_pct"]].sort_values("date").set_index("date"))

def plot_mm(df: pd.DataFrame):
    st.subheader("Moyennes mobiles (MM50 / MM200) & Cours")
    need = ["date","close","mm50","mm200"]
    miss = [c for c in need if c not in df.columns]
    if miss: st.error(f"Colonnes manquantes: {', '.join(miss)}"); return
    st.line_chart(df[need].sort_values("date").set_index("date"))

def plot_rsi(df: pd.DataFrame):
    st.subheader("RSI – court / moyen / long")
    if not {"date","close"}.issubset(df.columns): st.error("Colonnes requises: date, close"); return
    aliases_long = ["long terme","long","long_terme","rsi long","rsi_long"]
    rsi_cols = [c for c in ["court","moyen"] + aliases_long if c in df.columns]
    st.line_chart(df[["date","close"]].sort_values("date").set_index("date"))
    if rsi_cols:
        st.line_chart(df[["date"] + rsi_cols].sort_values("date").set_index("date"))
    else:
        st.info("Colonnes RSI non trouvées.")

# ================= UI =================
st.set_page_config(page_title="MCP (custom path) → Graphiques", layout="wide")
st.title("MCP (chemin d’appel custom) → Google Sheets → Graphiques")

with st.sidebar:
    st.header("Serveur MCP")
    sse_url = st.text_input("URL SSE MCP", value="", placeholder="https://.../mcp-test/<UUID>/sse")
    bearer = st.text_input("Bearer token (optionnel)", type="password")
    st.caption("La base HTTP est déduite en retirant /sse.")
    st.markdown("---")
    st.header("Invocation")
    call_path = st.text_input("Chemin d’appel HTTP", value="/call", help="Ex.: /call, /tool, /invoke, /run, /tools/call, /tool/call, /respond, etc.")
    shape_key = st.selectbox("Forme du payload", list(PAYLOAD_SHAPES.keys()), index=0)
    payload_fn = PAYLOAD_SHAPES[shape_key]
    st.markdown("---")
    st.subheader("Noms des tools")
    tool_var = st.text_input("Tool Variation", value="1")
    tool_mm  = st.text_input("Tool MM", value="2")
    tool_rsi = st.text_input("Tool RSI", value="3")
    EMPTY_ARGS: Dict[str,Any] = {}

colA, colB = st.columns(2)
with colA:
    if st.button("Lister /tools"):
        try:
            base = sse_to_base(sse_url)
            headers = {"Content-Type":"application/json"}
            if bearer: headers["Authorization"] = f"Bearer {bearer}"
            code, tools = list_tools(base, headers)
            st.write({"status": code, "tools": tools})
        except Exception as e:
            st.exception(e)

with colB:
    if st.button("Charger & tracer"):
        try:
            base = sse_to_base(sse_url)
            headers = {"Content-Type":"application/json"}
            if bearer: headers["Authorization"] = f"Bearer {bearer}"

            resp_var = call_tool(base, call_path, payload_fn, tool_var, EMPTY_ARGS, headers)
            resp_mm  = call_tool(base, call_path, payload_fn, tool_mm,  EMPTY_ARGS, headers)
            resp_rsi = call_tool(base, call_path, payload_fn, tool_rsi, EMPTY_ARGS, headers)

            df_var = normalize(rows_to_df(resp_var))
            df_mm  = normalize(rows_to_df(resp_mm))
            df_rsi = normalize(rows_to_df(resp_rsi))

            st.success("Données chargées.")
            with st.expander("Aperçu"):
                st.write("Variation"); st.dataframe(df_var.head(20))
                st.write("MM");        st.dataframe(df_mm.head(20))
                st.write("RSI");       st.dataframe(df_rsi.head(20))

            st.markdown("## Graphiques")
            plot_variation(df_var)
            plot_mm(df_mm)
            plot_rsi(df_rsi)

        except Exception as e:
            st.exception(e)
