"""
Digital PR: monitoramento de cobertura de campanhas.

Cada campanha tem termos próprios (nome do estudo, porta-voz, dado marcante) e, de preferência,
uma ou mais páginas da campanha no site do cliente (post, sala de imprensa ou LP).
Cada matéria encontrada recebe um destes status:
  - Linkou para a campanha
  - Linkou para o site (mas não para a campanha)
  - Citou sem link
  - Link da campanha quebrado
  - Notícia (URL não resolvida)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import urlparse

import core
import fluxo
import storage

LINKOU_CAMPANHA = "Linkou para a campanha"
LINKOU_SITE = "Linkou para o site"
SEM_LINK = "Citou sem link"
QUEBRADO = "Link da campanha quebrado"
NAO_RESOLVIDA = "Notícia (URL não resolvida)"
ORDEM = {QUEBRADO: 0, SEM_LINK: 1, LINKOU_SITE: 2, LINKOU_CAMPANHA: 3, NAO_RESOLVIDA: 4}


def _norm(u: str) -> str:
    p = urlparse(u if "://" in u else "https://" + u)
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return host + p.path.rstrip("/").lower()


def eh_pagina_da_campanha(href: str, paginas: list[str]) -> bool:
    h = _norm(href.split("#")[0].split("?")[0])
    return any(h == _norm(p) or h.startswith(_norm(p) + "/") for p in paginas if p.strip())


def status_da_materia(linha: dict, paginas: list[str]) -> str | None:
    st = linha.get("status", "")
    if st == core.ST_NOTICIA_NR:
        return NAO_RESOLVIDA
    if st in (core.ST_NAO_ENCONTRADO, "Erro ao acessar") or st.startswith("Página bloqueada"):
        return None
    links = [x.strip() for x in (linha.get("urls_linkadas") or "").split("|") if x.strip()]
    destinos = linha.get("destino_link") or ""
    if paginas and any(eh_pagina_da_campanha(h, paginas) for h in links):
        if st == core.ST_QUEBRADO and any(c in destinos for c in ("404", "410", "500", "503")):
            return QUEBRADO
        return LINKOU_CAMPANHA
    if links:
        return LINKOU_SITE
    if st in (core.ST_SEM_LINK, core.ST_COMUNIDADE):
        return SEM_LINK
    return None


def em_janela_de_alerta(camp: dict, hoje: date | None = None) -> bool:
    """Primeiros N dias depois do lançamento: alerta diário."""
    if camp.get("status") != "ativa" or not camp.get("lancamento"):
        return False
    hoje = hoje or date.today()
    ini = date.fromisoformat(camp["lancamento"])
    return ini <= hoje <= ini + timedelta(days=int(camp.get("dias_alerta") or 14))


def rodar_campanha(camp: dict, cliente: dict, chaves: dict | None = None, progresso=None,
                   executar=None) -> tuple[dict, list[str]]:
    """Busca a cobertura da campanha desde o lançamento e grava. Devolve (resumo, avisos)."""
    chaves = chaves or fluxo.chaves_do_ambiente()
    executar = executar or core.executar
    cfg = {**fluxo.PADRAO, **(cliente.get("config") or {})}
    conhecidas = [m["url"] for m in storage.cobertura_da_campanha(camp["id"])]
    stats: dict = {}
    inicio = storage.agora()
    periodo = f"desde:{camp['lancamento']}" if camp.get("lancamento") else ""
    linhas, avisos = executar(
        url_cliente=cliente["url"], termos=camp["termos"],
        serper_key=chaves.get("serper", ""), ahrefs_key=chaves.get("ahrefs", ""),
        hunter_key=chaves.get("hunter", ""), pais=cfg["pais"], idioma=cfg["idioma"],
        paginas=max(2, int(cfg["paginas"])), periodo=periodo, incluir_noticias=True,
        excluir=cfg["excluir"], puxar_dr=True, puxar_contatos=True, puxar_autor=True,
        perfis_google=cfg["perfis_google"], hunter_autor=cfg["hunter_autor"] and bool(chaves.get("hunter")),
        hunter_veiculo=False, so_oportunidades=True, comunidades=[], concorrentes=[],
        termos_negativos=cfg.get("termos_negativos") or [],
        urls_extras=conhecidas, urls_conhecidas=set(conhecidas), estatisticas=stats, progresso=progresso,
    )
    validas = []
    for ln in linhas:
        st = status_da_materia(ln, camp["paginas"])
        if st:
            ln["status_campanha"] = st
            validas.append(ln)
    resumo = storage.salvar_cobertura(camp["id"], validas, inicio)
    # Saúde das páginas da campanha (saiu do ar? mudou de endereço sem redirect?)
    if camp["paginas"]:
        dest = core.verificar_destinos(camp["paginas"])
        storage.atualizar_campanha(camp["id"], paginas_status={k: list(v) for k, v in dest.items()})
        fora = [p for p, (st, _) in dest.items() if not (200 <= st < 400)]
        if fora:
            avisos.append("Página da campanha fora do ar: " + ", ".join(fora))
    resumo["creditos_serper"] = stats.get("serper", 0)
    storage.registrar_execucao(cliente["id"], inicio, "campanha", stats,
                               {"novas": resumo["novas"], "novos_links": 0, "links_perdidos": 0})
    return resumo, avisos


def cruzar_mailing(camp_id: int) -> int:
    """Marca como 'Publicou' quem está no mailing e saiu na cobertura. Devolve quantos mudaram."""
    cob = {m["dominio"] for m in storage.cobertura_da_campanha(camp_id) if m.get("dominio")}
    lista = storage.listar_mailing(camp_id)
    mudou = 0
    for m in lista:
        dom = (m.get("dominio") or "").lower()
        if dom and any(core.pertence_ao_dominio(c, dom) or c == dom for c in cob) and m.get("status") != "Publicou":
            m["status"] = "Publicou"
            mudou += 1
    if mudou:
        storage.salvar_mailing(camp_id, lista)
    return mudou


def indicadores(cobertura: list[dict], mailing_lista: list[dict]) -> dict:
    por = {}
    for m in cobertura:
        por[m["status_campanha"]] = por.get(m["status_campanha"], 0) + 1
    drs = [m["dr"] for m in cobertura if m.get("dr") is not None]
    doms_mailing = {(m.get("dominio") or "").lower() for m in mailing_lista if m.get("dominio")}
    espontaneas = [m for m in cobertura if m.get("dominio") and not any(
        core.pertence_ao_dominio(m["dominio"], d) for d in doms_mailing)] if doms_mailing else []
    return {
        "materias": len(cobertura),
        "campanha": por.get(LINKOU_CAMPANHA, 0), "site": por.get(LINKOU_SITE, 0),
        "sem_link": por.get(SEM_LINK, 0), "quebrado": por.get(QUEBRADO, 0),
        "dr_medio": round(sum(drs) / len(drs)) if drs else None,
        "abordados": len(mailing_lista),
        "responderam": sum(1 for m in mailing_lista if m.get("status") in ("Respondeu", "Publicou", "Recusou")),
        "publicaram": sum(1 for m in mailing_lista if m.get("status") == "Publicou"),
        "espontaneas": len(espontaneas),
    }


def resumo_campanhas(cid: int, desde: datetime) -> list[dict]:
    """Linha por campanha ativa (ou encerrada recentemente) para o relatório periódico do cliente."""
    saida = []
    for c in storage.listar_campanhas(cid):
        if c["status"] == "rascunho":
            continue
        cob = storage.cobertura_da_campanha(c["id"])
        novas = sum(1 for m in cob if m.get("primeira_vez") and m["primeira_vez"] >= desde)
        if c["status"] == "encerrada" and not novas:
            continue
        ind = indicadores(cob, [])
        saida.append({"nome": c["nome"], "novas_periodo": novas, "campanha": ind["campanha"],
                      "sem_link": ind["sem_link"]})
    return saida
