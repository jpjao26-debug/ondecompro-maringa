"""Assaí Atacadista Maringá (Av. Colombo) — não vende online; só publica o "Jornal de Ofertas".

O site do Assaí bloqueia acessos automáticos fora de um navegador, então este coletor
roda no PC: abre a página de ofertas num navegador de verdade, lê a lista de jornais
de ofertas da loja e deixa a página carregar as imagens, que são guardadas no PC
(dados/encartes_assai/) para a IA ler.
As duas lojas de Maringá (79 "Maringá" e 215 "Maringá Seminário") recebem os mesmos jornais.
"""
import os
import time
from datetime import date, timedelta

from .comum import DADOS, hoje, ler_json, log, salvar_json

SITE = "https://www.assai.com.br"
LOJAS = {79, 215}
LISTA_SALVA = DADOS / "encartes_assai.json"   # última lista boa: serve se o site recusar no dia

LISTA_JS = """
async (lojas) => {
  try {
    const r = await fetch('/sites/default/files/static/ofertas_assai.json?t=' + Date.now());
    if (!r.ok) return {erro: r.status};
    const j = await r.json();
    return {ofertas: (j.ofertas || []).filter(o => (o.lojas || []).some(l => lojas.includes(Number(l.loja_id))))
      .map(o => ({id: o.id_oferta, inicio: o.start_date, fim: o.end_date, texto: o.custom_text,
                  imagens: (o.images || []).map(i => i.url)}))};
  } catch (e) {
    return {erro: String(e)};
  }
}
"""

CARREGAR_JS = """
async (urls) => {
  const ok = [];
  for (const u of urls) {
    const r = await new Promise(res => { const i = new Image(); i.onload = () => res(true); i.onerror = () => res(false); i.src = u; });
    if (r) ok.push(u);
  }
  return ok;
}
"""


def coletar(limite_paginas=None):
    return []  # sem catálogo online: os preços vêm do encarte


def encartes():
    from playwright.sync_api import sync_playwright

    pasta = DADOS / "encartes_assai"
    pasta.mkdir(parents=True, exist_ok=True)
    saida = []
    with sync_playwright() as p:
        opcoes = {"headless": True}
        if os.getenv("CHROME_PATH"):
            opcoes["executable_path"] = os.getenv("CHROME_PATH")
        elif os.name == "nt":
            opcoes["channel"] = os.getenv("NAVEGADOR", "msedge")
        for janela in (False, True):
            if janela:
                opcoes.update(headless=False, args=["--start-minimized"])
            nav = p.chromium.launch(**opcoes)
            pg = nav.new_context(locale="pt-BR").new_page()
            pg.goto(f"{SITE}/ofertas", wait_until="domcontentloaded", timeout=90000)
            r = None
            # com o navegador aberto, o site às vezes pede uns segundos de verificação: tenta 3 vezes
            for tentativa in range(3 if janela else 1):
                pg.wait_for_timeout(5000 if tentativa == 0 else 12000)
                r = pg.evaluate(LISTA_JS, sorted(LOJAS))
                if r and "erro" not in r:
                    break
                if janela and tentativa == 1:
                    pg.reload(wait_until="domcontentloaded", timeout=90000)
            if r and "erro" not in r:
                break
            nav.close()
            if janela:
                return _lista_anterior((r or {}).get("erro"))
            log(f"Assaí · lista recusada no modo invisível ({(r or {}).get('erro')}); abrindo o navegador minimizado")

        recebidas = {}

        def guardar(resp):
            if "cloudfront.net" in resp.url and resp.ok and resp.url not in recebidas:
                try:
                    recebidas[resp.url] = resp.body()
                except Exception:
                    pass
        pg.on("response", guardar)
        for of in r.get("ofertas") or []:
            urls = [u for u in of["imagens"] if u]
            pg.evaluate(CARREGAR_JS, urls)
            pg.wait_for_timeout(1500)
            arquivos, ok = [], []
            for n, u in enumerate(urls, 1):
                if u in recebidas:
                    caminho = pasta / f"{of['id']}-{n}.jpg"
                    caminho.write_bytes(recebidas[u])
                    ok.append(u)
                    arquivos.append(str(caminho))
            if ok:
                saida.append({"mercado": "assai", "titulo": of.get("texto") or "Jornal de Ofertas Assaí",
                              "inicio": of.get("inicio"), "fim": of.get("fim"),
                              "periodo": f"{of.get('inicio')} a {of.get('fim')}", "imagens": ok, "arquivos": arquivos})
            time.sleep(0.5)
        nav.close()
    log(f"Assaí · {len(saida)} jornais de ofertas, {sum(len(e['imagens']) for e in saida)} páginas")
    if saida:
        salvar_json(LISTA_SALVA, {"salvo": hoje(), "encartes": saida})
    return saida


def _data(t):
    """'2026-11-19...' ou '19/11/2026' -> date (None se não der para ler)."""
    t = str(t or "").strip()
    try:
        if "/" in t[:10]:
            d, m, a = t[:10].split("/")
            return date(int(a), int(m), int(d))
        return date.fromisoformat(t[:10])
    except ValueError:
        return None


def _lista_anterior(erro):
    """O site recusou hoje: usa os jornais da última coleta boa que ainda estão valendo."""
    salvo = ler_json(LISTA_SALVA, {}) or {}
    hj = date.fromisoformat(hoje())
    validos = []
    for e in salvo.get("encartes") or []:
        fim = _data(e.get("fim"))
        salvo_em = _data(salvo.get("salvo"))
        vale = fim >= hj if fim else bool(salvo_em and hj - salvo_em <= timedelta(days=2))
        if vale and all(os.path.exists(a) for a in e.get("arquivos") or []):
            validos.append(e)
    if not validos:
        raise RuntimeError(f"Assaí recusou a lista de ofertas ({erro}) e não há jornais anteriores valendo")
    log(f"Assaí · site recusou a lista hoje ({erro}); uso os {len(validos)} jornais da última coleta que ainda valem")
    return validos
