import io
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import core

load_dotenv()

st.set_page_config(page_title="Verificador de Menções", page_icon="🔎", layout="wide")
FUSO = ZoneInfo("America/Sao_Paulo")


def segredo(nome: str) -> str:
    """Lê do painel de Secrets do Streamlit Cloud; se não houver, do .env."""
    try:
        return str(st.secrets[nome])
    except Exception:
        return os.getenv(nome, "")


# Repassa os segredos para os módulos de banco, email e IA
for _k in ("DATABASE_URL", "SMTP_USUARIO", "SMTP_SENHA", "SMTP_HOST", "SMTP_PORTA",
           "SMTP_REMETENTE", "APP_URL", "GEMINI_API_KEY", "GEMINI_MODELO"):
    _v = segredo(_k)
    if _v:
        os.environ[_k] = _v

import fluxo  # noqa: E402
import ia  # noqa: E402
import relatorio  # noqa: E402
import storage  # noqa: E402

# ---------------- Senha ----------------
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

# ---------------- Configuração ----------------
PERIODOS = {"Qualquer data": "", "Últimas 24h": "d", "Última semana": "w", "Último mês": "m", "Último ano": "y"}
PERIODOS_INV = {v: k for k, v in PERIODOS.items()}
FREQUENCIAS = {"Quinzenal": 14, "Semanal": 7, "Mensal": 30}
FREQ_INV = {v: k for k, v in FREQUENCIAS.items()}
COMUNIDADES = core.COMUNIDADES_DISPONIVEIS          # nome -> domínio
COMUNIDADES_INV = {v: k for k, v in COMUNIDADES.items()}
NOVO = 0
CORES = ["#2a78d6", "#eb6834", "#1baf7a"]           # ordem fixa da paleta categórica
ICONE_SENT = {"positiva": "🟢 positiva", "negativa": "🔴 negativa", "neutra": "⚪ neutra", "mista": "🟡 mista"}


def _concorrentes_para_texto(nomes, dominios) -> str:
    linhas = list(nomes)
    for i, d in enumerate(dominios):
        if i < len(linhas):
            linhas[i] = f"{linhas[i]} | {d}"
        else:
            linhas.append(f"| {d}")
    return "\n".join(linhas)


def _texto_para_concorrentes(txt: str) -> tuple[list[str], list[str]]:
    nomes, doms = [], []
    for ln in txt.splitlines():
        if not ln.strip():
            continue
        nome, _, dom = ln.partition("|")
        if nome.strip():
            nomes.append(nome.strip())
        if dom.strip():
            doms.append(core.normalizar_dominio(dom.strip()))
    return nomes, doms


def aplicar_config(cfg: dict):
    c = {**fluxo.PADRAO, **(cfg or {})}
    ss = st.session_state
    ss["cfg_pais"] = c["pais"]
    ss["cfg_idioma"] = c["idioma"]
    ss["cfg_periodo"] = PERIODOS_INV.get(c["periodo"], "Qualquer data")
    ss["cfg_paginas"] = int(c["paginas"])
    for k in ("incluir_noticias", "puxar_dr", "puxar_contatos", "puxar_autor", "perfis_google",
              "hunter_autor", "hunter_veiculo", "so_oportunidades"):
        ss[f"cfg_{k}"] = bool(c[k])
    ss["cfg_excluir"] = "\n".join(c["excluir"])
    ss["cfg_periodo_monitoramento"] = PERIODOS_INV.get(c["periodo_monitoramento"], "Último mês")
    ss["cfg_paginas_monitoramento"] = int(c["paginas_monitoramento"])
    ss["cfg_comunidades"] = [COMUNIDADES_INV[d] for d in c["comunidades"] if d in COMUNIDADES_INV]
    ss["cfg_concorrentes"] = _concorrentes_para_texto(c["concorrentes"], c["dominios_concorrentes"])
    ss["cfg_paginas_concorrentes"] = int(c["paginas_concorrentes"])


