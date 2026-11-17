"""Alertas por email e itens ignorados."""

import re
from datetime import timedelta

import streamlit as st

import core
import pr
import relatorio
import storage
from comum import exigir_cliente, fmt_data

FREQUENCIAS = {"Quinzenal": 14, "Semanal": 7, "Mensal": 30}
FREQ_INV = {v: k for k, v in FREQUENCIAS.items()}


def _nov(cid, desde):
    nov = storage.novidades(cid, desde)
    nov["campanhas"] = pr.resumo_campanhas(cid, desde)
    return nov


def _emails(cliente):
    cid = cliente["id"]
    st.write("O robô roda todo dia de manhã. Toda segunda ele faz uma nova busca do cliente, reverifica as menções "
             "salvas e manda para cada email as novidades desde o último envio. Se houver menção negativa em "
             "comunidade, o assunto começa com ⚠️ NEGATIVA. Campanhas de Digital PR em alerta diário mandam um "
             "email no dia em que sai matéria nova.")
    if not storage.usando_banco_externo():
        st.error("Configure DATABASE_URL nos Secrets. Sem banco externo, o robô não enxerga os clientes.")
    if not relatorio.smtp_configurado():
        st.warning("Envio de email não configurado (SMTP_USUARIO e SMTP_SENHA nos Secrets).")

    inscr = storage.listar_inscricoes(cid)
    if not inscr:
        st.caption("Nenhum email cadastrado ainda.")
    for i in inscr:
        prox = (i["ultimo_envio"] + timedelta(days=i["frequencia_dias"])) if i["ultimo_envio"] else None
        c1, c2, c3, c4, c5 = st.columns([2.2, 1, 1.6, 1, 0.8])
        c1.write(f"**{i['email']}**")
        c2.write(FREQ_INV.get(i["frequencia_dias"], f"{i['frequencia_dias']} dias"))
        c3.write(f"Último envio: {fmt_data(i['ultimo_envio']) or 'ainda não'}"
                 + (f"  \nPróximo: na segunda a partir de {fmt_data(prox)}" if prox else "  \nPróximo: na próxima segunda"))
        if c4.button("Enviar prévia", key=f"prev_{i['id']}", disabled=not relatorio.smtp_configurado()):
            desde = storage.agora() - timedelta(days=i["frequencia_dias"])
            try:
                assunto, corpo = relatorio.montar(cliente, _nov(cid, desde), desde, storage.agora())
                relatorio.enviar(i["email"], "[Prévia] " + assunto, corpo)
                st.toast(f"Prévia enviada para {i['email']}.")
            except Exception as e:
                st.error(f"Falha ao enviar: {e}")
        if c5.button("Remover", key=f"rm_{i['id']}"):
            storage.remover_inscricao(i["id"])
            st.rerun()

    with st.form("nova_inscricao", clear_on_submit=True):
        f1, f2, f3 = st.columns([2.5, 1, 1])
        email = f1.text_input("Adicionar email", placeholder="nome@empresa.com")
        freq = f2.selectbox("Frequência", list(FREQUENCIAS), index=0)
        f3.write("")
        if f3.form_submit_button("Adicionar", type="primary"):
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()):
                st.error("Email inválido.")
            else:
                storage.adicionar_inscricao(cid, email, FREQUENCIAS[freq])
                st.rerun()

    with st.expander("Ver como fica o email (últimos 14 dias)"):
        desde = storage.agora() - timedelta(days=14)
        assunto, corpo = relatorio.montar(cliente, _nov(cid, desde), desde, storage.agora())
        st.caption(f"Assunto: {assunto}")
        st.html(corpo)


def _ignorados(cid):
    st.write("URLs e domínios ignorados não aparecem nas tabelas, nos emails nem nas próximas buscas.")
    itens = storage.listar_ignorados(cid)
    if not itens:
        st.caption("Nada ignorado ainda. Use a seleção de linhas em Menções e links.")
    for it in itens:
        c1, c2, c3 = st.columns([1, 5, 1])
        c1.write("Domínio" if it["tipo"] == "dominio" else "URL")
        c2.write(it["valor"])
        if c3.button("Restaurar", key=f"rest_{it['id']}"):
            storage.restaurar_ignorado(it["id"])
            st.rerun()
    with st.form("ignorar_manual", clear_on_submit=True):
        g1, g2, g3 = st.columns([1, 4, 1])
        tipo = g1.selectbox("Tipo", ["dominio", "url"], format_func=lambda t: "Domínio" if t == "dominio" else "URL")
        valor = g2.text_input("Adicionar manualmente", placeholder="exemplo.com.br ou URL completa")
        g3.write("")
        if g3.form_submit_button("Ignorar") and valor.strip():
            storage.ignorar(cid, tipo, [core.normalizar_dominio(valor) if tipo == "dominio" else valor.strip()])
            st.rerun()


def tela():
    cli = exigir_cliente()
    st.title(f"✉️ Alertas e ignorados · {cli['nome']}")
    a, b = st.tabs(["Emails automáticos", "Ignorados"])
    with a:
        _emails(cli)
    with b:
        _ignorados(cli["id"])
