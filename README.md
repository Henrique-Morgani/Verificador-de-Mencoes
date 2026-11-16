# Verificador de Menções

Coloque o site do cliente e os termos (marca, produto, porta-voz...). O app busca as menções no Google, abre cada página e mostra:

- **Status da menção**: com backlink dofollow, com backlink nofollow/sponsored/ugc, menção sem link (oportunidade de link reclamation) ou termo não encontrado (falso positivo do Google)
- **Anchor, rel e URL linkada** de cada link para o cliente (considera subdomínios e meta robots nofollow)
- **DR do domínio** pela Ahrefs
- **Contatos**: emails (inclusive os protegidos pelo Cloudflare e os escritos como "nome [at] site.com"), telefones, WhatsApp, redes sociais, páginas de contato/anuncie/expediente e se o site tem formulário
- **Jornalista/autor da matéria**: nome e página de autor (lidos do próprio site), email e redes que aparecem na página do autor, LinkedIn/X/Muck Rack via Google (1 crédito Serper por autor), email do autor e emails da redação pelo Hunter.io (opcional), além de links prontos de busca no LinkedIn e no Muck Rack
- Data de publicação, quando a página informa
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
| Ahrefs API v3 | DR | Endpoint gratuito (não gasta unidades), mas exige chave. Uma conta gratuita serve: Account settings > API keys |
| [Hunter.io](https://hunter.io) (opcional) | Email do autor e da redação | Plano grátis com créditos mensais; 1 crédito por autor ou por veículo |

Cada página do Google por termo consome 1 crédito do Serper. Com Google Notícias ligado, dobra. O app mostra a estimativa antes de rodar.

## Como a busca é feita

Para cada termo: `"termo" -site:cliente.com -site:dominio_excluido...`, no país, idioma e período escolhidos. Resultados repetidos entre termos viram uma linha só. A comparação do termo na página ignora acentos e maiúsculas.

## Limitações

- Sites com bloqueio anti-bot (Cloudflare desafio, por exemplo) aparecem como "Página bloqueada/indisponível". Vale checar manualmente.
- Links inseridos só via JavaScript não são vistos (o app lê o HTML da página).
- Link via encurtador ou redirecionamento de afiliado não é reconhecido como link para o cliente.
- O DR deve ser exibido com atribuição "Domain Rating by Ahrefs", conforme a licença do endpoint gratuito.

## Clientes salvos, histórico e relatório quinzenal

- **Clientes salvos**: escolha o cliente no topo. Cada busca nova soma ao histórico, sem apagar as menções anteriores. O app guarda quando cada menção apareceu, quando ganhou link e quando perdeu.
- **Reverificar menções salvas**: em cada busca, abre de novo as páginas já guardadas para ver se ganharam ou perderam link (não gasta créditos).
- **Alertas por email** (aba do cliente): cadastre um ou mais emails com frequência quinzenal, semanal ou mensal.

### Peças necessárias

| Peça | Para quê | Onde |
|---|---|---|
| Neon (Postgres grátis) | Guardar clientes, histórico e emails | neon.com |
| Senha de app do Gmail | Enviar os relatórios | myaccount.google.com > Segurança > Senhas de app |
| GitHub Actions | Rodar o robô toda segunda | Já vem no repositório (`.github/workflows/monitoramento.yml`) |

### Secrets

No Streamlit (Settings > Secrets):

```toml
SERPER_API_KEY = "..."
AHREFS_API_KEY = "..."
HUNTER_API_KEY = ""
APP_SENHA = "..."
DATABASE_URL = "postgresql://usuario:senha@host.neon.tech/neondb?sslmode=require"
SMTP_USUARIO = "seuemail@gmail.com"
SMTP_SENHA = "senha de app de 16 letras"
APP_URL = "https://seuapp.streamlit.app"
```

No GitHub (Settings > Secrets and variables > Actions > New repository secret), crie um secret para cada um: `DATABASE_URL`, `SERPER_API_KEY`, `AHREFS_API_KEY`, `HUNTER_API_KEY`, `SMTP_USUARIO`, `SMTP_SENHA`, `APP_URL`.

### Como o robô funciona

Toda segunda às 8h17 (Brasília), o GitHub roda `agendado.py`. Para cada email com envio vencido, ele faz uma nova busca do cliente (período padrão: último mês), reverifica as menções salvas, guarda tudo e envia as novidades desde o último envio. Para testar na hora: aba **Actions > Monitoramento de menções > Run workflow**, marcando "Enviar para todos agora".

Repositório público tem agendamentos desativados pelo GitHub após 60 dias sem atividade; o próprio workflow se reativa pela API a cada execução para evitar isso.

## Novidades da versão 3

- **Busca econômica**: todos os termos vão numa busca só (`"a" OR "b"`); comunidades numa busca só; o robô usa menos páginas. A barra lateral mostra os créditos gastos no mês, e cada busca registra quanto gastou.
- **Notícias grátis** pelo RSS do Google Notícias (os links são convertidos para a URL real da matéria; quando não dá, a notícia aparece com o link do Google e status "Notícia (URL não resolvida)").
- **Comunidades** (Reddit, Quora, Reclame Aqui, YouTube, LinkedIn, TikTok, X, Facebook): status "Menção em comunidade", com sentimento (positiva, negativa, neutra, mista), marcação de pergunta ou pedido de indicação e motivo, classificados pelo Gemini. Cada menção é classificada uma vez só.
- **Concorrentes**: sites que citam o concorrente e não citam o cliente viram "Prospect: cita concorrente".
- **Qualidade do link**: noindex, canonical para outra URL, posição do link (conteúdo, rodapé, barra lateral, menu, comentário) e resumo "Editorial" ou "Baixa: motivos".
- **Link para página quebrada**: se o link aponta para uma página do cliente que responde 404 ou erro.
- **Ignorar** URLs ou domínios inteiros (aba Ignorados para restaurar).
- **Outreach**: selecione linhas e marque Contatado, Respondeu, Recusou ou Link conquistado. Quando uma menção contatada ganha link, o status muda sozinho para Link conquistado. O topo mostra a taxa de conversão.
- **Evolução**: gráficos mensais de backlinks ativos, menções novas, links ganhos e perdidos.
- **Coluna Novidade** compara sempre com a última busca salva do cliente (manual ou do robô).
- **Email**: menções negativas em comunidades abrem o relatório e o assunto começa com "⚠️ NEGATIVA". Também traz perguntas, links quebrados e prospects.

### Novo segredo

`GEMINI_API_KEY`: chave grátis do Google AI Studio (aistudio.google.com > Get API key). Opcional: `GEMINI_MODELO` (padrão `gemini-flash-lite-latest`). Coloque nos Secrets do Streamlit e nos secrets do GitHub.
