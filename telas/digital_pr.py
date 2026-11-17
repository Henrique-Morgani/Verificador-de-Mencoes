"""Digital PR: campanhas com termos e páginas próprias, cobertura, status do link e mailing."""

from datetime import date

import pandas as pd
import streamlit as st

import pr
import storage
from comum import CONFIG_COLUNAS, baixar_excel, chaves, exigir_cliente, fmt_data, limpar_para_tabela, \
    progresso_streamlit

STATUS_MAILING = ["Enviado", "Abriu", "Respondeu", "Publicou", "Recusou", "Sem retorno"]
ICONE = {pr.LINKOU_CAMPANHA: "🟢", pr.LINKOU_SITE: "🔵", pr.SEM_LINK: "🟠", pr.QUEBRADO: "🔴",
         pr.NAO_RESOLVIDA: "⚪"}


def _linhas(txt):
    return [t.strip() for t in (txt or "").splitlines() if t.strip()]


def _form_campanha(cli, camp=None):
    s = f"_{camp['id'] if camp else 'nova'}"
    with st.form("camp" + s, clear_on_submit=camp is None):
        a, b, c = st.columns([2, 1, 1])
        nome = a.text_input("Nome da campanha", value=(camp or {}).get("nome", ""), key="cn" + s,
                            placeholder="Ex.: Estudo Preço do Carro Limpo 2026")
        lanc = b.date_input("Lançamento", value=date.fromisoformat(camp["lancamento"]) if camp and camp.get(
            "lancamento") else date.today(), format="DD/MM/YYYY", key="cl" + s)
        dias = c.number_input("Dias de alerta diário", 1, 60, int((camp or {}).get("dias_alerta") or 14), key="cd" + s,
                              help="Nos primeiros dias depois do lançamento o robô busca todo dia e manda email "
                                   "quando sai matéria nova. Depois, passa para semanal.")
        t1, t2 = st.columns(2)
        termos = t1.text_area("Termos da campanha (um por linha)", "\n".join((camp or {}).get("termos", [])),
                              height=120, key="ct" + s,
                              help="Nome do estudo, dado marcante, porta-voz. Use termos específicos da campanha, "
                                   "não só a marca.", placeholder="\"Preço do Carro Limpo\"\n68% dos motoristas")
        paginas = t2.text_area("Página(s) da campanha no site do cliente", "\n".join((camp or {}).get("paginas", [])),
                               height=120, key="cp" + s,
                               help="Post do blog, sala de imprensa ou landing page do estudo. É o link que "
                                    "queremos nas matérias.", placeholder="https://cliente.com.br/estudos/preco-carro-limpo")
        status = st.radio("Status", ["ativa", "rascunho", "encerrada"], horizontal=True, key="cs" + s,
                          index=["ativa", "rascunho", "encerrada"].index((camp or {}).get("status") or "ativa"))
        ok = st.form_submit_button("💾 Salvar campanha", type="primary")
    if ok:
        if not (nome.strip() and _linhas(termos)):
            st.error("Dê um nome e pelo menos um termo para a campanha.")
            return None
        if not _linhas(paginas):
            st.warning("Sem página da campanha, o app só consegue dizer se linkou para o site, não para o estudo.")
        cid = storage.salvar_campanha(cli["id"], nome, lanc.isoformat(), _linhas(termos), _linhas(paginas),
                                      status, dias, camp["id"] if camp else None)
        st.session_state["_camp_ir"] = cid
        st.rerun()
    return None


def _kpis(ind):
    c = st.columns(6)
    c[0].metric("Matérias", ind["materias"])
    c[1].metric("Linkaram para a campanha", ind["campanha"])
    c[2].metric("Linkaram só para o site", ind["site"])
    c[3].metric("Citaram sem link", ind["sem_link"])
    c[4].metric("Link quebrado", ind["quebrado"])
    c[5].metric("DR médio", ind["dr_medio"] if ind["dr_medio"] is not None else "–")
    if ind["abordados"]:
        m = st.columns(4)
        m[0].metric("Jornalistas abordados", ind["abordados"])
        m[1].metric("Responderam", ind["responderam"])
        m[2].metric("Publicaram", ind["publicaram"],
                    delta=f"{ind['publicaram'] / ind['abordados']:.0%} de conversão" if ind["abordados"] else None)
        m[3].metric("Matérias espontâneas", ind["espontaneas"], help="Saíram em veículos fora do mailing.")


