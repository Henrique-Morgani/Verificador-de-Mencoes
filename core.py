"""
Núcleo do Verificador de Menções.

Fluxo:
1. Busca no Google (via Serper.dev) cada termo entre aspas, excluindo o site do cliente.
2. Abre cada página encontrada e confirma se o termo aparece de fato no texto.
3. Procura links apontando para o domínio do cliente (com anchor e rel).
4. Puxa o DR de cada domínio pela API da Ahrefs.
5. Procura meios de contato no site (emails, telefones, WhatsApp, redes sociais, formulário).
"""

from __future__ import annotations

import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}
TIMEOUT = 15

# Domínios que normalmente não interessam como menção (redes sociais, buscadores etc.)
EXCLUIR_PADRAO = [
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "tiktok.com", "pinterest.com", "google.com", "wikipedia.org",
    "reclameaqui.com.br", "glassdoor.com.br", "glassdoor.com", "indeed.com",
]

REDES = {
    "Instagram": "instagram.com",
    "LinkedIn": "linkedin.com",
    "Facebook": "facebook.com",
    "X/Twitter": ("twitter.com", "x.com"),
    "YouTube": "youtube.com",
    "TikTok": "tiktok.com",
}

PALAVRAS_CONTATO = [
    "contato", "contact", "fale-conosco", "faleconosco", "fale conosco", "anuncie",
    "advertise", "publicidade", "sobre", "about", "expediente", "redacao", "redação",
    "quem-somos", "quem somos", "equipe", "team", "parcerias", "imprensa", "press",
]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
EMAIL_IGNORAR = re.compile(
    r"\.(png|jpe?g|gif|webp|svg|css|js)$|sentry|wixpress|example\.|exemplo\.|"
    r"@2x|@3x|noreply|no-reply|domain\.com|email\.com|seuemail|seu-email",
    re.I,
)
TEL_RE = re.compile(r"(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[\s.\-]?\d{4}")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def normalizar_dominio(url_ou_dominio: str) -> str:
    """'https://www.Site.com.br/x' -> 'site.com.br'"""
    s = url_ou_dominio.strip()
    if "://" not in s:
        s = "http://" + s
    host = urlparse(s).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def pertence_ao_dominio(host: str, dominio: str) -> bool:
    host = host.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host == dominio or host.endswith("." + dominio)


def sem_acento(txt: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", txt) if not unicodedata.combining(c)
    ).lower()


def baixar(url: str, sessao: requests.Session | None = None) -> tuple[int, str, str]:
    """Retorna (status, url_final, html). Status 0 = erro de conexão."""
    s = sessao or requests
    try:
        r = s.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype and "xml" not in ctype and ctype:
            return r.status_code, r.url, ""
        if "charset" not in ctype.lower():
            m = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', r.content[:3000], re.I)
            r.encoding = m.group(1).decode() if m else (r.apparent_encoding or "utf-8")
        return r.status_code, r.url, r.text
    except requests.RequestException:
        return 0, url, ""


def decodificar_cfemail(hexstr: str) -> str:
    """Decodifica emails protegidos pelo Cloudflare (data-cfemail)."""
    try:
        chave = int(hexstr[:2], 16)
        return "".join(
            chr(int(hexstr[i:i + 2], 16) ^ chave) for i in range(2, len(hexstr), 2)
        )
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# 1. Busca de menções (Serper.dev)
# ---------------------------------------------------------------------------

def montar_query(termo: str, dominio_cliente: str, excluir: list[str]) -> str:
    partes = [f'"{termo}"', f"-site:{dominio_cliente}"]
    partes += [f"-site:{d}" for d in excluir if d]
    return " ".join(partes)


