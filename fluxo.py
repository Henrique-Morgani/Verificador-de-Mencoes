"""
Fluxo completo de uma busca para um cliente salvo, usado pelo app e pelo robô:
busca, reverificação, sentimento nas comunidades, gravação no histórico e registro de créditos.
"""

from __future__ import annotations

import os

import core
import ia
import storage

PADRAO = {
    "pais": "br", "idioma": "pt-br", "periodo": "", "paginas": 3, "incluir_noticias": True,
    "puxar_dr": True, "puxar_contatos": True, "puxar_autor": True, "perfis_google": True,
    "hunter_autor": False, "hunter_veiculo": False, "so_oportunidades": True,
    "excluir": core.EXCLUIR_PADRAO, "periodo_monitoramento": "m", "paginas_monitoramento": 2,
    "comunidades": core.COMUNIDADES_PADRAO, "concorrentes": [], "dominios_concorrentes": [],
    "paginas_concorrentes": 1, "termos_negativos": [], "frases_categoria": [],
    "comunidades_concorrentes": True,
}


def chaves_do_ambiente() -> dict:
    return {k: os.getenv(v, "") for k, v in (("serper", "SERPER_API_KEY"), ("ahrefs", "AHREFS_API_KEY"),
                                             ("hunter", "HUNTER_API_KEY"))}


def parametros(cfg: dict, chaves: dict, robo: bool = False) -> dict:
    c = {**PADRAO, **(cfg or {})}
    return dict(
        serper_key=chaves.get("serper", ""), ahrefs_key=chaves.get("ahrefs", ""),
        hunter_key=chaves.get("hunter", ""),
        pais=c["pais"], idioma=c["idioma"],
        paginas=c["paginas_monitoramento"] if robo else c["paginas"],
        periodo=c["periodo_monitoramento"] if robo else c["periodo"],
        incluir_noticias=c["incluir_noticias"], excluir=c["excluir"],
        puxar_dr=c["puxar_dr"], puxar_contatos=c["puxar_contatos"], puxar_autor=c["puxar_autor"],
        perfis_google=c["perfis_google"],
        hunter_autor=c["hunter_autor"] and bool(chaves.get("hunter")),
        hunter_veiculo=c["hunter_veiculo"] and bool(chaves.get("hunter")),
        so_oportunidades=c["so_oportunidades"], comunidades=c["comunidades"],
        concorrentes=c["concorrentes"], dominios_concorrentes=c["dominios_concorrentes"],
        paginas_concorrentes=c["paginas_concorrentes"], termos_negativos=c["termos_negativos"],
        frases_categoria=c["frases_categoria"],
        comunidades_concorrentes=bool(c["comunidades_concorrentes"] and c["concorrentes"]),
    )


def rodar_cliente(cliente: dict, origem: str = "manual", chaves: dict | None = None,
                  reverificar: bool = True, cfg: dict | None = None, progresso=None,
                  executar=None) -> tuple[dict, list[str], dict]:
    """Devolve (resumo, avisos, créditos)."""
    chaves = chaves or chaves_do_ambiente()
    executar = executar or core.executar
    cid = cliente["id"]
    inicio = storage.agora()
    conhecidas = storage.urls_do_cliente(cid, sem_sociais=True)
    ign_urls, ign_doms = storage.conjuntos_ignorados(cid)
    stats: dict = {}
    linhas, avisos = executar(
        url_cliente=cliente["url"], termos=cliente["termos"],
        **parametros(cfg if cfg is not None else cliente.get("config", {}), chaves, robo=origem == "robô"),
        ignorar_urls=ign_urls, ignorar_dominios=ign_doms,
        urls_extras=conhecidas if reverificar else None, urls_conhecidas=set(conhecidas),
        estatisticas=stats, progresso=progresso,
    )
    aviso_ia = ia.aplicar_sentimento(linhas, marca=cliente["nome"], anteriores=storage.dados_salvos(cid))
    if aviso_ia:
        avisos.append(aviso_ia)
    resumo = storage.salvar_resultados(cid, linhas, inicio)
    storage.registrar_execucao(cid, inicio, origem, stats, resumo)
    # Histórico do DR do próprio cliente (endpoint gratuito da Ahrefs)
    try:
        dom = core.normalizar_dominio(cliente["url"])
        drs, _ = core.buscar_dr([dom], chaves.get("ahrefs", ""))
        storage.registrar_dr(cid, dom, drs.get(dom), inicio)
    except Exception:
        pass
    return resumo, avisos, stats
