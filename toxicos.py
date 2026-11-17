"""
Análise de links tóxicos a partir de uma lista enviada pela pessoa (export do Ahrefs, Semrush ou Search Console,
planilha qualquer ou lista colada) e geração do arquivo de disavow.

A pontuação é heurística e explicada (cada ponto tem um motivo). Serve para triagem: a decisão final de
desautorizar é da pessoa. O Google recomenda disavow só com ação manual ou links artificiais claros.
"""

from __future__ import annotations

import io
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pandas as pd
from bs4 import BeautifulSoup

import core

TOXICO, SUSPEITO, OK = "Tóxico", "Suspeito", "OK"

TLDS_SPAM = {"xyz", "top", "icu", "click", "loan", "work", "buzz", "gq", "tk", "ml", "cf", "ga", "pw", "bid", "win",
             "review", "stream", "download", "racing", "date", "men", "party", "trade", "webcam", "accountant",
             "cricket", "science", "faith", "kim", "rest", "cyou", "monster", "sbs", "cfd", "quest", "best", "lol"}
TLDS_ATENCAO = {"ru", "su", "cn", "online", "site", "website", "space", "fun", "info", "biz", "shop", "store", "link"}
PALAVRAS_SPAM = ["casino", "cassino", "bet", "apostas", "poker", "slot", "porn", "sex", "xxx", "adult", "escort",
                 "viagra", "cialis", "pharma", "pills", "payday", "loan", "emprestimo-rapido", "replica",
                 "essay", "bitcoin-", "crypto-", "forex-", "dating", "hookup", "hentai", "nude", "gambling",
                 "jogo-do-bicho", "tigrinho", "fortune-tiger"]
PALAVRAS_SEO = ["backlink", "linkdir", "directory", "diretorio", "seo-", "-seo", "rank", "submit", "bookmark",
                "linkfarm", "pbn", "webstats", "siteprice", "websiteworth", "statshow", "domaintools", "whois",
                "similar-sites", "sitelike", "worth", "traffic-", "-traffic", "hypestat", "site-analyzer"]

COLS_URL = ["referring page url", "source url", "url de origem", "url from", "url_from", "linking page", "pagina",
            "página", "source", "referring page", "url"]
COLS_DOM = ["referring domain", "domain", "domínio", "dominio", "linking site", "sites com links", "site", "host"]
COLS_ANCORA = ["anchor", "âncora", "ancora", "anchor text", "texto âncora", "link text"]
COLS_DR = ["domain rating", "dr", "page ascore", "authority score", "as", "ascore"]
COLS_LINKS = ["links to target", "external links", "backlinks", "links", "dofollow links"]


def _achar(colunas, opcoes, evitar=("rating", "score", "target", "destino", "title", "titulo")):
    norm = {c: core.sem_acento(str(c)).lower().strip() for c in colunas}
    norm_sub = {c: n for c, n in norm.items() if not any(e in n for e in evitar)}
    for op in opcoes:
        op_n = core.sem_acento(op).lower()
        for c, n in norm.items():
            if n == op_n:
                return c
    for op in opcoes:
        op_n = core.sem_acento(op).lower()
        if len(op_n) < 4:
            continue
        for c, n in norm_sub.items():
            if op_n in n:
                return c
    return None


def ler_arquivo(nome: str, conteudo: bytes) -> pd.DataFrame:
    """Lê CSV, TSV, TXT ou Excel de qualquer ferramenta e devolve um DataFrame com colunas padronizadas:
    url, dominio, ancora, dr, links."""
    nome = (nome or "").lower()
    if nome.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(conteudo))
    else:
        texto = None
        for enc in ("utf-8-sig", "utf-16", "latin-1"):
            try:
                texto = conteudo.decode(enc)
                if "\x00" not in texto:
                    break
            except UnicodeDecodeError:
                continue
        texto = texto or ""
        primeira = texto.splitlines()[0] if texto.strip() else ""
        if not any(s in primeira for s in (",", ";", "\t")) or nome.endswith(".txt") and "http" in primeira:
            return ler_lista(texto)
        sep = "\t" if "\t" in primeira else (";" if primeira.count(";") > primeira.count(",") else ",")
        df = pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, on_bad_lines="skip")
    return padronizar(df)


def ler_lista(texto: str) -> pd.DataFrame:
    """Uma URL ou domínio por linha. Linhas de disavow (domain:x) e comentários (#) também são aceitas."""
    linhas = []
    for ln in (texto or "").splitlines():
        ln = ln.strip().strip(",;\"'")
        if not ln or ln.startswith("#"):
            continue
        if ln.lower().startswith("domain:"):
            linhas.append({"url": "", "dominio": core.normalizar_dominio(ln[7:])})
        else:
            linhas.append({"url": ln if ln.startswith("http") else "", "dominio": core.normalizar_dominio(ln)})
    return pd.DataFrame(linhas, columns=["url", "dominio", "ancora", "dr", "links"]).fillna({"ancora": ""})


