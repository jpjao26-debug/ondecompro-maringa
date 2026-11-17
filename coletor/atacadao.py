"""Coletor do Atacadão — preço da loja Maringá Fernão Dias (vendedor atacadaobr42).

O catálogo do site é nacional (~57 mil itens), mas só ~8 mil estão à venda em Maringá.
1) A busca do site, com a região de Maringá, lista só o que a loja de Maringá vende;
2) a simulação de carrinho com a loja de Maringá dá o preço exato de lá
   (o mesmo que o site mostra depois que você informa o CEP).
"""
import time

import requests

from . import vtex
from .comum import log, sessao

BASE = "https://www.atacadao.com.br"
BUSCA = f"{BASE}/api/io/_v/api/intelligent-search/product_search"
VENDEDOR = "atacadaobr42"   # Maringá Fernão Dias
CEP = "87013000"            # CEP do centro de Maringá (só para o site saber a cidade)
LIMITE_BUSCA = 2500         # a busca não pagina além disso; departamentos maiores são divididos


def _regiao(s):
    r = s.get(f"{BASE}/api/checkout/pub/regions", params={"country": "BRA", "postalCode": CEP}, timeout=60)
    return r.json()[0]["id"]


def _pagina(s, caminho, regiao, pagina):
    for tentativa in range(4):
        try:
            r = s.get(f"{BUSCA}/{caminho}", timeout=60, params={
                "query": "", "count": 50, "page": pagina, "regionId": regiao,
                "hideUnavailableItems": "true", "sort": "name:asc"})
            if r.status_code == 200:
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(3 * (2 ** tentativa))
    raise RuntimeError(f"Atacadão: busca falhou em {caminho} página {pagina}")


def _listar(s, caminho, regiao, filhos, nome, saida, vistos, limite_paginas):
    j = _pagina(s, caminho, regiao, 1)
    total = j.get("recordsFiltered") or 0
    if total > LIMITE_BUSCA and filhos:
        for f in filhos:
            slug = f["url"].rstrip("/").split("/")[-1]
            nivel = caminho.count("category-") + 1
            _listar(s, f"{caminho}/category-{nivel}/{slug}", regiao, f.get("children") or [], nome,
                    saida, vistos, limite_paginas)
        return
    pagina = 1
    while True:
        for p in j.get("products") or []:
            for it in p.get("items") or []:
                if it.get("itemId") not in vistos:
                    vistos.add(it.get("itemId"))
                    saida.append((p, it, nome))
        if not j.get("products") or pagina * 50 >= min(total, LIMITE_BUSCA) or (limite_paginas and pagina >= limite_paginas):
            break
        pagina += 1
        time.sleep(vtex.PAUSA)
        j = _pagina(s, caminho, regiao, pagina)


def coletar(limite_paginas=None):
    s = sessao()
    regiao = _regiao(s)
    arvore = s.get(f"{BASE}/api/catalog_system/pub/category/tree/3", timeout=60).json()
    lista, vistos = [], set()
    for d in arvore:
        slug = d["url"].rstrip("/").split("/")[-1]
        antes = len(lista)
        try:
            _listar(s, f"category-1/{slug}", regiao, d.get("children") or [], d["name"], lista, vistos, limite_paginas)
        except RuntimeError as e:
            log(str(e))
        log(f"Atacadão · {d['name']}: +{len(lista) - antes} à venda em Maringá (total {len(lista)})")
    log(f"Atacadão · conferindo o preço da loja de Maringá em {len(lista)} itens…")
    precos = vtex.simular(BASE, [it["itemId"] for _, it, _ in lista], VENDEDOR, CEP)
    produtos = []
    for p, it, depto in lista:
        pr = precos.get(it["itemId"])
        if pr:
            produtos.append(vtex.item("atacadao", BASE, p, it, depto, pr["preco"], pr["de"], True))
    return produtos


def encartes():
    return []
