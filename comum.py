"""Peças compartilhadas pelas telas do DizemAI (formatação, tabela de menções, exportação)."""

from __future__ import annotations

import io
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import core
import storage

FUSO = ZoneInfo("America/Sao_Paulo")
CORES = ["#2a78d6", "#eb6834", "#1baf7a", "#8b5cf6", "#d4a017"]   # ordem fixa da paleta categórica
ICONE_SENT = {"positiva": "🟢 positiva", "negativa": "🔴 negativa", "neutra": "⚪ neutra", "mista": "🟡 mista"}
PERIODOS = {"Qualquer data": "", "Últimas 24h": "d", "Última semana": "w", "Último mês": "m", "Último ano": "y"}
PERIODOS_INV = {v: k for k, v in PERIODOS.items()}
COMUNIDADES = core.COMUNIDADES_DISPONIVEIS          # nome -> domínio
COMUNIDADES_INV = {v: k for k, v in COMUNIDADES.items()}


def segredo(nome: str) -> str:
    """Lê do painel de Secrets do Streamlit Cloud; se não houver, do ambiente (.env)."""
    try:
        return str(st.secrets[nome])
    except Exception:
        return os.getenv(nome, "")


def chaves() -> dict:
    """Chaves configuradas no servidor, com as digitadas na Busca rápida por cima."""
    base = {"serper": segredo("SERPER_API_KEY"), "ahrefs": segredo("AHREFS_API_KEY"),
            "hunter": segredo("HUNTER_API_KEY")}
    for k, v in (st.session_state.get("chaves_digitadas") or {}).items():
        if v and not base.get(k):
            base[k] = v
    return base


def cliente_atual() -> dict | None:
    cid = st.session_state.get("cid")
    return storage.obter_cliente(cid) if cid else None


def exigir_cliente() -> dict:
    c = cliente_atual()
    if not c:
        st.info("Escolha um cliente na barra lateral ou cadastre um em **Configurações do cliente**.")
        st.stop()
    return c


def fmt_data(d, com_hora=False):
    if d is None or d is pd.NaT or (isinstance(d, float) and pd.isna(d)):
        return ""
    if isinstance(d, str):
        return d
    return d.astimezone(FUSO).strftime("%d/%m/%Y %H:%M" if com_hora else "%d/%m/%Y")


def limpar_para_tabela(df: pd.DataFrame, colunas: list[str]) -> pd.DataFrame:
    df = df.copy()
    for c in colunas:
        if c not in df.columns:
            df[c] = ""
        if not (pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_datetime64_any_dtype(df[c])):
            df[c] = df[c].astype(object).where(df[c].notna(), "").replace({"None": "", "nan": ""})
    return df


def progresso_streamlit(texto="Iniciando…"):
    barra = st.progress(0.0, text=texto)

    def progresso(etapa, frac):
        barra.progress(min(max(frac, 0.0), 1.0), text=etapa)
    return progresso


# ------------------------------------------------------------------ tabela de menções

COLUNAS = [
    "novidade", "status", "dominio", "dr", "url", "titulo", "outreach_status", "outreach_data_dt",
    "outreach_obs", "encontrada_em", "link_desde_dt", "perdeu_link_dt",
    "qualidade_link", "posicao_link", "noindex", "canonical_outra", "destino_link",
    "termos_encontrados", "concorrentes_citados", "anchors", "rel",
    "autor", "autor_email", "hunter_email_autor", "hunter_confianca", "hunter_cargo_autor",
    "autor_linkedin", "autor_x", "autor_instagram", "autor_muckrack", "autor_pagina",
    "buscar_autor_linkedin", "buscar_autor_muckrack",
    "emails", "emails_veiculo_hunter", "telefones", "whatsapp", "redes_sociais",
    "tem_formulario", "paginas_contato",
    "publicado_em", "data_google", "trecho_mencao", "urls_linkadas", "fonte",
]
_T = st.column_config.TextColumn
_L = st.column_config.LinkColumn
CONFIG_COLUNAS = {
    "novidade": _T("Novidade"), "status": _T("Status"), "dominio": _T("Domínio"), "titulo": _T("Título"),
    "noindex": _T("Noindex"), "termos_encontrados": _T("Termos encontrados"),
    "concorrentes_citados": _T("Concorrentes citados"), "anchors": _T("Anchor"), "autor": _T("Autor"),
    "autor_email": _T("Email do autor"), "hunter_email_autor": _T("Email do autor (Hunter)"),
    "emails": _T("Emails do site"), "emails_veiculo_hunter": _T("Emails da redação (Hunter)"),
    "telefones": _T("Telefones"), "whatsapp": _T("WhatsApp"), "redes_sociais": _T("Redes sociais"),
    "tem_formulario": _T("Formulário"), "paginas_contato": _T("Páginas de contato"),
    "publicado_em": _T("Publicado em"), "data_google": _T("Data (Google)"), "urls_linkadas": _T("URLs linkadas"),
    "fonte": _T("Canal"), "outreach_status": _T("Outreach"), "outreach_data_dt": _T("Contatado em"),
    "outreach_obs": _T("Obs. outreach"), "encontrada_em": _T("Encontrada em"), "link_desde_dt": _T("Link desde"),
    "perdeu_link_dt": _T("Perdeu link em"), "qualidade_link": _T("Qualidade do link"),
    "posicao_link": _T("Posição do link"), "canonical_outra": _L("Canonical para"),
    "destino_link": _T("Destino do link (HTTP)"), "url": _L("URL"), "autor_linkedin": _L("LinkedIn do autor"),
    "autor_x": _L("X do autor"), "autor_instagram": _L("Instagram do autor"),
    "autor_muckrack": _L("Muck Rack do autor"), "autor_pagina": _L("Página do autor"),
    "buscar_autor_linkedin": _L("Buscar no LinkedIn", display_text="buscar"),
    "buscar_autor_muckrack": _L("Buscar no Muck Rack", display_text="buscar"),
    "hunter_confianca": st.column_config.NumberColumn("Confiança Hunter", format="%d%%"),
    "dr": st.column_config.NumberColumn("DR", format="%.0f"),
    "trecho_mencao": _T("Trecho", width="large"),
    "sentimento_vis": _T("Sentimento"), "pergunta_indicacao": _T("Pergunta/indicação"),
    "motivo_sentimento": _T("Motivo", width="medium"), "assunto": _T("Assunto"),
    "conversa_status": _T("Status da conversa"), "marca": _T("Marca"),
}