def padronizar(df: pd.DataFrame) -> pd.DataFrame:
    c_url, c_dom = _achar(df.columns, COLS_URL), _achar(df.columns, COLS_DOM)
    if c_url is None and c_dom is None:
        c_url = df.columns[0]  # sem cabeçalho reconhecível: a primeira coluna
    out = pd.DataFrame()
    out["url"] = df[c_url].astype(str) if c_url is not None else ""
    if c_dom is not None and (c_url is None or core.sem_acento(str(c_dom)).lower() in COLS_DOM):
        out["dominio"] = df[c_dom].astype(str).map(core.normalizar_dominio)
    else:
        out["dominio"] = out["url"].map(core.normalizar_dominio)
    c_anc, c_lk = _achar(df.columns, COLS_ANCORA), _achar(df.columns, COLS_LINKS)
    c_dr = _achar(df.columns, COLS_DR, evitar=("target", "destino"))
    out["ancora"] = df[c_anc].astype(str) if c_anc is not None else ""
    out["dr"] = pd.to_numeric(df[c_dr], errors="coerce") if c_dr is not None else None
    out["links"] = pd.to_numeric(df[c_lk], errors="coerce") if c_lk is not None else None
    out = out[out["dominio"].astype(str).str.contains(r"\.", regex=True)]
    out["url"] = out["url"].where(out["url"].astype(str).str.startswith("http"), "")
    return out.fillna({"ancora": "", "url": ""}).reset_index(drop=True)


def _tem(texto: str, palavras, dominio: bool = False) -> list[str]:
    """Domínio: o termo tem que começar uma parte do nome (betano, my-bet; não alphabet).
    Texto: palavra inteira (sex, não sexta)."""
    t = core.sem_acento(texto or "").lower()
    achados = []
    for p in palavras:
        nucleo = re.escape(p if dominio else p.strip("-"))
        padrao = (nucleo if p.startswith("-") else rf"(?<![a-z0-9]){nucleo}") if dominio else rf"(?<![a-z0-9]){nucleo}s?(?![a-z0-9])"
        if re.search(padrao, t):
            achados.append(p.strip("-"))
    return list(dict.fromkeys(achados))


def _checar_pagina(url: str) -> dict:
    status, final, html, _ = core.baixar_completo(url)
    r = {"http": status}
    if not html:
        return r
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    r["noindex"] = bool(meta and "noindex" in (meta.get("content") or "").lower())
    host = core.normalizar_dominio(final or url)
    externos = [a for a in soup.find_all("a", href=True)
                if a["href"].startswith("http") and not core.pertence_ao_dominio(core.normalizar_dominio(a["href"]), host)]
    r["links_externos"] = len(externos)
    r["spam_pagina"] = _tem(soup.get_text(" ")[:20000], PALAVRAS_SPAM)[:5]
    return r


