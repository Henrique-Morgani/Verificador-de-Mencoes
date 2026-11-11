import io
import os
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import core

load_dotenv()

st.set_page_config(page_title="Verificador de Menções", page_icon="🔎", layout="wide")


def segredo(nome: str) -> str:
    """Lê do painel de Secrets do Streamlit Cloud; se não houver, do .env."""
    try:
        return str(st.secrets[nome])
    except Exception:
        return os.getenv(nome, "")


# Senha de acesso (definida em Secrets como APP_SENHA). Sem ela, o app abre direto.
senha_app = segredo("APP_SENHA")
if senha_app and not st.session_state.get("autenticado"):
    st.title("🔎 Verificador de Menções")
    senha = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if senha == senha_app:
            st.session_state["autenticado"] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")
    st.stop()

st.title("🔎 Verificador de Menções")
st.caption("Encontre menções ao cliente, veja quem já linka, quem não linka e como entrar em contato.")

# ---------------- Barra lateral: chaves e configurações ----------------
with st.sidebar:
    st.header("Chaves de API")
    serper_key = segredo("SERPER_API_KEY")
    ahrefs_key = segredo("AHREFS_API_KEY")
    if serper_key:
        st.success("Chave do Serper configurada no servidor.")
    else:
        serper_key = st.text_input(
            "Serper.dev (busca Google)", type="password",
            help="Crie em serper.dev. A conta gratuita vem com 2.500 buscas.",
        )
    if ahrefs_key:
        st.success("Chave da Ahrefs configurada no servidor.")
    else:
        ahrefs_key = st.text_input(
            "Ahrefs API v3 (necessária para o DR)", type="password",
            help="O endpoint de DR é gratuito (não gasta unidades), mas exige chave. "
                 "Uma conta gratuita da Ahrefs serve: Account settings > API keys.",
        )
    hunter_key = segredo("HUNTER_API_KEY")
    if hunter_key:
        st.success("Chave do Hunter configurada no servidor.")
    else:
        hunter_key = st.text_input(
            "Hunter.io (opcional, emails de jornalistas)", type="password",
            help="Plano grátis com créditos mensais. Cada email de autor ou busca por veículo gasta 1 crédito.",
        )

    st.header("Busca")
    pais = st.selectbox("País do Google", ["br", "pt", "mx", "co", "ar", "us", "es"], index=0)
    idioma = st.selectbox("Idioma", ["pt-br", "pt", "es", "en"], index=0)
    periodo_label = st.selectbox(
        "Período", ["Qualquer data", "Últimas 24h", "Última semana", "Último mês", "Último ano"], index=0
    )
    periodo = {"Qualquer data": "", "Últimas 24h": "d", "Última semana": "w",
               "Último mês": "m", "Último ano": "y"}[periodo_label]
    paginas = st.slider("Páginas do Google por termo", 1, 10, 3,
                        help="Cada página = 10 resultados = 1 crédito do Serper.")
    incluir_noticias = st.checkbox("Incluir Google Notícias", value=True)

    st.header("O que puxar")
    puxar_dr = st.checkbox("DR (Ahrefs)", value=True)
    puxar_contatos = st.checkbox("Contatos do site (email, WhatsApp, redes, formulário)", value=True)

    st.header("Jornalista / autor")
    puxar_autor = st.checkbox("Identificar autor da matéria e sua página", value=True,
                              help="Grátis. Lê o nome do autor e a página de autor do próprio site.")
    perfis_google = st.checkbox("Buscar LinkedIn, X e Muck Rack do autor no Google", value=True,
                                help="Gasta 1 crédito do Serper por autor.")
    hunter_autor = st.checkbox("Hunter: descobrir email do autor", value=bool(hunter_key),
                               disabled=not hunter_key, help="1 crédito do Hunter por autor.")
    hunter_veiculo = st.checkbox("Hunter: emails da redação do veículo", value=False,
                                 disabled=not hunter_key, help="1 crédito do Hunter por domínio.")
    so_oportunidades = st.checkbox("Gastar créditos só com oportunidades", value=True,
                                   help="Busca no Google e Hunter apenas para menções sem link "
                                        "ou com link nofollow.")

    excluir_txt = st.text_area(
        "Domínios a excluir (um por linha)",
        value="\n".join(core.EXCLUIR_PADRAO),
        height=180,
    )

# ---------------- Entrada principal ----------------
c1, c2 = st.columns([1, 1])
with c1:
    url_cliente = st.text_input("Site do cliente", placeholder="https://www.cliente.com.br")
with c2:
    termos_txt = st.text_area(
        "Termos para buscar como menção (um por linha)",
        placeholder="Nome da marca\nNome do produto\nNome do CEO",
        height=110,
    )

termos = [t.strip() for t in termos_txt.splitlines() if t.strip()]
excluir = [d.strip() for d in excluir_txt.splitlines() if d.strip()]

if termos and serper_key:
    custo = len(termos) * paginas * (2 if incluir_noticias else 1)
    extra = " + 1 por autor encontrado" if (puxar_autor and perfis_google) else ""
    st.caption(f"Estimativa: até {custo} créditos do Serper na busca{extra}.")

rodar = st.button("Buscar menções", type="primary", disabled=not (url_cliente and termos and serper_key))
if not serper_key:
    st.info("Informe a chave do Serper.dev na barra lateral (ou no arquivo .env) para começar.")

