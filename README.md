# DizemAI

Programa de SEO off page da agência. Monitora o que dizem do cliente na web, em notícias e em comunidades, quem linka e quem não linka, acompanha campanhas de Digital PR e compara o cliente com os concorrentes.

## Telas

| Tela | O que faz |
|---|---|
| **Resumo** | Big numbers do período (DR com variação, backlinks, novos links, menções sem link, perdidos, comunidades), positivos, pontos de atenção, próximas ações, atualizações e resumo em texto com IA |
| **Menções e links** | Busca e histórico de menções na web e em notícias: status do link, qualidade, contatos, autor, outreach, ignorar, evolução mensal, Excel |
| **O que dizem aí** | Comunidades em três abas (sobre a marca, conversas da categoria, concorrentes): termômetro contra o período anterior, assuntos, fila "Precisa de resposta" com sugestão de resposta pela IA e status da conversa |
| **Digital PR** | Campanhas com termos e página(s) próprias; cobertura com 4 status de link; KPIs; matérias por dia; mailing com cruzamento automático; saúde das páginas; alerta diário nos primeiros dias |
| **Concorrentes** | Comparativo (DR, domínios de referência, backlinks, tráfego), evolução de 6 meses, links novos dos concorrentes, link gap (envia para o outreach) e páginas mais linkadas |
| **Configurações do cliente** | Termos, termos negativos, frases da categoria, concorrentes (Nome \| site), comunidades, busca manual e do robô |
| **Alertas e ignorados** | Emails automáticos (quinzenal, semanal ou mensal) e lista de ignorados |
| **Busca rápida** | Busca avulsa, sem histórico; dá para salvar como cliente depois |

## Arquivos

| Arquivo | Papel |
|---|---|
| `app.py` | Entrada do app: senha, barra lateral, navegação |
| `comum.py` | Peças compartilhadas das telas |
| `telas/` | Uma tela por arquivo |
| `core.py` | Motor de busca e análise das páginas |
| `fluxo.py` | Busca completa de um cliente (usada pelo app e pelo robô) |
| `pr.py` | Digital PR: status das matérias, busca da cobertura, mailing |
| `concorrentes.py` | Análise de concorrentes e link gap |
| `provedores.py` | Camada de dados de backlinks: Ahrefs agora, Semrush depois |
| `ia.py` | Gemini: sentimento, assunto, sugestão de resposta e resumo |
| `storage.py` | Banco (Neon Postgres ou SQLite local); cria e atualiza as tabelas sozinho |
| `relatorio.py` | Emails (relatório periódico e alerta de campanha) |
| `agendado.py` + `.github/workflows/monitoramento.yml` | Robô diário |

## Chaves (Secrets do Streamlit)

```toml
SERPER_API_KEY = "..."          # busca no Google
AHREFS_API_KEY = "..."          # chave gratuita, só para o DR
HUNTER_API_KEY = ""             # opcional
GEMINI_API_KEY = "..."          # IA (aistudio.google.com)
APP_SENHA = "..."
DATABASE_URL = "postgresql://..."
SMTP_USUARIO = "seuemail@gmail.com"
SMTP_SENHA = "senha de app"
APP_URL = "https://seuapp.streamlit.app"

# Concorrentes (opcional, quando a agência liberar a API paga)
PROVEDOR_DADOS = "ahrefs"       # depois: "semrush"
AHREFS_API_KEY_PAGA = ""        # chave de conta Lite ou acima
AHREFS_MAX_LINHAS = "100"       # Lite: 100 linhas por requisição; Standard: 250
SEMRUSH_API_KEY = ""            # quando o provedor Semrush for implementado
```

No GitHub (Settings > Secrets and variables > Actions) ficam os do robô: `DATABASE_URL`, `SERPER_API_KEY`, `AHREFS_API_KEY`, `HUNTER_API_KEY`, `GEMINI_API_KEY`, `SMTP_USUARIO`, `SMTP_SENHA`, `APP_URL`. O robô não usa a API paga.

## Robô

Roda todo dia às 8h17 (Brasília):

- **Todo dia**: campanhas de Digital PR dentro da janela de alerta (padrão: 14 dias após o lançamento) buscam a cobertura e mandam email aos inscritos do cliente quando sai matéria nova.
- **Segunda**: campanhas ativas fora da janela fazem a busca semanal; clientes com envio vencido fazem a busca completa e recebem o relatório (que agora inclui pedidos de indicação da categoria e o resumo das campanhas).

Para testar: aba **Actions > Robô DizemAI > Run workflow**, marcando "Enviar relatório para todos agora".

## Trocar o provedor de concorrentes para Semrush

O app só conversa com a interface `Provedor` de `provedores.py`. Para mudar:

1. Implementar `SemrushProvedor` com os quatro métodos (`visao_geral`, `historico_refdomains`, `refdomains`, `paginas_mais_linkadas`), devolvendo os mesmos campos.
2. Colocar `SEMRUSH_API_KEY` e trocar `PROVEDOR_DADOS` para `"semrush"` nos Secrets.

O DR continua vindo do endpoint gratuito da Ahrefs em qualquer caso. Com Semrush, a métrica de autoridade nativa é o Authority Score; o DizemAI segue mostrando o DR para manter a comparação com o histórico.

## Rodar no computador

```bash
pip install -r requirements.txt
streamlit run app.py
```

Sem `DATABASE_URL`, usa um arquivo SQLite local (`mencoes.db`).

## Limitações

- Sites com bloqueio anti-bot aparecem como "Página bloqueada/indisponível".
- Links inseridos só via JavaScript não são vistos.
- O DR deve ser exibido com a atribuição "Domain Rating by Ahrefs".
