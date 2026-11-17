"""Analista de concorrentes: comparativo, links novos, link gap e páginas mais linkadas."""

import math

import pandas as pd
import streamlit as st

import concorrentes
import provedores
import storage
from comum import CORES, chaves, exigir_cliente, fmt_data, progresso_streamlit

LINK = st.column_config.LinkColumn


def _estimativa(n_conc: int) -> int:
    """Número aproximado de requisições de uma atualização completa."""
    sites = n_conc + 1
    return sites * 3 + n_conc * 3 + math.ceil((n_conc * 40) / 50)


def _comparativo(res, cid):
    vis = pd.DataFrame(res.get("visao") or [])
    if vis.empty:
        st.info("Sem dados.")
        return
    tab = vis.rename(columns={"nome": "Site", "dominio": "Domínio", "dr": "DR", "refdomains": "Domínios de referência",
                              "backlinks": "Backlinks", "trafego": "Tráfego orgânico", "keywords": "Palavras-chave"})
    cols = [c for c in ["Site", "Domínio", "DR", "Domínios de referência", "Backlinks", "Tráfego orgânico",
                        "Palavras-chave"] if c in tab.columns]
    st.dataframe(tab[cols], hide_index=True, width="stretch",
                 column_config={"DR": st.column_config.NumberColumn(format="%.0f")})
    st.caption("DR: Domain Rating by Ahrefs (endpoint gratuito). Demais números: provedor "
               f"{res.get('provedor', '')}.")
    a, b = st.columns(2)
    with a:
        st.markdown("##### Domínios de referência")
        st.bar_chart(tab.set_index("Site")[["Domínios de referência"]], horizontal=True, color=CORES[0],
                     x_label="Domínios", y_label="")
    with b:
        st.markdown("##### DR")
        st.bar_chart(tab.set_index("Site")[["DR"]], horizontal=True, color=CORES[1], x_label="DR", y_label="")
    hist = res.get("historico") or {}
    rot = res.get("rotulos") or {}
    linhas = [{"Mês": h["data"][:7], "Site": rot.get(d, d), "Domínios": h["refdomains"]}
              for d, lst in hist.items() for h in lst if h.get("refdomains") is not None]
    if linhas:
        st.markdown("##### Evolução dos domínios de referência (6 meses)")
        piv = pd.DataFrame(linhas).pivot_table(index="Mês", columns="Site", values="Domínios", aggfunc="last")
        st.line_chart(piv, color=CORES[:len(piv.columns)], x_label="Mês", y_label="Domínios")
    snaps = storage.snapshots(cid)
    if len({s["data"].date() for s in snaps}) > 1:
        with st.expander("Histórico das atualizações feitas no DizemAI"):
            st.dataframe(pd.DataFrame([{**s, "data": fmt_data(s["data"])} for s in snaps])
                         [["data", "dominio", "dr", "refdomains", "backlinks", "trafego", "keywords"]],
                         hide_index=True, width="stretch")


def _novos(res):
    novos = pd.DataFrame(res.get("novos") or [])
    if novos.empty:
        st.info("Nenhum domínio novo linkando para os concorrentes no período.")
        return
    novos["Cliente já tem?"] = novos["cliente_linka"].map({True: "✅ sim", False: "não"})
    st.caption("Domínios que passaram a linkar para os concorrentes recentemente. Os que ainda não linkam para o "
               "cliente são os mais quentes para outreach.")
    so_sem = st.checkbox("Só os que não linkam para o cliente", value=True)
    if so_sem:
        novos = novos[~novos["cliente_linka"]]
    novos["url"] = "https://" + novos["dominio"].astype(str)
    st.dataframe(novos[["first_seen", "dominio", "url", "dr", "concorrente", "Cliente já tem?"]], hide_index=True,
                 width="stretch", column_config={"first_seen": "Visto em", "dominio": "Domínio", "url": LINK("Abrir"),
                                                 "dr": st.column_config.NumberColumn("DR", format="%.0f"),
                                                 "concorrente": "Linkou para"})


