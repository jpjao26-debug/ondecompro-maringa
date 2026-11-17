"""Assaí Atacadista Maringá (Av. Colombo) — não vende online; só publica o "Jornal de Ofertas".

O site do Assaí bloqueia acessos automáticos fora de um navegador, então este coletor
roda no PC: abre a página de ofertas num navegador de verdade, lê a lista de jornais
de ofertas da loja e deixa a página carregar as imagens, que são guardadas no PC
(dados/encartes_assai/) para a IA ler.
As duas lojas de Maringá (79 "Maringá" e 215 "Maringá Seminário") recebem os mesmos jornais.
"""
import os
import time

from .comum import DADOS, log

SITE = "https://www.assai.com.br"
LOJAS = {79, 215}

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
            pg.wait_for_timeout(5000)
            r = pg.evaluate(LISTA_JS, sorted(LOJAS))
            if r and "erro" not in r:
                break
            nav.close()
            if janela:
                raise RuntimeError(f"Assaí recusou a lista de ofertas ({(r or {}).get('erro')})")
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
    return saida
