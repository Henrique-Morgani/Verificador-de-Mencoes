"""Cadastro e configuração do cliente: termos, negativos, categoria, concorrentes, comunidades e busca."""

import streamlit as st

import core
import fluxo
import ia
import relatorio
import storage
from comum import COMUNIDADES, COMUNIDADES_INV, PERIODOS, PERIODOS_INV, chaves

NOVO = 0


def _linhas(txt: str) -> list[str]:
    return [t.strip() for t in (txt or "").splitlines() if t.strip()]


def concorrentes_para_texto(nomes, dominios, mapa=None) -> str:
    if mapa:
        com_site = set(mapa.values())
        return "\n".join([f"{n} | {d}" for d, n in mapa.items()] + [n for n in nomes if n not in com_site])
    linhas = list(nomes)
    for i, d in enumerate(dominios):
        if i < len(linhas):
            linhas[i] = f"{linhas[i]} | {d}"
        else:
            linhas.append(f"| {d}")
    return "\n".join(linhas)


def mapa_concorrentes(txt: str) -> dict[str, str]:
    """{domínio: nome} para os concorrentes com site."""
    mapa = {}
    for ln in (txt or "").splitlines():
        nome, _, dom = ln.partition("|")
        if dom.strip():
            d = core.normalizar_dominio(dom.strip())
            mapa[d] = nome.strip() or d
    return mapa


def texto_para_concorrentes(txt: str) -> tuple[list[str], list[str]]:
    nomes, doms = [], []
    for ln in (txt or "").splitlines():
        if not ln.strip():
            continue
        nome, _, dom = ln.partition("|")
        nome, dom = nome.strip(), dom.strip()
        if dom:
            doms.append(core.normalizar_dominio(dom))
            nomes.append(nome or core.normalizar_dominio(dom))
        elif nome:
            nomes.append(nome)
    return nomes, doms


