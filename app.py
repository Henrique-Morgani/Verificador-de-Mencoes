"""DizemAI: monitoramento off page (menções, links, comunidades, Digital PR e concorrentes)."""

import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()
st.set_page_config(page_title="DizemAI", page_icon="💬", layout="wide")

from comum import segredo  # noqa: E402

# Repassa os segredos para os módulos de banco, email, IA e provedores
for _k in ("DATABASE_URL", "SMTP_USUARIO", "SMTP_SENHA", "SMTP_HOST", "SMTP_PORTA", "SMTP_REMETENTE",
           "APP_URL", "GEMINI_API_KEY", "GEMINI_MODELO", "SERPER_API_KEY", "AHREFS_API_KEY",
           "HUNTER_API_KEY", "AHREFS_API_KEY_PAGA", "AHREFS_MAX_LINHAS", "PROVEDOR_DADOS", "SEMRUSH_API_KEY"):
    _v = segredo(_k)
    if _v:
        os.environ[_k] = _v

import storage  # noqa: E402
from telas import (alertas, analista, busca_rapida, comunidades, config_cliente, digital_pr,  # noqa: E402
                   mencoes, resumo)

# ---------------- Senha ----------------
senha_app = segredo("APP_SENHA")
if senha_app and not st.session_state.get("autenticado"):
    st.title("💬 DizemAI")
    senha = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if senha == senha_app:
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")
    st.stop()

# ---------------- Banco ----------------
try:
    lista = storage.listar_clientes()
    erro_banco = ""
except Exception as e:
    lista, erro_banco = [], str(e)

# Troca de cliente pedida por alguma tela (ex.: depois de salvar um cliente novo)
if "_ir_para" in st.session_state:
    st.session_state["cid"] = st.session_state.pop("_ir_para")

ids = [c["id"] for c in lista]
if st.session_state.get("cid") not in ids:
    st.session_state["cid"] = ids[0] if ids else None

# ---------------- Barra lateral ----------------
with st.sidebar:
    st.markdown("## 💬 DizemAI")
    st.caption("Off page: menções, links, comunidades e PR")
    if ids:
        nomes = {c["id"]: c["nome"] for c in lista}
        st.selectbox("Cliente", ids, format_func=lambda i: nomes[i], key="cid")
    else:
        st.caption("Nenhum cliente cadastrado ainda.")

paginas = {
    "": [
        st.Page(resumo.tela, title="Resumo", icon="🏠", url_path="resumo", default=True),
    ],
    "Monitoramento": [
        st.Page(mencoes.tela, title="Menções e links", icon="🔗", url_path="mencoes"),
        st.Page(comunidades.tela, title="O que dizem aí", icon="💬", url_path="comunidades"),
        st.Page(digital_pr.tela, title="Digital PR", icon="📣", url_path="digital-pr"),
        st.Page(analista.tela, title="Concorrentes", icon="📊", url_path="concorrentes"),
    ],
    "Cliente": [
        st.Page(config_cliente.tela, title="Configurações do cliente", icon="⚙️", url_path="config"),
        st.Page(alertas.tela, title="Alertas e ignorados", icon="✉️", url_path="alertas"),
    ],
    "Ferramentas": [
        st.Page(busca_rapida.tela, title="Busca rápida", icon="🔎", url_path="busca-rapida"),
    ],
}
nav = st.navigation(paginas)

if erro_banco:
    st.error(f"Não consegui conectar ao banco de dados. Confira o DATABASE_URL nos Secrets. Detalhe: {erro_banco[:300]}")
elif not storage.usando_banco_externo():
    st.warning("Banco de dados não configurado: clientes e histórico ficam só até o app reiniciar, "
               "e os alertas por email não funcionam. Configure DATABASE_URL nos Secrets.")

with st.sidebar:
    if not erro_banco:
        st.divider()
        cm = storage.creditos_no_mes()
        st.caption(f"**Créditos neste mês (todos os clientes):** Serper {cm['serper']} · "
                   f"Hunter {cm['hunter']} · {cm['execucoes']} busca(s)")

nav.run()
