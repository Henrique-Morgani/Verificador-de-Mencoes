"""
Classificação de sentimento das menções em comunidades, com o Gemini (API do Google AI Studio).

- Só classifica linhas com status "Menção em comunidade".
- Cada menção é classificada uma vez; só reclassifica se o título ou o trecho mudarem.
- Sem GEMINI_API_KEY, não faz nada (e devolve um aviso).
"""

from __future__ import annotations

import hashlib
import json
import os
import time

import requests

STATUS_COMUNIDADE = "Menção em comunidade"
STATUS_SOCIAIS = {"Menção em comunidade", "Conversa da categoria", "Concorrente em comunidade"}
SENTIMENTOS = ["positiva", "negativa", "neutra", "mista"]
MODELO_PADRAO = "gemini-flash-lite-latest"

INSTRUCAO = """Você analisa menções a uma marca em comunidades online (Reddit, Quora, Reclame Aqui, YouTube etc.).
Cada item traz a marca a avaliar no campo "marca" (para conversas da categoria, a marca pode estar vazia:
avalie o tom da conversa sobre o tipo de serviço e sobre as empresas citadas).
Para cada item, leia o título e o trecho e responda:
- sentimento: "positiva" (elogio, recomendação), "negativa" (reclamação, crítica, experiência ruim),
  "neutra" (citação factual, sem opinião) ou "mista" (elogio e crítica juntos).
  O sentimento é sobre a MARCA indicada, não sobre o assunto geral do post.
- pergunta: true se o autor está pedindo indicação, opinião ou tirando dúvida sobre a marca ou o tipo de serviço
  (ex.: "alguém já usou X?", "qual empresa vocês recomendam?"). Pode ser true junto com qualquer sentimento.
- motivo: uma frase curta em português explicando o principal ponto (ex.: "reclama de atraso no atendimento").
- confianca: "alta", "media" ou "baixa". Use "baixa" quando o trecho for curto ou ambíguo.
- assunto: o tema principal em 1 a 3 palavras, em português, com inicial maiúscula
  (ex.: "Prazo", "Atendimento", "Preço", "Qualidade do serviço", "Indicação"). Reutilize os mesmos rótulos entre itens.
Responda somente com o JSON pedido, um objeto por item, mantendo o mesmo id."""

SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "id": {"type": "STRING"},
            "sentimento": {"type": "STRING", "enum": SENTIMENTOS},
            "pergunta": {"type": "BOOLEAN"},
            "motivo": {"type": "STRING"},
            "confianca": {"type": "STRING", "enum": ["alta", "media", "baixa"]},
            "assunto": {"type": "STRING"},
        },
        "required": ["id", "sentimento", "pergunta", "motivo", "confianca", "assunto"],
    },
}


