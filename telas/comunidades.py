"""O que dizem aí: conversas sobre a marca, sobre a categoria e sobre os concorrentes em comunidades."""

import hashlib
from datetime import timedelta

import pandas as pd
import streamlit as st

import ia
import storage
from comum import CONFIG_COLUNAS, ICONE_SENT, exigir_cliente, fmt_data, limpar_para_tabela

PERIODOS_DIAS = {"Últimos 7 dias": 7, "Últimos 30 dias": 30, "Últimos 90 dias": 90}
SENTIMENTOS = ["positiva", "neutra", "mista", "negativa"]


def _termometro(atual: list[dict], anterior: list[dict]):
    def contar(lst):
        return {s: sum(1 for m in lst if m.get("sentimento") == s) for s in SENTIMENTOS}
    a, b = contar(atual), contar(anterior)
    cols = st.columns(5)
    cols[0].metric("Conversas no período", len(atual), delta=len(atual) - len(anterior) if anterior else None)
    for i, s in enumerate(["positiva", "negativa", "neutra", "mista"], start=1):
        cols[i].metric(ICONE_SENT[s].capitalize(), a[s], delta=(a[s] - b[s]) if anterior else None,
                       delta_color="inverse" if s == "negativa" else "normal")
    total = sum(a.values())
    if total:
        saldo = (a["positiva"] - a["negativa"]) / total
        st.progress((saldo + 1) / 2, text=f"Termômetro: saldo {saldo:+.0%} (positivas menos negativas, "
                                          f"sobre {total} classificadas)")


def _assuntos(lst: list[dict]):
    if not any(m.get("assunto") for m in lst):
        st.caption("Os assuntos aparecem depois que o Gemini classificar as conversas.")
        return
    df = pd.DataFrame([{"Assunto": m.get("assunto") or "Sem assunto", "Sentimento": m.get("sentimento") or "neutra"}
                       for m in lst])
    tab = df.pivot_table(index="Assunto", columns="Sentimento", aggfunc="size", fill_value=0)
    for s in SENTIMENTOS:
        if s not in tab.columns:
            tab[s] = 0
    tab = tab[SENTIMENTOS]
    tab["Total"] = tab.sum(axis=1)
    tab = tab.sort_values("Total", ascending=False).head(12)
    st.bar_chart(tab[SENTIMENTOS], horizontal=True, stack=True,
                 color=["#1baf7a", "#9aa4b2", "#d4a017", "#d64545"], x_label="Conversas", y_label="")


def _fila(cli: dict, lst: list[dict], chave: str, marca: str):
    pend = [m for m in lst if m.get("conversa_status") in storage.CONVERSA_PENDENTES
            and (m.get("pergunta_indicacao") == "Sim" or m.get("sentimento") == "negativa")]
    pend.sort(key=lambda m: (m.get("sentimento") != "negativa", -(m["primeira_vez"].timestamp()
                                                                  if m.get("primeira_vez") else 0)))
    st.markdown(f"##### Precisa de resposta ({len(pend)})")
    if not pend:
        st.caption("Nada pendente: negativas e pedidos de indicação aparecem aqui até alguém tratar.")
        return
    for m in pend[:20]:
        rotulo = ("🔴 " if m.get("sentimento") == "negativa" else "❓ ") + (m.get("titulo") or m["url"])[:110]
        with st.expander(rotulo):
            st.markdown(f"[{m.get('dominio')}]({m['url']}) · {fmt_data(m.get('primeira_vez'))} · "
                        f"{ICONE_SENT.get(m.get('sentimento'), 'não classificada')} · {m.get('assunto') or ''}")
            if m.get("motivo_sentimento"):
                st.write(f"**Resumo:** {m['motivo_sentimento']}")
            if m.get("trecho_mencao") or m.get("snippet"):
                st.caption(m.get("trecho_mencao") or m.get("snippet"))
            k = f"{chave}_{hashlib.sha1(m['url'].encode()).hexdigest()[:10]}"
            st.session_state.setdefault("resp" + k, m.get("conversa_resposta") or "")
            if st.button("✨ Sugerir resposta", key="sug" + k, disabled=not ia.configurado()):
                try:
                    texto = ia.sugerir_resposta(marca, m.get("dominio", ""), m.get("titulo", ""),
                                                m.get("trecho_mencao") or m.get("snippet", ""),
                                                tipo=m.get("status", ""), contexto=cli["url"])
                    storage.definir_conversa(cli["id"], [m["url"]], resposta=texto)
                    st.session_state["resp" + k] = texto
                    st.rerun()
                except Exception as e:
                    st.error(f"Gemini: {e}")
            resp = st.text_area("Rascunho de resposta (revise antes de publicar)", key="resp" + k, height=120)
            c1, c2, c3 = st.columns([1.4, 2, 1])
            status = c1.selectbox("Status", storage.CONVERSA_OPCOES,
                                  index=storage.CONVERSA_OPCOES.index(m.get("conversa_status") or "Nova"),
                                  key="st" + k)
            obs = c2.text_input("Observação", value=m.get("conversa_obs") or "", key="obs" + k)
            c3.write("")
            if c3.button("Salvar", key="sv" + k, type="primary"):
                storage.definir_conversa(cli["id"], [m["url"]], status=status, obs=obs, resposta=resp)
                st.rerun()


