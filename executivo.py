"""Resumo executivo do cliente em PowerPoint (.pptx) ou PDF, a partir de resumo_dados.fatos()."""

from __future__ import annotations

import io
from zoneinfo import ZoneInfo

import core
import resumo_dados as rd

FUSO = ZoneInfo("America/Sao_Paulo")
AZUL_ESCURO = (0x1F, 0x2A, 0x44)
AZUL = (0x2A, 0x78, 0xD6)
VERDE = (0x06, 0x76, 0x47)
LARANJA = (0xB5, 0x47, 0x08)
CINZA = (0x66, 0x70, 0x85)
FUNDO_CARD = (0xF2, 0xF4, 0xF7)
RODAPE = "DizemAI · Domain Rating by Ahrefs"


def _d(dt) -> str:
    return dt.astimezone(FUSO).strftime("%d/%m/%Y") if dt else ""


def _periodo(f) -> str:
    return f"{_d(f['desde'])} a {_d(f['ate'])}"


def _top_links(f, n=10):
    lst = sorted(f["novos_links"], key=lambda m: -(m.get("dr") or -1))[:n]
    return [[m.get("dominio") or "", f"{m['dr']:.0f}" if m.get("dr") is not None else "-",
             "Dofollow" if m["status"] == core.ST_DOFOLLOW else "Nofollow",
             (m.get("titulo") or m["url"])[:70]] for m in lst]


def _tabela_concorrentes(f):
    c = f.get("concorrentes") or {}
    linhas = []
    for v in c.get("visao") or []:
        linhas.append([v.get("nome") or v.get("dominio"), "-" if v.get("dr") is None else f"{v['dr']:.0f}",
                       _n(v.get("refdomains")), _n(v.get("backlinks")), _n(v.get("trafego"))])
    return linhas


def _n(x) -> str:
    if x is None:
        return "-"
    try:
        return f"{int(x):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(x)


def _gap(f, n=8):
    c = f.get("concorrentes") or {}
    return [[g["dominio"], "-" if g.get("dr") is None else f"{g['dr']:.0f}", ", ".join(g.get("linka_para") or [])]
            for g in (c.get("gap") or [])[:n]]


def _campanhas(f):
    return [[c["nome"], str(c["materias"]), str(c["novas_periodo"]), str(c["linkaram_campanha"]),
             str(c["linkaram_site"]), str(c["sem_link"])] for c in f["campanhas"]]


# ------------------------------------------------------------------ PowerPoint