def configurado() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def hash_texto(linha: dict) -> str:
    base = (linha.get("titulo") or "") + "|" + (linha.get("trecho_mencao") or "")
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def _gerar(instrucao: str, conteudo: str, schema: dict | None = None, temperatura: float = 0) -> str:
    """Chamada genérica ao Gemini. Devolve o texto da resposta."""
    chave = os.getenv("GEMINI_API_KEY", "").strip()
    modelo = os.getenv("GEMINI_MODELO", "").strip() or MODELO_PADRAO
    cfg = {"temperature": temperatura}
    if schema:
        cfg.update(responseMimeType="application/json", responseSchema=schema)
    corpo = {
        "systemInstruction": {"parts": [{"text": instrucao}]},
        "contents": [{"role": "user", "parts": [{"text": conteudo}]}],
        "generationConfig": cfg,
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
    for tentativa in range(3):
        r = requests.post(url, headers={"x-goog-api-key": chave, "Content-Type": "application/json"},
                          json=corpo, timeout=90)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(5 * (tentativa + 1))
            continue
        if r.status_code != 200:
            raise RuntimeError(f"Gemini {r.status_code}: {r.text[:200]}")
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    raise RuntimeError("Gemini: limite de requisições atingido, tente mais tarde.")


def _chamar_gemini(marca: str, itens: list[dict]) -> list[dict]:
    return json.loads(_gerar(INSTRUCAO, json.dumps({"marca": marca, "itens": itens}, ensure_ascii=False), SCHEMA))


def sugerir_resposta(marca: str, plataforma: str, titulo: str, trecho: str, tipo: str = "",
                     contexto: str = "") -> str:
    """Rascunho de resposta para uma conversa, no tom da comunidade. A equipe revisa antes de publicar."""
    instr = ("Você é da equipe de comunicação de uma marca e vai responder a uma conversa pública numa comunidade "
             "online. Escreva em português do Brasil, no tom da plataforma (Reddit: informal e direto; "
             "Reclame Aqui: cordial, objetivo, assumindo o problema e oferecendo solução; Quora: explicativo). "
             "Não invente fatos, preços, prazos ou promoções. Onde faltar informação, use colchetes, como "
             "[canal de atendimento]. Se for pedido de indicação sem citar a marca, responda de forma útil e só "
             "então apresente a marca, sem parecer propaganda. No máximo 120 palavras. Devolva só o texto.")
    conteudo = json.dumps({"marca": marca, "plataforma": plataforma, "tipo": tipo, "titulo": titulo,
                           "trecho": trecho, "contexto_da_marca": contexto}, ensure_ascii=False)
    return _gerar(instr, conteudo, temperatura=0.4).strip()


def resumo_cliente(fatos: dict) -> str:
    """Parágrafo de resumo do período, a partir dos números já calculados pelo app."""
    instr = ("Escreva um parágrafo de 4 a 6 frases, em português do Brasil, resumindo o período para um gestor de "
             "SEO off page. Use apenas os números e fatos do JSON, sem inventar nada. Comece pelo mais importante, "
             "cite um ponto positivo e um ponto de atenção, e termine com a próxima ação sugerida. "
             "Não use travessão. Devolva só o parágrafo.")
    return _gerar(instr, json.dumps(fatos, ensure_ascii=False, default=str), temperatura=0.3).strip()


def aplicar_sentimento(linhas: list[dict], marca: str, anteriores: dict[str, dict] | None = None,
                       lote: int = 15) -> str:
    """
    Preenche sentimento nas linhas de comunidade (altera a lista).
    anteriores: {url: dados já salvos} para reaproveitar classificações.
    Retorna um aviso (vazio se deu tudo certo).
    """
    anteriores = anteriores or {}
    pendentes = []
    for ln in linhas:
        if ln.get("status") not in STATUS_SOCIAIS:
            continue
        h = hash_texto(ln)
        ant = anteriores.get(ln["url"], {})
        if ant.get("sentimento") and ant.get("sentimento_hash") == h:
            for k in ("sentimento", "pergunta_indicacao", "motivo_sentimento", "confianca_sentimento",
                      "assunto", "sentimento_hash"):
                ln[k] = ant.get(k, "")
            continue
        ln["sentimento_hash"] = h
        pendentes.append(ln)

    if not pendentes:
        return ""
    if not configurado():
        return (f"{len(pendentes)} conversa(s) em comunidades sem classificação de sentimento: "
                "configure GEMINI_API_KEY nos Secrets.")

    falhas = 0
    for i in range(0, len(pendentes), lote):
        grupo = pendentes[i:i + lote]
        itens = [{"id": str(j), "titulo": g.get("titulo", ""), "trecho": g.get("trecho_mencao", ""),
                  "site": g.get("dominio", ""),
                  "marca": (g.get("marca") or "") if g.get("status") != STATUS_COMUNIDADE else marca,
                  "tipo": {"Conversa da categoria": "categoria"}.get(g.get("status"), "marca")}
                 for j, g in enumerate(grupo)]
        try:
            resp = {str(x.get("id")): x for x in _chamar_gemini(marca, itens)}
        except Exception:
            falhas += len(grupo)
            for g in grupo:
                g.pop("sentimento_hash", None)  # tenta de novo na próxima busca
            continue
        for j, g in enumerate(grupo):
            x = resp.get(str(j))
            if not x:
                falhas += 1
                g.pop("sentimento_hash", None)
                continue
            g["sentimento"] = x.get("sentimento", "")
            g["pergunta_indicacao"] = "Sim" if x.get("pergunta") else "Não"
            g["motivo_sentimento"] = x.get("motivo", "")
            g["confianca_sentimento"] = x.get("confianca", "")
            g["assunto"] = (x.get("assunto") or "").strip()[:40]
    return f"{falhas} menção(ões) em comunidades não puderam ser classificadas agora." if falhas else ""