def config_atual() -> dict:
    ss = st.session_state
    nomes, doms = _texto_para_concorrentes(ss["cfg_concorrentes"])
    return {
        "pais": ss["cfg_pais"], "idioma": ss["cfg_idioma"], "periodo": PERIODOS[ss["cfg_periodo"]],
        "paginas": ss["cfg_paginas"], "incluir_noticias": ss["cfg_incluir_noticias"],
        "puxar_dr": ss["cfg_puxar_dr"], "puxar_contatos": ss["cfg_puxar_contatos"],
        "puxar_autor": ss["cfg_puxar_autor"], "perfis_google": ss["cfg_perfis_google"],
        "hunter_autor": ss["cfg_hunter_autor"], "hunter_veiculo": ss["cfg_hunter_veiculo"],
        "so_oportunidades": ss["cfg_so_oportunidades"],
        "excluir": [d.strip() for d in ss["cfg_excluir"].splitlines() if d.strip()],
        "periodo_monitoramento": PERIODOS[ss["cfg_periodo_monitoramento"]],
        "paginas_monitoramento": ss["cfg_paginas_monitoramento"],
        "comunidades": [COMUNIDADES[n] for n in ss["cfg_comunidades"]],
        "concorrentes": nomes, "dominios_concorrentes": doms,
        "paginas_concorrentes": ss["cfg_paginas_concorrentes"],
    }


def carregar_cliente():
    cid = st.session_state.get("cliente_sel", NOVO)
    st.session_state.pop("resultado", None)
    st.session_state.pop("avisos", None)
    if cid == NOVO:
        st.session_state["nome_cliente"] = ""
        st.session_state["url_cliente"] = ""
        st.session_state["termos_txt"] = ""
        aplicar_config({})
        return
    c = storage.obter_cliente(cid)
    if c:
        st.session_state["nome_cliente"] = c["nome"]
        st.session_state["url_cliente"] = c["url"]
        st.session_state["termos_txt"] = "\n".join(c["termos"])
        aplicar_config(c["config"])


if "cfg_pais" not in st.session_state:
    aplicar_config({})
if "_ir_para" in st.session_state:
    st.session_state["cliente_sel"] = st.session_state.pop("_ir_para")
    carregar_cliente()
for _k in ("nome_cliente", "url_cliente", "termos_txt"):
    st.session_state.setdefault(_k, "")

try:
    lista_clientes = storage.listar_clientes()
    erro_banco = ""
except Exception as e:
    lista_clientes, erro_banco = [], str(e)

st.title("🔎 Verificador de Menções")
st.caption("Menções ao cliente na web, em notícias e em comunidades: quem linka, quem não linka, "
           "qualidade do link e como entrar em contato.")
if erro_banco:
    st.error(f"Não consegui conectar ao banco de dados. Confira o DATABASE_URL nos Secrets. Detalhe: {erro_banco[:300]}")
elif not storage.usando_banco_externo():
    st.warning("Banco de dados não configurado: clientes e histórico ficam só até o app reiniciar, "
               "e os alertas por email não funcionam. Configure DATABASE_URL nos Secrets.")