def analisar(df: pd.DataFrame, dominio_cliente: str, ahrefs_key: str = "", checar_paginas: bool = False,
             max_paginas: int = 60, progresso=None) -> dict:
    """Pontua cada domínio de 0 a 100 e classifica em Tóxico (60+), Suspeito (30 a 59) ou OK."""
    log = progresso or (lambda etapa, frac: None)
    df = df[~df["dominio"].map(lambda d: core.pertence_ao_dominio(d, dominio_cliente))]
    grupos = {}
    for _, r in df.iterrows():
        d = r["dominio"]
        g = grupos.setdefault(d, {"dominio": d, "urls": [], "ancoras": set(), "dr": None, "links": 0})
        if r.get("url"):
            g["urls"].append(r["url"])
        if r.get("ancora") and str(r["ancora"]).strip() not in ("", "nan"):
            g["ancoras"].add(str(r["ancora"]).strip()[:120])
        if pd.notna(r.get("dr")) and r.get("dr") is not None:
            g["dr"] = float(r["dr"])
        g["links"] += int(r["links"]) if pd.notna(r.get("links")) and r.get("links") is not None else 1

    log("Buscando DR", 0.1)
    sem_dr = [d for d, g in grupos.items() if g["dr"] is None]
    aviso_dr = ""
    if sem_dr and ahrefs_key:
        drs, aviso_dr = core.buscar_dr(sem_dr, ahrefs_key)
        for d, v in drs.items():
            if d in grupos and v is not None:
                grupos[d]["dr"] = float(v)

    paginas = {}
    if checar_paginas:
        alvo = sorted(grupos.values(), key=lambda g: (g["dr"] if g["dr"] is not None else -1))[:max_paginas]
        urls = [g["urls"][0] if g["urls"] else f"https://{g['dominio']}/" for g in alvo]
        with ThreadPoolExecutor(8) as ex:
            for i, (u, res) in enumerate(zip(urls, ex.map(_checar_pagina, urls))):
                paginas[core.normalizar_dominio(u)] = res
                log(f"Abrindo páginas ({i + 1}/{len(urls)})", 0.2 + 0.7 * (i + 1) / len(urls))

    saida = []
    for d, g in grupos.items():
        pontos, motivos = 0, []

        def soma(p, m):
            nonlocal pontos
            pontos += p
            motivos.append(m)

        tld = d.rsplit(".", 1)[-1]
        if tld in TLDS_SPAM:
            soma(25, f"extensão .{tld} muito usada por spam")
        elif tld in TLDS_ATENCAO:
            soma(10, f"extensão .{tld}")
        sp = _tem(d, PALAVRAS_SPAM, dominio=True)
        if sp:
            soma(40, "domínio com termo de spam: " + ", ".join(sp[:3]))
        seo = _tem(d, PALAVRAS_SEO, dominio=True)
        if seo:
            soma(30, "diretório, agregador de métricas ou site de SEO: " + ", ".join(seo[:3]))
        nome = d.rsplit(".", 1)[0]
        if nome.count("-") >= 3:
            soma(10, "muitos hífens no domínio")
        if sum(ch.isdigit() for ch in nome) >= 4:
            soma(10, "muitos números no domínio")
        if len(nome) > 30:
            soma(5, "domínio muito longo")
        anc = " ".join(g["ancoras"])
        sp_a = _tem(anc, PALAVRAS_SPAM)
        if sp_a:
            soma(35, "âncora com termo de spam: " + ", ".join(sp_a[:3]))
        if re.search(r"[Ѐ-ӿ一-鿿؀-ۿ฀-๿]", anc):
            soma(15, "âncora em alfabeto estrangeiro (cirílico, chinês, árabe ou tailandês)")
        if g["links"] >= 100:
            soma(10, f"{g['links']} links do mesmo domínio (sitewide)")
        if g["dr"] is not None:
            if g["dr"] < 5:
                soma(20, f"DR {g['dr']:.0f}")
            elif g["dr"] < 15:
                soma(10, f"DR {g['dr']:.0f}")
            elif g["dr"] >= 50 and pontos:
                pontos -= 20
                motivos.append(f"DR {g['dr']:.0f} alto (reduz a pontuação)")
        pg = paginas.get(d) or {}
        if pg:
            if pg.get("spam_pagina"):
                soma(30, "página com termos de spam: " + ", ".join(pg["spam_pagina"][:3]))
            if (pg.get("links_externos") or 0) >= 150:
                soma(15, f"página com {pg['links_externos']} links externos")
            if pg.get("noindex"):
                soma(5, "página com noindex")
            if pg.get("http") in (0, 404, 410) or (pg.get("http") or 0) >= 500:
                motivos.append(f"página não abriu (HTTP {pg.get('http')}): o link pode nem existir mais")
        pontos = max(0, min(100, pontos))
        classe = TOXICO if pontos >= 60 else SUSPEITO if pontos >= 30 else OK
        saida.append({"dominio": d, "pontuacao": pontos, "classificacao": classe, "dr": g["dr"],
                      "links": g["links"], "motivos": "; ".join(motivos), "ancoras": " | ".join(sorted(g["ancoras"]))[:300],
                      "exemplo_url": g["urls"][0] if g["urls"] else "",
                      "decisao": "Desautorizar" if classe == TOXICO else "Revisar" if classe == SUSPEITO else "Manter"})
    saida.sort(key=lambda x: (-x["pontuacao"], x["dominio"]))
    log("Concluído", 1.0)
    return {"dominios": saida, "total_linhas": int(len(df)), "aviso_dr": aviso_dr,
            "paginas_checadas": len(paginas)}


DECISOES = ["Desautorizar", "Revisar", "Manter"]


def gerar_disavow(cliente: str, dominios: list[str], existente: str = "") -> str:
    """Arquivo no formato do Google: comentários com # e uma linha domain:exemplo.com por domínio.
    Se vier um disavow existente, mantém as linhas dele e acrescenta só os domínios novos."""
    ja = set()
    linhas_exist = []
    for ln in (existente or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        linhas_exist.append(s)
        if s.lower().startswith("domain:"):
            ja.add(core.normalizar_dominio(s[7:]))
    novos = sorted({core.normalizar_dominio(d) for d in dominios} - ja)
    cab = [f"# Disavow gerado pelo DizemAI para {cliente} em {datetime.now():%d/%m/%Y}",
           f"# {len(novos)} domínio(s) novo(s)" + (f", {len(ja)} já existente(s)" if ja else "")]
    return "\n".join((linhas_exist + [""] if linhas_exist else []) + cab + [f"domain:{d}" for d in novos]) + "\n"