def _cobertura(camp, cob):
    if not cob:
        st.info("Nenhuma matéria ainda. Clique em **Buscar cobertura agora**.")
        return
    df = pd.DataFrame(cob)
    df["status_vis"] = df["status_campanha"].map(lambda s: f"{ICONE.get(s, '')} {s}")
    df["encontrada_em"] = df["primeira_vez"].map(fmt_data)
    df["ordem"] = df["status_campanha"].map(lambda s: pr.ORDEM.get(s, 9))
    df = df.sort_values(["ordem", "dr"], ascending=[True, False], na_position="last").reset_index(drop=True)
    cols = ["status_vis", "dominio", "dr", "url", "titulo", "encontrada_em", "outreach_status", "outreach_obs",
            "urls_linkadas", "anchors", "rel", "autor", "autor_email", "autor_linkedin", "emails", "publicado_em",
            "fonte"]
    df = limpar_para_tabela(df, cols)
    ev = st.dataframe(df[cols], hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row",
                      key=f"cob_{camp['id']}",
                      column_config={**CONFIG_COLUNAS, "status_vis": st.column_config.TextColumn("Status do link")})
    st.caption("Domain Rating by Ahrefs (https://ahrefs.com/)")
    sel = df.iloc[ev.selection.rows] if ev and ev.selection.rows else df.iloc[0:0]
    with st.container(border=True):
        if sel.empty:
            st.caption("Selecione matérias para registrar o pedido de link (ex.: citou sem link, linkou só para "
                       "a home). Quando o link para a campanha aparecer, o status vira Link conquistado sozinho.")
        else:
            a, b, c = st.columns([1.2, 2, 1])
            stt = a.selectbox("Outreach", storage.OUTREACH_OPCOES, index=1, key=f"cobst_{camp['id']}")
            obs = b.text_input("Observação", key=f"cobobs_{camp['id']}")
            c.write("")
            if c.button("Aplicar", type="primary", key=f"cobap_{camp['id']}"):
                storage.outreach_cobertura(camp["id"], sel["url"].tolist(), stt, obs)
                st.rerun()
    baixar_excel({"Cobertura": df[cols].rename(columns={"status_vis": "Status do link"})},
                 f"cobertura_{camp['nome']}", chave=f"xl_{camp['id']}")


def _dia_a_dia(camp, cob):
    if not cob:
        st.caption("O gráfico aparece quando houver matérias.")
        return
    df = pd.DataFrame(cob)
    df["dia"] = pd.to_datetime(df["primeira_vez"].map(lambda d: d.date() if d is not None else None))
    tab = df.pivot_table(index="dia", columns="status_campanha", aggfunc="size", fill_value=0)
    ordem = [s for s in (pr.LINKOU_CAMPANHA, pr.LINKOU_SITE, pr.SEM_LINK, pr.QUEBRADO, pr.NAO_RESOLVIDA)
             if s in tab.columns]
    cores = {pr.LINKOU_CAMPANHA: "#1baf7a", pr.LINKOU_SITE: "#2a78d6", pr.SEM_LINK: "#eb6834",
             pr.QUEBRADO: "#d64545", pr.NAO_RESOLVIDA: "#9aa4b2"}
    st.markdown("##### Matérias encontradas por dia")
    st.bar_chart(tab[ordem], color=[cores[s] for s in ordem], stack=True, x_label="Dia", y_label="Matérias")
    st.caption("A data é a do primeiro dia em que o DizemAI encontrou a matéria.")


def _mailing(camp):
    st.write("Cole ou digite a lista de jornalistas abordados. O domínio do veículo é o que cruza com a "
             "cobertura (ex.: g1.globo.com).")
    lista = storage.listar_mailing(camp["id"])
    df = pd.DataFrame(lista or [], columns=["jornalista", "veiculo", "dominio", "email", "status", "obs"])
    ed = st.data_editor(
        df[["jornalista", "veiculo", "dominio", "email", "status", "obs"]], num_rows="dynamic", width="stretch",
        hide_index=True, key=f"mail_{camp['id']}",
        column_config={"jornalista": "Jornalista", "veiculo": "Veículo", "dominio": "Domínio do veículo",
                       "email": "Email", "obs": "Obs.",
                       "status": st.column_config.SelectboxColumn("Status", options=STATUS_MAILING, default="Enviado")})
    a, b = st.columns(2)
    if a.button("💾 Salvar mailing", type="primary", key=f"mailsv_{camp['id']}"):
        storage.salvar_mailing(camp["id"], ed.fillna("").to_dict("records"))
        st.toast("Mailing salvo.")
        st.rerun()
    if b.button("🔁 Cruzar com a cobertura", key=f"mailcz_{camp['id']}",
                help="Marca como Publicou quem está no mailing e apareceu na cobertura."):
        n = pr.cruzar_mailing(camp["id"])
        st.toast(f"{n} jornalista(s) marcado(s) como Publicou.")
        st.rerun()