# ---------------- Barra lateral ----------------
with st.sidebar:
    st.header("Chaves de API")
    serper_key = segredo("SERPER_API_KEY")
    ahrefs_key = segredo("AHREFS_API_KEY")
    hunter_key = segredo("HUNTER_API_KEY")
    for nome_k, valor in (("Serper", serper_key), ("Ahrefs", ahrefs_key), ("Hunter", hunter_key)):
        if valor:
            st.success(f"Chave do {nome_k} configurada no servidor.")
    if ia.configurado():
        st.success("Gemini configurado (sentimento).")
    else:
        st.caption("Sem GEMINI_API_KEY: menções em comunidades ficam sem sentimento.")
    if not serper_key:
        serper_key = st.text_input("Serper.dev (busca Google)", type="password")
    if not ahrefs_key:
        ahrefs_key = st.text_input("Ahrefs API v3 (para o DR)", type="password")
    if not hunter_key:
        hunter_key = st.text_input("Hunter.io (opcional)", type="password")

    st.header("Busca")
    st.selectbox("País do Google", ["br", "pt", "mx", "co", "ar", "us", "es"], key="cfg_pais")
    st.selectbox("Idioma", ["pt-br", "pt", "es", "en"], key="cfg_idioma")
    st.selectbox("Período", list(PERIODOS), key="cfg_periodo")
    st.slider("Páginas do Google (web)", 1, 10, key="cfg_paginas",
              help="Todos os termos vão numa busca só. Cada página = 1 crédito do Serper.")
    st.checkbox("Incluir Google Notícias (grátis, via RSS)", key="cfg_incluir_noticias")

    st.header("Comunidades")
    st.multiselect("Monitorar menções em", list(COMUNIDADES), key="cfg_comunidades",
                   help="Uma busca só para todas = 1 crédito. Sentimento classificado pelo Gemini.")

    st.header("Concorrentes")
    st.text_area("Um por linha (opcional: nome | site)", key="cfg_concorrentes", height=90,
                 placeholder="Concorrente A | concorrentea.com.br\nConcorrente B")
    st.slider("Páginas do Google (concorrentes)", 1, 5, key="cfg_paginas_concorrentes")

    st.header("O que puxar")
    st.checkbox("DR (Ahrefs)", key="cfg_puxar_dr")
    st.checkbox("Contatos do site (email, WhatsApp, redes, formulário)", key="cfg_puxar_contatos")
    st.checkbox("Identificar autor da matéria e sua página", key="cfg_puxar_autor")
    st.checkbox("Buscar LinkedIn, X e Muck Rack do autor no Google", key="cfg_perfis_google",
                help="1 crédito do Serper por autor novo.")
    st.checkbox("Hunter: email do autor", key="cfg_hunter_autor", disabled=not hunter_key)
    st.checkbox("Hunter: emails da redação", key="cfg_hunter_veiculo", disabled=not hunter_key)
    st.checkbox("Gastar créditos só com oportunidades", key="cfg_so_oportunidades",
                help="Google e Hunter só para menções sem link, nofollow, links quebrados e prospects.")
    st.text_area("Domínios a excluir (um por linha)", key="cfg_excluir", height=140)

    if not erro_banco:
        st.divider()
        cm = storage.creditos_no_mes()
        st.caption(f"**Créditos neste mês (todos os clientes):** Serper {cm['serper']} · "
                   f"Hunter {cm['hunter']} · {cm['execucoes']} busca(s)")

# ---------------- Cliente ----------------
opcoes = [NOVO] + [c["id"] for c in lista_clientes]
nomes = {NOVO: "➕ Novo cliente / busca avulsa", **{c["id"]: c["nome"] for c in lista_clientes}}
if st.session_state.get("cliente_sel") not in opcoes:
    st.session_state["cliente_sel"] = NOVO

c0, c00 = st.columns([1, 1])
c0.selectbox("Cliente", opcoes, format_func=lambda i: nomes[i], key="cliente_sel", on_change=carregar_cliente)
cid = st.session_state["cliente_sel"]
c00.text_input("Nome do cliente (para salvar)", key="nome_cliente", placeholder="Ex.: LáVamos")

c1, c2 = st.columns([1, 1])
c1.text_input("Site do cliente", key="url_cliente", placeholder="https://www.cliente.com.br")
c2.text_area("Termos para buscar como menção (um por linha)", key="termos_txt",
             placeholder="Nome da marca\nNome do produto\nNome do CEO", height=110)

url_cliente = st.session_state["url_cliente"].strip()
termos = [t.strip() for t in st.session_state["termos_txt"].splitlines() if t.strip()]
cfg = config_atual()
chaves = {"serper": serper_key, "ahrefs": ahrefs_key, "hunter": hunter_key}

