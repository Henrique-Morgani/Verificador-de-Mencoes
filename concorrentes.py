"""
Analista de concorrentes: painel comparativo, links novos dos concorrentes, link gap e
páginas mais linkadas. Usa o provedor configurado (provedores.py) e o DR gratuito da Ahrefs.
"""

from __future__ import annotations

from datetime import date, timedelta

import core
import storage
from provedores import Provedor, ProvedorErro


def _lotes(lista, n):
    for i in range(0, len(lista), n):
        yield lista[i:i + n]


def quem_ja_linka(prov: Provedor, dominio_cliente: str, candidatos: list[str]) -> set[str]:
    """Dos candidatos, quais já são domínios de referência do cliente."""
    achados = set()
    for lote in _lotes(sorted(set(candidatos)), 50):
        for r in prov.refdomains(dominio_cliente, limite=len(lote), dominios=lote):
            if r.get("dominio"):
                achados.add(r["dominio"].lower())
    return achados


def analisar(cliente: dict, prov: Provedor, ahrefs_key_gratis: str = "", dias_novos: int = 15,
             top_por_concorrente: int = 100, min_concorrentes: int = 2, progresso=None) -> dict:
    """Roda a análise completa e guarda. Devolve o resultado (também salvo em 'analises')."""
    log = progresso or (lambda etapa, frac: None)
    cfg = cliente.get("config") or {}
    dom_cliente = core.normalizar_dominio(cliente["url"])
    nomes = cfg.get("concorrentes") or []
    doms = [core.normalizar_dominio(d) for d in (cfg.get("dominios_concorrentes") or []) if d.strip()]
    if not doms:
        raise ProvedorErro("Cadastre os domínios dos concorrentes (Configurações do cliente, campo "
                           "Concorrentes, no formato 'Nome | site.com.br').")
    mapa = cfg.get("mapa_concorrentes") or {}
    rotulo = {dom_cliente: cliente["nome"]}
    for i, d in enumerate(doms):
        rotulo[d] = mapa.get(d) or (nomes[i] if i < len(nomes) else d)
    todos = [dom_cliente] + doms
    resultado = {"cliente": dom_cliente, "rotulos": rotulo, "provedor": prov.nome, "avisos": []}

    # 1. Visão geral + DR gratuito
    log("Visão geral dos sites", 0.05)
    drs, erro = core.buscar_dr(todos, ahrefs_key_gratis)
    if erro:
        resultado["avisos"].append(erro)
    visao = []
    for i, d in enumerate(todos):
        try:
            v = prov.visao_geral(d)
        except ProvedorErro as e:
            resultado["avisos"].append(str(e))
            v = {}
        visao.append({"dominio": d, "nome": rotulo[d], "dr": drs.get(d), **v})
        log(f"Visão geral ({i + 1}/{len(todos)})", 0.05 + 0.2 * (i + 1) / len(todos))
    storage.salvar_snapshot(cliente["id"], visao, prov.nome)
    resultado["visao"] = visao

    # 2. Histórico de domínios de referência (para o gráfico)
    hist = {}
    for d in todos:
        try:
            hist[d] = prov.historico_refdomains(d, 6)
        except ProvedorErro as e:
            resultado["avisos"].append(str(e))
    resultado["historico"] = hist
    log("Histórico", 0.35)

    # 3. Links novos dos concorrentes
    desde = (date.today() - timedelta(days=dias_novos)).isoformat()
    novos = []
    for i, d in enumerate(doms):
        try:
            for r in prov.refdomains(d, limite=100, desde=desde):
                novos.append({**r, "concorrente": rotulo[d], "dominio_concorrente": d})
        except ProvedorErro as e:
            resultado["avisos"].append(str(e))
        log(f"Links novos ({i + 1}/{len(doms)})", 0.35 + 0.2 * (i + 1) / len(doms))

    # 4. Link gap: top domínios de cada concorrente
    contagem: dict[str, dict] = {}
    for i, d in enumerate(doms):
        try:
            for r in prov.refdomains(d, limite=top_por_concorrente):
                k = (r.get("dominio") or "").lower()
                if not k or core.pertence_ao_dominio(k, dom_cliente) or any(core.pertence_ao_dominio(k, x) for x in doms):
                    continue
                item = contagem.setdefault(k, {"dominio": k, "dr": r.get("dr"), "linka_para": []})
                item["linka_para"].append(rotulo[d])
        except ProvedorErro as e:
            resultado["avisos"].append(str(e))
        log(f"Link gap ({i + 1}/{len(doms)})", 0.55 + 0.2 * (i + 1) / len(doms))

    candidatos = [k for k, v in contagem.items() if len(v["linka_para"]) >= min(min_concorrentes, len(doms))]
    candidatos += [n["dominio"].lower() for n in novos if n.get("dominio")]
    log("Conferindo quem já linka para o cliente", 0.8)
    try:
        ja_linkam = quem_ja_linka(prov, dom_cliente, candidatos)
    except ProvedorErro as e:
        resultado["avisos"].append(str(e))
        ja_linkam = set()
    for n in novos:
        n["cliente_linka"] = (n.get("dominio") or "").lower() in ja_linkam
    gap = [v for k, v in contagem.items() if k in candidatos and k not in ja_linkam]
    gap.sort(key=lambda x: (-len(x["linka_para"]), -(x["dr"] or 0)))
    resultado["novos"] = sorted(novos, key=lambda x: x.get("first_seen") or "", reverse=True)
    resultado["gap"] = gap

    # 5. Páginas mais linkadas de cada concorrente
    paginas = []
    for d in doms:
        try:
            for p in prov.paginas_mais_linkadas(d, 10):
                paginas.append({**p, "concorrente": rotulo[d]})
        except ProvedorErro as e:
            resultado["avisos"].append(str(e))
    resultado["paginas"] = paginas
    resultado["unidades"] = prov.unidades
    storage.salvar_analise(cliente["id"], "concorrentes", resultado)
    log("Concluído", 1.0)
    return resultado


def enviar_gap_para_outreach(cid: int, itens: list[dict]) -> int:
    """Leva domínios do link gap para a tabela de menções/outreach, como prospects."""
    linhas = [{"url": f"https://{i['dominio']}/", "dominio": i["dominio"], "status": storage.ST_GAP,
               "dr": i.get("dr"), "titulo": "Link gap: linka para " + ", ".join(i.get("linka_para") or []),
               "fonte": "Link gap"} for i in itens]
    return storage.salvar_resultados(cid, linhas)["novas"]
