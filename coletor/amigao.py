"""Coletor do Amigão — preço da loja online de Maringá (vendedor amigao001)."""
from . import vtex
from .comum import log

API = "https://amigao.vtexcommercestable.com.br"
SITE = "https://www.amigao.com"
VENDEDOR = "amigao001"   # Maringá
CEP = "87013000"


def coletar(limite_paginas=None):
    lista = vtex.catalogo(API, {}, limite_paginas, rotulo="Amigão")
    log(f"Amigão · conferindo preço da loja de Maringá em {len(lista)} itens…")
    precos = vtex.simular(API, [it["itemId"] for _, it, _ in lista], VENDEDOR, CEP)
    produtos = []
    for p, it, depto in lista:
        pr = precos.get(it["itemId"])
        if pr:
            produtos.append(vtex.item("amigao", SITE, p, it, depto, pr["preco"], pr["de"], True))
    return produtos


def encartes():
    return []
