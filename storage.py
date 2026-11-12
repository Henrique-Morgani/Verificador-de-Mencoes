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
    UniqueConstraint, create_engine, delete, insert, select, update,
)

STATUS_COM_LINK = {"Com backlink dofollow", "Com backlink nofollow/sponsored/ugc"}
STATUS_FALHA = {"Erro ao acessar"}

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
    UniqueConstraint("cliente_id", "url", name="uq_cliente_url"),
)

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
    return _engine


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

            tinha_link = antigo["status"] in STATUS_COM_LINK
            valores = dict(status=status, ultima_vez=quando,
                           dr=linha.get("dr") if linha.get("dr") is not None else antigo["dr"],
                           dados=json.dumps(novos, ensure_ascii=False, default=str))
            if tem_link and not tinha_link:
                valores["link_desde"] = quando
                valores["perdeu_link_em"] = None
                resumo["novos_links"] += 1
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


def mencoes_do_cliente(cid: int) -> list[dict]:
    with engine().connect() as c:
        rows = c.execute(select(mencoes).where(mencoes.c.cliente_id == cid)).mappings().all()
    saida = []
    for r in rows:
        d = json.loads(r["dados"] or "{}")
        d.update(
            status=r["status"], dr=r["dr"], url=r["url"], dominio=r["dominio"],
            primeira_vez=_tz(r["primeira_vez"]), ultima_vez=_tz(r["ultima_vez"]),
            link_desde=_tz(r["link_desde"]), perdeu_link_em=_tz(r["perdeu_link_em"]),
        )
        saida.append(d)
    return saida


def novidades(cid: int, desde: datetime) -> dict:
    """Backlinks novos, menções novas sem link e links perdidos desde uma data."""
    desde = _tz(desde)
    todas = mencoes_do_cliente(cid)
    return {
        "novos_links": sorted([m for m in todas if m["link_desde"] and m["link_desde"] >= desde
                               and m["status"] in STATUS_COM_LINK], key=lambda m: -(m["dr"] or -1)),
        "novas_oportunidades": sorted([m for m in todas if m["primeira_vez"] >= desde
                                       and m["status"] == "Menção sem link (oportunidade)"
                                       and not (m["perdeu_link_em"] and m["perdeu_link_em"] >= desde)],
                                      key=lambda m: -(m["dr"] or -1)),
        "links_perdidos": [m for m in todas if m["perdeu_link_em"] and m["perdeu_link_em"] >= desde],
        "total_links": sum(1 for m in todas if m["status"] in STATUS_COM_LINK),
        "total_mencoes": sum(1 for m in todas if m["status"] != "Termo não encontrado na página"),
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
