"""
Robô do DizemAI. Roda todo dia pelo GitHub Actions (ver .github/workflows/monitoramento.yml).

Todo dia:
  - Campanhas de Digital PR em alerta diário (primeiros N dias depois do lançamento): busca a cobertura e,
    se saiu matéria nova, manda email para os inscritos do cliente.
Toda segunda (ou com --forcar):
  - Campanhas ativas fora da janela de alerta: busca semanal da cobertura.
  - Clientes com email cadastrado e envio vencido: nova busca, reverificação e relatório.

Uso:  python agendado.py            (rotina normal)
      python agendado.py --forcar   (relatório para todos os inscritos agora, ignorando dia e frequência)
"""

from __future__ import annotations

import sys
import traceback
from datetime import timedelta

import fluxo
import pr
import relatorio
import storage


def campanhas(hoje_segunda: bool, forcar: bool, log=print) -> int:
    falhas = 0
    agora = storage.agora()
    for camp in storage.listar_campanhas(status="ativa"):
        diaria = pr.em_janela_de_alerta(camp)
        semanal_vencida = camp.get("ultima_busca") is None or agora - camp["ultima_busca"] >= timedelta(days=6)
        if not (diaria or ((hoje_segunda or forcar) and semanal_vencida)):
            continue
        cliente = storage.obter_cliente(camp["cliente_id"])
        if not cliente:
            continue
        log(f"Campanha: {camp['nome']} ({cliente['nome']}) {'diária' if diaria else 'semanal'}")
        try:
            resumo, avisos = pr.rodar_campanha(camp, cliente)
            log(f"  {resumo}")
            for a in avisos:
                log(f"  aviso: {a}")
        except Exception:
            falhas += 1
            traceback.print_exc()
            continue
        if not (diaria and relatorio.smtp_configurado()):
            continue
        desde = camp.get("ultimo_envio") or camp.get("criado_em") or (agora - timedelta(days=1))
        cob = storage.cobertura_da_campanha(camp["id"])
        novas = [m for m in cob if m.get("primeira_vez") and m["primeira_vez"] > desde]
        if not novas:
            continue
        ind = pr.indicadores(cob, storage.listar_mailing(camp["id"]))
        assunto, corpo = relatorio.montar_campanha(cliente, camp, novas, ind)
        for i in storage.listar_inscricoes(cliente["id"]):
            if not i["ativo"]:
                continue
            try:
                relatorio.enviar(i["email"], assunto, corpo)
                log(f"  Enviado para {i['email']}: {assunto}")
            except Exception:
                falhas += 1
                traceback.print_exc()
        storage.atualizar_campanha(camp["id"], ultimo_envio=max(m["primeira_vez"] for m in novas))
    return falhas


def relatorios(forcar: bool, log=print) -> int:
    falhas = 0
    agora = storage.agora()
    por_cliente: dict[int, list] = {}
    for i in storage.listar_inscricoes():
        if i["ativo"] and (forcar or storage.inscricao_vencida(i, agora)):
            por_cliente.setdefault(i["cliente_id"], []).append(i)
    if not por_cliente:
        log("Nenhum relatório vencido hoje.")
    for cid, insc in por_cliente.items():
        cliente = storage.obter_cliente(cid)
        if not cliente:
            continue
        log(f"Cliente: {cliente['nome']} ({len(insc)} destinatário(s))")
        try:
            resumo, avisos, stats = fluxo.rodar_cliente(cliente, origem="robô")
            log(f"  {resumo} | Serper {stats.get('serper', 0)}, Hunter {stats.get('hunter', 0)}, "
                f"RSS {stats.get('noticias_rss', 0)}")
            for a in avisos:
                log(f"  aviso: {a}")
        except Exception:
            falhas += 1
            log("  Falha na busca, o relatório sai com o que já estava salvo:")
            traceback.print_exc()
        for i in insc:
            desde = storage.inicio_periodo(i)
            try:
                nov = storage.novidades(cid, desde)
                nov["campanhas"] = pr.resumo_campanhas(cid, desde)
                assunto, corpo = relatorio.montar(cliente, nov, desde, agora)
                relatorio.enviar(i["email"], assunto, corpo)
                storage.marcar_envio(i["id"], agora)
                log(f"  Enviado para {i['email']}: {assunto}")
            except Exception:
                falhas += 1
                log(f"  Falha ao enviar para {i['email']}:")
                traceback.print_exc()
    return falhas


def main(forcar: bool = False, hoje_segunda: bool | None = None) -> int:
    if not storage.usando_banco_externo():
        print("ERRO: DATABASE_URL não configurado. O robô precisa do mesmo banco do app.")
        return 1
    if not relatorio.smtp_configurado():
        print("AVISO: SMTP não configurado; as buscas rodam, mas nenhum email sai.")
    if hoje_segunda is None:
        from zoneinfo import ZoneInfo
        hoje_segunda = storage.agora().astimezone(ZoneInfo("America/Sao_Paulo")).weekday() == 0
    falhas = campanhas(hoje_segunda, forcar)
    if hoje_segunda or forcar:
        if relatorio.smtp_configurado():
            falhas += relatorios(forcar)
    else:
        print("Hoje não é segunda: relatórios de clientes ficam para a próxima segunda.")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main(forcar="--forcar" in sys.argv))
