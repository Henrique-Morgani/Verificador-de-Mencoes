import io
import os
import re
from datetime import datetime, timedelta, timezone
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


# Repassa os segredos para os módulos de banco e email
for _k in ("DATABASE_URL", "SMTP_USUARIO", "SMTP_SENHA", "SMTP_HOST", "SMTP_PORTA",
           "SMTP_REMETENTE", "APP_URL"):
    _v = segredo(_k)
    if _v:
        os.environ[_k] = _v

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

# ---------------- Configuração padrão e carregamento de clientes ----------------
PERIODOS = {"Qualquer data": "", "Últimas 24h": "d", "Última semana": "w", "Último mês": "m", "Último ano": "y"}
PERIODOS_INV = {v: k for k, v in PERIODOS.items()}
FREQUENCIAS = {"Quinzenal": 14, "Semanal": 7, "Mensal": 30}
FREQ_INV = {v: k for k, v in FREQUENCIAS.items()}
NOVO = 0

PADRAO = {
    "pais": "br", "idioma": "pt-br", "periodo": "", "paginas": 3, "incluir_noticias": True,
    "puxar_dr": True, "puxar_contatos": True, "puxar_autor": True, "perfis_google": True,
    "hunter_autor": False, "hunter_veiculo": False, "so_oportunidades": True,
    "excluir": core.EXCLUIR_PADRAO, "periodo_monitoramento": "m",
}


def aplicar_config(cfg: dict):
    c = {**PADRAO, **(cfg or {})}
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


def config_atual() -> dict:
    ss = st.session_state
    return {
        "pais": ss["cfg_pais"], "idioma": ss["cfg_idioma"], "periodo": PERIODOS[ss["cfg_periodo"]],
        "paginas": ss["cfg_paginas"], "incluir_noticias": ss["cfg_incluir_noticias"],
        "puxar_dr": ss["cfg_puxar_dr"], "puxar_contatos": ss["cfg_puxar_contatos"],
        "puxar_autor": ss["cfg_puxar_autor"], "perfis_google": ss["cfg_perfis_google"],
        "hunter_autor": ss["cfg_hunter_autor"], "hunter_veiculo": ss["cfg_hunter_veiculo"],
        "so_oportunidades": ss["cfg_so_oportunidades"],
        "excluir": [d.strip() for d in ss["cfg_excluir"].splitlines() if d.strip()],
        "periodo_monitoramento": PERIODOS[ss["cfg_periodo_monitoramento"]],
    }


def carregar_cliente():
    cid = st.session_state.get("cliente_sel", NOVO)
    st.session_state.pop("resultado", None)
    st.session_state.pop("ts_execucao", None)
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
# Troca de cliente pedida por um botão (precisa acontecer antes de desenhar os campos)
if "_ir_para" in st.session_state:
    st.session_state["cliente_sel"] = st.session_state.pop("_ir_para")
    carregar_cliente()
for _k in ("nome_cliente", "url_cliente", "termos_txt"):
    st.session_state.setdefault(_k, "")

try:
    lista_clientes = storage.listar_clientes()
    erro_banco = ""
except Exception as e:  # banco fora do ar ou URL errada
    lista_clientes, erro_banco = [], str(e)