def gerar_pptx(f: dict, texto_ia: str = "") -> bytes:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    vazio = prs.slide_layouts[6]
    cor = lambda t: RGBColor(*t)  # noqa: E731

    def texto(slide, x, y, w, h, txt, tam=14, negrito=False, c=AZUL_ESCURO, alinhar=None):
        caixa = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = caixa.text_frame
        tf.word_wrap = True
        linhas = txt if isinstance(txt, list) else [txt]
        for i, ln in enumerate(linhas):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = ln
            p.font.size, p.font.bold, p.font.name = Pt(tam), negrito, "Arial"
            p.font.color.rgb = cor(c)
            p.space_after = Pt(6)
            if alinhar:
                p.alignment = alinhar
        return caixa

    def novo_slide(titulo):
        s = prs.slides.add_slide(vazio)
        barra = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(0.12))
        barra.fill.solid()
        barra.fill.fore_color.rgb = cor(AZUL)
        barra.line.fill.background()
        texto(s, 0.6, 0.4, 12, 0.8, titulo, 28, True)
        texto(s, 0.6, 6.95, 12, 0.4, f"{f['cliente']} · {_periodo(f)} · {RODAPE}", 10, c=CINZA)
        return s

    def tabela(s, cab, linhas, x=0.6, y=1.5, w=12.1, larguras=None):
        if not linhas:
            texto(s, x, y, w, 0.5, "Sem dados no período.", 14, c=CINZA)
            return
        tb = s.shapes.add_table(len(linhas) + 1, len(cab), Inches(x), Inches(y), Inches(w),
                                Inches(0.4 * (len(linhas) + 1))).table
        if larguras:
            for i, lg in enumerate(larguras):
                tb.columns[i].width = Inches(lg)
        for j, h in enumerate(cab):
            cel = tb.cell(0, j)
            cel.text = h
            cel.fill.solid()
            cel.fill.fore_color.rgb = cor(AZUL_ESCURO)
            p = cel.text_frame.paragraphs[0]
            p.font.size, p.font.bold, p.font.name = Pt(12), True, "Arial"
            p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        for i, ln in enumerate(linhas, start=1):
            for j, v in enumerate(ln):
                cel = tb.cell(i, j)
                cel.text = str(v)
                cel.fill.solid()
                cel.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if i % 2 else cor(FUNDO_CARD)
                p = cel.text_frame.paragraphs[0]
                p.font.size, p.font.name = Pt(11), "Arial"
                p.font.color.rgb = cor(AZUL_ESCURO)

    # Capa
    s = prs.slides.add_slide(vazio)
    fundo = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    fundo.fill.solid()
    fundo.fill.fore_color.rgb = cor(AZUL_ESCURO)
    fundo.line.fill.background()
    texto(s, 0.9, 2.3, 11.5, 1, "Resumo executivo de off page", 40, True, (0xFF, 0xFF, 0xFF))
    texto(s, 0.9, 3.4, 11.5, 0.8, f['cliente'], 28, False, (0xC8, 0xD8, 0xF0))
    texto(s, 0.9, 4.2, 11.5, 0.6, f"Período: {_periodo(f)} ({f['periodo_dias']} dias)", 16, False, (0xC8, 0xD8, 0xF0))
    texto(s, 0.9, 6.6, 11.5, 0.4, "DizemAI", 14, True, (0xFF, 0xFF, 0xFF))

    # Big numbers
    s = novo_slide("Números do período")
    for i, (rot, val, det) in enumerate(rd.big_numbers(f)):
        x, y = 0.6 + (i % 3) * 4.1, 1.6 + (i // 3) * 2.5
        card = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(3.8), Inches(2.2))
        card.fill.solid()
        card.fill.fore_color.rgb = cor(FUNDO_CARD)
        card.line.fill.background()
        texto(s, x + 0.3, y + 0.25, 3.3, 0.5, rot, 14, c=CINZA)
        texto(s, x + 0.3, y + 0.7, 3.3, 1, val, 40, True)
        if det:
            texto(s, x + 0.3, y + 1.6, 3.3, 0.4, det, 12, c=CINZA)

    # Destaques
    s = novo_slide("Destaques")
    texto(s, 0.6, 1.4, 5.9, 0.5, "Positivos", 18, True, VERDE)
    texto(s, 0.6, 1.95, 5.9, 4.8, [f"• {p}" for p in rd.positivos(f, rich=False)] or ["Nada de destaque."], 14)
    texto(s, 6.9, 1.4, 5.9, 0.5, "Pontos de atenção", 18, True, LARANJA)
    texto(s, 6.9, 1.95, 5.9, 4.8, [f"• {p}" for p in rd.atencao(f, rich=False)] or ["Nenhum ponto de atenção."], 14)

    if texto_ia:
        s = novo_slide("Leitura do período")
        texto(s, 0.6, 1.5, 12.1, 5.2, texto_ia, 16)

    s = novo_slide("Novos backlinks (maiores DR)")
    tabela(s, ["Domínio", "DR", "Tipo", "Página"], _top_links(f), larguras=[3.4, 0.9, 1.4, 6.4])

    if f["campanhas"]:
        s = novo_slide("Digital PR")
        tabela(s, ["Campanha", "Matérias", "No período", "Link p/ campanha", "Link p/ site", "Sem link"],
               _campanhas(f), larguras=[4.1, 1.4, 1.5, 1.9, 1.6, 1.6])

    if _tabela_concorrentes(f):
        s = novo_slide("Comparativo com concorrentes")
        tabela(s, ["Site", "DR", "Domínios de ref.", "Backlinks", "Tráfego orgânico"], _tabela_concorrentes(f),
               larguras=[3.6, 1.2, 2.4, 2.4, 2.5])
        gap = _gap(f, 6)
        if gap:
            texto(s, 0.6, 1.6 + 0.4 * (len(_tabela_concorrentes(f)) + 1) + 0.3, 12, 0.4,
                  "Link gap (sites que linkam para concorrentes e não para o cliente): "
                  + ", ".join(g[0] for g in gap), 12, c=CINZA)

    s = novo_slide("Próximas ações")
    ac = rd.acoes(f)
    texto(s, 0.6, 1.5, 12.1, 5, [f"• {n} · {t}" for t, n in ac] or ["Nada pendente."], 18)

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ PDF

