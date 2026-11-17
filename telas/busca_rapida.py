"""Busca avulsa, sem cliente salvo (ex.: prospecção ou checagem rápida)."""

import pandas as pd
import streamlit as st

import core
import fluxo
import ia
import storage
from comum import PERIODOS, chaves, mostrar_mencoes, progresso_streamlit


def tela():
    st.title("🔎 Busca rápida")
    st.caption("Uma busca avulsa, sem guardar histórico. Se gostar do resultado, salve como cliente.")
    k = chaves()
    if not k["serper"]:
        with st.expander("Chaves de API (não configuradas no servidor)", expanded=True):
            dig = st.session_state.setdefault("chaves_digitadas", {})
            dig["serper"] = st.text_input("Serper.dev", type="password", value=dig.get("serper", ""))
            dig["ahrefs"] = st.text_input("Ahrefs gratuita (DR)", type="password", value=dig.get("ahrefs", ""))
            k = chaves()

    with st.form("busca_rapida"):
        a, b = st.columns(2)
        url = a.text_input("Site do cliente", placeholder="https://www.cliente.com.br")
        termos = b.text_area("Termos (um por linha)", height=100)
        c1, c2, c3, c4 = st.columns(4)
        periodo = c1.selectbox("Período", list(PERIODOS))
        paginas = c2.slider("Páginas do Google", 1, 10, 2)
        noticias = c3.checkbox("Google Notícias (grátis)", value=True)
        comunidades = c4.checkbox("Comunidades padrão (+1 crédito)", value=True)
        negativos = st.text_input("Termos negativos (separados por vírgula)", placeholder="Ex.: Smiles")
        ir = st.form_submit_button("🔎 Buscar", type="primary", disabled=not k["serper"])

    termos_l = [t.strip() for t in termos.splitlines() if t.strip()]
    if ir:
        if not (url.strip() and termos_l):
            st.error("Informe o site e pelo menos um termo.")
        else:
            cfg = {**fluxo.PADRAO, "periodo": PERIODOS[periodo], "paginas": paginas, "incluir_noticias": noticias,
                   "comunidades": core.COMUNIDADES_PADRAO if comunidades else [],
                   "termos_negativos": [n.strip() for n in negativos.split(",") if n.strip()]}
            stats: dict = {}
            try:
                linhas, avisos = core.executar(url_cliente=url.strip(), termos=termos_l,
                                               **fluxo.parametros(cfg, k), estatisticas=stats,
                                               progresso=progresso_streamlit())
                aviso_ia = ia.aplicar_sentimento(linhas, marca=termos_l[0])
                if aviso_ia:
                    avisos.append(aviso_ia)
                avisos.append(f"Créditos usados: Serper {stats.get('serper', 0)}, Hunter {stats.get('hunter', 0)}.")
                st.session_state["rapida"] = {"linhas": linhas, "avisos": avisos, "url": url.strip(),
                                              "termos": termos_l, "cfg": cfg}
            except Exception as e:
                st.error(f"Erro: {e}")

    r = st.session_state.get("rapida")
    if not r:
        return
    for a_ in r["avisos"]:
        st.warning(a_)
    mostrar_mencoes(pd.DataFrame(r["linhas"]), historico=False, nome_base=core.normalizar_dominio(r["url"]))
    with st.form("salvar_rapida"):
        nome = st.text_input("Salvar como cliente", placeholder="Nome do cliente")
        if st.form_submit_button("💾 Salvar cliente com estas menções") and nome.strip():
            try:
                cid = storage.salvar_cliente(nome, r["url"], r["termos"], r["cfg"])
                storage.salvar_resultados(cid, r["linhas"])
                st.session_state["_ir_para"] = cid
                st.session_state.pop("rapida", None)
                st.toast("Cliente salvo.")
                st.rerun()
            except Exception as e:
                st.error(f"Não consegui salvar: {e}")