st.title("🔎 Verificador de Menções")
st.caption("Encontre menções ao cliente, veja quem já linka, quem não linka e como entrar em contato.")
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
    if not serper_key:
        serper_key = st.text_input("Serper.dev (busca Google)", type="password",
                                   help="Crie em serper.dev. A conta gratuita vem com 2.500 buscas.")
    if not ahrefs_key:
        ahrefs_key = st.text_input("Ahrefs API v3 (para o DR)", type="password",
                                   help="Endpoint gratuito, não gasta unidades. Conta gratuita serve: "
                                        "Account settings > API keys.")
    if not hunter_key:
        hunter_key = st.text_input("Hunter.io (opcional, emails de jornalistas)", type="password",
                                   help="Plano grátis com créditos mensais.")

    st.header("Busca")
    st.selectbox("País do Google", ["br", "pt", "mx", "co", "ar", "us", "es"], key="cfg_pais")
    st.selectbox("Idioma", ["pt-br", "pt", "es", "en"], key="cfg_idioma")
    st.selectbox("Período", list(PERIODOS), key="cfg_periodo")
    st.slider("Páginas do Google por termo", 1, 10, key="cfg_paginas",
              help="Cada página = 10 resultados = 1 crédito do Serper.")
    st.checkbox("Incluir Google Notícias", key="cfg_incluir_noticias")

    st.header("O que puxar")
    st.checkbox("DR (Ahrefs)", key="cfg_puxar_dr")
    st.checkbox("Contatos do site (email, WhatsApp, redes, formulário)", key="cfg_puxar_contatos")

    st.header("Jornalista / autor")
    st.checkbox("Identificar autor da matéria e sua página", key="cfg_puxar_autor",
                help="Grátis. Lê o nome do autor e a página de autor do próprio site.")
    st.checkbox("Buscar LinkedIn, X e Muck Rack do autor no Google", key="cfg_perfis_google",
                help="Gasta 1 crédito do Serper por autor novo.")
    st.checkbox("Hunter: descobrir email do autor", key="cfg_hunter_autor", disabled=not hunter_key,
                help="1 crédito do Hunter por autor novo.")
    st.checkbox("Hunter: emails da redação do veículo", key="cfg_hunter_veiculo", disabled=not hunter_key,
                help="1 crédito do Hunter por domínio novo.")
    st.checkbox("Gastar créditos só com oportunidades", key="cfg_so_oportunidades",
                help="Google e Hunter só para menções sem link ou com link nofollow.")
    st.text_area("Domínios a excluir (um por linha)", key="cfg_excluir", height=180)

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

if termos and serper_key:
    custo = len(termos) * cfg["paginas"] * (2 if cfg["incluir_noticias"] else 1)
    extra = " + 1 por autor novo" if (cfg["puxar_autor"] and cfg["perfis_google"]) else ""
    st.caption(f"Estimativa: até {custo} créditos do Serper na busca{extra}.")

b1, b2, b3, b4 = st.columns([1.2, 1.2, 1.4, 1])
rodar = b1.button("🔎 Buscar menções", type="primary", disabled=not (url_cliente and termos and serper_key))
salvar = b2.button("💾 Salvar cliente" if cid == NOVO else "💾 Salvar alterações",
                   disabled=bool(erro_banco) or not (st.session_state["nome_cliente"].strip() and url_cliente and termos))
reverificar = b3.checkbox("Reverificar menções salvas", value=True, disabled=cid == NOVO,
                          help="Abre de novo as páginas já guardadas para ver se ganharam ou perderam link. "
                               "Não gasta créditos.")
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
        # Se havia uma busca avulsa na tela, guarda no histórico do novo cliente
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
        conhecidas = storage.urls_do_cliente(cid) if cid != NOVO else []
        inicio = storage.agora()
        linhas, avisos = core.executar(
            url_cliente=url_cliente, termos=termos, serper_key=serper_key, ahrefs_key=ahrefs_key,
            hunter_key=hunter_key, pais=cfg["pais"], idioma=cfg["idioma"], paginas=cfg["paginas"],
            periodo=cfg["periodo"], incluir_noticias=cfg["incluir_noticias"], excluir=cfg["excluir"],
            puxar_dr=cfg["puxar_dr"], puxar_contatos=cfg["puxar_contatos"], puxar_autor=cfg["puxar_autor"],
            perfis_google=cfg["perfis_google"], hunter_autor=cfg["hunter_autor"] and bool(hunter_key),
            hunter_veiculo=cfg["hunter_veiculo"] and bool(hunter_key),
            so_oportunidades=cfg["so_oportunidades"],
            urls_extras=conhecidas if reverificar else None, urls_conhecidas=set(conhecidas),
            progresso=progresso,
        )
        st.session_state["avisos"] = avisos
        if cid != NOVO:
            res = storage.salvar_resultados(cid, linhas, inicio)
            st.session_state["ts_execucao"] = inicio
            st.session_state["resumo_execucao"] = res
        else:
            st.session_state["resultado"] = pd.DataFrame(linhas)
    except Exception as e:
        st.error(f"Erro: {e}")


