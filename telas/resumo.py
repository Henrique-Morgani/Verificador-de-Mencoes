"""Resumo do cliente: big numbers, positivos, pontos de atenção, atualizações e próximas ações."""

from datetime import timedelta

import streamlit as st

import core
import ia
import pr
import storage
from comum import delta_dr, exigir_cliente, fmt_data

PERIODOS = {"7 dias": 7, "30 dias": 30, "90 dias": 90}


def _fatos(cli, dias):
    cid = cli["id"]
    agora = storage.agora()
    desde = agora - timedelta(days=dias)
    nov = storage.novidades(cid, desde)
    todas = storage.mencoes_do_cliente(cid)
    dom = core.normalizar_dominio(cli["url"])
    dr, ddr = delta_dr(cid, dom, dias)
    sociais = [m for m in todas if m["status"] == storage.ST_COMUNIDADE and m.get("primeira_vez")
               and m["primeira_vez"] >= desde]
    pendentes = [m for m in todas if m["status"] in storage.STATUS_SOCIAIS
                 and m.get("conversa_status") in storage.CONVERSA_PENDENTES
                 and (m.get("sentimento") == "negativa" or m.get("pergunta_indicacao") == "Sim")]
    sem_link_nc = [m for m in todas if m["status"] == core.ST_SEM_LINK and m.get("outreach_status") == "Não contatado"]
    gap_nc = [m for m in todas if m["status"] == storage.ST_GAP and m.get("outreach_status") == "Não contatado"]
    aguardando = [m for m in todas if m.get("outreach_status") in ("Contatado", "Respondeu")]
    camps = storage.listar_campanhas(cid, status="ativa")
    camp_info = []
    for c in camps:
        cob = storage.cobertura_da_campanha(c["id"])
        ind = pr.indicadores(cob, storage.listar_mailing(c["id"]))
        fora = [p for p, v in (c.get("paginas_status") or {}).items() if v and not (200 <= int(v[0] or 0) < 400)]
        camp_info.append({"nome": c["nome"], "materias": ind["materias"], "linkaram_campanha": ind["campanha"],
                          "sem_link": ind["sem_link"], "quebrado": ind["quebrado"], "paginas_fora": fora,
                          "novas_periodo": sum(1 for m in cob if m.get("primeira_vez") and m["primeira_vez"] >= desde),
                          "alerta_diario": pr.em_janela_de_alerta(c), "ultima_busca": c.get("ultima_busca")})
    return {
        "periodo_dias": dias, "dr": dr, "variacao_dr": ddr, "backlinks_total": nov["total_links"],
        "mencoes_total": nov["total_mencoes"], "novos_links": nov["novos_links"],
        "novas_oportunidades": nov["novas_oportunidades"], "links_perdidos": nov["links_perdidos"],
        "links_quebrados": nov["links_quebrados"], "negativas": nov["negativas"], "perguntas": nov["perguntas"],
        "categoria": nov["categoria"], "comunidade_periodo": sociais, "conversas_pendentes": pendentes,
        "sem_link_nao_contatadas": sem_link_nc, "gap_nao_contatados": gap_nc, "aguardando_resposta": aguardando,
        "campanhas": camp_info, "ultima_execucao": storage.ultima_execucao(cid),
        "analise_concorrentes": storage.ultima_analise(cid, "concorrentes")[0],
    }


def _para_ia(f):
    """Versão só com números, para o Gemini não receber listas longas."""
    contagem = {k: (len(v) if isinstance(v, list) else v) for k, v in f.items()
                if k not in ("ultima_execucao", "campanhas", "analise_concorrentes")}
    contagem["campanhas"] = [{k: v for k, v in c.items() if k != "ultima_busca"} for c in f["campanhas"]]
    contagem["dofollow_novos"] = sum(1 for m in f["novos_links"] if m["status"] == core.ST_DOFOLLOW)
    return contagem