def _gap(res, cid):
    gap = pd.DataFrame(res.get("gap") or [])
    if gap.empty:
        st.info("Nenhum domínio no link gap. Com 2 concorrentes ou mais, entram os sites que linkam para pelo "
                "menos 2 deles e não linkam para o cliente.")
        return
    gap["linka_para_txt"] = gap["linka_para"].map(lambda x: ", ".join(x) if isinstance(x, list) else str(x))
    gap["qtd"] = gap["linka_para"].map(lambda x: len(x) if isinstance(x, list) else 1)
    gap["url"] = "https://" + gap["dominio"].astype(str)
    a, b = st.columns([1, 3])
    dr_min = a.number_input("DR mínimo", 0, 100, 20)
    vis = gap[gap["dr"].fillna(0) >= dr_min].reset_index(drop=True)
    ev = st.dataframe(vis[["dominio", "url", "dr", "qtd", "linka_para_txt"]], hide_index=True, width="stretch",
                      on_select="rerun", selection_mode="multi-row", key="gap_tab",
                      column_config={"dominio": "Domínio", "url": LINK("Abrir"),
                                     "dr": st.column_config.NumberColumn("DR", format="%.0f"),
                                     "qtd": "Nº de concorrentes", "linka_para_txt": "Linka para"})
    sel = vis.iloc[ev.selection.rows] if ev and ev.selection.rows else vis.iloc[0:0]
    if st.button(f"➡️ Enviar {len(sel)} selecionado(s) para o outreach", disabled=sel.empty, type="primary"):
        n = concorrentes.enviar_gap_para_outreach(cid, sel.to_dict("records"))
        st.toast(f"{n} domínio(s) novo(s) em Menções e links, com status Prospect: link gap.")


def _paginas(res):
    pg = pd.DataFrame(res.get("paginas") or [])
    if pg.empty:
        st.info("Sem dados de páginas.")
        return
    st.caption("O conteúdo que mais atrai links nos concorrentes: boas pistas de pauta e de conteúdo linkável.")
    for nome, grupo in pg.groupby("concorrente"):
        st.markdown(f"##### {nome}")
        st.dataframe(grupo[["refdomains", "titulo", "url"]], hide_index=True, width="stretch",
                     column_config={"refdomains": "Domínios de referência", "titulo": "Título", "url": LINK("Página")})


def tela():
    cli = exigir_cliente()
    cfg = cli.get("config") or {}
    st.title(f"📊 Concorrentes · {cli['nome']}")
    doms = cfg.get("dominios_concorrentes") or []
    try:
        prov = provedores.obter_provedor()
        erro_prov = ""
    except provedores.ProvedorErro as e:
        prov, erro_prov = None, str(e)

    quando, res = storage.ultima_analise(cli["id"], "concorrentes")
    c1, c2 = st.columns([3, 1.4])
    if erro_prov:
        c1.error(erro_prov)
    elif prov is None:
        c1.info("Para ativar, coloque **AHREFS_API_KEY_PAGA** nos Secrets (chave de uma conta Ahrefs Lite ou "
                "acima). O DR continua pela chave gratuita.")
    elif not doms:
        c1.info("Cadastre os concorrentes com domínio em **Configurações do cliente** (Nome | site.com.br).")
    else:
        c1.caption(f"Provedor: **{prov.nome}** · {len(doms)} concorrente(s) · uma atualização faz cerca de "
                   f"{_estimativa(len(doms))} requisições (a Ahrefs cobra no mínimo 50 unidades por requisição). "
                   "O resultado fica salvo: abrir esta tela não gasta nada.")
    if c2.button("🔄 Atualizar dados (gasta unidades)", type="primary", disabled=not (prov and doms)):
        try:
            res = concorrentes.analisar(cli, prov, chaves()["ahrefs"], progresso=progresso_streamlit())
            st.toast(f"Atualizado. Unidades usadas: {res.get('unidades', 0)}.")
            st.rerun()
        except provedores.ProvedorErro as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Erro: {e}")

    if not res:
        st.info("Ainda não há análise salva para este cliente.")
        return
    st.caption(f"Dados de {fmt_data(quando, True)} · unidades usadas na última atualização: {res.get('unidades', '?')}")
    for a in res.get("avisos") or []:
        st.warning(a)
    t1, t2, t3, t4 = st.tabs(["Comparativo", "Links novos dos concorrentes", "Link gap", "Páginas mais linkadas"])
    with t1:
        _comparativo(res, cli["id"])
    with t2:
        _novos(res)
    with t3:
        _gap(res, cli["id"])
    with t4:
        _paginas(res)