if rodar:
    barra = st.progress(0.0, text="Iniciando…")

    def progresso(etapa, frac):
        barra.progress(min(frac, 1.0), text=etapa)

    try:
        linhas, avisos = core.executar(
            url_cliente=url_cliente, termos=termos, serper_key=serper_key, ahrefs_key=ahrefs_key,
            hunter_key=hunter_key, pais=pais, idioma=idioma, paginas=paginas, periodo=periodo,
            incluir_noticias=incluir_noticias, excluir=excluir,
            puxar_dr=puxar_dr, puxar_contatos=puxar_contatos, puxar_autor=puxar_autor,
            perfis_google=perfis_google, hunter_autor=hunter_autor and bool(hunter_key),
            hunter_veiculo=hunter_veiculo and bool(hunter_key), so_oportunidades=so_oportunidades,
            progresso=progresso,
        )
        st.session_state["resultado"] = pd.DataFrame(linhas)
        st.session_state["avisos"] = avisos
        st.session_state["cliente"] = core.normalizar_dominio(url_cliente)
    except Exception as e:
        st.error(f"Erro: {e}")

# ---------------- Resultados ----------------
df = st.session_state.get("resultado")
if df is not None:
    if df.empty:
        st.warning("Nenhuma menção encontrada com esses termos.")
        st.stop()

    for aviso in st.session_state.get("avisos", []):
        st.warning(aviso)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("URLs encontradas", len(df))
    m2.metric("Domínios únicos", df["dominio"].nunique())
    m3.metric("Com backlink dofollow", int((df["status"] == "Com backlink dofollow").sum()))
    m4.metric("Com backlink nofollow", int((df["status"] == "Com backlink nofollow/sponsored/ugc").sum()))
    m5.metric("Sem link (oportunidade)", int((df["status"] == "Menção sem link (oportunidade)").sum()))

    f1, f2, f3 = st.columns([2, 1, 1])
    status_opts = sorted(df["status"].unique())
    padrao = [s for s in status_opts if s != "Termo não encontrado na página"]
    filtro_status = f1.multiselect("Status", status_opts, default=padrao)
    dr_min = f2.number_input("DR mínimo", 0, 100, 0)
    so_contato = f3.checkbox("Só com algum email ou WhatsApp")

    vis = df[df["status"].isin(filtro_status)]
    if dr_min:
        vis = vis[vis["dr"].fillna(-1) >= dr_min]
    if so_contato:
        cols_ct = [c for c in ("emails", "whatsapp", "autor_email", "hunter_email_autor",
                               "emails_veiculo_hunter") if c in vis.columns]
        if cols_ct:
            vis = vis[(vis[cols_ct].fillna("").astype(str) != "").any(axis=1)]

    colunas = [c for c in [
        "status", "dominio", "dr", "url", "titulo", "termos_encontrados", "anchors", "rel",
        "autor", "autor_email", "hunter_email_autor", "hunter_confianca", "hunter_cargo_autor",
        "autor_linkedin", "autor_x", "autor_instagram", "autor_muckrack", "autor_pagina",
        "buscar_autor_linkedin", "buscar_autor_muckrack",
        "emails", "emails_veiculo_hunter", "telefones", "whatsapp", "redes_sociais",
        "tem_formulario", "paginas_contato",
        "publicado_em", "data_google", "trecho_mencao", "urls_linkadas", "fonte",
    ] if c in vis.columns]

    st.dataframe(
        vis[colunas],
        width="stretch",
        hide_index=True,
        column_config={
            "url": st.column_config.LinkColumn("URL"),
            "autor_linkedin": st.column_config.LinkColumn("LinkedIn do autor"),
            "autor_x": st.column_config.LinkColumn("X do autor"),
            "autor_instagram": st.column_config.LinkColumn("Instagram do autor"),
            "autor_muckrack": st.column_config.LinkColumn("Muck Rack do autor"),
            "autor_pagina": st.column_config.LinkColumn("Página do autor"),
            "buscar_autor_linkedin": st.column_config.LinkColumn("Buscar no LinkedIn", display_text="buscar"),
            "buscar_autor_muckrack": st.column_config.LinkColumn("Buscar no Muck Rack", display_text="buscar"),
            "hunter_confianca": st.column_config.NumberColumn("Confiança Hunter", format="%d%%"),
            "dr": st.column_config.NumberColumn("DR", format="%.0f"),
            "trecho_mencao": st.column_config.TextColumn("Trecho", width="large"),
        },
    )
    if puxar_dr:
        st.caption("Domain Rating by Ahrefs (https://ahrefs.com/)")

    # Exportação
    nome = f"mencoes_{st.session_state.get('cliente', 'cliente')}_{datetime.now():%Y%m%d_%H%M}"
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        vis[colunas].to_excel(xw, index=False, sheet_name="Menções")
        agg = dict(
            dr=("dr", "max"), urls=("url", "count"),
            urls_com_dofollow=("links_dofollow", lambda s: int((s > 0).sum())),
            status=("status", lambda s: " | ".join(sorted(set(s)))),
        )
        for c in ("emails", "emails_veiculo_hunter", "whatsapp", "telefones", "redes_sociais"):
            if c in df.columns:
                agg[c] = (c, "first")
        resumo = (df.groupby("dominio").agg(**agg).reset_index()
                  .sort_values("dr", ascending=False, na_position="last"))
        resumo.to_excel(xw, index=False, sheet_name="Por domínio")
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(
                    60, max(10, max(len(str(c.value or "")) for c in col[:50]) + 2))
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Baixar Excel", buf.getvalue(), f"{nome}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    d2.download_button("⬇️ Baixar CSV", vis[colunas].to_csv(index=False).encode("utf-8-sig"),
                       f"{nome}.csv", "text/csv")