def tela():
    cli = exigir_cliente()
    st.title(f"🏠 {cli['nome']}")
    st.caption(cli["url"])
    rot = st.segmented_control("Período", list(PERIODOS), default="30 dias", key="res_periodo") or "30 dias"
    dias = PERIODOS[rot]
    f = _fatos(cli, dias)

    c = st.columns(6)
    c[0].metric("DR", f"{f['dr']:.0f}" if f["dr"] is not None else "–",
                delta=f"{f['variacao_dr']:+.0f}" if f["variacao_dr"] else None,
                help="Domain Rating by Ahrefs. Variação contra o registro mais próximo do início do período.")
    c[1].metric("Backlinks monitorados", f["backlinks_total"])
    c[2].metric("Novos backlinks", len(f["novos_links"]))
    c[3].metric("Menções sem link novas", len(f["novas_oportunidades"]))
    c[4].metric("Perdidos ou quebrados", len(f["links_perdidos"]) + len(f["links_quebrados"]),
                delta_color="inverse")
    c[5].metric("Conversas em comunidades", len(f["comunidade_periodo"]),
                delta=f"{len(f['negativas'])} negativa(s)" if f["negativas"] else None, delta_color="inverse")

    esq, dir_ = st.columns(2)
    with esq:
        with st.container(border=True):
            st.markdown("##### ✅ Positivos")
            pos = []
            dof = [m for m in f["novos_links"] if m["status"] == core.ST_DOFOLLOW]
            if dof:
                top = max(dof, key=lambda m: m.get("dr") or 0)
                pos.append(f"{len(dof)} backlink(s) dofollow novo(s); o melhor em **{top['dominio']}**"
                           + (f" (DR {top['dr']:.0f})" if top.get("dr") is not None else ""))
            if f["variacao_dr"] and f["variacao_dr"] > 0:
                pos.append(f"DR subiu {f['variacao_dr']:.0f} ponto(s) no período")
            positivas = [m for m in f["comunidade_periodo"] if m.get("sentimento") == "positiva"]
            if positivas:
                pos.append(f"{len(positivas)} menção(ões) positiva(s) em comunidades")
            for cp in f["campanhas"]:
                if cp["linkaram_campanha"]:
                    pos.append(f"Campanha **{cp['nome']}**: {cp['linkaram_campanha']} matéria(s) linkando para o estudo")
            conq = storage.metricas_outreach(cli["id"])["conquistados"]
            if conq:
                pos.append(f"{conq} link(s) conquistado(s) por outreach no total")
            for p in pos or ["Nada de destaque no período ainda."]:
                st.markdown(f"- {p}")
    with dir_:
        with st.container(border=True):
            st.markdown("##### ⚠️ Atenção")
            at = []
            if f["negativas"]:
                at.append(f"{len(f['negativas'])} menção(ões) negativa(s) em comunidades")
            if f["conversas_pendentes"]:
                at.append(f"{len(f['conversas_pendentes'])} conversa(s) esperando resposta da agência")
            if f["links_perdidos"]:
                at.append(f"{len(f['links_perdidos'])} link(s) perdido(s)")
            if f["links_quebrados"]:
                at.append(f"{len(f['links_quebrados'])} link(s) apontando para página quebrada do cliente")
            if f["variacao_dr"] and f["variacao_dr"] < 0:
                at.append(f"DR caiu {abs(f['variacao_dr']):.0f} ponto(s) no período")
            for cp in f["campanhas"]:
                if cp["paginas_fora"]:
                    at.append(f"Campanha **{cp['nome']}**: página fora do ar")
                if cp["quebrado"]:
                    at.append(f"Campanha **{cp['nome']}**: {cp['quebrado']} matéria(s) com link quebrado")
            ult = f["ultima_execucao"]
            if not ult or (storage.agora() - ult["inicio"]).days > 14:
                at.append("Sem busca nos últimos 14 dias")
            for p in at or ["Nenhum ponto de atenção."]:
                st.markdown(f"- {p}")

    with st.container(border=True):
        st.markdown("##### 👉 Próximas ações")
        acoes = []
        if f["conversas_pendentes"]:
            acoes.append(("Responder conversas pendentes", len(f["conversas_pendentes"]), "telas/comunidades"))
        if f["sem_link_nao_contatadas"]:
            acoes.append(("Pedir link nas menções sem link (link reclamation)", len(f["sem_link_nao_contatadas"]),
                          "telas/mencoes"))
        if f["links_quebrados"]:
            acoes.append(("Pedir correção de links quebrados", len(f["links_quebrados"]), "telas/mencoes"))
        if f["gap_nao_contatados"]:
            acoes.append(("Abordar domínios do link gap", len(f["gap_nao_contatados"]), "telas/mencoes"))
        if f["aguardando_resposta"]:
            acoes.append(("Fazer follow-up de quem foi contatado", len(f["aguardando_resposta"]), "telas/mencoes"))
        if not acoes:
            st.caption("Nada pendente.")
        for txt, n, _ in acoes:
            st.markdown(f"- **{n}** · {txt}")

    with st.container(border=True):
        st.markdown("##### 🔄 Atualizações")
        ult = f["ultima_execucao"]
        st.markdown(f"- Última busca: **{fmt_data(ult['inicio'], True)}** ({ult['origem']})" if ult
                    else "- Nenhuma busca ainda")
        st.markdown(f"- Concorrentes: {('dados de ' + fmt_data(f['analise_concorrentes'])) if f['analise_concorrentes'] else 'sem análise'}")
        for cp in f["campanhas"]:
            st.markdown(f"- Campanha {cp['nome']}: {cp['materias']} matéria(s), {cp['novas_periodo']} no período"
                        + (" · 🔔 alerta diário" if cp["alerta_diario"] else ""))

    st.markdown("##### ✨ Resumo em texto")
    chave = f"resumo_ia_{cli['id']}_{dias}"
    if st.button("Gerar resumo com IA", disabled=not ia.configurado(),
                 help="Usa o Gemini só com os números desta tela."):
        try:
            st.session_state[chave] = ia.resumo_cliente(_para_ia(f))
        except Exception as e:
            st.error(f"Gemini: {e}")
    if st.session_state.get(chave):
        st.info(st.session_state[chave])
    st.caption("Domain Rating by Ahrefs (https://ahrefs.com/)")
