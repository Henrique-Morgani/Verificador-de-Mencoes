"""Resumo do cliente: big numbers, positivos, pontos de atenção, próximas ações e resumo executivo."""

import re

import streamlit as st

import executivo
import ia
import resumo_dados as rd
from comum import exigir_cliente, fmt_data

PERIODOS = {"7 dias": 7, "30 dias": 30, "90 dias": 90}


def _download(cli, f, texto_ia):
    with st.container(border=True):
        st.markdown("##### 📄 Resumo executivo")
        a, b, c = st.columns([1.3, 1, 2.2])
        formato = a.radio("Formato", ["PDF", "PowerPoint"], horizontal=True, key="exec_formato")
        base = re.sub(r"[^\w-]", "_", cli["nome"])
        data = f["ate"].strftime("%Y%m%d")
        b.write("")
        try:
            if formato == "PDF":
                b.download_button("⬇️ Baixar", executivo.gerar_pdf(f, texto_ia), f"resumo_{base}_{data}.pdf",
                                  "application/pdf", type="primary", key="exec_pdf")
            else:
                b.download_button("⬇️ Baixar", executivo.gerar_pptx(f, texto_ia), f"resumo_{base}_{data}.pptx",
                                  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                  type="primary", key="exec_ppt")
        except Exception as e:
            b.error(f"Não consegui gerar: {e}")
        c.caption("Números do período escolhido, destaques, novos backlinks, Digital PR, concorrentes e próximas "
                  "ações. Se gerar o resumo com IA (no fim da página), ele entra no arquivo.")


def tela():
    cli = exigir_cliente()
    st.title(cli["nome"])
    st.caption(cli["url"])
    rot = st.segmented_control("Período", list(PERIODOS), default="30 dias", key="res_periodo") or "30 dias"
    dias = PERIODOS[rot]
    f = rd.fatos(cli, dias)
    chave_ia = f"resumo_ia_{cli['id']}_{dias}"
    _download(cli, f, st.session_state.get(chave_ia, ""))

    cols = st.columns(6)
    for col, (rotulo, valor, detalhe) in zip(cols, rd.big_numbers(f)):
        if rotulo == "DR":
            col.metric(rotulo, valor, delta=f"{f['variacao_dr']:+.0f}" if f["variacao_dr"] else None,
                       help="Domain Rating by Ahrefs. Variação contra o registro mais próximo do início do período.")
        elif rotulo == "Conversas em comunidades":
            col.metric(rotulo, valor, delta=detalhe or None, delta_color="inverse")
        else:
            col.metric(rotulo, valor)

    esq, dir_ = st.columns(2)
    with esq:
        with st.container(border=True):
            st.markdown("##### ✅ Positivos")
            for p in rd.positivos(f) or ["Nada de destaque no período ainda."]:
                st.markdown(f"- {p}")
    with dir_:
        with st.container(border=True):
            st.markdown("##### ⚠️ Atenção")
            for p in rd.atencao(f) or ["Nenhum ponto de atenção."]:
                st.markdown(f"- {p}")

    with st.container(border=True):
        st.markdown("##### 👉 Próximas ações")
        ac = rd.acoes(f)
        if not ac:
            st.caption("Nada pendente.")
        for txt, n in ac:
            st.markdown(f"- **{n}** · {txt}")

    with st.container(border=True):
        st.markdown("##### 🔄 Atualizações")
        ult = f["ultima_execucao"]
        st.markdown(f"- Última busca: **{fmt_data(ult['inicio'], True)}** ({ult['origem']})" if ult
                    else "- Nenhuma busca ainda")
        st.markdown("- Concorrentes: " + (f"dados de {fmt_data(f['analise_concorrentes'])}"
                                          if f["analise_concorrentes"] else "sem análise"))
        st.markdown("- Links tóxicos: " + (f"última análise em {fmt_data(f['analise_toxicos'])}"
                                           if f["analise_toxicos"] else "sem análise"))
        for cp in f["campanhas"]:
            st.markdown(f"- Campanha {cp['nome']}: {cp['materias']} matéria(s), {cp['novas_periodo']} no período"
                        + (" · 🔔 alerta diário" if cp["alerta_diario"] else ""))

    with st.container(border=True):
        st.markdown("##### ✨ Resumo em texto")
        if st.button("Gerar resumo com IA", disabled=not ia.configurado(),
                     help="Usa o Gemini só com os números desta tela."):
            try:
                st.session_state[chave_ia] = ia.resumo_cliente(rd.para_ia(f))
            except Exception as e:
                st.error(f"Gemini: {e}")
        if st.session_state.get(chave_ia):
            st.info(st.session_state[chave_ia])

    st.caption("Domain Rating by Ahrefs (https://ahrefs.com/)")