if termos and serper_key:
    custo = cfg["paginas"] + (1 if cfg["comunidades"] else 0) + \
        (cfg["paginas_concorrentes"] if cfg["concorrentes"] else 0)
    extra = " + 1 por autor novo" if (cfg["puxar_autor"] and cfg["perfis_google"]) else ""
    st.caption(f"Estimativa desta busca: até {custo} crédito(s) do Serper{extra}. Notícias: grátis.")

b1, b2, b3, b4 = st.columns([1.2, 1.2, 1.4, 1])
rodar = b1.button("🔎 Buscar menções", type="primary", disabled=not (url_cliente and termos and serper_key))
salvar = b2.button("💾 Salvar cliente" if cid == NOVO else "💾 Salvar alterações",
                   disabled=bool(erro_banco) or not (st.session_state["nome_cliente"].strip() and url_cliente and termos))
reverificar = b3.checkbox("Reverificar menções salvas", value=True, disabled=cid == NOVO,
                          help="Abre de novo as páginas já guardadas para ver se ganharam ou perderam link.")
if cid != NOVO:
    with b4.popover("🗑️ Excluir"):
        st.write(f"Excluir **{nomes[cid]}**, todo o histórico e os alertas?")
        if st.button("Confirmar exclusão", type="primary"):
            storage.excluir_cliente(cid)
            st.session_state["_ir_para"] = NOVO
            st.rerun()

if not serper_key:
    st.info("Informe a chave do Serper.dev na barra lateral (ou nos Secrets) para começar.")

if salvar:
    try:
        novo_id = storage.salvar_cliente(st.session_state["nome_cliente"], url_cliente, termos, cfg,
                                         None if cid == NOVO else cid)
        if cid == NOVO and st.session_state.get("resultado") is not None:
            storage.salvar_resultados(novo_id, st.session_state["resultado"].to_dict("records"))
        st.session_state["_ir_para"] = novo_id
        st.toast("Cliente salvo.")
        st.rerun()
    except Exception as e:
        st.error(f"Não consegui salvar: {e}")

if rodar:
    barra = st.progress(0.0, text="Iniciando…")

    def progresso(etapa, frac):
        barra.progress(min(frac, 1.0), text=etapa)

    try:
        if cid != NOVO:
            cliente_atual = {"id": cid, "nome": st.session_state["nome_cliente"] or nomes[cid],
                             "url": url_cliente, "termos": termos}
            _, avisos, _ = fluxo.rodar_cliente(cliente_atual, origem="manual", chaves=chaves,
                                               reverificar=reverificar, cfg=cfg, progresso=progresso)
            st.session_state["avisos"] = avisos
            st.rerun()
        else:
            stats: dict = {}
            linhas, avisos = core.executar(url_cliente=url_cliente, termos=termos,
                                           **fluxo.parametros(cfg, chaves), estatisticas=stats,
                                           progresso=progresso)
            aviso_ia = ia.aplicar_sentimento(linhas, marca=st.session_state["nome_cliente"] or termos[0])
            if aviso_ia:
                avisos.append(aviso_ia)
            avisos.append(f"Créditos usados: Serper {stats.get('serper', 0)}, Hunter {stats.get('hunter', 0)}.")
            st.session_state["resultado"] = pd.DataFrame(linhas)
        st.session_state["avisos"] = avisos
    except Exception as e:
        st.error(f"Erro: {e}")


# ---------------- Utilidades de exibição ----------------
def fmt_data(d, com_hora=False):
    if d is None or d is pd.NaT or (isinstance(d, float) and pd.isna(d)):
        return ""
    if isinstance(d, str):
        return d
    return d.astimezone(FUSO).strftime("%d/%m/%Y %H:%M" if com_hora else "%d/%m/%Y")


