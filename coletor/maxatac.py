"""Max Atacadista Maringá (Av. Colombo, 2720; loja 35 do Grupo Muffato) — só encartes."""
from .comum import sessao

API = "https://institucional.supermuffato.com.br/webtools/services/api/sm-rds-ofertas.php"
LOJA = "35"


def coletar(limite_paginas=None):
    return []  # sem catálogo online: os preços vêm do encarte


def encartes():
    s = sessao()
    j = s.get(API, params={"action": "getOffers", "store": LOJA}, timeout=60).json()
    saida = []
    for o in j.get("offers") or []:
        for fl in o.get("flyer") or []:
            imgs = [it for it in fl.get("item") or [] if str(it.get("type")) == "1" and it.get("image")]
            if not imgs:
                continue
            imgs.sort(key=lambda it: int(it.get("position") or 0))
            urls = []
            for it in imgs:
                u = it["image"]
                u = ("https:" + u if u.startswith("//") else u).replace(" ", "%20")
                if u not in urls:
                    urls.append(u)
            saida.append({"mercado": "max", "titulo": "Ofertas Max Atacadista", "inicio": None, "fim": None,
                          "periodo": None, "imagens": urls})
    return saida
