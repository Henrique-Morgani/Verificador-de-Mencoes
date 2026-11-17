"""Monta e envia o relatório de novidades por email (SMTP, por padrão o Gmail)."""

from __future__ import annotations

import html
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")


def smtp_configurado() -> bool:
    return bool(os.getenv("SMTP_USUARIO") and os.getenv("SMTP_SENHA"))


def _d(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(FUSO).strftime("%d/%m/%Y")


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _dr(m) -> str:
    return "" if m.get("dr") is None else f"{m['dr']:.0f}"


def _tabela(cabecalho: list[str], linhas: list[list[str]]) -> str:
    th = "".join(f'<th style="text-align:left;padding:8px;border-bottom:2px solid #ddd;'
                 f'font-size:13px;color:#555">{h}</th>' for h in cabecalho)
    corpo = ""
    for ln in linhas:
        corpo += "<tr>" + "".join(
            f'<td style="padding:8px;border-bottom:1px solid #eee;font-size:13px;vertical-align:top">{c}</td>'
            for c in ln) + "</tr>"
    return (f'<table style="border-collapse:collapse;width:100%;margin:8px 0 24px">'
            f"<thead><tr>{th}</tr></thead><tbody>{corpo}</tbody></table>")


def _link(url: str, texto: str | None = None) -> str:
    if not url:
        return ""
    t = texto or (url if len(url) <= 70 else url[:67] + "...")
    return f'<a href="{_e(url)}" style="color:#1a56db">{_e(t)}</a>'


def _contato(m: dict) -> str:
    partes = []
    for k in ("autor_email", "hunter_email_autor"):
        if m.get(k):
            partes.append(_e(m[k]))
    if m.get("emails"):
        partes.append(_e(str(m["emails"]).split(",")[0]))
    if m.get("autor_linkedin"):
        partes.append(_link(m["autor_linkedin"], "LinkedIn"))
    if m.get("whatsapp"):
        partes.append(_link(str(m["whatsapp"]).split(",")[0], "WhatsApp"))
    return "<br>".join(dict.fromkeys(partes))


def _card(valor, rotulo, fundo, cor):
    return (f'<td style="padding:12px 16px;background:{fundo};border-radius:8px;text-align:center">'
            f'<div style="font-size:24px;font-weight:bold;color:{cor}">{valor}</div>'
            f'<div style="font-size:12px;color:#555">{rotulo}</div></td><td style="width:10px"></td>')


def _titulo_secao(texto, cor="#222"):
    return f'<h3 style="color:{cor};margin:24px 0 4px">{texto}</h3>'


def montar(cliente: dict, nov: dict, desde: datetime, ate: datetime) -> tuple[str, str]:
    nl, op, perd = nov["novos_links"], nov["novas_oportunidades"], nov["links_perdidos"]
    neg, perg = nov.get("negativas", []), nov.get("perguntas", [])
    outras, prosp, queb = nov.get("comunidade_outras", []), nov.get("prospects", []), nov.get("links_quebrados", [])
    periodo = f"{_d(desde)} a {_d(ate)}"

    partes_assunto = [f"{len(nl)} novo(s) backlink(s)", f"{len(op)} menção(ões) sem link"]
    if perg:
        partes_assunto.append(f"{len(perg)} pergunta(s) em comunidades")
    assunto = f"[DizemAI] {cliente['nome']}: " + ", ".join(partes_assunto) + f" ({periodo})"
    if neg:
        assunto = f"⚠️ NEGATIVA | {len(neg)} menção(ões) negativa(s) em comunidades | " + assunto

    blocos = [f"""
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:860px;margin:auto;color:#222">
    <h2 style="margin-bottom:4px">DizemAI · relatório de {_e(cliente['nome'])}</h2>
    <p style="color:#666;margin-top:0">{_e(cliente['url'])} · período de {periodo}</p>
    <table style="margin:16px 0 8px"><tr>
      {_card(len(nl), "novos backlinks", "#ecfdf3", "#067647")}
      {_card(len(op), "menções sem link", "#fff7e6", "#b54708")}
      {_card(len(neg), "negativas em comunidades", "#fef3f2", "#b42318")}
      {_card(len(perd) + len(queb), "links perdidos ou quebrados", "#fef3f2", "#b42318")}
      {_card(nov['total_links'], "backlinks no total", "#f2f4f7", "#344054")}
    </tr></table>"""]

    if neg:
        blocos.append(_titulo_secao("⚠️ Menções negativas em comunidades", "#b42318"))
        blocos.append(_tabela(
            ["Onde", "Post", "Motivo", "Confiança"],
            [[_e(m.get("dominio")), _link(m["url"], m.get("titulo") or None),
              _e(m.get("motivo_sentimento", "")) + (" <b>(também é pergunta/pedido de indicação)</b>"
                                                    if m.get("pergunta_indicacao") == "Sim" else ""),
              _e(m.get("confianca_sentimento", ""))] for m in neg]))
    if perg:
        blocos.append(_titulo_secao("❓ Perguntas e pedidos de indicação", "#1a56db"))
        blocos.append(_tabela(
            ["Onde", "Post", "Sentimento", "Resumo"],
            [[_e(m.get("dominio")), _link(m["url"], m.get("titulo") or None),
              _e(m.get("sentimento", "")), _e(m.get("motivo_sentimento", ""))] for m in perg]))
    if nl:
        blocos.append(_titulo_secao("Novos backlinks"))
        blocos.append(_tabela(
            ["Domínio", "DR", "Página", "Tipo", "Qualidade", "Anchor"],
            [[_e(m.get("dominio")), _dr(m), _link(m["url"], m.get("titulo") or None),
              "dofollow" if m["status"] == "Com backlink dofollow" else "nofollow/sponsored/ugc",
              _e(m.get("qualidade_link", "")), _e(m.get("anchors", ""))] for m in nl]))
    if op:
        blocos.append(_titulo_secao("Menções sem link (oportunidades de link reclamation)"))
        blocos.append(_tabela(
            ["Domínio", "DR", "Página", "Autor", "Contato"],
            [[_e(m.get("dominio")), _dr(m), _link(m["url"], m.get("titulo") or None),
              _e(m.get("autor", "")), _contato(m)] for m in op]))
    if queb:
        blocos.append(_titulo_secao("Links para páginas quebradas do cliente", "#b54708"))
        blocos.append(_tabela(
            ["Domínio", "DR", "Página que linka", "Destino do link", "Contato"],
            [[_e(m.get("dominio")), _dr(m), _link(m["url"], m.get("titulo") or None),
              _e(m.get("destino_link", "")) + "<br>" + _e(m.get("urls_linkadas", "")), _contato(m)]
             for m in queb]))
    if perd:
        blocos.append(_titulo_secao("Links perdidos"))
        blocos.append(_tabela(
            ["Domínio", "DR", "Página", "Status atual"],
            [[_e(m.get("dominio")), _dr(m), _link(m["url"]), _e(m["status"])] for m in perd]))
    if prosp:
        blocos.append(_titulo_secao("Prospects: sites que citam concorrentes e não citam o cliente"))
        blocos.append(_tabela(
            ["Domínio", "DR", "Página", "Concorrentes citados", "Contato"],
            [[_e(m.get("dominio")), _dr(m), _link(m["url"], m.get("titulo") or None),
              _e(m.get("concorrentes_citados", "")), _contato(m)] for m in prosp[:30]]))
    cat = nov.get("categoria", [])
    if cat:
        blocos.append(_titulo_secao("💡 Pedidos de indicação na categoria (sem citar a marca)", "#1a56db"))
        blocos.append(_tabela(
            ["Onde", "Post", "Resumo"],
            [[_e(m.get("dominio")), _link(m["url"], m.get("titulo") or None), _e(m.get("motivo_sentimento", ""))]
             for m in cat[:20]]))
    camps = nov.get("campanhas", [])
    if camps:
        blocos.append(_titulo_secao("📣 Campanhas de Digital PR"))
        blocos.append(_tabela(
            ["Campanha", "Matérias no período", "Linkaram para a campanha (total)", "Citaram sem link (total)"],
            [[_e(c["nome"]), str(c["novas_periodo"]), str(c["campanha"]), str(c["sem_link"])] for c in camps]))
    if outras:
        blocos.append(_titulo_secao("Outras menções em comunidades"))
        blocos.append(_tabela(
            ["Onde", "Post", "Sentimento", "Resumo"],
            [[_e(m.get("dominio")), _link(m["url"], m.get("titulo") or None),
              _e(m.get("sentimento", "") or "não classificada"), _e(m.get("motivo_sentimento", ""))]
             for m in outras]))
    if not (nl or op or perd or neg or perg or outras or prosp or queb or cat):
        blocos.append('<p style="padding:16px;background:#f9fafb;border-radius:8px">'
                      "Nenhuma novidade neste período. O monitoramento continua ativo.</p>")

    app_url = os.getenv("APP_URL", "")
    rodape = "Enviado automaticamente pelo DizemAI."
    if app_url:
        rodape += f' Veja o histórico completo em {_link(app_url, app_url)}.'
    blocos.append(f'<p style="color:#888;font-size:12px;margin-top:32px">{rodape} '
                  "Domain Rating by Ahrefs.</p></div>")
    return assunto, "".join(blocos)


STATUS_COR = {"Linkou para a campanha": "#067647", "Linkou para o site": "#1a56db", "Citou sem link": "#b54708",
             "Link da campanha quebrado": "#b42318"}


def montar_campanha(cliente: dict, camp: dict, novas: list[dict], ind: dict) -> tuple[str, str]:
    """Email do alerta diário de Digital PR: só as matérias novas desde o último envio."""
    assunto = f"[DizemAI PR] {camp['nome']}: {len(novas)} matéria(s) nova(s)"
    linhas = []
    for m in sorted(novas, key=lambda x: -(x.get("dr") or -1)):
        cor = STATUS_COR.get(m.get("status_campanha"), "#555")
        linhas.append([_e(m.get("dominio")), _dr(m), _link(m["url"], m.get("titulo") or None),
                       f'<b style="color:{cor}">{_e(m.get("status_campanha"))}</b>', _contato(m)])
    corpo = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:860px;margin:auto;color:#222">
    <h2 style="margin-bottom:4px">Cobertura nova: {_e(camp['nome'])}</h2>
    <p style="color:#666;margin-top:0">{_e(cliente['nome'])} · lançamento em {_e(camp.get('lancamento'))}</p>
    <table style="margin:16px 0 8px"><tr>
      {_card(ind['materias'], "matérias no total", "#f2f4f7", "#344054")}
      {_card(ind['campanha'], "linkaram para a campanha", "#ecfdf3", "#067647")}
      {_card(ind['site'], "linkaram só para o site", "#eff4ff", "#1a56db")}
      {_card(ind['sem_link'], "citaram sem link", "#fff7e6", "#b54708")}
    </tr></table>
    {_titulo_secao("Matérias novas")}
    {_tabela(["Veículo", "DR", "Matéria", "Link", "Contato"], linhas)}
    <p style="color:#555;font-size:13px">Quem citou sem link ou linkou só para a home é candidato a pedido de ajuste
    do link para a página da campanha.</p>
    <p style="color:#888;font-size:12px;margin-top:32px">Enviado automaticamente pelo DizemAI.
    Domain Rating by Ahrefs.</p></div>"""
    return assunto, corpo


def enviar(para: str, assunto: str, corpo_html: str):
    usuario = os.getenv("SMTP_USUARIO", "")
    senha = os.getenv("SMTP_SENHA", "").replace(" ", "")
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    porta = int(os.getenv("SMTP_PORTA", "465"))
    remetente = os.getenv("SMTP_REMETENTE", usuario)
    if not (usuario and senha):
        raise RuntimeError("SMTP não configurado (faltam SMTP_USUARIO e SMTP_SENHA).")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = assunto
    msg["From"] = f"DizemAI <{remetente}>"
    msg["To"] = para
    msg.attach(MIMEText("Abra este email em um leitor com suporte a HTML.", "plain", "utf-8"))
    msg.attach(MIMEText(corpo_html, "html", "utf-8"))

    contexto = ssl.create_default_context()
    if porta == 465:
        with smtplib.SMTP_SSL(host, porta, context=contexto, timeout=30) as s:
            s.login(usuario, senha)
            s.sendmail(remetente, [para], msg.as_string())
    else:
        with smtplib.SMTP(host, porta, timeout=30) as s:
            s.starttls(context=contexto)
            s.login(usuario, senha)
            s.sendmail(remetente, [para], msg.as_string())
