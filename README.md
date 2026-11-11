# Verificador de Menções

Coloque o site do cliente e os termos (marca, produto, porta-voz...). O app busca as menções no Google, abre cada página e mostra:

- **Status da menção**: com backlink dofollow, com backlink nofollow/sponsored/ugc, menção sem link (oportunidade de link reclamation) ou termo não encontrado (falso positivo do Google)
- **Anchor, rel e URL linkada** de cada link para o cliente (considera subdomínios e meta robots nofollow)
- **DR do domínio** pela Ahrefs
- **Contatos**: emails (inclusive os protegidos pelo Cloudflare e os escritos como "nome [at] site.com"), telefones, WhatsApp, redes sociais, páginas de contato/anuncie/expediente e se o site tem formulário
- Autor e data de publicação, quando a página informa
- Exportação em Excel (aba por URL + aba por domínio) e CSV

## Instalação (uma vez)

Precisa de Python 3.10 ou mais novo.

```bash
cd verificador-mencoes
pip install -r requirements.txt
```

Renomeie `.env.exemplo` para `.env` e cole as chaves (ou cole direto na barra lateral do app).

## Rodar

```bash
streamlit run app.py
```

Abre no navegador em http://localhost:8501.

## Chaves

| Serviço | Para quê | Custo |
|---|---|---|
| [Serper.dev](https://serper.dev) | Busca no Google (web e notícias) | 2.500 buscas grátis; depois cerca de US$ 1 por mil |
| Ahrefs API v3 | DR | Endpoint gratuito da Ahrefs. Funciona sem chave (um domínio por vez); com chave (a gratuita, gerada em Account settings > API keys) consulta em lote |

Cada página do Google por termo consome 1 crédito do Serper. Com Google Notícias ligado, dobra. O app mostra a estimativa antes de rodar.

## Como a busca é feita

Para cada termo: `"termo" -site:cliente.com -site:dominio_excluido...`, no país, idioma e período escolhidos. Resultados repetidos entre termos viram uma linha só. A comparação do termo na página ignora acentos e maiúsculas.

## Limitações

- Sites com bloqueio anti-bot (Cloudflare desafio, por exemplo) aparecem como "Página bloqueada/indisponível". Vale checar manualmente.
- Links inseridos só via JavaScript não são vistos (o app lê o HTML da página).
- Link via encurtador ou redirecionamento de afiliado não é reconhecido como link para o cliente.
- O DR deve ser exibido com atribuição "Domain Rating by Ahrefs", conforme a licença do endpoint gratuito.