def preparar(df: pd.DataFrame, historico: bool, ts) -> pd.DataFrame:
    df = df.copy()
    if "sentimento" in df.columns:
        df["sentimento_vis"] = df["sentimento"].map(lambda s: ICONE_SENT.get(s, "") if isinstance(s, str) else "")
    if historico:
        def novidade(r):
            if ts is None:
                return ""
            if pd.notna(r["primeira_vez"]) and r["primeira_vez"] >= ts:
                return "🆕 Nova"
            if pd.notna(r["link_desde"]) and r["link_desde"] >= ts:
                return "🔗 Ganhou link"
            if pd.notna(r["perdeu_link_em"]) and r["perdeu_link_em"] >= ts:
                return "⚠️ Perdeu link"
            return ""
        df["novidade"] = df.apply(novidade, axis=1)
        df["encontrada_em"] = df["primeira_vez"].map(fmt_data)
        df["link_desde_dt"] = df["link_desde"].map(fmt_data)
        df["perdeu_link_dt"] = df["perdeu_link_em"].map(fmt_data)
        df["outreach_data_dt"] = df["outreach_data"].map(fmt_data)
    return df


def baixar_excel(abas: dict[str, pd.DataFrame], nome_base: str, rotulo="⬇️ Baixar Excel", chave=None):
    base = re.sub(r"[^\w-]", "_", nome_base)
    nome_arq = f"{base}_{datetime.now(FUSO):%Y%m%d_%H%M}.xlsx"
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for nome, df in abas.items():
            df.to_excel(xw, index=False, sheet_name=nome[:31])
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(
                    60, max(10, max(len(str(c.value or "")) for c in col[:50]) + 2))
    st.download_button(rotulo, buf.getvalue(), nome_arq, key=chave,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def exportar(vis, df, colunas, nome_base):
    agg = dict(dr=("dr", "max"), urls=("url", "count"), status=("status", lambda s: " | ".join(sorted(set(s)))))
    for c in ("emails", "emails_veiculo_hunter", "whatsapp", "telefones", "redes_sociais"):
        if c in df.columns:
            agg[c] = (c, "first")
    por_dom = (df.groupby("dominio").agg(**agg).reset_index()
               .sort_values("dr", ascending=False, na_position="last"))
    d1, d2 = st.columns(2)
    with d1:
        baixar_excel({"Menções": vis[colunas], "Por domínio": por_dom}, f"mencoes_{nome_base}")
    d2.download_button("⬇️ Baixar CSV", vis[colunas].to_csv(index=False).encode("utf-8-sig"),
                       f"mencoes_{nome_base}.csv", "text/csv")


def mostrar_mencoes(df: pd.DataFrame | None, historico: bool, cid: int | None = None, nome_base="avulsa"):
    ts = None
    if historico:
        ult = storage.ultima_execucao(cid)
        if ult:
            ts = ult["inicio"]
            st.info(f"**Última busca:** {fmt_data(ult['inicio'], True)} ({ult['origem']}) · "
                    f"{ult['novas']} menção(ões) nova(s), {ult['novos_links']} link(s) ganho(s), "
                    f"{ult['links_perdidos']} perdido(s) · créditos: Serper {ult['creditos_serper']}, "
                    f"Hunter {ult['creditos_hunter']}")
    if df is None or df.empty:
        st.info("Nenhuma menção ainda. Clique em **Buscar agora**." if historico
                else "Nenhuma menção encontrada com esses termos.")
        return
    df = preparar(df, historico, ts)

    m = st.columns(6)
    m[0].metric("URLs", len(df))
    m[1].metric("Backlink dofollow", int((df["status"] == core.ST_DOFOLLOW).sum()))
    m[2].metric("Backlink nofollow", int((df["status"] == core.ST_NOFOLLOW).sum()))
    m[3].metric("Sem link (oportunidade)", int((df["status"] == core.ST_SEM_LINK).sum()))
    m[4].metric("Links quebrados", int((df["status"] == core.ST_QUEBRADO).sum()))
    m[5].metric("Prospects (link gap)", int(df["status"].isin([storage.ST_GAP, core.ST_PROSPECT]).sum()))

    if historico:
        mo = storage.metricas_outreach(cid)
        o = st.columns(4)
        o[0].metric("Contatados", mo["contatados"])
        o[1].metric("Responderam", mo["responderam"])
        o[2].metric("Links conquistados", mo["conquistados"])
        o[3].metric("Conversão do outreach", f"{mo['taxa']:.0%}" if mo["taxa"] is not None else "–")

    f1, f2, f3, f4 = st.columns([2.4, 0.8, 1, 1])
    status_opts = sorted(df["status"].dropna().unique())
    padrao = [s for s in status_opts if s != core.ST_NAO_ENCONTRADO]
    filtro_status = f1.multiselect("Status", status_opts, default=padrao, key=f"fs_{cid}")
    dr_min = f2.number_input("DR mínimo", 0, 100, 0, key=f"dr_{cid}")
    so_contato = f3.checkbox("Só com email ou WhatsApp", key=f"sc_{cid}")
    so_novas = f4.checkbox("Só novidades", disabled=not historico or ts is None, key=f"sn_{cid}")

    vis = df[df["status"].isin(filtro_status)]
    if dr_min:
        vis = vis[vis["dr"].fillna(-1) >= dr_min]
    if so_contato:
        cols_ct = [c for c in ("emails", "whatsapp", "autor_email", "hunter_email_autor",
                               "emails_veiculo_hunter") if c in vis.columns]
        if cols_ct:
            vis = vis[(vis[cols_ct].fillna("").astype(str) != "").any(axis=1)]
    if so_novas and historico:
        vis = vis[vis["novidade"] != ""]
    vis = vis.reset_index(drop=True)
    colunas = [c for c in COLUNAS if c in vis.columns]
    vis = limpar_para_tabela(vis, colunas)

    evento = st.dataframe(
        vis[colunas], width="stretch", hide_index=True, column_config=CONFIG_COLUNAS,
        on_select="rerun" if historico else "ignore", selection_mode="multi-row",
        key=f"tabela_{cid}" if historico else "tabela_avulsa",
    )
    st.caption("Domain Rating by Ahrefs (https://ahrefs.com/)")

    if historico:
        selecionadas = vis.iloc[evento.selection.rows] if evento and evento.selection.rows else vis.iloc[0:0]
        with st.container(border=True):
            if selecionadas.empty:
                st.caption("Selecione linhas na tabela (caixa à esquerda) para marcar outreach ou ignorar.")
            else:
                st.markdown(f"**{len(selecionadas)} linha(s) selecionada(s)**")
                a1, a2, a3 = st.columns([1.2, 2, 1])
                novo_status = a1.selectbox("Status de outreach", storage.OUTREACH_OPCOES, index=1)
                obs = a2.text_input("Observação (opcional)", placeholder="Ex.: email enviado para a redação")
                a3.write("")
                if a3.button("Aplicar outreach", type="primary"):
                    storage.definir_outreach(cid, selecionadas["url"].tolist(), novo_status, obs)
                    st.rerun()
                i1, i2 = st.columns(2)
                if i1.button("🚫 Ignorar estas URLs"):
                    storage.ignorar(cid, "url", selecionadas["url"].tolist())
                    st.rerun()
                if i2.button("🚫 Ignorar estes domínios inteiros"):
                    storage.ignorar(cid, "dominio", selecionadas["dominio"].tolist())
                    st.rerun()

    exportar(vis, df, colunas, nome_base)


def delta_dr(cid: int, dominio: str, dias: int = 30):
    """(DR atual, variação contra o registro mais próximo de N dias atrás)."""
    hist = storage.historico_dr(cid, dominio)
    if not hist:
        return None, None
    atual = hist[-1][1]
    corte = storage.agora() - timedelta(days=dias)
    antes = [v for d, v in hist if d <= corte]
    base = antes[-1] if antes else hist[0][1]
    return atual, (atual - base) if len(hist) > 1 else None
