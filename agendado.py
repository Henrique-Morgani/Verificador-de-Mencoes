"""
Robô de monitoramento. Roda pelo GitHub Actions (ver .github/workflows/monitoramento.yml).

Para cada cliente com email cadastrado e envio vencido:
1. Faz uma nova busca (web, notícias via RSS, comunidades e concorrentes; período padrão: último mês).
2. Reverifica as menções já conhecidas (ganhou ou perdeu link?).
3. Junta tudo ao histórico.
4. Envia o relatório com as novidades desde o último envio.

Uso:  python agendado.py            (só clientes com envio vencido)
      python agendado.py --forcar   (todos os clientes com email, ignorando a frequência)
"""

from __future__ import annotations

import os
import sys
import traceback

import fluxo
import relatorio
import storage


def buscar_e_salvar(cliente: dict, log=print) -> tuple[dict, list[str]]:
    resumo, avisos, stats = fluxo.rodar_cliente(cliente, origem="robô")
    log(f"  {cliente['nome']}: {resumo} | créditos Serper: {stats.get('serper', 0)}, "
        f"Hunter: {stats.get('hunter', 0)}, notícias RSS: {stats.get('noticias_rss', 0)}")
    for a in avisos:
        log(f"  aviso: {a}")
    return resumo, avisos


def main(forcar: bool = False) -> int:
    if not storage.usando_banco_externo():
        print("ERRO: DATABASE_URL não configurado. O robô precisa do mesmo banco do app.")
        return 1
    if not relatorio.smtp_configurado():
        print("ERRO: SMTP_USUARIO e SMTP_SENHA não configurados.")
        return 1

    agora = storage.agora()
    falhas = 0
    por_cliente: dict[int, list] = {}
    for i in storage.listar_inscricoes():
        if i["ativo"] and (forcar or storage.inscricao_vencida(i, agora)):
            por_cliente.setdefault(i["cliente_id"], []).append(i)

    if not por_cliente:
        print("Nenhum envio vencido hoje.")
        return 0

    for cid, insc in por_cliente.items():
        cliente = storage.obter_cliente(cid)
        if not cliente:
            continue
        print(f"Cliente: {cliente['nome']} ({len(insc)} destinatário(s))")
        try:
            buscar_e_salvar(cliente)
        except Exception:
            falhas += 1
            print("  Falha na busca, o relatório sai com o que já estava salvo:")
            traceback.print_exc()

        for i in insc:
            desde = storage.inicio_periodo(i)
            try:
                nov = storage.novidades(cid, desde)
                assunto, corpo = relatorio.montar(cliente, nov, desde, agora)
                relatorio.enviar(i["email"], assunto, corpo)
                storage.marcar_envio(i["id"], agora)
                print(f"  Enviado para {i['email']}: {assunto}")
            except Exception:
                falhas += 1
                print(f"  Falha ao enviar para {i['email']}:")
                traceback.print_exc()

    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(forcar="--forcar" in sys.argv))
