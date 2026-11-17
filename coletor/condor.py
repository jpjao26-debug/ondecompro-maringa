"""Coletor do Condor — loja Maringá Av. Paraná (loja 1440 na plataforma OSuper, empresa 314).

É a mesma plataforma do Semar: o site bloqueia acessos de servidores na nuvem, então
o coletor roda no PC, abre o site num navegador de verdade e pede os produtos à mesma
busca que o próprio site usa (20 por vez).
"""
import os
import re
import time

from .comum import ean_valido, log

SITE = "https://www.condor.com.br"
EMPRESA, LOJA = "314", "1440"
BUSCA = f"https://sense.osuper.com.br/{EMPRESA}/{LOJA}/v2/search"
PAUSA = float(os.getenv("CONDOR_PAUSA", "0.4"))

DEPARTAMENTOS = {
    "1032075": "Mercearia", "1032058": "Açougue e Peixaria", "1032244": "Hortifrúti",
    "1032263": "Frios e Laticínios", "1032236": "Frios e Laticínios", "1031905": "Higiene e Beleza",
    "1032299": "Limpeza", "1031975": "Bebidas", "1032474": "Bebidas", "1032427": "Pet",
    "1032172": "Padaria", "1032414": "Especiais", "1032159": "Congelados", "1032462": "Mercearia",
    "1032336": "Bazar e Utilidades", "1032402": "Bazar e Utilidades", "1032450": "Bazar e Utilidades",
    "1032048": "Bazar e Utilidades", "1032192": "Bazar e Utilidades", "1032394": "Bazar e Utilidades",
}

BUSCAR_JS = """
async ([url]) => {
  try {
    const r = await fetch(url);
    if (!r.ok) return {erro: r.status};
    return await r.json();
  } catch (e) {
    return {erro: String(e)};
  }
}
"""


def _abrir(p, janela=False):
    opcoes = {"headless": not janela}
    if janela:
        opcoes["args"] = ["--start-minimized"]
    if os.getenv("CHROME_PATH"):
        opcoes["executable_path"] = os.getenv("CHROME_PATH")
    elif os.name == "nt":
        opcoes["channel"] = os.getenv("NAVEGADOR", "msedge")
    nav = p.chromium.launch(**opcoes)
    ctx = nav.new_context(locale="pt-BR", viewport={"width": 420, "height": 900})
    return nav, ctx


def _produto(h, categoria):
    pr = h.get("pricing") or {}
    preco = pr.get("price")
    if not preco:
        return None
    promo = None
    if pr.get("promotion") and pr.get("promotionalPrice") and pr["promotionalPrice"] < preco:
        promo = {"preco": float(pr["promotionalPrice"]), "tipo": "Oferta", "ate": None, "preco_de": float(preco)}
        preco = pr["promotionalPrice"]
    q = h.get("quantity") or {}
    foto = h.get("image") or ""
    # o Condor costuma pôr o código de barras no nome do arquivo da foto
    m = re.search(r"(?<!\d)(\d{13})(?!\d)", foto.rsplit("/", 1)[-1])
    return {
        "mercado": "condor",
        "id": f"condor:{h.get('id')}",
        "nome": (h.get("name") or "").strip(),
        "marca": h.get("brandName") or None,
        "ean": ean_valido(m.group(1)) if m else None,
        "preco": float(preco),
        "atacado": [],
        "promo": promo,
        "categoria": categoria,
        "unidade": "kg" if (h.get("saleUnit") or "").upper() == "KG" or q.get("sellByWeightAndUnit") else None,
        "url": f"{SITE}/produtos/{h.get('id')}/{h.get('slug') or ''}",
        "foto": foto or None,
        "disponivel": (q.get("inStock") or 0) > 0 if q else True,
    }


def coletar(limite_paginas=None):
    from playwright.sync_api import sync_playwright

    produtos, vistos = [], set()
    with sync_playwright() as p:
        teste = f"{BUSCA}?brands=&categories=&tags=&sortField=_score&sortOrder=desc&search=&size=1&from=0"
        for janela in (False, True):
            nav, ctx = _abrir(p, janela)
            pg = ctx.new_page()
            pg.goto(SITE, wait_until="domcontentloaded", timeout=90000)
            pg.wait_for_timeout(4000)
            r = pg.evaluate(BUSCAR_JS, [teste])
            if r and "erro" not in r:
                break
            nav.close()
            if janela:
                raise RuntimeError(f"Condor recusou a busca mesmo com o navegador aberto ({(r or {}).get('erro')})")
            log(f"Condor · busca recusada no modo invisível ({(r or {}).get('erro')}); abrindo o navegador minimizado")
        for cid, nome in DEPARTAMENTOS.items():
            inicio, antes, paginas = 0, len(produtos), 0
            while True:
                url = (f"{BUSCA}?brands=&categories=&tags=&sortField=_score&sortOrder=desc"
                       f"&search=&size=20&from={inicio}&categoryId={cid}")
                j = None
                for tentativa in range(3):
                    j = pg.evaluate(BUSCAR_JS, [url])
                    if j and "erro" not in j:
                        break
                    time.sleep(5 * (tentativa + 1))
                if not j or "erro" in j:
                    log(f"Condor · {nome}: busca falhou em {inicio} ({(j or {}).get('erro')})")
                    break
                for h in j.get("hits") or []:
                    item = _produto(h, nome)
                    if item and item["id"] not in vistos:
                        vistos.add(item["id"])
                        produtos.append(item)
                paginas += 1
                if not j.get("hasNext") or (limite_paginas and paginas >= limite_paginas):
                    break
                inicio = j.get("nextFrom") or inicio + 20
                time.sleep(PAUSA)
            log(f"Condor · {nome}: +{len(produtos) - antes} (total {len(produtos)})")
        nav.close()
    return produtos


def encartes():
    return []