def tela():
    st.title("⚙️ Configurações do cliente")
    k = chaves()
    with st.expander("Integrações configuradas no servidor"):
        itens = [("Serper (busca Google)", k["serper"]), ("Ahrefs gratuita (DR)", k["ahrefs"]),
                 ("Ahrefs paga (concorrentes)", storage_env("AHREFS_API_KEY_PAGA")),
                 ("Hunter (emails)", k["hunter"]), ("Gemini (IA)", ia.configurado()),
                 ("Email (SMTP)", relatorio.smtp_configurado()), ("Banco externo", storage.usando_banco_externo())]
        for nome, ok in itens:
            st.write(("✅ " if ok else "⬜ ") + nome)
        st.caption("As chaves ficam nos Secrets do Streamlit Cloud (Manage app > Settings > Secrets).")

    lista = storage.listar_clientes()
    opcoes = [NOVO] + [c["id"] for c in lista]
    nomes = {NOVO: "➕ Novo cliente", **{c["id"]: c["nome"] for c in lista}}
    padrao = st.session_state.get("cid") or NOVO
    alvo = st.radio("Editar", opcoes, index=opcoes.index(padrao) if padrao in opcoes else 0,
                    format_func=lambda i: nomes[i], horizontal=True, key="cfg_alvo")
    cli = storage.obter_cliente(alvo) if alvo else None
    c = {**fluxo.PADRAO, **((cli or {}).get("config") or {})}
    s = f"_{alvo}"  # sufixo: cada cliente tem seus próprios campos

    with st.form(f"form_cliente{s}"):
        st.subheader("Cliente")
        a, b = st.columns(2)
        nome = a.text_input("Nome do cliente", value=(cli or {}).get("nome", ""), key="nome" + s)
        url = b.text_input("Site do cliente", value=(cli or {}).get("url", ""), key="url" + s,
                           placeholder="https://www.cliente.com.br")

        st.subheader("Termos")
        t1, t2, t3 = st.columns(3)
        termos = t1.text_area("Termos da marca (um por linha)", "\n".join((cli or {}).get("termos", [])),
                              height=140, key="termos" + s, placeholder="Nome da marca\nProduto\nPorta-voz")
        negativos = t2.text_area("Termos negativos (excluir)", "\n".join(c["termos_negativos"]), height=140,
                                 key="neg" + s, placeholder="Ex.: Smiles (quando a marca é OpenSmiles)",
                                 help="Quando a marca contém uma palavra comum ou outra marca. A busca usa "
                                      "palavra inteira e ignora o trecho que só bate por causa destes termos.")
        frases = t3.text_area("Conversas da categoria", "\n".join(c["frases_categoria"]), height=140,
                              key="frases" + s, placeholder="indicação de lavagem a seco\nhigienização de sofá vale a pena",
                              help="Frases que pessoas usam ao pedir indicação no seu mercado, sem citar a marca. "
                                   "1 crédito do Serper por busca.")

        st.subheader("Concorrentes")
        conc = st.text_area("Um por linha, no formato Nome | site.com.br",
                            concorrentes_para_texto(c["concorrentes"], c["dominios_concorrentes"],
                                                    c.get("mapa_concorrentes")),
                            height=110, key="conc" + s, placeholder="Concorrente A | concorrentea.com.br")
        cc1, cc2 = st.columns(2)
        conc_com = cc1.checkbox("Monitorar concorrentes nas comunidades", value=bool(c["comunidades_concorrentes"]),
                                key="concom" + s, help="1 crédito do Serper por busca.")

        st.subheader("Comunidades")
        comunidades = st.multiselect("Monitorar menções em", list(COMUNIDADES),
                                     default=[COMUNIDADES_INV[d] for d in c["comunidades"] if d in COMUNIDADES_INV],
                                     key="com" + s)

        st.subheader("Busca manual")
        b1, b2, b3, b4 = st.columns(4)
        pais = b1.selectbox("País do Google", ["br", "pt", "mx", "co", "ar", "us", "es"],
                            index=["br", "pt", "mx", "co", "ar", "us", "es"].index(c["pais"]), key="pais" + s)
        idioma = b2.selectbox("Idioma", ["pt-br", "pt", "es", "en"],
                              index=["pt-br", "pt", "es", "en"].index(c["idioma"]), key="idioma" + s)
        periodo = b3.selectbox("Período", list(PERIODOS),
                               index=list(PERIODOS).index(PERIODOS_INV.get(c["periodo"], "Qualquer data")),
                               key="per" + s)
        paginas = b4.slider("Páginas do Google", 1, 10, int(c["paginas"]), key="pags" + s,
                            help="Cada página = 1 crédito do Serper.")
        noticias = st.checkbox("Incluir Google Notícias (grátis, via RSS)", value=bool(c["incluir_noticias"]),
                               key="news" + s)

        st.subheader("Robô (buscas automáticas)")
        r1, r2 = st.columns(2)
        per_rob = r1.selectbox("Período", ["Última semana", "Último mês"],
                               index=0 if c["periodo_monitoramento"] == "w" else 1, key="perrob" + s)
        pag_rob = r2.slider("Páginas do Google", 1, 5, int(c["paginas_monitoramento"]), key="pagrob" + s)

        st.subheader("O que puxar")
        o1, o2, o3 = st.columns(3)
        puxar_dr = o1.checkbox("DR (Ahrefs gratuita)", value=bool(c["puxar_dr"]), key="dr" + s)
        contatos = o1.checkbox("Contatos do site", value=bool(c["puxar_contatos"]), key="ct" + s)
        autor = o2.checkbox("Autor da matéria", value=bool(c["puxar_autor"]), key="au" + s)
        perfis = o2.checkbox("LinkedIn, X e Muck Rack do autor (1 crédito por autor)",
                             value=bool(c["perfis_google"]), key="pf" + s)
        h_autor = o3.checkbox("Hunter: email do autor", value=bool(c["hunter_autor"]), key="ha" + s,
                              disabled=not k["hunter"])
        h_veic = o3.checkbox("Hunter: emails da redação", value=bool(c["hunter_veiculo"]), key="hv" + s,
                             disabled=not k["hunter"])
        so_op = st.checkbox("Gastar créditos só com oportunidades", value=bool(c["so_oportunidades"]), key="so" + s)
        excluir = st.text_area("Domínios a excluir (um por linha)", "\n".join(c["excluir"]), height=120,
                               key="exc" + s)

        salvar = st.form_submit_button("💾 Salvar", type="primary")

    if salvar:
        termos_l = _linhas(termos)
        if not (nome.strip() and url.strip() and termos_l):
            st.error("Preencha nome, site e pelo menos um termo.")
            return
        nomes_c, doms_c = texto_para_concorrentes(conc)
        cfg = {
            **c, "pais": pais, "idioma": idioma, "periodo": PERIODOS[periodo], "paginas": paginas,
            "incluir_noticias": noticias, "periodo_monitoramento": "w" if per_rob == "Última semana" else "m",
            "paginas_monitoramento": pag_rob, "puxar_dr": puxar_dr, "puxar_contatos": contatos,
            "puxar_autor": autor, "perfis_google": perfis, "hunter_autor": h_autor, "hunter_veiculo": h_veic,
            "so_oportunidades": so_op, "excluir": _linhas(excluir),
            "comunidades": [COMUNIDADES[n] for n in comunidades], "concorrentes": nomes_c,
            "dominios_concorrentes": doms_c, "comunidades_concorrentes": conc_com,
            "mapa_concorrentes": mapa_concorrentes(conc),
            "termos_negativos": _linhas(negativos), "frases_categoria": _linhas(frases),
        }
        try:
            novo = storage.salvar_cliente(nome, url.strip(), termos_l, cfg, alvo or None)
        except Exception as e:
            st.error(f"Não consegui salvar: {e}")
            return
        st.session_state["_ir_para"] = novo
        st.session_state.pop("cfg_alvo", None)
        st.toast("Cliente salvo.")
        st.rerun()

    if cli:
        custo = c["paginas"] + (1 if c["comunidades"] else 0) + (1 if c["frases_categoria"] else 0) + \
            (1 if c["comunidades_concorrentes"] and c["concorrentes"] else 0)
        st.caption(f"Estimativa de uma busca manual: até {custo} crédito(s) do Serper, mais 1 por autor novo "
                   "se os perfis do autor estiverem ligados. Notícias via RSS: grátis.")
        with st.popover("🗑️ Excluir cliente"):
            st.write(f"Excluir **{cli['nome']}**, todo o histórico, campanhas e alertas?")
            if st.button("Confirmar exclusão", type="primary"):
                storage.excluir_cliente(cli["id"])
                st.session_state.pop("cfg_alvo", None)
                st.session_state["_ir_para"] = None
                st.rerun()


def storage_env(nome: str) -> bool:
    import os
    return bool(os.getenv(nome, "").strip())
