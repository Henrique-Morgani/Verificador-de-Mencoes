"""Menções e links do cliente: busca, histórico, outreach e evolução."""

import pandas as pd
import streamlit as st

import fluxo
import storage
from comum import CORES, chaves, exigir_cliente, mostrar_mencoes, progresso_streamlit


def buscar_agora(cli: dict, reverificar: bool):
    k = chaves()
    if not k["serper"]:
        st.error("Falta SERPER_API_KEY nos Secrets.")
        return
    try:
        _, avisos, _ = fluxo.rodar_cliente(cli, origem="manual", chaves=k, reverificar=reverificar,
                                           progresso=progresso_streamlit())
        st.session_state[f"avisos_{cli['id']}"] = avisos
        st.rerun()
    except Exception as e:
        st.error(f"Erro na busca: {e}")


def aba_evolucao(cid: int):
    dados = storage.evolucao_mensal(cid)
    if not dados:
        st.info("Ainda não há histórico suficiente. O gráfico aparece depois das primeiras buscas.")
        return
    ev = pd.DataFrame(dados).set_index("mes")
    st.markdown("##### Backlinks ativos no fim de cada mês")
    st.line_chart(ev[["backlinks_ativos"]].rename(columns={"backlinks_ativos": "Backlinks ativos"}),
                  color=CORES[0], y_label="Backlinks", x_label="Mês")
    st.markdown("##### Movimento do mês")
    mov = ev[["mencoes_novas", "links_ganhos", "links_perdidos"]].rename(columns={
        "mencoes_novas": "Menções novas", "links_ganhos": "Links ganhos", "links_perdidos": "Links perdidos"})
    st.bar_chart(mov, color=CORES[:3], stack=False, y_label="Quantidade", x_label="Mês")
    with st.expander("Ver tabela"):
        st.dataframe(ev, width="stretch")
    cm = storage.creditos_no_mes(cid)
    st.caption(f"Créditos deste cliente no mês: Serper {cm['serper']} · Hunter {cm['hunter']} · "
               f"{cm['execucoes']} busca(s).")


def tela():
    cli = exigir_cliente()
    st.title(f"🔗 Menções e links · {cli['nome']}")
    st.caption("Menções na web e em notícias: quem linka, quem não linka, qualidade do link e contato. "
               "Comunidades ficam em **O que dizem aí**.")
    b1, b2, _ = st.columns([1, 1.6, 3])
    rodar = b1.button("🔎 Buscar agora", type="primary")
    reverificar = b2.checkbox("Reverificar menções salvas", value=True,
                              help="Abre de novo as páginas já guardadas para ver se ganharam ou perderam link.")
    if rodar:
        buscar_agora(cli, reverificar)
    for aviso in st.session_state.get(f"avisos_{cli['id']}", []) or []:
        st.warning(aviso)

    aba1, aba2 = st.tabs(["📋 Histórico", "📈 Evolução"])
    with aba1:
        dados = [m for m in storage.mencoes_do_cliente(cli["id"]) if m["status"] not in storage.STATUS_SOCIAIS]
        mostrar_mencoes(pd.DataFrame(dados) if dados else None, historico=True, cid=cli["id"],
                        nome_base=cli["nome"])
    with aba2:
        aba_evolucao(cli["id"])