COLUNAS = [
    "novidade", "status", "sentimento_vis", "pergunta_indicacao", "motivo_sentimento", "dominio", "dr",
    "url", "titulo", "outreach_status", "outreach_data_dt", "outreach_obs",
    "encontrada_em", "link_desde_dt", "perdeu_link_dt",
    "qualidade_link", "posicao_link", "noindex", "canonical_outra", "destino_link",
    "termos_encontrados", "concorrentes_citados", "anchors", "rel",
    "autor", "autor_email", "hunter_email_autor", "hunter_confianca", "hunter_cargo_autor",
    "autor_linkedin", "autor_x", "autor_instagram", "autor_muckrack", "autor_pagina",
    "buscar_autor_linkedin", "buscar_autor_muckrack",
    "emails", "emails_veiculo_hunter", "telefones", "whatsapp", "redes_sociais",
    "tem_formulario", "paginas_contato",
    "publicado_em", "data_google", "trecho_mencao", "urls_linkadas", "fonte",
]
CONFIG_COLUNAS = {
    "novidade": st.column_config.TextColumn("Novidade"),
    "status": st.column_config.TextColumn("Status"),
    "dominio": st.column_config.TextColumn("Domínio"),
    "titulo": st.column_config.TextColumn("Título"),
    "noindex": st.column_config.TextColumn("Noindex"),
    "termos_encontrados": st.column_config.TextColumn("Termos encontrados"),
    "concorrentes_citados": st.column_config.TextColumn("Concorrentes citados"),
    "anchors": st.column_config.TextColumn("Anchor"),
    "autor": st.column_config.TextColumn("Autor"),
    "autor_email": st.column_config.TextColumn("Email do autor"),
    "hunter_email_autor": st.column_config.TextColumn("Email do autor (Hunter)"),
    "emails": st.column_config.TextColumn("Emails do site"),
    "emails_veiculo_hunter": st.column_config.TextColumn("Emails da redação (Hunter)"),
    "telefones": st.column_config.TextColumn("Telefones"),
    "whatsapp": st.column_config.TextColumn("WhatsApp"),
    "redes_sociais": st.column_config.TextColumn("Redes sociais"),
    "tem_formulario": st.column_config.TextColumn("Formulário"),
    "paginas_contato": st.column_config.TextColumn("Páginas de contato"),
    "publicado_em": st.column_config.TextColumn("Publicado em"),
    "data_google": st.column_config.TextColumn("Data (Google)"),
    "urls_linkadas": st.column_config.TextColumn("URLs linkadas"),
    "fonte": st.column_config.TextColumn("Canal"),
    "sentimento_vis": st.column_config.TextColumn("Sentimento"),
    "pergunta_indicacao": st.column_config.TextColumn("Pergunta/indicação"),
    "motivo_sentimento": st.column_config.TextColumn("Motivo", width="medium"),
    "outreach_status": st.column_config.TextColumn("Outreach"),
    "outreach_data_dt": st.column_config.TextColumn("Contatado em"),
    "outreach_obs": st.column_config.TextColumn("Obs. outreach"),
    "encontrada_em": st.column_config.TextColumn("Encontrada em"),
    "link_desde_dt": st.column_config.TextColumn("Link desde"),
    "perdeu_link_dt": st.column_config.TextColumn("Perdeu link em"),
    "qualidade_link": st.column_config.TextColumn("Qualidade do link"),
    "posicao_link": st.column_config.TextColumn("Posição do link"),
    "canonical_outra": st.column_config.LinkColumn("Canonical para"),
    "destino_link": st.column_config.TextColumn("Destino do link (HTTP)"),
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


def exportar(vis, df, colunas):
    base = re.sub(r"[^\w-]", "_", st.session_state.get("nome_cliente") or core.normalizar_dominio(url_cliente or "x"))
    nome_arq = f"mencoes_{base}_{datetime.now(FUSO):%Y%m%d_%H%M}"
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        vis[colunas].to_excel(xw, index=False, sheet_name="Menções")
        agg = dict(dr=("dr", "max"), urls=("url", "count"),
                   status=("status", lambda s: " | ".join(sorted(set(s)))))
        for c in ("emails", "emails_veiculo_hunter", "whatsapp", "telefones", "redes_sociais"):
            if c in df.columns:
                agg[c] = (c, "first")
        (df.groupby("dominio").agg(**agg).reset_index()
           .sort_values("dr", ascending=False, na_position="last")
           .to_excel(xw, index=False, sheet_name="Por domínio"))
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(
                    60, max(10, max(len(str(c.value or "")) for c in col[:50]) + 2))
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Baixar Excel", buf.getvalue(), f"{nome_arq}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    d2.download_button("⬇️ Baixar CSV", vis[colunas].to_csv(index=False).encode("utf-8-sig"),
                       f"{nome_arq}.csv", "text/csv")


def mostrar_mencoes(df: pd.DataFrame | None, historico: bool, cid: int | None = None):
    for aviso in st.session_state.get("avisos", []) or []:
        st.warning(aviso)
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
        st.info("Nenhuma menção ainda. Clique em **Buscar menções**." if historico
                else "Nenhuma menção encontrada com esses termos.")
        return
    df = preparar(df, historico, ts)

    m = st.columns(7)
    m[0].metric("URLs", len(df))
    m[1].metric("Backlink dofollow", int((df["status"] == core.ST_DOFOLLOW).sum()))
    m[2].metric("Backlink nofollow", int((df["status"] == core.ST_NOFOLLOW).sum()))
    m[3].metric("Sem link (oportunidade)", int((df["status"] == core.ST_SEM_LINK).sum()))
    m[4].metric("Links quebrados", int((df["status"] == core.ST_QUEBRADO).sum()))
    m[5].metric("Em comunidades", int((df["status"] == core.ST_COMUNIDADE).sum()),
                delta=(f"{int((df.get('sentimento') == 'negativa').sum())} negativa(s)"
                       if "sentimento" in df.columns and (df["sentimento"] == "negativa").any() else None),
                delta_color="inverse")
    m[6].metric("Prospects (concorrentes)", int((df["status"] == core.ST_PROSPECT).sum()))

    if historico:
        mo = storage.metricas_outreach(cid)
        o = st.columns(4)
        o[0].metric("Contatados", mo["contatados"])
        o[1].metric("Responderam", mo["responderam"])
        o[2].metric("Links conquistados", mo["conquistados"])
        o[3].metric("Conversão do outreach", f"{mo['taxa']:.0%}" if mo["taxa"] is not None else "–")

    f1, f2, f3, f4, f5 = st.columns([2.2, 0.8, 1.2, 1, 1])
    status_opts = sorted(df["status"].dropna().unique())
    padrao = [s for s in status_opts if s != core.ST_NAO_ENCONTRADO]
    filtro_status = f1.multiselect("Status", status_opts, default=padrao)
    dr_min = f2.number_input("DR mínimo", 0, 100, 0)
    sent_opts = [s for s in ("negativa", "mista", "neutra", "positiva")
                 if "sentimento" in df.columns and (df["sentimento"] == s).any()]
    filtro_sent = f3.multiselect("Sentimento (comunidades)", sent_opts, placeholder="Todos")
    so_contato = f4.checkbox("Só com email ou WhatsApp")
    so_novas = f5.checkbox("Só novidades", disabled=not historico or ts is None)

    vis = df[df["status"].isin(filtro_status)]
    if dr_min:
        vis = vis[vis["dr"].fillna(-1) >= dr_min]
    if filtro_sent:
        vis = vis[vis["sentimento"].isin(filtro_sent)]
    if so_contato:
        cols_ct = [c for c in ("emails", "whatsapp", "autor_email", "hunter_email_autor",
                               "emails_veiculo_hunter") if c in vis.columns]
        if cols_ct:
            vis = vis[(vis[cols_ct].fillna("").astype(str) != "").any(axis=1)]
    if so_novas and historico:
        vis = vis[vis["novidade"] != ""]
    vis = vis.reset_index(drop=True)
    colunas = [c for c in COLUNAS if c in vis.columns]
    for c in colunas:
        if not (pd.api.types.is_numeric_dtype(vis[c]) or pd.api.types.is_datetime64_any_dtype(vis[c])):
            vis[c] = vis[c].astype(object).where(vis[c].notna(), "").replace({"None": "", "nan": ""})

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

    exportar(vis, df, colunas)


# ---------------- Evolução ----------------
def aba_evolucao(cid: int):
    dados = storage.evolucao_mensal(cid)
    if not dados:
        st.info("Ainda não há histórico suficiente. O gráfico aparece depois das primeiras buscas.")
        return
    ev = pd.DataFrame(dados).set_index("mes")
    st.markdown("##### Backlinks ativos no fim de cada mês")
    st.line_chart(ev[["backlinks_ativos"]].rename(columns={"backlinks_ativos": "Backlinks ativos"}),
                  color=CORES[0], y_label="Backlinks", x_label="Mês")
    st.markdown("##### Movimento do mês")
    mov = ev[["mencoes_novas", "links_ganhos", "links_perdidos"]].rename(columns={
        "mencoes_novas": "Menções novas", "links_ganhos": "Links ganhos", "links_perdidos": "Links perdidos"})
    st.bar_chart(mov, color=CORES, stack=False, y_label="Quantidade", x_label="Mês")
    with st.expander("Ver tabela"):
        st.dataframe(ev.rename(columns={"mencoes_novas": "Menções novas", "links_ganhos": "Links ganhos",
                                        "links_perdidos": "Links perdidos",
                                        "backlinks_ativos": "Backlinks ativos"}), width="stretch")
    cm = storage.creditos_no_mes(cid)
    st.caption(f"Créditos deste cliente no mês: Serper {cm['serper']} · Hunter {cm['hunter']} · "
               f"{cm['execucoes']} busca(s).")


# ---------------- Ignorados ----------------
def aba_ignorados(cid: int):
    st.write("URLs e domínios ignorados não aparecem na tabela, nos emails nem nas próximas buscas.")
    itens = storage.listar_ignorados(cid)
    if not itens:
        st.caption("Nada ignorado ainda. Use a seleção de linhas na aba de menções.")
    for it in itens:
        c1, c2, c3 = st.columns([1, 5, 1])
        c1.write("Domínio" if it["tipo"] == "dominio" else "URL")
        c2.write(it["valor"])
        if c3.button("Restaurar", key=f"rest_{it['id']}"):
            storage.restaurar_ignorado(it["id"])
            st.rerun()
    with st.form("ignorar_manual", clear_on_submit=True):
        g1, g2, g3 = st.columns([1, 4, 1])
        tipo = g1.selectbox("Tipo", ["dominio", "url"], format_func=lambda t: "Domínio" if t == "dominio" else "URL")
        valor = g2.text_input("Adicionar manualmente", placeholder="exemplo.com.br ou URL completa")
        g3.write("")
        if g3.form_submit_button("Ignorar") and valor.strip():
            storage.ignorar(cid, tipo, [core.normalizar_dominio(valor) if tipo == "dominio" else valor.strip()])
            st.rerun()


# ---------------- Alertas por email ----------------
def aba_alertas(cid: int):
    cliente = storage.obter_cliente(cid)
    st.subheader(f"Relatório automático de {cliente['nome']}")
    st.write("O robô roda toda segunda de manhã. Ele faz uma nova busca, reverifica as menções salvas e "
             "manda para cada email as novidades desde o último envio. Se houver menção negativa em "
             "comunidade, o assunto do email começa com ⚠️ NEGATIVA.")
    if not storage.usando_banco_externo():
        st.error("Configure DATABASE_URL nos Secrets. Sem banco externo, o robô não enxerga os clientes.")
    if not relatorio.smtp_configurado():
        st.warning("Envio de email não configurado (SMTP_USUARIO e SMTP_SENHA nos Secrets).")

    col_a, col_b, col_c = st.columns([1.5, 1.5, 1])
    col_a.selectbox("Período das buscas automáticas", ["Última semana", "Último mês"],
                    key="cfg_periodo_monitoramento")
    col_b.slider("Páginas do Google nas buscas automáticas", 1, 5, key="cfg_paginas_monitoramento",
                 help="Como a busca é só do último mês, 1 ou 2 páginas costumam bastar.")
    col_c.write("")
    if col_c.button("Salvar"):
        storage.salvar_cliente(cliente["nome"], cliente["url"], cliente["termos"], config_atual(), cid)
        st.toast("Configuração do monitoramento salva.")

    st.markdown("##### Emails cadastrados")
    inscr = storage.listar_inscricoes(cid)
    if not inscr:
        st.caption("Nenhum email cadastrado ainda.")
    for i in inscr:
        prox = (i["ultimo_envio"] + timedelta(days=i["frequencia_dias"])) if i["ultimo_envio"] else None
        c1, c2, c3, c4, c5 = st.columns([2.2, 1, 1.4, 1, 0.8])
        c1.write(f"**{i['email']}**")
        c2.write(FREQ_INV.get(i["frequencia_dias"], f"{i['frequencia_dias']} dias"))
        c3.write(f"Último envio: {fmt_data(i['ultimo_envio']) or 'ainda não'}"
                 + (f"<br>Próximo: a partir de {fmt_data(prox)}" if prox else "<br>Próximo: na próxima segunda"),
                 unsafe_allow_html=True)
        if c4.button("Enviar prévia", key=f"prev_{i['id']}", disabled=not relatorio.smtp_configurado()):
            desde = storage.agora() - timedelta(days=i["frequencia_dias"])
            try:
                assunto, corpo = relatorio.montar(cliente, storage.novidades(cid, desde), desde, storage.agora())
                relatorio.enviar(i["email"], "[Prévia] " + assunto, corpo)
                st.toast(f"Prévia enviada para {i['email']}.")
            except Exception as e:
                st.error(f"Falha ao enviar: {e}")
        if c5.button("Remover", key=f"rm_{i['id']}"):
            storage.remover_inscricao(i["id"])
            st.rerun()

    with st.form("nova_inscricao", clear_on_submit=True):
        f1, f2, f3 = st.columns([2.5, 1, 1])
        email = f1.text_input("Adicionar email", placeholder="nome@empresa.com")
        freq = f2.selectbox("Frequência", list(FREQUENCIAS), index=0)
        f3.write("")
        if f3.form_submit_button("Adicionar", type="primary"):
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()):
                st.error("Email inválido.")
            else:
                storage.adicionar_inscricao(cid, email, FREQUENCIAS[freq])
                st.rerun()

    with st.expander("Ver como fica o email (últimos 14 dias)"):
        desde = storage.agora() - timedelta(days=14)
        assunto, corpo = relatorio.montar(cliente, storage.novidades(cid, desde), desde, storage.agora())
        st.caption(f"Assunto: {assunto}")
        st.html(corpo)


# ---------------- Exibição ----------------
if cid != NOVO and not erro_banco:
    aba1, aba2, aba3, aba4 = st.tabs(["📋 Menções (histórico)", "📈 Evolução", "✉️ Alertas por email",
                                      "🚫 Ignorados"])
    with aba1:
        dados = storage.mencoes_do_cliente(cid)
        mostrar_mencoes(pd.DataFrame(dados) if dados else None, historico=True, cid=cid)
    with aba2:
        aba_evolucao(cid)
    with aba3:
        aba_alertas(cid)
    with aba4:
        aba_ignorados(cid)
else:
    df = st.session_state.get("resultado")
    if df is not None:
        if not df.empty:
            st.info("Busca avulsa. Dê um nome e clique em **Salvar cliente** para guardar estas menções "
                    "no histórico e ativar alertas por email.")
        mostrar_mencoes(df, historico=False)