def _feed(lst: list[dict], chave: str):
    if not lst:
        return
    df = pd.DataFrame(lst)
    df["sentimento_vis"] = df.get("sentimento", pd.Series(dtype=object)).map(
        lambda s: ICONE_SENT.get(s, "") if isinstance(s, str) else "")
    df["encontrada_em"] = df["primeira_vez"].map(fmt_data)
    f1, f2 = st.columns(2)
    sent = f1.multiselect("Sentimento", SENTIMENTOS, key="fsent" + chave, placeholder="Todos")
    sts = f2.multiselect("Status da conversa", storage.CONVERSA_OPCOES, key="fst" + chave, placeholder="Todos")
    if sent:
        df = df[df["sentimento"].isin(sent)]
    if sts:
        df = df[df["conversa_status"].isin(sts)]
    cols = ["encontrada_em", "sentimento_vis", "pergunta_indicacao", "assunto", "motivo_sentimento", "dominio",
            "url", "titulo", "marca", "conversa_status", "conversa_obs", "trecho_mencao"]
    df = limpar_para_tabela(df.reset_index(drop=True), cols)
    st.dataframe(df[cols], hide_index=True, width="stretch",
                 column_config={**CONFIG_COLUNAS, "encontrada_em": st.column_config.TextColumn("Encontrada em"),
                                "conversa_obs": st.column_config.TextColumn("Obs.")})


def _bloco(cli, todas, status, dias, chave, marca):
    agora = storage.agora()
    ini, ini_ant = agora - timedelta(days=dias), agora - timedelta(days=2 * dias)
    lst = [m for m in todas if m["status"] == status]
    atual = [m for m in lst if m.get("primeira_vez") and m["primeira_vez"] >= ini]
    anterior = [m for m in lst if m.get("primeira_vez") and ini_ant <= m["primeira_vez"] < ini]
    if not lst:
        return False
    _termometro(atual, anterior)
    st.markdown("##### Assuntos do período")
    _assuntos(atual)
    _fila(cli, lst, chave, marca)
    st.markdown("##### Todas as conversas")
    _feed(lst, chave)
    return True


def tela():
    cli = exigir_cliente()
    cfg = cli.get("config") or {}
    st.title(f"💬 O que dizem aí · {cli['nome']}")
    st.caption("Conversas em Reddit, Quora, Reclame Aqui e outras comunidades. A agência acompanha, sugere "
               "resposta e registra o que foi feito. Atualiza a cada busca do cliente (manual ou robô).")
    if not ia.configurado():
        st.warning("Sem GEMINI_API_KEY: as conversas ficam sem sentimento, assunto e sugestão de resposta.")
    dias = PERIODOS_DIAS[st.segmented_control("Período", list(PERIODOS_DIAS), default="Últimos 30 dias",
                                              key="com_periodo") or "Últimos 30 dias"]
    todas = storage.mencoes_do_cliente(cli["id"])
    a1, a2, a3 = st.tabs(["Sobre a marca", "Conversas da categoria", "Concorrentes nas comunidades"])
    with a1:
        if not _bloco(cli, todas, storage.ST_COMUNIDADE, dias, "marca", cli["nome"]):
            st.info("Nenhuma menção em comunidade ainda. Escolha as comunidades em **Configurações do cliente** "
                    "e rode uma busca em **Menções e links**.")
    with a2:
        if not _bloco(cli, todas, storage.ST_CATEGORIA, dias, "cat", cli["nome"]):
            st.info("Cadastre frases da categoria em **Configurações do cliente** (ex.: \"indicação de "
                    "higienização de sofá\"). São pedidos de indicação que não citam a marca: ótimas portas "
                    "de entrada.")
    with a3:
        conc = [m for m in todas if m["status"] == storage.ST_COMUNIDADE_CONC]
        if not conc and not cfg.get("concorrentes"):
            st.info("Cadastre concorrentes em **Configurações do cliente** para comparar.")
        elif not conc:
            st.info("Nenhuma conversa sobre concorrentes encontrada ainda.")
        else:
            agora = storage.agora()
            ini = agora - timedelta(days=dias)
            marca_l = [m for m in todas if m["status"] == storage.ST_COMUNIDADE and m.get("primeira_vez")
                       and m["primeira_vez"] >= ini]
            linhas = [{"Marca": cli["nome"], **{s: sum(1 for m in marca_l if m.get("sentimento") == s)
                                                for s in SENTIMENTOS}, "Total": len(marca_l)}]
            nomes = sorted({(m.get("marca") or "").strip() for m in conc if m.get("marca")})
            for n in nomes:
                lst = [m for m in conc if m.get("marca") == n and m.get("primeira_vez") and m["primeira_vez"] >= ini]
                linhas.append({"Marca": n, **{s: sum(1 for m in lst if m.get("sentimento") == s)
                                              for s in SENTIMENTOS}, "Total": len(lst)})
            comp = pd.DataFrame(linhas).set_index("Marca")
            st.markdown("##### Comparativo de conversas no período")
            st.bar_chart(comp[SENTIMENTOS], horizontal=True, stack=True,
                         color=["#1baf7a", "#9aa4b2", "#d4a017", "#d64545"], x_label="Conversas", y_label="")
            st.dataframe(comp, width="stretch")
            st.markdown("##### Conversas sobre concorrentes")
            _feed(conc, "conc")
