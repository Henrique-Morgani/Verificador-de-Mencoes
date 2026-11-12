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


def montar(cliente: dict, nov: dict, desde: datetime, ate: datetime) -> tuple[str, str]:
    nl, op, perd = nov["novos_links"], nov["novas_oportunidades"], nov["links_perdidos"]
    periodo = f"{_d(desde)} a {_d(ate)}"
    assunto = (f"[Menções] {cliente['nome']}: {len(nl)} novo(s) backlink(s), "
               f"{len(op)} menção(ões) sem link ({periodo})")

    blocos = [f"""
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:860px;margin:auto;color:#222">
    <h2 style="margin-bottom:4px">Relatório de menções: {_e(cliente['nome'])}</h2>
    <p style="color:#666;margin-top:0">{_e(cliente['url'])} · período de {periodo}</p>
    <table style="margin:16px 0 24px"><tr>
      <td style="padding:12px 20px;background:#ecfdf3;border-radius:8px;text-align:center">
        <div style="font-size:26px;font-weight:bold;color:#067647">{len(nl)}</div>
        <div style="font-size:12px;color:#555">novos backlinks</div></td>
      <td style="width:12px"></td>
      <td style="padding:12px 20px;background:#fff7e6;border-radius:8px;text-align:center">
        <div style="font-size:26px;font-weight:bold;color:#b54708">{len(op)}</div>
        <div style="font-size:12px;color:#555">menções sem link</div></td>
      <td style="width:12px"></td>
      <td style="padding:12px 20px;background:#fef3f2;border-radius:8px;text-align:center">
        <div style="font-size:26px;font-weight:bold;color:#b42318">{len(perd)}</div>
        <div style="font-size:12px;color:#555">links perdidos</div></td>
      <td style="width:12px"></td>
      <td style="padding:12px 20px;background:#f2f4f7;border-radius:8px;text-align:center">
        <div style="font-size:26px;font-weight:bold;color:#344054">{nov['total_links']}</div>
        <div style="font-size:12px;color:#555">backlinks no total</div></td>
    </tr></table>"""]

    if nl:
        blocos.append("<h3>Novos backlinks</h3>")
        blocos.append(_tabela(
            ["Domínio", "DR", "Página", "Tipo", "Anchor"],
            [[_e(m.get("dominio")), _dr(m), _link(m["url"], m.get("titulo") or None),
              "dofollow" if m["status"] == "Com backlink dofollow" else "nofollow/sponsored/ugc",
              _e(m.get("anchors", ""))] for m in nl]))
    if op:
        blocos.append("<h3>Menções sem link (oportunidades de link reclamation)</h3>")
        blocos.append(_tabela(
            ["Domínio", "DR", "Página", "Autor", "Contato"],
            [[_e(m.get("dominio")), _dr(m), _link(m["url"], m.get("titulo") or None),
              _e(m.get("autor", "")), _contato(m)] for m in op]))
    if perd:
        blocos.append("<h3>Links perdidos</h3>")
        blocos.append(_tabela(
            ["Domínio", "DR", "Página", "Status atual"],
            [[_e(m.get("dominio")), _dr(m), _link(m["url"]), _e(m["status"])] for m in perd]))
    if not (nl or op or perd):
        blocos.append('<p style="padding:16px;background:#f9fafb;border-radius:8px">'
                      "Nenhuma novidade neste período. O monitoramento continua ativo.</p>")

    app_url = os.getenv("APP_URL", "")
    rodape = "Enviado automaticamente pelo Verificador de Menções."
    if app_url:
        rodape += f' Veja o histórico completo em {_link(app_url, app_url)}.'
    blocos.append(f'<p style="color:#888;font-size:12px;margin-top:32px">{rodape} '
                  "Domain Rating by Ahrefs.</p></div>")
    return assunto, "".join(blocos)


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
    msg["From"] = f"Verificador de Menções <{remetente}>"
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