def gerar_pdf(f: dict, texto_ia: str = "") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    rgb = lambda t: colors.Color(*(v / 255 for v in t))  # noqa: E731
    est = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=est["Title"], textColor=rgb(AZUL_ESCURO), alignment=0, fontSize=22)
    h2 = ParagraphStyle("h2", parent=est["Heading2"], textColor=rgb(AZUL_ESCURO), spaceBefore=14)
    corpo = ParagraphStyle("c", parent=est["BodyText"], fontSize=10.5, leading=15)
    cinza = ParagraphStyle("g", parent=corpo, textColor=rgb(CINZA), fontSize=9)

    def esc(t):
        return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def tab(cab, linhas, larguras):
        if not linhas:
            return Paragraph("Sem dados no período.", cinza)
        dados = [[Paragraph(f"<b>{esc(h)}</b>", ParagraphStyle("th", parent=corpo, textColor=colors.white,
                                                                 fontSize=9))
                  for h in cab]] + [[Paragraph(esc(v), ParagraphStyle("td", parent=corpo, fontSize=9, leading=12))
                                     for v in ln] for ln in linhas]
        t = Table(dados, colWidths=[w * cm for w in larguras], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), rgb(AZUL_ESCURO)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, rgb(FUNDO_CARD)]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, rgb((0xE4, 0xE7, 0xEC))),
        ]))
        return t

    def rodape(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(rgb(CINZA))
        canvas.drawString(2 * cm, 1.2 * cm, f"{f['cliente']} · {_periodo(f)} · {RODAPE}")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {doc.page}")
        canvas.restoreState()

    els = [Paragraph("Resumo executivo de off page", h1),
           Paragraph(f"<b>{esc(f['cliente'])}</b> · {esc(f['url'])}", corpo),
           Paragraph(f"Período: {_periodo(f)} ({f['periodo_dias']} dias)", cinza), Spacer(1, 12)]

    bn = rd.big_numbers(f)
    celulas = [[Paragraph(f"<font color='#667085' size='9'>{esc(r)}</font><br/>"
                          f"<font size='20'><b>{esc(v)}</b></font><br/>"
                          f"<font color='#667085' size='8'>{esc(d) or '&nbsp;'}</font>",
                          ParagraphStyle("bn", parent=corpo, leading=22)) for r, v, d in bn[i:i + 3]]
               for i in (0, 3)]
    t = Table(celulas, colWidths=[5.6 * cm] * 3, rowHeights=[2.4 * cm] * 2)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), rgb(FUNDO_CARD)),
                           ("BOX", (0, 0), (-1, -1), 4, colors.white),
                           ("INNERGRID", (0, 0), (-1, -1), 4, colors.white),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    els.append(t)

    els.append(Paragraph("Positivos", ParagraphStyle("hv", parent=h2, textColor=rgb(VERDE))))
    els += [Paragraph(f"• {esc(p)}", corpo) for p in rd.positivos(f, rich=False)] or [Paragraph("Nada de destaque.", cinza)]
    els.append(Paragraph("Pontos de atenção", ParagraphStyle("ha", parent=h2, textColor=rgb(LARANJA))))
    els += [Paragraph(f"• {esc(p)}", corpo) for p in rd.atencao(f, rich=False)] or [Paragraph("Nenhum.", cinza)]

    if texto_ia:
        els += [Paragraph("Leitura do período", h2), Paragraph(esc(texto_ia), corpo)]

    els += [Paragraph("Novos backlinks (maiores DR)", h2),
            tab(["Domínio", "DR", "Tipo", "Página"], _top_links(f), [4.2, 1.2, 2, 9.4])]
    if f["campanhas"]:
        els += [Paragraph("Digital PR", h2),
                tab(["Campanha", "Matérias", "No período", "Link p/ campanha", "Link p/ site", "Sem link"],
                    _campanhas(f), [5.2, 1.9, 2, 2.6, 2.3, 2.8])]
    if _tabela_concorrentes(f):
        els += [Paragraph("Comparativo com concorrentes", h2),
                tab(["Site", "DR", "Domínios de ref.", "Backlinks", "Tráfego orgânico"], _tabela_concorrentes(f),
                    [5, 1.6, 3.4, 3.4, 3.4])]
        gap = _gap(f)
        if gap:
            els += [Paragraph("Link gap: sites que linkam para concorrentes e não para o cliente", h2),
                    tab(["Domínio", "DR", "Linka para"], gap, [6, 1.6, 9.2])]
    els.append(Paragraph("Próximas ações", h2))
    els += [Paragraph(f"• <b>{n}</b> · {esc(t)}", corpo) for t, n in rd.acoes(f)] or [Paragraph("Nada pendente.", cinza)]

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                      bottomMargin=2 * cm, title=f"Resumo executivo {f['cliente']}").build(
        els, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()