def _paginas(camp):
    if not camp["paginas"]:
        st.info("Nenhuma página da campanha cadastrada.")
        return
    stt = camp.get("paginas_status") or {}
    for p in camp["paginas"]:
        cod, final = (stt.get(p) or [None, ""])[:2]
        if cod is None:
            st.write(f"⬜ {p} · ainda não verificada")
        elif 200 <= int(cod) < 400:
            extra = f" (redireciona para {final})" if final and final.rstrip("/") != p.rstrip("/") else ""
            st.write(f"✅ {p} · HTTP {cod}{extra}")
        else:
            st.write(f"🔴 {p} · HTTP {cod}. As matérias estão linkando para uma página fora do ar.")
    st.caption("Verificada a cada busca de cobertura.")


def tela():
    cli = exigir_cliente()
    st.title(f"📣 Digital PR · {cli['nome']}")
    camps = storage.listar_campanhas(cli["id"])
    opcoes = [0] + [c["id"] for c in camps]
    nomes = {0: "➕ Nova campanha", **{c["id"]: f"{c['nome']} ({c['status']})" for c in camps}}
    if "_camp_ir" in st.session_state:
        st.session_state["camp_sel"] = st.session_state.pop("_camp_ir")
    if st.session_state.get("camp_sel") not in opcoes:
        st.session_state["camp_sel"] = opcoes[1] if len(opcoes) > 1 else 0
    sel = st.selectbox("Campanha", opcoes, format_func=lambda i: nomes[i], key="camp_sel")

    if sel == 0:
        st.caption("Cada campanha tem termos próprios e a página do estudo no site (post, sala de imprensa ou LP). "
                   "O DizemAI busca a cobertura desde o lançamento e diz se cada matéria linkou para a campanha, "
                   "só para o site, citou sem link ou linkou para uma página quebrada.")
        _form_campanha(cli)
        return

    camp = storage.obter_campanha(sel)
    cob = storage.cobertura_da_campanha(camp["id"])
    mailing = storage.listar_mailing(camp["id"])
    janela = pr.em_janela_de_alerta(camp)
    st.caption(f"Lançamento {date.fromisoformat(camp['lancamento']).strftime('%d/%m/%Y') if camp.get('lancamento') else '?'}"
               f" · última busca {fmt_data(camp.get('ultima_busca'), True) or 'ainda não'}"
               + (" · 🔔 em alerta diário" if janela else ""))
    b1, _ = st.columns([1, 4])
    if b1.button("🔎 Buscar cobertura agora", type="primary", disabled=not chaves()["serper"]):
        try:
            resumo, avisos = pr.rodar_campanha(camp, cli, chaves(), progresso=progresso_streamlit())
            st.session_state[f"camp_avisos_{camp['id']}"] = avisos + [
                f"{resumo['novas']} matéria(s) nova(s), {resumo['mudaram']} mudaram de status. "
                f"Créditos Serper: {resumo.get('creditos_serper', 0)}."]
            st.rerun()
        except Exception as e:
            st.error(f"Erro na busca: {e}")
    for a in st.session_state.get(f"camp_avisos_{camp['id']}", []):
        st.info(a)

    _kpis(pr.indicadores(cob, mailing))
    t1, t2, t3, t4, t5 = st.tabs(["📰 Cobertura", "📈 Dia a dia", "📇 Mailing", "🩺 Páginas da campanha", "⚙️ Editar"])
    with t1:
        _cobertura(camp, cob)
    with t2:
        _dia_a_dia(camp, cob)
    with t3:
        _mailing(camp)
    with t4:
        _paginas(camp)
    with t5:
        _form_campanha(cli, camp)
        with st.popover("🗑️ Excluir campanha"):
            st.write("Excluir a campanha, a cobertura e o mailing?")
            if st.button("Confirmar exclusão", type="primary", key=f"excamp_{camp['id']}"):
                storage.excluir_campanha(camp["id"])
                st.session_state["_camp_ir"] = None
                st.rerun()
