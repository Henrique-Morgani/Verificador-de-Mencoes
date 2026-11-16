"""
Banco de dados do Verificador de Menções.

Usa a variável DATABASE_URL (Postgres do Neon, por exemplo).
Sem ela, usa um arquivo SQLite local (mencoes.db), que serve para testes no computador
mas é apagado a cada reinício no Streamlit Cloud.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, MetaData, String, Table, Text,
    UniqueConstraint, create_engine, delete, func, insert, inspect, select, text, update,
)

ST_DOFOLLOW = "Com backlink dofollow"
ST_NOFOLLOW = "Com backlink nofollow/sponsored/ugc"
ST_QUEBRADO = "Link para página quebrada"
ST_SEM_LINK = "Menção sem link (oportunidade)"
ST_COMUNIDADE = "Menção em comunidade"
ST_PROSPECT = "Prospect: cita concorrente"
ST_NAO_ENCONTRADO = "Termo não encontrado na página"

STATUS_COM_LINK = {ST_DOFOLLOW, ST_NOFOLLOW, ST_QUEBRADO}
STATUS_FALHA = {"Erro ao acessar"}

OUTREACH_OPCOES = ["Não contatado", "Contatado", "Respondeu", "Recusou", "Link conquistado"]
OUTREACH_CONTATADOS = {"Contatado", "Respondeu", "Recusou", "Link conquistado"}

meta = MetaData()

clientes = Table(
    "clientes", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nome", String(200), nullable=False, unique=True),
    Column("url", String(500), nullable=False),
    Column("termos", Text, nullable=False),      # JSON: lista de termos
    Column("config", Text, nullable=False),      # JSON: país, idioma, páginas etc.
    Column("criado_em", DateTime(timezone=True)),
    Column("ultima_busca", DateTime(timezone=True)),
)

mencoes = Table(
    "mencoes", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cliente_id", Integer, ForeignKey("clientes.id", ondelete="CASCADE"), nullable=False),
    Column("url", String(1000), nullable=False),
    Column("dominio", String(300)),
    Column("status", String(100)),
    Column("dr", Float),
    Column("dados", Text),                        # JSON com a linha completa
    Column("primeira_vez", DateTime(timezone=True)),
    Column("ultima_vez", DateTime(timezone=True)),
    Column("link_desde", DateTime(timezone=True)),
    Column("perdeu_link_em", DateTime(timezone=True)),
    Column("outreach_status", String(40)),
    Column("outreach_data", DateTime(timezone=True)),
    Column("outreach_obs", Text),
    UniqueConstraint("cliente_id", "url", name="uq_cliente_url"),
)

execucoes = Table(
    "execucoes", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cliente_id", Integer, ForeignKey("clientes.id", ondelete="CASCADE"), nullable=False),
    Column("inicio", DateTime(timezone=True)),
    Column("fim", DateTime(timezone=True)),
    Column("origem", String(20)),                 # manual | robô
    Column("creditos_serper", Integer, default=0),
    Column("creditos_hunter", Integer, default=0),
    Column("noticias_rss", Integer, default=0),
    Column("novas", Integer, default=0),
    Column("novos_links", Integer, default=0),
    Column("links_perdidos", Integer, default=0),
)

ignorados = Table(
    "ignorados", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cliente_id", Integer, ForeignKey("clientes.id", ondelete="CASCADE"), nullable=False),
    Column("tipo", String(10), nullable=False),   # url | dominio
    Column("valor", String(1000), nullable=False),
    Column("criado_em", DateTime(timezone=True)),
    UniqueConstraint("cliente_id", "tipo", "valor", name="uq_ignorado"),
)

# Colunas acrescentadas depois da primeira versão (o banco já existente recebe via ALTER TABLE)
_COLUNAS_NOVAS = {
    "mencoes": {"outreach_status": "VARCHAR(40)", "outreach_data": "TIMESTAMP WITH TIME ZONE",
                "outreach_obs": "TEXT"},
}

inscricoes = Table(
    "inscricoes", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cliente_id", Integer, ForeignKey("clientes.id", ondelete="CASCADE"), nullable=False),
    Column("email", String(300), nullable=False),
    Column("frequencia_dias", Integer, default=14),
    Column("ultimo_envio", DateTime(timezone=True)),
    Column("ativo", Boolean, default=True),
    Column("criado_em", DateTime(timezone=True)),
    UniqueConstraint("cliente_id", "email", name="uq_cliente_email"),
)

_engine = None


def agora() -> datetime:
    return datetime.now(timezone.utc)


def _tz(d):
    """SQLite devolve datas sem fuso; normaliza para UTC."""
    if d is not None and d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d


def engine():
    global _engine
    if _engine is None:
        url = os.getenv("DATABASE_URL", "").strip()
        if not url:
            url = "sqlite:///mencoes.db"
        elif url.startswith("postgres://"):
            url = "postgresql+psycopg2://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg2://" + url[len("postgresql://"):]
        _engine = create_engine(url, pool_pre_ping=True, pool_recycle=280)
        meta.create_all(_engine)
        _migrar(_engine)
    return _engine


def _migrar(eng):
    insp = inspect(eng)
    for tabela, cols in _COLUNAS_NOVAS.items():
        existentes = {c["name"] for c in insp.get_columns(tabela)}
        for nome, tipo in cols.items():
            if nome not in existentes:
                if eng.dialect.name == "sqlite":
                    tipo = tipo.replace(" WITH TIME ZONE", "")
                with eng.begin() as c:
                    c.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}"))


def usando_banco_externo() -> bool:
    return bool(os.getenv("DATABASE_URL", "").strip())


# ---------------------------------------------------------------- clientes

def listar_clientes() -> list[dict]:
    with engine().connect() as c:
        rows = c.execute(select(clientes).order_by(clientes.c.nome)).mappings().all()
    return [_cliente(r) for r in rows]


def obter_cliente(cid: int) -> dict | None:
    with engine().connect() as c:
        r = c.execute(select(clientes).where(clientes.c.id == cid)).mappings().first()
    return _cliente(r) if r else None


def _cliente(r) -> dict:
    d = dict(r)
    d["termos"] = json.loads(d["termos"] or "[]")
    d["config"] = json.loads(d["config"] or "{}")
    d["ultima_busca"] = _tz(d.get("ultima_busca"))
    return d


def salvar_cliente(nome: str, url: str, termos: list[str], config: dict, cid: int | None = None) -> int:
    valores = dict(nome=nome.strip(), url=url.strip(), termos=json.dumps(termos, ensure_ascii=False),
                   config=json.dumps(config, ensure_ascii=False))
    with engine().begin() as c:
        if cid:
            c.execute(update(clientes).where(clientes.c.id == cid).values(**valores))
            return cid
        res = c.execute(insert(clientes).values(**valores, criado_em=agora()))
        return res.inserted_primary_key[0]


def excluir_cliente(cid: int):
    with engine().begin() as c:
        c.execute(delete(execucoes).where(execucoes.c.cliente_id == cid))
        c.execute(delete(ignorados).where(ignorados.c.cliente_id == cid))
        c.execute(delete(mencoes).where(mencoes.c.cliente_id == cid))
        c.execute(delete(inscricoes).where(inscricoes.c.cliente_id == cid))
        c.execute(delete(clientes).where(clientes.c.id == cid))


# ---------------------------------------------------------------- menções

def urls_do_cliente(cid: int, so_relevantes: bool = True) -> list[str]:
    """URLs já conhecidas. so_relevantes: ignora as que não tinham o termo."""
    q = select(mencoes.c.url, mencoes.c.status).where(mencoes.c.cliente_id == cid)
    with engine().connect() as c:
        rows = c.execute(q).all()
    if so_relevantes:
        return [u for u, s in rows if s != "Termo não encontrado na página"]
    return [u for u, _ in rows]


def salvar_resultados(cid: int, linhas: list[dict], quando: datetime | None = None) -> dict:
    """
    Junta o resultado de uma busca ao histórico do cliente.
    Mantém a data em que a menção apareceu pela primeira vez, quando ganhou link e quando perdeu.
    Não apaga dados de contato antigos se a nova verificação vier vazia.
    """
    quando = quando or agora()
    resumo = {"novas": 0, "novos_links": 0, "links_perdidos": 0, "atualizadas": 0}
    with engine().begin() as c:
        existentes = {
            r["url"]: dict(r)
            for r in c.execute(select(mencoes).where(mencoes.c.cliente_id == cid)).mappings()
        }
        for linha in linhas:
            linha = _limpo(linha)
            url = linha["url"]
            status = linha.get("status", "")
            tem_link = status in STATUS_COM_LINK
            antigo = existentes.get(url)

            if antigo is None:
                c.execute(insert(mencoes).values(
                    cliente_id=cid, url=url, dominio=linha.get("dominio"), status=status,
                    dr=linha.get("dr"), dados=json.dumps(_limpo(linha), ensure_ascii=False, default=str),
                    primeira_vez=quando, ultima_vez=quando,
                    link_desde=quando if tem_link else None,
                ))
                resumo["novas"] += 1
                if tem_link:
                    resumo["novos_links"] += 1
                continue

            # Falha temporária de acesso: mantém o que já sabíamos
            if status in STATUS_FALHA or status.startswith("Página bloqueada"):
                c.execute(update(mencoes).where(mencoes.c.id == antigo["id"]).values(ultima_vez=quando))
                continue

            dados_antigos = json.loads(antigo["dados"] or "{}")
            novos = _limpo(linha)
            for k, v in dados_antigos.items():
                if (novos.get(k) in (None, "", [])) and v not in (None, ""):
                    novos[k] = v
            if linha.get("fonte") == "Reverificação" and dados_antigos.get("fonte"):
                novos["fonte"] = dados_antigos["fonte"]
                novos["termos_busca"] = dados_antigos.get("termos_busca", "")
                novos["titulo"] = novos.get("titulo") or dados_antigos.get("titulo", "")

            if status == ST_QUEBRADO and antigo["status"] != ST_QUEBRADO:
                novos["quebrado_desde"] = quando.isoformat()
            tinha_link = antigo["status"] in STATUS_COM_LINK
            valores = dict(status=status, ultima_vez=quando,
                           dr=linha.get("dr") if linha.get("dr") is not None else antigo["dr"],
                           dados=json.dumps(novos, ensure_ascii=False, default=str))
            if tem_link and not tinha_link:
                valores["link_desde"] = quando
                valores["perdeu_link_em"] = None
                resumo["novos_links"] += 1
                if antigo.get("outreach_status") in ("Contatado", "Respondeu"):
                    valores["outreach_status"] = "Link conquistado"
            elif tinha_link and not tem_link:
                valores["perdeu_link_em"] = quando
                resumo["links_perdidos"] += 1
            c.execute(update(mencoes).where(mencoes.c.id == antigo["id"]).values(**valores))
            resumo["atualizadas"] += 1

        c.execute(update(clientes).where(clientes.c.id == cid).values(ultima_busca=quando))
    return resumo


def _limpo(linha: dict) -> dict:
    out = {}
    for k, v in linha.items():
        if isinstance(v, float) and v != v:  # NaN
            v = None
        out[k] = v
    return out


def mencoes_do_cliente(cid: int, incluir_ignorados: bool = False) -> list[dict]:
    with engine().connect() as c:
        rows = c.execute(select(mencoes).where(mencoes.c.cliente_id == cid)).mappings().all()
    urls_ign, doms_ign = conjuntos_ignorados(cid)
    saida = []
    for r in rows:
        if not incluir_ignorados and _esta_ignorado(r["url"], r["dominio"], urls_ign, doms_ign):
            continue
        d = json.loads(r["dados"] or "{}")
        d.update(
            status=r["status"], dr=r["dr"], url=r["url"], dominio=r["dominio"],
            primeira_vez=_tz(r["primeira_vez"]), ultima_vez=_tz(r["ultima_vez"]),
            link_desde=_tz(r["link_desde"]), perdeu_link_em=_tz(r["perdeu_link_em"]),
            outreach_status=r["outreach_status"] or "Não contatado",
            outreach_data=_tz(r["outreach_data"]), outreach_obs=r["outreach_obs"] or "",
        )
        saida.append(d)
    return saida


def dados_salvos(cid: int) -> dict[str, dict]:
    """{url: dados} para reaproveitar classificações já feitas."""
    with engine().connect() as c:
        rows = c.execute(select(mencoes.c.url, mencoes.c.dados).where(mencoes.c.cliente_id == cid)).all()
    return {u: json.loads(d or "{}") for u, d in rows}


# ---------------------------------------------------------------- ignorados

def _esta_ignorado(url, dominio, urls_ign, doms_ign) -> bool:
    if url in urls_ign:
        return True
    dominio = (dominio or "").lower()
    return any(dominio == d or dominio.endswith("." + d) for d in doms_ign)


def conjuntos_ignorados(cid: int) -> tuple[set, set]:
    with engine().connect() as c:
        rows = c.execute(select(ignorados.c.tipo, ignorados.c.valor)
                         .where(ignorados.c.cliente_id == cid)).all()
    return {v for t, v in rows if t == "url"}, {v for t, v in rows if t == "dominio"}


def listar_ignorados(cid: int) -> list[dict]:
    with engine().connect() as c:
        rows = c.execute(select(ignorados).where(ignorados.c.cliente_id == cid)
                         .order_by(ignorados.c.tipo, ignorados.c.valor)).mappings().all()
    return [dict(r) for r in rows]


def ignorar(cid: int, tipo: str, valores: list[str]):
    with engine().begin() as c:
        existentes = {v for (v,) in c.execute(select(ignorados.c.valor).where(
            (ignorados.c.cliente_id == cid) & (ignorados.c.tipo == tipo))).all()}
        for v in dict.fromkeys(x.strip().lower() if tipo == "dominio" else x.strip() for x in valores):
            if v and v not in existentes:
                c.execute(insert(ignorados).values(cliente_id=cid, tipo=tipo, valor=v, criado_em=agora()))


def restaurar_ignorado(iid: int):
    with engine().begin() as c:
        c.execute(delete(ignorados).where(ignorados.c.id == iid))


# ---------------------------------------------------------------- outreach

def definir_outreach(cid: int, urls: list[str], status: str, obs: str | None = None):
    with engine().begin() as c:
        for u in urls:
            atual = c.execute(select(mencoes.c.id, mencoes.c.outreach_data).where(
                (mencoes.c.cliente_id == cid) & (mencoes.c.url == u))).first()
            if not atual:
                continue
            valores = {"outreach_status": status}
            if status in OUTREACH_CONTATADOS and atual[1] is None:
                valores["outreach_data"] = agora()
            if status == "Não contatado":
                valores["outreach_data"] = None
            if obs is not None and obs.strip():
                valores["outreach_obs"] = obs.strip()
            c.execute(update(mencoes).where(mencoes.c.id == atual[0]).values(**valores))


def metricas_outreach(cid: int) -> dict:
    ms = mencoes_do_cliente(cid)
    contatados = [m for m in ms if m["outreach_status"] in OUTREACH_CONTATADOS]
    conquistados = [m for m in ms if m["outreach_status"] == "Link conquistado"]
    return {
        "contatados": len(contatados),
        "responderam": sum(1 for m in contatados if m["outreach_status"] in ("Respondeu", "Recusou",
                                                                              "Link conquistado")),
        "conquistados": len(conquistados),
        "taxa": (len(conquistados) / len(contatados)) if contatados else None,
    }


# ---------------------------------------------------------------- execuções e créditos

def registrar_execucao(cid: int, inicio: datetime, origem: str, stats: dict, resumo: dict):
    with engine().begin() as c:
        c.execute(insert(execucoes).values(
            cliente_id=cid, inicio=inicio, fim=agora(), origem=origem,
            creditos_serper=int(stats.get("serper", 0)), creditos_hunter=int(stats.get("hunter", 0)),
            noticias_rss=int(stats.get("noticias_rss", 0)), novas=resumo.get("novas", 0),
            novos_links=resumo.get("novos_links", 0), links_perdidos=resumo.get("links_perdidos", 0)))


def ultima_execucao(cid: int) -> dict | None:
    with engine().connect() as c:
        r = c.execute(select(execucoes).where(execucoes.c.cliente_id == cid)
                      .order_by(execucoes.c.inicio.desc()).limit(1)).mappings().first()
    if not r:
        return None
    d = dict(r)
    d["inicio"], d["fim"] = _tz(d["inicio"]), _tz(d["fim"])
    return d


def creditos_no_mes(cid: int | None = None, referencia: datetime | None = None) -> dict:
    ref = referencia or agora()
    inicio_mes = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    q = select(func.coalesce(func.sum(execucoes.c.creditos_serper), 0),
               func.coalesce(func.sum(execucoes.c.creditos_hunter), 0),
               func.count(execucoes.c.id)).where(execucoes.c.inicio >= inicio_mes)
    if cid is not None:
        q = q.where(execucoes.c.cliente_id == cid)
    with engine().connect() as c:
        serper, hunter, n = c.execute(q).first()
    return {"serper": int(serper), "hunter": int(hunter), "execucoes": int(n)}


def evolucao_mensal(cid: int, meses: int = 12) -> list[dict]:
    """Por mês: menções novas, links ganhos, links perdidos e backlinks ativos no fim do mês."""
    ms = mencoes_do_cliente(cid)
    hoje = agora()
    pontos = []
    ano, mes = hoje.year, hoje.month
    for _ in range(meses):
        pontos.append((ano, mes))
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    saida = []
    for ano, mes in reversed(pontos):
        ini = datetime(ano, mes, 1, tzinfo=timezone.utc)
        fim = datetime(ano + (mes == 12), (mes % 12) + 1, 1, tzinfo=timezone.utc)

        def no_mes(d):
            return d is not None and ini <= d < fim
        ativos = sum(1 for m in ms if m["link_desde"] is not None and m["link_desde"] < fim
                     and (m["perdeu_link_em"] is None or m["perdeu_link_em"] >= fim
                          or m["perdeu_link_em"] < m["link_desde"]))
        saida.append({
            "mes": f"{mes:02d}/{ano}",
            "mencoes_novas": sum(1 for m in ms if no_mes(m["primeira_vez"])
                                 and m["status"] != ST_NAO_ENCONTRADO),
            "links_ganhos": sum(1 for m in ms if no_mes(m["link_desde"])),
            "links_perdidos": sum(1 for m in ms if no_mes(m["perdeu_link_em"])),
            "backlinks_ativos": ativos,
        })
    while saida and not any(v for k, v in saida[0].items() if k != "mes"):
        saida.pop(0)
    return saida


def _iso(v):
    if not v:
        return None
    try:
        return _tz(datetime.fromisoformat(str(v)))
    except ValueError:
        return None


def novidades(cid: int, desde: datetime) -> dict:
    """Tudo que é novo desde uma data, para o relatório."""
    desde = _tz(desde)
    todas = mencoes_do_cliente(cid)

    def desde_data(d):
        return d is not None and d >= desde

    def por_dr(lista):
        return sorted(lista, key=lambda m: -(m["dr"] or -1))

    comunidade_novas = [m for m in todas if m["status"] == ST_COMUNIDADE and desde_data(m["primeira_vez"])]
    return {
        "novos_links": por_dr([m for m in todas if desde_data(m["link_desde"])
                               and m["status"] in (ST_DOFOLLOW, ST_NOFOLLOW)]),
        "novas_oportunidades": por_dr([m for m in todas if desde_data(m["primeira_vez"])
                                       and m["status"] == ST_SEM_LINK
                                       and not desde_data(m["perdeu_link_em"])]),
        "links_quebrados": por_dr([m for m in todas if m["status"] == ST_QUEBRADO
                                   and (desde_data(m["primeira_vez"]) or desde_data(_iso(m.get("quebrado_desde"))))]),
        "links_perdidos": [m for m in todas if desde_data(m["perdeu_link_em"])],
        "negativas": [m for m in comunidade_novas if m.get("sentimento") == "negativa"],
        "perguntas": [m for m in comunidade_novas if m.get("pergunta_indicacao") == "Sim"
                      and m.get("sentimento") != "negativa"],
        "comunidade_outras": [m for m in comunidade_novas if m.get("sentimento") != "negativa"
                              and m.get("pergunta_indicacao") != "Sim"],
        "prospects": por_dr([m for m in todas if m["status"] == ST_PROSPECT
                             and desde_data(m["primeira_vez"])]),
        "total_links": sum(1 for m in todas if m["status"] in STATUS_COM_LINK),
        "total_mencoes": sum(1 for m in todas if m["status"] not in (ST_NAO_ENCONTRADO, ST_PROSPECT)),
    }


# ---------------------------------------------------------------- inscrições

def listar_inscricoes(cid: int | None = None) -> list[dict]:
    q = select(inscricoes)
    if cid is not None:
        q = q.where(inscricoes.c.cliente_id == cid)
    with engine().connect() as c:
        rows = c.execute(q.order_by(inscricoes.c.email)).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["ultimo_envio"] = _tz(d["ultimo_envio"])
        d["criado_em"] = _tz(d["criado_em"])
        out.append(d)
    return out


def adicionar_inscricao(cid: int, email: str, frequencia_dias: int = 14):
    email = email.strip().lower()
    with engine().begin() as c:
        existe = c.execute(select(inscricoes.c.id).where(
            (inscricoes.c.cliente_id == cid) & (inscricoes.c.email == email))).first()
        if existe:
            c.execute(update(inscricoes).where(inscricoes.c.id == existe[0])
                      .values(ativo=True, frequencia_dias=frequencia_dias))
        else:
            c.execute(insert(inscricoes).values(cliente_id=cid, email=email, frequencia_dias=frequencia_dias,
                                                ativo=True, criado_em=agora()))


def remover_inscricao(iid: int):
    with engine().begin() as c:
        c.execute(delete(inscricoes).where(inscricoes.c.id == iid))


def marcar_envio(iid: int, quando: datetime | None = None):
    with engine().begin() as c:
        c.execute(update(inscricoes).where(inscricoes.c.id == iid).values(ultimo_envio=quando or agora()))


def inscricao_vencida(i: dict, quando: datetime | None = None) -> bool:
    """Tolerância de 1 dia, porque o robô roda semanalmente e o horário pode variar."""
    quando = quando or agora()
    if not i["ativo"]:
        return False
    if i["ultimo_envio"] is None:
        return True
    return quando - i["ultimo_envio"] >= timedelta(days=i["frequencia_dias"] - 1)


def inicio_periodo(i: dict) -> datetime:
    """Desde quando contar as novidades de uma inscrição."""
    return i["ultimo_envio"] or i["criado_em"] or (agora() - timedelta(days=i["frequencia_dias"]))
