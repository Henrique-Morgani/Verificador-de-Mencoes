"""Dados do resumo do cliente, usados pela tela Resumo e pelo resumo executivo (PPT e PDF)."""

from __future__ import annotations

from datetime import timedelta

import core
import pr
import storage


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


def fatos(cli: dict, dias: int) -> dict:
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
    camp_info = []
    for c in storage.listar_campanhas(cid, status="ativa"):
        cob = storage.cobertura_da_campanha(c["id"])
        ind = pr.indicadores(cob, storage.listar_mailing(c["id"]))
        fora = [p for p, v in (c.get("paginas_status") or {}).items() if v and not (200 <= int(v[0] or 0) < 400)]
        camp_info.append({"nome": c["nome"], "materias": ind["materias"], "linkaram_campanha": ind["campanha"],
                          "linkaram_site": ind["site"], "sem_link": ind["sem_link"], "quebrado": ind["quebrado"],
                          "dr_medio": ind["dr_medio"], "paginas_fora": fora,
                          "novas_periodo": sum(1 for m in cob if m.get("primeira_vez") and m["primeira_vez"] >= desde),
                          "alerta_diario": pr.em_janela_de_alerta(c), "ultima_busca": c.get("ultima_busca")})
    quando_conc, conc = storage.ultima_analise(cid, "concorrentes")
    quando_tox, tox = storage.ultima_analise(cid, "toxicos")
    return {
        "cliente": cli["nome"], "url": cli["url"], "periodo_dias": dias, "desde": desde, "ate": agora,
        "dr": dr, "variacao_dr": ddr, "backlinks_total": nov["total_links"],
        "mencoes_total": nov["total_mencoes"], "novos_links": nov["novos_links"],
        "novas_oportunidades": nov["novas_oportunidades"], "links_perdidos": nov["links_perdidos"],
        "links_quebrados": nov["links_quebrados"], "negativas": nov["negativas"], "perguntas": nov["perguntas"],
        "categoria": nov["categoria"], "comunidade_periodo": sociais, "conversas_pendentes": pendentes,
        "sem_link_nao_contatadas": sem_link_nc, "gap_nao_contatados": gap_nc, "aguardando_resposta": aguardando,
        "campanhas": camp_info, "ultima_execucao": storage.ultima_execucao(cid),
        "analise_concorrentes": quando_conc, "concorrentes": conc,
        "analise_toxicos": quando_tox, "toxicos": tox,
        "outreach": storage.metricas_outreach(cid),
    }


def _b(txt: str, rich: bool) -> str:
    return f"**{txt}**" if rich else txt


def positivos(f: dict, rich: bool = True) -> list[str]:
    pos = []
    dof = [m for m in f["novos_links"] if m["status"] == core.ST_DOFOLLOW]
    if dof:
        top = max(dof, key=lambda m: m.get("dr") or 0)
        pos.append(f"{len(dof)} backlink(s) dofollow novo(s); o melhor em {_b(top['dominio'], rich)}"
                   + (f" (DR {top['dr']:.0f})" if top.get("dr") is not None else ""))
    if f["variacao_dr"] and f["variacao_dr"] > 0:
        pos.append(f"DR subiu {f['variacao_dr']:.0f} ponto(s) no período")
    positivas = [m for m in f["comunidade_periodo"] if m.get("sentimento") == "positiva"]
    if positivas:
        pos.append(f"{len(positivas)} menção(ões) positiva(s) em comunidades")
    for cp in f["campanhas"]:
        if cp["linkaram_campanha"]:
            pos.append(f"Campanha {_b(cp['nome'], rich)}: {cp['linkaram_campanha']} matéria(s) linkando para o estudo")
    if f["outreach"]["conquistados"]:
        pos.append(f"{f['outreach']['conquistados']} link(s) conquistado(s) por outreach no total")
    return pos


def atencao(f: dict, rich: bool = True) -> list[str]:
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
            at.append(f"Campanha {_b(cp['nome'], rich)}: página fora do ar")
        if cp["quebrado"]:
            at.append(f"Campanha {_b(cp['nome'], rich)}: {cp['quebrado']} matéria(s) com link quebrado")
    tox = f.get("toxicos") or {}
    n_tox = sum(1 for d in tox.get("dominios", []) if d.get("classificacao") == "Tóxico")
    if n_tox:
        at.append(f"{n_tox} domínio(s) classificado(s) como tóxico(s) na última análise")
    ult = f["ultima_execucao"]
    if not ult or (storage.agora() - ult["inicio"]).days > 14:
        at.append("Sem busca nos últimos 14 dias")
    return at


def acoes(f: dict) -> list[tuple[str, int]]:
    lst = []
    if f["conversas_pendentes"]:
        lst.append(("Responder conversas pendentes em comunidades", len(f["conversas_pendentes"])))
    if f["sem_link_nao_contatadas"]:
        lst.append(("Pedir link nas menções sem link (link reclamation)", len(f["sem_link_nao_contatadas"])))
    if f["links_quebrados"]:
        lst.append(("Pedir correção de links quebrados", len(f["links_quebrados"])))
    if f["gap_nao_contatados"]:
        lst.append(("Abordar domínios do link gap", len(f["gap_nao_contatados"])))
    if f["aguardando_resposta"]:
        lst.append(("Fazer follow-up de quem foi contatado", len(f["aguardando_resposta"])))
    return lst


def big_numbers(f: dict) -> list[tuple[str, str, str]]:
    """[(rótulo, valor, detalhe)] na ordem de exibição."""
    dr = f"{f['dr']:.0f}" if f["dr"] is not None else "-"
    ddr = f"{f['variacao_dr']:+.0f} no período" if f["variacao_dr"] else ""
    neg = len(f["negativas"])
    return [
        ("DR", dr, ddr),
        ("Backlinks monitorados", str(f["backlinks_total"]), ""),
        ("Novos backlinks", str(len(f["novos_links"])), ""),
        ("Menções sem link novas", str(len(f["novas_oportunidades"])), "oportunidades de link"),
        ("Perdidos ou quebrados", str(len(f["links_perdidos"]) + len(f["links_quebrados"])), ""),
        ("Conversas em comunidades", str(len(f["comunidade_periodo"])), f"{neg} negativa(s)" if neg else ""),
    ]


def para_ia(f: dict) -> dict:
    """Versão só com números, para o Gemini não receber listas longas."""
    fora = ("ultima_execucao", "campanhas", "analise_concorrentes", "concorrentes", "analise_toxicos", "toxicos",
            "desde", "ate", "outreach")
    contagem = {k: (len(v) if isinstance(v, list) else v) for k, v in f.items() if k not in fora}
    contagem["campanhas"] = [{k: v for k, v in c.items() if k != "ultima_busca"} for c in f["campanhas"]]
    contagem["dofollow_novos"] = sum(1 for m in f["novos_links"] if m["status"] == core.ST_DOFOLLOW)
    contagem["links_conquistados_outreach"] = f["outreach"]["conquistados"]
    return contagem
