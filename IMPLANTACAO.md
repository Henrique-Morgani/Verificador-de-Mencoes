# DizemAI: ordem de implementação

## Fases

| Fase | Entrega | Depende de |
|---|---|---|
| 1. Base DizemAI | Navegação por telas, Resumo, Configurações do cliente, Menções e links, Alertas, Busca rápida, termos negativos com palavra inteira | Nada novo (já entregue neste pacote) |
| 2. Digital PR | Campanhas, cobertura com 4 status, mailing, saúde das páginas, alerta diário pelo robô | Nada novo (já entregue) |
| 3. O que dizem aí | Termômetro, assuntos, fila de resposta com IA, conversas da categoria, concorrentes nas comunidades | Gemini (já entregue) |
| 4. Concorrentes | Comparativo, links novos, link gap, páginas mais linkadas | AHREFS_API_KEY_PAGA (código pronto, liga quando a chave entrar) |
| 5. Links | Monitor de links conquistados, catálogo de publicações pagas, rascunho de email de outreach com IA, links tóxicos e disavow por upload | Próximo pacote |
| 6. Produto | Login por pessoa, relatório mensal para o cliente, alertas no Slack ou Google Chat, visibilidade em IA (GEO), share of voice, checagem de indexação | Depois |

## Como subir este pacote

1. No GitHub, abra o repositório `Verificador-de-Mencoes` > **Add file > Upload files**.
2. Arraste **todo o conteúdo** da pasta do zip, incluindo a pasta `telas` (ela é nova) e a pasta `.github`. Se o navegador não mostrar `.github`, envie o `monitoramento.yml` em **.github/workflows** pelo botão Add file > Create new file, colando o conteúdo.
3. **Commit changes**. O Streamlit Cloud atualiza sozinho em 1 a 3 minutos. O banco cria as tabelas novas sozinho; nada do histórico se perde.
4. No Streamlit (Manage app > Settings > Secrets) não precisa mudar nada para as fases 1 a 3.
5. Fase 4, quando a agência liberar a API paga: adicionar nos Secrets do Streamlit
   ```toml
   PROVEDOR_DADOS = "ahrefs"
   AHREFS_API_KEY_PAGA = "chave_da_conta_paga"
   AHREFS_MAX_LINHAS = "100"
   ```
   A chave gratuita (`AHREFS_API_KEY`) continua sendo usada para o DR.
6. Robô: agora roda todo dia (campanhas) e faz os relatórios na segunda. Os secrets do GitHub são os mesmos.

## Primeiro uso

1. **Configurações do cliente**: revisar cada cliente. Concorrentes no formato `Nome | site.com.br`; frases da categoria (ex.: "indicação de higienização de sofá"); termos negativos quando a marca contém outra palavra ou marca.
2. **Menções e links > Buscar agora** em cada cliente, para popular comunidades, categoria e DR.
3. **Digital PR**: cadastrar a campanha ativa com termos e a página do estudo.
4. **Concorrentes > Atualizar dados** só depois da chave paga; cada atualização mostra as unidades gastas.

## Semrush depois

Trocar só `provedores.py` (classe `SemrushProvedor`) e o secret `PROVEDOR_DADOS`. Telas, banco e link gap não mudam.
