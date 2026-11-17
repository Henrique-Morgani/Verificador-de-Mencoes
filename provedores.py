"""
Provedores de dados de backlinks para o analista de concorrentes.

O resto do app só conversa com a interface abaixo. Para trocar de Ahrefs para Semrush,
basta implementar SemrushProvedor e mudar PROVEDOR_DADOS nos Secrets. O DR continua vindo
do endpoint gratuito da Ahrefs (core.buscar_dr), seja qual for o provedor.

Secrets:
  PROVEDOR_DADOS     = "ahrefs" (padrão) ou "semrush"
  AHREFS_API_KEY_PAGA = chave da conta paga (Lite ou acima); separada da chave gratuita do DR
  SEMRUSH_API_KEY    = chave do Semrush (plano Business/Advanced com unidades)
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

import requests


class ProvedorErro(RuntimeError):
    pass


class Provedor:
    nome = "base"

    def __init__(self):
        self.unidades = 0  # custo acumulado informado pelo provedor

    def visao_geral(self, dominio: str) -> dict:
        """{"backlinks", "refdomains", "trafego", "keywords"}"""
        raise NotImplementedError

    def historico_refdomains(self, dominio: str, meses: int = 6) -> list[dict]:
        """[{"data": "AAAA-MM-DD", "refdomains": int}]"""
        raise NotImplementedError

    def refdomains(self, dominio: str, limite: int = 100, desde: str | None = None,
                   dominios: list[str] | None = None) -> list[dict]:
        """Domínios de referência: [{"dominio", "dr", "first_seen", "links"}].
        desde: só os vistos a partir da data (links novos). dominios: só esses (para checar quem já linka)."""
        raise NotImplementedError

    def paginas_mais_linkadas(self, dominio: str, limite: int = 10) -> list[dict]:
        """[{"url", "refdomains", "titulo"}]"""
        raise NotImplementedError


class AhrefsProvedor(Provedor):
    nome = "ahrefs"
    BASE = "https://api.ahrefs.com/v3/site-explorer/"

    def __init__(self, chave: str, max_linhas: int = 100):
        super().__init__()
        if not chave:
            raise ProvedorErro("Falta AHREFS_API_KEY_PAGA nos Secrets.")
        self.chave = chave
        self.max_linhas = max_linhas  # Lite: 100 linhas por requisição; Standard: 250

    def _get(self, endpoint: str, params: dict) -> dict:
        r = requests.get(self.BASE + endpoint, params={**params, "output": "json"}, timeout=60,
                         headers={"Authorization": f"Bearer {self.chave}", "Accept": "application/json"})
        try:
            self.unidades += int(r.headers.get("x-api-units-cost-total-actual") or 0)
        except ValueError:
            pass
        if r.status_code != 200:
            raise ProvedorErro(f"Ahrefs {endpoint} respondeu {r.status_code}: {r.text[:200]}")
        return r.json()

    @staticmethod
    def _lista(js: dict) -> list:
        for v in (js or {}).values():
            if isinstance(v, list):
                return v
        return []

    def visao_geral(self, dominio: str) -> dict:
        hoje = date.today().isoformat()
        bl = self._get("backlinks-stats", {"target": dominio, "date": hoje, "mode": "subdomains"}).get("metrics", {})
        mt = self._get("metrics", {"target": dominio, "date": hoje, "mode": "subdomains"}).get("metrics", {})
        return {"backlinks": bl.get("live"), "refdomains": bl.get("live_refdomains"),
                "trafego": mt.get("org_traffic"), "keywords": mt.get("org_keywords")}

    def historico_refdomains(self, dominio: str, meses: int = 6) -> list[dict]:
        ini = (date.today().replace(day=1) - timedelta(days=31 * (meses - 1))).replace(day=1).isoformat()
        js = self._get("refdomains-history", {"target": dominio, "date_from": ini,
                                              "history_grouping": "monthly", "mode": "subdomains"})
        return [{"data": str(x.get("date"))[:10], "refdomains": x.get("refdomains")}
                for x in self._lista(js)]

    def refdomains(self, dominio: str, limite: int = 100, desde: str | None = None,
                   dominios: list[str] | None = None) -> list[dict]:
        filtros = []
        if desde:
            filtros.append({"field": "first_seen", "is": ["gte", desde]})
        if dominios:
            filtros.append({"or": [{"field": "domain", "is": ["eq", d]} for d in dominios]})
        params = {"target": dominio, "mode": "subdomains", "history": "live",
                  "select": "domain,domain_rating,first_seen,links_to_target",
                  "order_by": "first_seen:desc" if desde else "domain_rating:desc",
                  "limit": min(limite, self.max_linhas)}
        if filtros:
            params["where"] = json.dumps(filtros[0] if len(filtros) == 1 else {"and": filtros})
        js = self._get("refdomains", params)
        return [{"dominio": x.get("domain"), "dr": x.get("domain_rating"),
                 "first_seen": str(x.get("first_seen") or "")[:10], "links": x.get("links_to_target")}
                for x in self._lista(js)]

    def paginas_mais_linkadas(self, dominio: str, limite: int = 10) -> list[dict]:
        js = self._get("pages-by-backlinks", {"target": dominio, "mode": "subdomains", "history": "live",
                                              "select": "url_to,refdomains_target,title_target",
                                              "order_by": "refdomains_target:desc",
                                              "limit": min(limite, self.max_linhas)})
        return [{"url": x.get("url_to"), "refdomains": x.get("refdomains_target"), "titulo": x.get("title_target")}
                for x in self._lista(js)]


class SemrushProvedor(Provedor):
    """A implementar quando a agência confirmar o acesso à API do Semrush.
    Endpoints previstos: backlinks_overview (visão geral), domain_ranks (tráfego e palavras),
    backlinks_refdomains (domínios de referência, ordenando por first_seen para os novos)."""
    nome = "semrush"

    def __init__(self, chave: str):
        super().__init__()
        raise ProvedorErro("O provedor Semrush ainda não foi implementado. Use PROVEDOR_DADOS = \"ahrefs\".")


def obter_provedor() -> Provedor | None:
    """Devolve o provedor configurado, ou None se não houver chave paga."""
    qual = (os.getenv("PROVEDOR_DADOS") or "ahrefs").strip().lower()
    if qual == "semrush":
        return SemrushProvedor(os.getenv("SEMRUSH_API_KEY", ""))
    chave = os.getenv("AHREFS_API_KEY_PAGA", "").strip()
    if not chave:
        return None
    return AhrefsProvedor(chave, int(os.getenv("AHREFS_MAX_LINHAS", "100")))