# ---------------- Tabela de menções ----------------
def fmt_data(d):
    if d is None or (isinstance(d, float) and pd.isna(d)) or d is pd.NaT:
        return ""
    if isinstance(d, str):
        return d
    return d.astimezone(FUSO).strftime("%d/%m/%Y")


def mostrar_mencoes(df: pd.DataFrame, historico: bool):
    if df is None or df.empty:
        st.info("Nenhuma menção ainda. Clique em **Buscar menções**." if historico
                else "Nenhuma menção encontrada com esses termos.")
        return
    for aviso in st.session_state.get("avisos", []):
        st.warning(aviso)

    ts = st.session_state.get("ts_execucao")
    if historico:
        def novidade(r):
            if ts is None:
                return ""
            if r["primeira_vez"] is not None and r["primeira_vez"] >= ts:
                return "🆕 Nova"
            if r["link_desde"] is not None and r["link_desde"] >= ts:
                return "🔗 Ganhou link"
            if r["perdeu_link_em"] is not None and r["perdeu_link_em"] >= ts:
                return "⚠️ Perdeu link"
            return ""
        df = df.copy()
        df["novidade"] = df.apply(novidade, axis=1)
        df["encontrada_em"] = df["primeira_vez"].map(fmt_data)
        df["link_desde_dt"] = df["link_desde"].map(fmt_data)
        df["perdeu_link_dt"] = df["perdeu_link_em"].map(fmt_data)
        res = st.session_state.get("resumo_execucao")
        if res and ts is not None:
            st.success(f"Busca concluída: {res['novas']} menção(ões) nova(s), {res['novos_links']} backlink(s) "
                       f"novo(s), {res['links_perdidos']} link(s) perdido(s).")

    m = st.columns(6 if historico else 5)
    m[0].metric("URLs", len(df))
    m[1].metric("Domínios", df["dominio"].nunique())
    m[2].metric("Backlink dofollow", int((df["status"] == "Com backlink dofollow").sum()))
    m[3].metric("Backlink nofollow", int((df["status"] == "Com backlink nofollow/sponsored/ugc").sum()))
    m[4].metric("Sem link (oportunidade)", int((df["status"] == "Menção sem link (oportunidade)").sum()))
    if historico:
        m[5].metric("Novidades na última busca", int((df["novidade"] != "").sum()))

    f1, f2, f3, f4 = st.columns([2, 1, 1, 1])
    status_opts = sorted(df["status"].dropna().unique())
    padrao = [s for s in status_opts if s != "Termo não encontrado na página"]
    filtro_status = f1.multiselect("Status", status_opts, default=padrao)
    dr_min = f2.number_input("DR mínimo", 0, 100, 0)
    so_contato = f3.checkbox("Só com email ou WhatsApp")
    so_novas = f4.checkbox("Só novidades da última busca", disabled=not historico or ts is None)

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

    colunas = [c for c in [
        "novidade", "status", "dominio", "dr", "url", "titulo", "encontrada_em", "link_desde_dt",
        "perdeu_link_dt", "termos_encontrados", "anchors", "rel",
        "autor", "autor_email", "hunter_email_autor", "hunter_confianca", "hunter_cargo_autor",
        "autor_linkedin", "autor_x", "autor_instagram", "autor_muckrack", "autor_pagina",
        "buscar_autor_linkedin", "buscar_autor_muckrack",
        "emails", "emails_veiculo_hunter", "telefones", "whatsapp", "redes_sociais",
        "tem_formulario", "paginas_contato",
        "publicado_em", "data_google", "trecho_mencao", "urls_linkadas", "fonte",
    ] if c in vis.columns]

    st.dataframe(
        vis[colunas], width="stretch", hide_index=True,
        column_config={
            "novidade": st.column_config.TextColumn("Novidade"),
            "encontrada_em": st.column_config.TextColumn("Encontrada em"),
            "link_desde_dt": st.column_config.TextColumn("Link desde"),
            "perdeu_link_dt": st.column_config.TextColumn("Perdeu link em"),
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
    st.caption("Domain Rating by Ahrefs (https://ahrefs.com/)")

    base = re.sub(r"[^\w-]", "_", st.session_state.get("nome_cliente") or core.normalizar_dominio(url_cliente or "x"))
    nome_arq = f"mencoes_{base}_{datetime.now(FUSO):%Y%m%d_%H%M}"
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        vis[colunas].to_excel(xw, index=False, sheet_name="Menções")
        agg = dict(dr=("dr", "max"), urls=("url", "count"),
                   status=("status", lambda s: " | ".join(sorted(set(s)))))
        if "links_dofollow" in df.columns:
            agg["urls_com_dofollow"] = ("links_dofollow", lambda s: int((pd.to_numeric(s, errors="coerce") > 0).sum()))
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


# ---------------- Alertas por email ----------------
def aba_alertas(cid: int):
    cliente = storage.obter_cliente(cid)
    st.subheader(f"Relatório automático de {cliente['nome']}")
    st.write("O robô roda toda segunda de manhã. Ele faz uma nova busca, reverifica as menções salvas e "
             "manda para cada email as novidades desde o último envio: backlinks novos, menções sem link "
             "e links perdidos.")
    if not storage.usando_banco_externo():
        st.error("Configure DATABASE_URL nos Secrets. Sem banco externo, o robô não enxerga os clientes.")
    if not relatorio.smtp_configurado():
        st.warning("Envio de email não configurado (SMTP_USUARIO e SMTP_SENHA nos Secrets). "
                   "Você pode cadastrar os emails agora, mas a prévia não será enviada.")

    col_a, col_b = st.columns([2, 1])
    col_a.selectbox("Período das buscas automáticas", ["Última semana", "Último mês"],
                    key="cfg_periodo_monitoramento",
                    help="Último mês cobre bem o envio quinzenal com folga.")
    if col_b.button("Salvar período"):
        storage.salvar_cliente(cliente["nome"], cliente["url"], cliente["termos"], config_atual(), cid)
        st.toast("Período salvo.")

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
        enviado = f3.form_submit_button("Adicionar", type="primary")
        if enviado:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()):
                st.error("Email inválido.")
            else:
                storage.adicionar_inscricao(cid, email, FREQUENCIAS[freq])
                st.rerun()

    with st.expander("Ver como fica o email (últimos 14 dias)"):
        desde = storage.agora() - timedelta(days=14)
        _, corpo = relatorio.montar(cliente, storage.novidades(cid, desde), desde, storage.agora())
        st.html(corpo)


# ---------------- Exibição ----------------
if cid != NOVO and not erro_banco:
    aba1, aba2 = st.tabs(["📋 Menções (histórico)", "✉️ Alertas por email"])
    with aba1:
        dados = storage.mencoes_do_cliente(cid)
        mostrar_mencoes(pd.DataFrame(dados) if dados else None, historico=True)
    with aba2:
        aba_alertas(cid)
else:
    df = st.session_state.get("resultado")
    if df is not None:
        if not df.empty:
            st.info("Busca avulsa. Dê um nome e clique em **Salvar cliente** para guardar estas menções "
                    "no histórico e ativar alertas por email.")
        mostrar_mencoes(df, historico=False)
