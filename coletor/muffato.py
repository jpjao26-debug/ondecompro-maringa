"""Coletor do Super Muffato — loja online de Maringá João Paulino (canal de venda 2).

O Muffato do Catuaí (Av. Colombo) não vende online; por decisão do usuário, o app
usa o preço da loja online João Paulino como referência do Muffato em Maringá.
"""
from . import vtex

BASE = "https://www.supermuffato.com.br"
CANAL = "2"  # Maringá - João Paulino


def coletar(limite_paginas=None):
    produtos = []
    for p, it, depto in vtex.catalogo(BASE, {"sc": CANAL}, limite_paginas, rotulo="Muffato"):
        oferta = None
        for v in it.get("sellers") or []:
            o = v.get("commertialOffer") or {}
            if o.get("Price"):
                oferta = o
                break
        if not oferta:
            continue
        produtos.append(vtex.item("muffato", BASE, p, it, depto, oferta["Price"], oferta.get("ListPrice"),
                                  (oferta.get("AvailableQuantity") or 0) > 0))
    return produtos


def encartes():
    return []