def buscar_serper(
    query: str,
    api_key: str,
    pais: str = "br",
    idioma: str = "pt-br",
    paginas: int = 1,
    periodo: str = "",
    tipo: str = "search",
) -> list[dict]:
    """tipo: 'search' (web) ou 'news' (Google Notícias)."""
    resultados = []
    for pagina in range(1, paginas + 1):
        corpo = {"q": query, "gl": pais, "hl": idioma, "num": 10, "page": pagina}
        if periodo:
            corpo["tbs"] = f"qdr:{periodo}"
        r = requests.post(
            f"https://google.serper.dev/{tipo}",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json=corpo,
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Serper retornou {r.status_code}: {r.text[:200]}")
        dados = r.json()
        itens = dados.get("organic" if tipo == "search" else "news", [])
        if not itens:
            break
        for it in itens:
            resultados.append({
                "url": it.get("link", ""),
                "titulo": it.get("title", ""),
                "snippet": it.get("snippet", ""),
                "data": it.get("date", ""),
            })
        if len(itens) < 10:
            break
    return resultados


# ---------------------------------------------------------------------------
# 2 e 3. Análise da página: menção confirmada + backlinks
# ---------------------------------------------------------------------------

@dataclass
class LinkCliente:
    href: str
    anchor: str
    rel: str
    dofollow: bool


@dataclass
class AnalisePagina:
    status_http: int = 0
    url_final: str = ""
    termos_encontrados: list[str] = field(default_factory=list)
    trecho: str = ""
    links: list[LinkCliente] = field(default_factory=list)
    meta_nofollow: bool = False
    autor: str = ""
    autor_url: str = ""
    publicado_em: str = ""
    html: str = ""


def analisar_pagina(
    url: str, dominio_cliente: str, termos: list[str], sessao=None
) -> AnalisePagina:
    a = AnalisePagina()
    a.status_http, a.url_final, a.html = baixar(url, sessao)
    if not a.html:
        return a

    soup = BeautifulSoup(a.html, "html.parser")

    robots = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    if robots and "nofollow" in (robots.get("content") or "").lower():
        a.meta_nofollow = True

    a.autor, a.autor_url = extrair_autor(soup, a.url_final)
    pub = soup.find("meta", attrs={"property": "article:published_time"})
    if pub:
        a.publicado_em = (pub.get("content") or "")[:10]

    # Links para o cliente (antes de remover header/footer, link em rodapé também conta)
    for tag in soup.find_all("a", href=True):
        href = urljoin(a.url_final, tag["href"].strip())
        host = urlparse(href).netloc
        if host and pertence_ao_dominio(host, dominio_cliente):
            rel = " ".join(tag.get("rel") or []).lower()
            dofollow = not any(x in rel for x in ("nofollow", "sponsored", "ugc"))
            if a.meta_nofollow:
                dofollow = False
            a.links.append(LinkCliente(
                href=href,
                anchor=tag.get_text(" ", strip=True)[:120] or "(imagem/sem texto)",
                rel=rel or "(nenhum)",
                dofollow=dofollow,
            ))

    # Texto visível para confirmar menção
    for t in soup(["script", "style", "noscript", "template"]):
        t.decompose()
    texto = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    texto_norm = sem_acento(texto)

    for termo in termos:
        tn = sem_acento(termo)
        pos = texto_norm.find(tn)
        if pos >= 0:
            a.termos_encontrados.append(termo)
            if not a.trecho:
                ini, fim = max(0, pos - 120), min(len(texto), pos + len(termo) + 120)
                a.trecho = ("…" if ini else "") + texto[ini:fim] + ("…" if fim < len(texto) else "")
    return a


# ---------------------------------------------------------------------------
# 4. DR (Ahrefs)
# ---------------------------------------------------------------------------

def buscar_dr(dominios: list[str], api_key: str = "") -> tuple[dict, str]:
    """
    Endpoint gratuito da Ahrefs (não consome unidades), mas exige chave APIv3.
    A chave pode ser de uma conta gratuita: Account settings > API keys.
    Retorna ({dominio: dr}, mensagem_de_erro).
    """
    dominios = sorted(set(d for d in dominios if d))
    resultado: dict[str, float | None] = {d: None for d in dominios}
    if not dominios:
        return resultado, ""
    base = "https://api.ahrefs.com/v3/public/domain-rating-free"
    cab = {"Accept": "application/json", "User-Agent": UA}
    erros: list[str] = []

    if not api_key:
        # Tenta sem chave (o anúncio da Ahrefs dizia que não precisava). Se recusar, avisa.
        try:
            r = requests.get(base, params={"target": dominios[0], "output": "json"}, headers=cab, timeout=30)
            ok = r.status_code == 200
        except requests.RequestException:
            ok = False
        if not ok:
            return resultado, ("A Ahrefs não liberou o DR sem chave. O endpoint é gratuito, mas exige "
                               "uma chave APIv3: crie uma conta gratuita na Ahrefs e gere em "
                               "Account settings > API keys. Depois coloque em AHREFS_API_KEY nos Secrets.")
    else:
        cab["Authorization"] = f"Bearer {api_key}"

    # Tentativa em lote (até 1000 por chamada; só com chave)
    for i in range(0, len(dominios) if api_key else 0, 1000):
        lote = dominios[i:i + 1000]
        try:
            r = requests.post(base, headers=cab, json={"targets": lote}, timeout=60)
            if r.status_code == 200:
                for item in _extrair_lista_dr(r.json()):
                    alvo = normalizar_dominio(item.get("target", ""))
                    if alvo in resultado:
                        resultado[alvo] = _numero_dr(item.get("domain_rating"))
            else:
                erros.append(f"lote {r.status_code}: {r.text[:150]}")
        except (requests.RequestException, ValueError) as e:
            erros.append(f"lote: {e}")

    # Completa um a um o que faltou
    def um(d):
        for tentativa in range(3):
            try:
                r = requests.get(base, params={"target": d, "output": "json"}, headers=cab, timeout=30)
            except requests.RequestException as e:
                return d, None, str(e)
            if r.status_code == 200:
                return d, _numero_dr(r.json().get("domain_rating")), ""
            if r.status_code == 429:
                time.sleep(2 * (tentativa + 1))
                continue
            return d, None, f"{r.status_code}: {r.text[:150]}"
        return d, None, "429: limite de requisições"

    faltando = [d for d, v in resultado.items() if v is None]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for d, dr, erro in ex.map(um, faltando):
            resultado[d] = dr
            if erro:
                erros.append(f"{d} {erro}")

    msg = ""
    if all(v is None for v in resultado.values()) and erros:
        msg = "A Ahrefs recusou as consultas de DR. Detalhe: " + erros[-1]
    return resultado, msg


def _numero_dr(v):
    if isinstance(v, dict):
        v = v.get("domain_rating")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _extrair_lista_dr(js) -> list[dict]:
    """Aceita as variações de formato da resposta em lote."""
    if isinstance(js, dict):
        for chave in ("targets", "domain_rating", "data", "results"):
            v = js.get(chave)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
            if isinstance(v, dict) and isinstance(v.get("targets"), list):
                return v["targets"]
    if isinstance(js, list):
        return [x for x in js if isinstance(x, dict)]
    return []


# ---------------------------------------------------------------------------
# 5. Contatos
# ---------------------------------------------------------------------------

@dataclass
class Contatos:
    emails: set = field(default_factory=set)
    telefones: set = field(default_factory=set)
    whatsapp: set = field(default_factory=set)
    redes: dict = field(default_factory=dict)
    paginas_contato: set = field(default_factory=set)
    formulario: bool = False

    def mesclar_html(self, html: str, url_base: str):
        soup = BeautifulSoup(html, "html.parser")

        for el in soup.select("[data-cfemail]"):
            e = decodificar_cfemail(el.get("data-cfemail", ""))
            if EMAIL_RE.fullmatch(e or ""):
                self.emails.add(e.lower())

        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            low = href.lower()
            if low.startswith("mailto:"):
                e = low[7:].split("?")[0].strip()
                if EMAIL_RE.fullmatch(e):
                    self.emails.add(e)
            elif low.startswith("tel:"):
                self.telefones.add(re.sub(r"[^\d+]", "", href[4:]))
            elif "wa.me/" in low or "api.whatsapp.com" in low or "whatsapp.com/send" in low:
                self.whatsapp.add(href)
            else:
                abs_url = urljoin(url_base, href)
                host = urlparse(abs_url).netloc.lower()
                for nome, dom in REDES.items():
                    doms = dom if isinstance(dom, tuple) else (dom,)
                    if any(pertence_ao_dominio(host, d) for d in doms):
                        caminho = urlparse(abs_url).path.strip("/")
                        if caminho and not re.match(r"^(share|sharer|intent|dialog|plugins)", caminho):
                            self.redes.setdefault(nome, abs_url.split("?")[0])

        if soup.find("form") and soup.find(["textarea"]):
            self.formulario = True

        texto = soup.get_text(" ")
        texto = re.sub(r"\s*[\[(]\s*(at|arroba)\s*[\])]\s*", "@", texto, flags=re.I)
        texto = re.sub(r"\s*[\[(]\s*(dot|ponto)\s*[\])]\s*", ".", texto, flags=re.I)
        for e in EMAIL_RE.findall(texto):
            if not EMAIL_IGNORAR.search(e):
                self.emails.add(e.lower().strip("."))

    def como_dict(self) -> dict:
        return {
            "emails": ", ".join(sorted(self.emails)),
            "telefones": ", ".join(sorted(self.telefones)),
            "whatsapp": ", ".join(sorted(self.whatsapp)),
            "redes_sociais": ", ".join(f"{k}: {v}" for k, v in sorted(self.redes.items())),
            "paginas_contato": ", ".join(sorted(self.paginas_contato)),
            "tem_formulario": "Sim" if self.formulario else "Não",
        }


def buscar_contatos(dominio: str, artigos: list[tuple[str, str]] | None = None,
                    max_paginas: int = 6) -> dict:
    """artigos: lista de (url, html) já baixados desse domínio, para reaproveitar."""
    c = Contatos()
    sessao = requests.Session()
    for url_artigo, html_artigo in artigos or []:
        if html_artigo:
            c.mesclar_html(html_artigo, url_artigo)

    status, url_home, html_home = baixar(f"https://{dominio}/", sessao)
    if not html_home:
        status, url_home, html_home = baixar(f"http://{dominio}/", sessao)
    candidatos: list[str] = []
    if html_home:
        c.mesclar_html(html_home, url_home)
        soup = BeautifulSoup(html_home, "html.parser")
        for tag in soup.find_all("a", href=True):
            alvo = urljoin(url_home, tag["href"])
            if not pertence_ao_dominio(urlparse(alvo).netloc, dominio):
                continue
            chave = sem_acento(alvo + " " + tag.get_text(" ", strip=True))
            if any(sem_acento(p) in chave for p in PALAVRAS_CONTATO):
                alvo = alvo.split("#")[0]
                if alvo not in candidatos and alvo.rstrip("/") != url_home.rstrip("/"):
                    candidatos.append(alvo)

    # caminhos comuns, caso a home não linke
    for caminho in ("/contato", "/contact", "/fale-conosco", "/anuncie", "/sobre", "/expediente"):
        u = f"https://{dominio}{caminho}"
        if u not in candidatos:
            candidatos.append(u)

    visitadas = 0
    for u in candidatos:
        if visitadas >= max_paginas:
            break
        st, final, html = baixar(u, sessao)
        if st == 200 and html:
            visitadas += 1
            c.paginas_contato.add(final)
            c.mesclar_html(html, final)
    return c


# ---------------------------------------------------------------------------
# 6. Autor / jornalista
# ---------------------------------------------------------------------------

AUTOR_GENERICO = re.compile(
    r"reda[cç][aã]o|equipe|admin|editorial|assessoria|staff|colaborador|"
    r"conte[uú]do|marketing|^por$|an[oô]nimo|ag[eê]ncia|estad[aã]o conte|folhapress|reuters|"
    r"\bafp\b|\bap\b|efe|press release|patrocinado|publieditorial|branded",
    re.I,
)


def _limpar_nome(n: str) -> str:
    n = re.sub(r"\s+", " ", n or "").strip(" |-–,")
    n = re.sub(r"^(por|by|de|escrito por|texto)\s*:?\s+", "", n, flags=re.I)
    n = re.split(r"\s[|•·]\s|\s-\s|,\s", n)[0].strip()
    if len(n) > 60 or len(n) < 3 or "@" in n or "http" in n:
        return ""
    return n


def extrair_autor(soup: BeautifulSoup, url_base: str) -> tuple[str, str]:
    """Tenta achar nome e página do autor: JSON-LD, meta, rel=author, byline."""
    import json
    nome, url = "", ""

    def do_ld(obj):
        nonlocal nome, url
        if isinstance(obj, list):
            for o in obj:
                do_ld(o)
            return
        if not isinstance(obj, dict):
            return
        if "@graph" in obj:
            do_ld(obj["@graph"])
        aut = obj.get("author") or obj.get("creator")
        if aut and not nome:
            if isinstance(aut, list):
                aut = aut[0] if aut else None
            if isinstance(aut, dict):
                nome = _limpar_nome(str(aut.get("name", "")))
                u = aut.get("url") or aut.get("@id") or ""
                if isinstance(u, str) and u.startswith("http") and "#" not in u.split("/")[-1]:
                    url = u
            elif isinstance(aut, str):
                nome = _limpar_nome(aut)

    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            do_ld(json.loads(sc.string or sc.get_text() or "{}"))
        except (ValueError, TypeError):
            continue
        if nome:
            break

    if not nome:
        for attrs in ({"name": "author"}, {"property": "article:author"}, {"name": "parsely-author"},
                      {"name": "sailthru.author"}, {"name": "dc.creator"}):
            m = soup.find("meta", attrs={k: re.compile(f"^{re.escape(v)}$", re.I) for k, v in attrs.items()})
            if m and m.get("content"):
                c = m["content"].strip()
                if c.startswith("http"):
                    url = url or c
                else:
                    nome = _limpar_nome(c)
                if nome:
                    break

    link_autor = soup.find("a", rel=lambda r: r and "author" in r)
    if link_autor is None:
        link_autor = soup.find("a", href=re.compile(r"/(autor|author|autores|authors|colunista|colunistas|equipe|perfil)/", re.I))
    if link_autor is not None:
        if not url:
            url = urljoin(url_base, link_autor.get("href", ""))
        if not nome:
            nome = _limpar_nome(link_autor.get_text(" ", strip=True))

    if not nome:
        el = soup.find(attrs={"itemprop": "author"}) or soup.find(
            class_=re.compile(r"(^|[-_ ])(author|autor|byline)([-_ ]|name|$)", re.I))
        if el is not None:
            nome = _limpar_nome(el.get_text(" ", strip=True))

    if url and not urlparse(url).netloc:
        url = ""
    return nome, url


def autor_generico(nome: str) -> bool:
    return not nome or bool(AUTOR_GENERICO.search(nome)) or len(nome.split()) < 2


def perfis_autor_google(nome: str, serper_key: str, buscador, pais: str, idioma: str) -> dict:
    """1 crédito do Serper por autor. Procura LinkedIn, X, Muck Rack e Instagram."""
    q = (f'"{nome}" (site:linkedin.com/in OR site:x.com OR site:twitter.com '
         f'OR site:muckrack.com OR site:instagram.com)')
    try:
        res = buscador(q, serper_key, pais, idioma, 1, "", "search")
    except Exception:
        return {}
    sobrenome = sem_acento(nome.split()[-1])
    achou: dict[str, str] = {}
    for r in res:
        link, titulo = r.get("url", ""), sem_acento(r.get("titulo", "") + " " + r.get("url", ""))
        if sobrenome not in titulo:
            continue
        host = urlparse(link).netloc.lower()
        if "linkedin.com" in host and "/in/" in link:
            achou.setdefault("autor_linkedin", link)
        elif host.endswith("x.com") or "twitter.com" in host:
            if not re.search(r"/status/", link):
                achou.setdefault("autor_x", link)
        elif "muckrack.com" in host:
            achou.setdefault("autor_muckrack", link)
        elif "instagram.com" in host and "/p/" not in link:
            achou.setdefault("autor_instagram", link)
    return achou


# ---------------------------------------------------------------------------
# 7. Hunter.io (opcional, plano grátis com créditos mensais)
# ---------------------------------------------------------------------------

CARGOS_IMPRENSA = re.compile(
    r"edit|jornal|journal|report|rep[oó]rter|reda|news|conte[uú]d|content|comunica|"
    r"pauta|colun|marketing|publicidade|comercial|parcer|partner|seo|m[ií]dia|media",
    re.I,
)


def hunter_email_autor(dominio: str, nome: str, key: str) -> tuple[dict, str]:
    try:
        r = requests.get("https://api.hunter.io/v2/email-finder",
                         params={"domain": dominio, "full_name": nome, "api_key": key}, timeout=30)
    except requests.RequestException as e:
        return {}, str(e)
    if r.status_code != 200:
        return {}, f"Hunter {r.status_code}: {r.text[:150]}"
    d = (r.json() or {}).get("data") or {}
    if not d.get("email"):
        return {}, ""
    return {
        "hunter_email_autor": d.get("email", ""),
        "hunter_confianca": d.get("score"),
        "hunter_cargo_autor": d.get("position") or "",
        "autor_linkedin_hunter": d.get("linkedin_url") or d.get("linkedin") or "",
    }, ""


def hunter_emails_veiculo(dominio: str, key: str, limite: int = 10) -> tuple[str, str]:
    try:
        r = requests.get("https://api.hunter.io/v2/domain-search",
                         params={"domain": dominio, "api_key": key, "limit": limite}, timeout=30)
    except requests.RequestException as e:
        return "", str(e)
    if r.status_code != 200:
        return "", f"Hunter {r.status_code}: {r.text[:150]}"
    emails = ((r.json() or {}).get("data") or {}).get("emails") or []
    itens = []
    for e in emails:
        nome = " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x)
        cargo = e.get("position") or e.get("department") or ""
        desc = ", ".join(x for x in (nome, cargo) if x)
        itens.append((0 if CARGOS_IMPRENSA.search(cargo or "") else 1,
                      f"{e.get('value')}" + (f" ({desc})" if desc else "")))
    itens.sort()
    return " | ".join(i[1] for i in itens), ""


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------

def classificar(a: AnalisePagina) -> str:
    if a.status_http == 0:
        return "Erro ao acessar"
    if not a.html:
        return f"Página bloqueada/indisponível ({a.status_http})"
    if not a.termos_encontrados:
        return "Termo não encontrado na página"
    if any(l.dofollow for l in a.links):
        return "Com backlink dofollow"
    if a.links:
        return "Com backlink nofollow/sponsored/ugc"
    return "Menção sem link (oportunidade)"


OPORTUNIDADES = {"Menção sem link (oportunidade)", "Com backlink nofollow/sponsored/ugc"}


def executar(
    url_cliente: str,
    termos: list[str],
    serper_key: str,
    ahrefs_key: str = "",
    hunter_key: str = "",
    pais: str = "br",
    idioma: str = "pt-br",
    paginas: int = 1,
    periodo: str = "",
    incluir_noticias: bool = False,
    excluir: list[str] | None = None,
    puxar_dr: bool = True,
    puxar_contatos: bool = True,
    puxar_autor: bool = True,
    perfis_google: bool = False,
    hunter_autor: bool = False,
    hunter_veiculo: bool = False,
    so_oportunidades: bool = True,
    threads: int = 8,
    progresso=None,
    buscador=None,
) -> tuple[list[dict], list[str]]:
    """Roda o fluxo completo. Devolve (linhas, avisos)."""
    log = progresso or (lambda etapa, frac: None)
    buscador = buscador or buscar_serper
    avisos: list[str] = []
    dominio_cliente = normalizar_dominio(url_cliente)
    excluir = [normalizar_dominio(d) for d in (excluir or []) if d.strip()]
    termos = [t.strip() for t in termos if t.strip()]

    # 1. Busca
    achados: dict[str, dict] = {}
    tipos = ["search"] + (["news"] if incluir_noticias else [])
    total_buscas = len(termos) * len(tipos)
    feitas = 0
    for termo in termos:
        q = montar_query(termo, dominio_cliente, excluir)
        for tipo in tipos:
            for r in buscador(q, serper_key, pais, idioma, paginas, periodo, tipo):
                url = r["url"]
                host = urlparse(url).netloc
                if not url or pertence_ao_dominio(host, dominio_cliente):
                    continue
                if any(pertence_ao_dominio(host, d) for d in excluir):
                    continue
                item = achados.setdefault(url, {**r, "termos_busca": set(), "fonte": set()})
                item["termos_busca"].add(termo)
                item["fonte"].add("Notícias" if tipo == "news" else "Web")
            feitas += 1
            log(f"Buscando menções ({feitas}/{total_buscas})", 0.2 * feitas / max(total_buscas, 1))

    if not achados:
        return [], avisos

    # 2 e 3. Análise das páginas
    urls = list(achados)
    analises: dict[str, AnalisePagina] = {}
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futs = {ex.submit(analisar_pagina, u, dominio_cliente, termos): u for u in urls}
        for i, f in enumerate(as_completed(futs), 1):
            analises[futs[f]] = f.result()
            log(f"Analisando páginas ({i}/{len(urls)})", 0.2 + 0.35 * i / len(urls))

    status = {u: classificar(analises[u]) for u in urls}
    dominios = sorted({normalizar_dominio(u) for u in urls})
    dominios_oport = {normalizar_dominio(u) for u in urls if status[u] in OPORTUNIDADES}

    # 4. DR
    drs: dict[str, float | None] = {}
    if puxar_dr:
        log("Consultando DR na Ahrefs", 0.57)
        drs, erro_dr = buscar_dr(dominios, ahrefs_key)
        if erro_dr:
            avisos.append(erro_dr)

    # 5. Contatos do site (um por domínio, reaproveitando o HTML dos artigos)
    contatos: dict[str, Contatos] = {}
    if puxar_contatos:
        por_dominio: dict[str, list] = {}
        for u in urls:
            por_dominio.setdefault(normalizar_dominio(u), []).append((u, analises[u].html))
        with ThreadPoolExecutor(max_workers=threads) as ex:
            futs = {ex.submit(buscar_contatos, d, por_dominio[d]): d for d in dominios}
            for i, f in enumerate(as_completed(futs), 1):
                try:
                    contatos[futs[f]] = f.result()
                except Exception:
                    contatos[futs[f]] = Contatos()
                log(f"Buscando contatos do site ({i}/{len(dominios)})", 0.6 + 0.2 * i / len(dominios))

    # 6 e 7. Autor / jornalista (um por par domínio + autor)
    dados_autor: dict[tuple, dict] = {}
    if puxar_autor:
        pares: dict[tuple, str] = {}
        for u in urls:
            a = analises[u]
            if a.autor or a.autor_url:
                chave = (normalizar_dominio(u), a.autor)
                if a.autor_url and not pares.get(chave):
                    pares[chave] = a.autor_url
                else:
                    pares.setdefault(chave, a.autor_url)

        erros_hunter: list[str] = []

        def enriquecer(par):
            d, nome = par
            info: dict = {}
            url_autor = pares[par]
            if url_autor and pertence_ao_dominio(urlparse(url_autor).netloc, d):
                st, final, html = baixar(url_autor)
                if html:
                    ca = Contatos()
                    ca.mesclar_html(html, final)
                    site = contatos.get(d, Contatos())
                    emails = ca.emails - site.emails
                    redes = {k: v for k, v in ca.redes.items() if v not in site.redes.values()}
                    if emails:
                        info["autor_email"] = ", ".join(sorted(emails))
                    if "LinkedIn" in redes:
                        info["autor_linkedin"] = redes["LinkedIn"]
                    if "X/Twitter" in redes:
                        info["autor_x"] = redes["X/Twitter"]
                    if "Instagram" in redes:
                        info["autor_instagram"] = redes["Instagram"]
            if autor_generico(nome):
                return par, info
            prioridade = (not so_oportunidades) or d in dominios_oport
            if perfis_google and prioridade:
                for k, v in perfis_autor_google(nome, serper_key, buscador, pais, idioma).items():
                    info.setdefault(k, v)
            if hunter_key and hunter_autor and prioridade:
                h, erro = hunter_email_autor(d, nome, hunter_key)
                if erro:
                    erros_hunter.append(erro)
                for k, v in h.items():
                    if k == "autor_linkedin_hunter":
                        if v:
                            info.setdefault("autor_linkedin", v)
                    else:
                        info[k] = v
            return par, info

        if pares:
            with ThreadPoolExecutor(max_workers=4) as ex:
                for i, (par, info) in enumerate(ex.map(enriquecer, list(pares)), 1):
                    dados_autor[par] = info
                    log(f"Buscando dados dos autores ({i}/{len(pares)})", 0.8 + 0.12 * i / len(pares))
        if erros_hunter:
            avisos.append("Hunter (autor): " + erros_hunter[-1])

    emails_veiculo: dict[str, str] = {}
    if hunter_key and hunter_veiculo:
        alvo = sorted(dominios_oport if so_oportunidades else dominios)
        erros = []
        for i, d in enumerate(alvo, 1):
            emails_veiculo[d], erro = hunter_emails_veiculo(d, hunter_key)
            if erro:
                erros.append(erro)
                if "429" in erro or "quota" in erro.lower() or "limit" in erro.lower():
                    break
            log(f"Hunter: emails dos veículos ({i}/{len(alvo)})", 0.92 + 0.08 * i / max(len(alvo), 1))
        if erros:
            avisos.append("Hunter (veículos): " + erros[-1])

    # Monta a tabela
    linhas = []
    for u in urls:
        a, r = analises[u], achados[u]
        d = normalizar_dominio(u)
        linha = {
            "status": status[u],
            "dominio": d,
            "dr": drs.get(d),
            "url": u,
            "titulo": r.get("titulo", ""),
            "termos_encontrados": ", ".join(a.termos_encontrados),
            "termos_busca": ", ".join(sorted(r["termos_busca"])),
            "fonte": ", ".join(sorted(r["fonte"])),
            "data_google": r.get("data", ""),
            "publicado_em": a.publicado_em,
            "autor": a.autor,
            "autor_pagina": a.autor_url,
            "qtd_links_cliente": len(a.links),
            "links_dofollow": sum(1 for l in a.links if l.dofollow),
            "anchors": " | ".join(dict.fromkeys(l.anchor for l in a.links)),
            "urls_linkadas": " | ".join(dict.fromkeys(l.href for l in a.links)),
            "rel": " | ".join(dict.fromkeys(l.rel for l in a.links)),
            "trecho_mencao": a.trecho or r.get("snippet", ""),
            "http": a.status_http,
        }
        if puxar_autor:
            info = dados_autor.get((d, a.autor), {})
            for k in ("autor_email", "hunter_email_autor", "hunter_confianca", "hunter_cargo_autor",
                      "autor_linkedin", "autor_x", "autor_instagram", "autor_muckrack"):
                linha[k] = info.get(k, "")
            if a.autor and not autor_generico(a.autor):
                from urllib.parse import quote_plus
                linha["buscar_autor_muckrack"] = f"https://muckrack.com/search/results?q={quote_plus(a.autor)}"
                linha["buscar_autor_linkedin"] = (
                    "https://www.google.com/search?q=" + quote_plus(f'"{a.autor}" site:linkedin.com/in'))
            else:
                linha["buscar_autor_muckrack"] = linha["buscar_autor_linkedin"] = ""
        if hunter_key and hunter_veiculo:
            linha["emails_veiculo_hunter"] = emails_veiculo.get(d, "")
        if d in contatos:
            linha.update(contatos[d].como_dict())
        linhas.append(linha)

    ordem = {
        "Menção sem link (oportunidade)": 0,
        "Com backlink nofollow/sponsored/ugc": 1,
        "Com backlink dofollow": 2,
        "Termo não encontrado na página": 4,
    }
    linhas.sort(key=lambda x: (ordem.get(x["status"], 3), -(x["dr"] or -1)))
    log("Concluído", 1.0)
    return linhas, avisos
