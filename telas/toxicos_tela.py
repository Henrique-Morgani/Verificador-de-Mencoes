"""Links tóxicos: a pessoa sobe a lista de links, o DizemAI pontua e gera o disavow."""

import re

import pandas as pd
import streamlit as st

import core
import storage
import toxicos
from comum import baixar_excel, chaves, exigir_cliente, fmt_data, progresso_streamlit

ICONE = {toxicos.TOXICO: "🔴 Tóxico", toxicos.SUSPEITO: "🟠 Suspeito", toxicos.OK: "🟢 OK"}


def _entrada():
    st.markdown("##### 1. Envie a lista de links")
    st.caption("Aceita o export de backlinks ou domínios de referência do Ahrefs, do Semrush ou do Search Console "
               "(CSV ou Excel), uma planilha qualquer com uma coluna de URL ou domínio, ou uma lista colada. "
               "Pode ser a lista total ou só os links que você quer conferir.")
    a, b = st.tabs(["Subir arquivo", "Colar lista"])
    df = None
    with a:
        arqs = st.file_uploader("Arquivos", type=["csv", "tsv", "txt", "xlsx", "xls"], accept_multiple_files=True,
                                key="tox_arquivos")
        if arqs:
            partes = []
            for arq in arqs:
                try:
                    partes.append(toxicos.ler_arquivo(arq.name, arq.getvalue()))
                except Exception as e:
                    st.error(f"Não consegui ler {arq.name}: {e}")
            if partes:
                df = pd.concat(partes, ignore_index=True)
    with b:
        txt = st.text_area("Uma URL ou domínio por linha", height=160, key="tox_colado",
                           placeholder="https://site-suspeito.xyz/pagina\nspamdomain.top\ndomain:outro.com")
        if txt.strip() and df is None:
            df = toxicos.ler_lista(txt)
    return df


def _resultado(cli, quando, res):
    dados = pd.DataFrame(res.get("dominios") or [])
    if dados.empty:
        st.info("Nenhum domínio na análise.")
        return
    st.markdown("##### 2. Resultado")
    st.caption(f"Análise de {fmt_data(quando, True)} · {res.get('total_linhas', 0)} linha(s), {len(dados)} domínio(s)"
               + (f", {res['paginas_checadas']} página(s) abertas" if res.get("paginas_checadas") else ""))
    if res.get("aviso_dr"):
        st.warning(res["aviso_dr"])
    cont = dados["classificacao"].value_counts()
    m = st.columns(3)
    m[0].metric("Tóxicos (60+)", int(cont.get(toxicos.TOXICO, 0)))
    m[1].metric("Suspeitos (30 a 59)", int(cont.get(toxicos.SUSPEITO, 0)))
    m[2].metric("OK", int(cont.get(toxicos.OK, 0)))

    f1, f2 = st.columns([2, 1])
    filtro = f1.multiselect("Mostrar", list(ICONE), default=[toxicos.TOXICO, toxicos.SUSPEITO],
                            format_func=lambda c: ICONE[c], key="tox_filtro")
    busca = f2.text_input("Buscar domínio", key="tox_busca")
    vis = dados[dados["classificacao"].isin(filtro)] if filtro else dados
    if busca.strip():
        vis = vis[vis["dominio"].str.contains(re.escape(busca.strip().lower()))]
    vis = vis.assign(classe=vis["classificacao"].map(ICONE)).reset_index(drop=True)
    cols = ["decisao", "dominio", "classe", "pontuacao", "dr", "links", "motivos", "ancoras", "exemplo_url"]
    ed = st.data_editor(
        vis[cols], hide_index=True, width="stretch", key=f"tox_ed_{quando}",
        disabled=[c for c in cols if c != "decisao"],
        column_config={
            "decisao": st.column_config.SelectboxColumn("Decisão", options=toxicos.DECISOES, required=True),
            "dominio": "Domínio", "classe": "Classificação",
            "pontuacao": st.column_config.ProgressColumn("Pontuação", min_value=0, max_value=100, format="%d"),
            "dr": st.column_config.NumberColumn("DR", format="%.0f"), "links": "Links",
            "motivos": st.column_config.TextColumn("Motivos", width="large"), "ancoras": "Âncoras",
            "exemplo_url": st.column_config.LinkColumn("Exemplo de URL")})
    st.caption("Ajuste a coluna Decisão e clique em Salvar decisões. Domain Rating by Ahrefs (https://ahrefs.com/)")
    if st.button("💾 Salvar decisões"):
        mudancas = dict(zip(ed["dominio"], ed["decisao"]))
        for d in res["dominios"]:
            if d["dominio"] in mudancas:
                d["decisao"] = mudancas[d["dominio"]]
        storage.salvar_analise(cli["id"], "toxicos", res)
        st.toast("Decisões salvas.")
        st.rerun()

    st.markdown("##### 3. Arquivo de disavow")
    st.info("O Google recomenda usar o disavow só quando há ação manual por links artificiais ou quando você tem "
            "certeza de que há links pagos ou de esquema apontando para o site. Na dúvida, não desautorize: o "
            "Google já ignora a maior parte do spam sozinho. Revise a lista antes de subir no Search Console.")
    desaut = [d["dominio"] for d in res["dominios"] if d.get("decisao") == "Desautorizar"]
    exist = st.file_uploader("Disavow atual do cliente (opcional, para juntar sem perder o que já existe)",
                             type=["txt"], key="tox_exist")
    texto_exist = exist.getvalue().decode("utf-8", errors="ignore") if exist else ""
    arquivo = toxicos.gerar_disavow(cli["nome"], desaut, texto_exist)
    a, b = st.columns(2)
    a.download_button(f"⬇️ Baixar disavow.txt ({len(desaut)} domínio(s) marcados)", arquivo.encode("utf-8"),
                      "disavow.txt", "text/plain", type="primary", disabled=not desaut)
    with b:
        baixar_excel({"Análise": dados.drop(columns=["classe"], errors="ignore")},
                     f"toxicos_{cli['nome']}", "⬇️ Baixar análise em Excel", chave="tox_xl")
    with st.expander("Ver o arquivo"):
        st.code(arquivo, language="text")


def tela():
    cli = exigir_cliente()
    st.title(f"☣️ Links tóxicos · {cli['nome']}")
    df = _entrada()
    if df is not None and not df.empty:
        st.caption(f"{len(df)} linha(s) lida(s), {df['dominio'].nunique()} domínio(s) diferente(s).")
        c1, c2 = st.columns([2, 1])
        checar = c1.checkbox("Abrir as páginas para uma checagem mais profunda (spam no texto, excesso de links, "
                             "página fora do ar)", value=False,
                             help="Mais lento. Abre até 60 páginas, começando pelos domínios de DR mais baixo.")
        if c2.button("☣️ Analisar", type="primary"):
            res = toxicos.analisar(df, core.normalizar_dominio(cli["url"]), chaves()["ahrefs"], checar,
                                   progresso=progresso_streamlit())
            storage.salvar_analise(cli["id"], "toxicos", res)
            st.rerun()
    elif df is not None:
        st.warning("Não encontrei URLs nem domínios nesse conteúdo.")
    quando, res = storage.ultima_analise(cli["id"], "toxicos")
    if res:
        _resultado(cli, quando, res)
    else:
        st.caption("Nenhuma análise salva para este cliente ainda.")
