"""Leitura do catálogo de lojas feitas na plataforma VTEX (Muffato, Atacadão, Amigão).

Usa as mesmas consultas públicas que o próprio site usa:
- a árvore de categorias, para percorrer o catálogo inteiro;
- a busca de produtos (50 por página; a VTEX só deixa ir até o item 2.500 por consulta,
  então categorias maiores são divididas nas subcategorias);
- a "simulação de carrinho" com a loja de Maringá, que devolve o preço e a disponibilidade
  daquela loja (é o que o site mostra quando você escolhe a loja ou digita o CEP).
"""
import os
import re
import time

import requests

from .comum import ean_valido, log, sessao

PAUSA = float(os.getenv("VTEX_PAUSA", "0.3"))
LIMITE_VTEX = 2500


def _get(s, url, params, tentativas=4):
    ultimo = None
    for i in range(tentativas):
        try:
            r = s.get(url, params=params, timeout=60)
            if r.status_code in (200, 206):
                return r
            ultimo = f"HTTP {r.status_code}"
            if r.status_code in (400, 401, 403, 404):
                break
        except requests.RequestException as e:
            ultimo = e.__class__.__name__
        time.sleep(3 * (2 ** i))
    raise RuntimeError(f"VTEX: falha em {url} ({ultimo})")


def _total(r):
    m = re.search(r"/(\d+)$", r.headers.get("resources") or "")
    return int(m.group(1)) if m else None


def _buscar(s, base, fq, extra, inicio):
    params = {"fq": fq, "_from": inicio, "_to": inicio + 49, "O": "OrderByNameASC", **extra}
    return _get(s, f"{base}/api/catalog_system/pub/products/search", params)


def _percorrer(s, base, cat, caminho, nome_depto, extra, produtos, vistos, limite_paginas):
    fq = "C:/" + "/".join(caminho) + "/"
    r = _buscar(s, base, fq, extra, 0)
    total = _total(r) or 0
    filhos = cat.get("children") or []
    if total > LIMITE_VTEX and filhos:
        for f in filhos:
            _percorrer(s, base, f, caminho + [str(f["id"])], nome_depto, extra, produtos, vistos, limite_paginas)
        return
    inicio, paginas = 0, 0
    while True:
        lista = r.json() if r.status_code in (200, 206) else []
        for p in lista:
            for it in p.get("items") or []:
                if it.get("itemId") in vistos:
                    continue
                vistos.add(it.get("itemId"))
                produtos.append((p, it, nome_depto))
        paginas += 1
        inicio += 50
        if inicio >= min(total, LIMITE_VTEX) or not lista or (limite_paginas and paginas >= limite_paginas):
            break
        time.sleep(PAUSA)
        r = _buscar(s, base, fq, extra, inicio)


def catalogo(base, extra=None, limite_paginas=None, nomes=None, rotulo="VTEX"):
    """Devolve [(produto, sku, departamento)] do catálogo inteiro."""
    s = sessao()
    extra = extra or {}
    arvore = _get(s, f"{base}/api/catalog_system/pub/category/tree/3", {}).json()
    produtos, vistos = [], set()
    for d in arvore:
        nome = (nomes or {}).get(str(d["id"])) or d.get("name")
        antes = len(produtos)
        try:
            _percorrer(s, base, d, [str(d["id"])], nome, extra, produtos, vistos, limite_paginas)
        except RuntimeError as e:
            log(f"{rotulo} · {nome}: {e}")
        log(f"{rotulo} · {nome}: +{len(produtos) - antes} (total {len(produtos)})")
    return produtos


def simular(base, skus, vendedor, cep, extra=None):
    """Preço e disponibilidade de cada SKU na loja escolhida (em lotes de 50)."""
    s = sessao()
    s.headers["content-type"] = "application/json"
    saida = {}
    for i in range(0, len(skus), 50):
        lote = skus[i:i + 50]
        corpo = {"items": [{"id": k, "quantity": 1, "seller": vendedor} for k in lote],
                 "country": "BRA", "postalCode": cep}
        for tentativa in range(4):
            try:
                r = s.post(f"{base}/api/checkout/pub/orderForms/simulation", params=extra or {}, json=corpo, timeout=60)
                if r.status_code == 200:
                    for it in r.json().get("items") or []:
                        if it.get("availability") == "available" and it.get("price"):
                            saida[it["id"]] = {
                                "preco": it["price"] / 100,
                                "de": (it.get("listPrice") or 0) / 100,
                            }
                    break
            except requests.RequestException:
                pass
            time.sleep(3 * (2 ** tentativa))
        time.sleep(PAUSA)
    return saida


def item(mercado, base_url, p, it, depto, preco, preco_de=None, disponivel=True):
    imagens = it.get("images") or []
    foto = imagens[0].get("imageUrl") if imagens else None
    promo = None
    if preco_de and preco_de > preco + 0.009:
        promo = {"preco": float(preco), "tipo": "Oferta", "ate": None, "preco_de": float(preco_de)}
    nome = (p.get("productName") or it.get("nameComplete") or "").strip()
    unidade = (it.get("measurementUnit") or "").lower()
    # vendido por peso: unidade "kg", multiplicador fracionado ou nome terminando em "kg" sem número antes
    por_kg = unidade == "kg" or (it.get("unitMultiplier") or 1) != 1 or bool(re.search(r"(?i)(?<![\d,.])\s+kg$", nome))
    return {
        "mercado": mercado,
        "id": f"{mercado}:{it.get('itemId')}",
        "nome": nome,
        "marca": p.get("brand") or None,
        "ean": ean_valido(it.get("ean")),
        "preco": float(preco),
        "atacado": [],
        "promo": promo,
        "categoria": depto,
        "unidade": "kg" if por_kg else None,
        "url": f"{base_url}/{p.get('linkText')}/p" if p.get("linkText") else base_url,
        "foto": foto,
        "disponivel": bool(disponivel),
    }
