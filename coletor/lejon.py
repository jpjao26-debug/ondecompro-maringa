"""Lejon Atacarejo (Rua Fernão Dias, 601) — não vende online; só publica encartes no site."""
import re
from urllib.parse import urljoin

from .comum import sessao

SITE = "https://lejonautoservico.com.br/"


def coletar(limite_paginas=None):
    return []  # sem catálogo online: os preços vêm do encarte


def encartes():
    s = sessao()
    s.headers["Accept"] = "text/html"
    html = s.get(SITE, timeout=60).text
    pdfs = re.findall(r'/uploads/encartes/(\d{14})_([^"\']+?)\.pdf', html)
    nomes = {}
    for marca, nome in pdfs:
        nomes[marca[:12]] = nome.replace("_", " ").strip()
    grupos = {}
    for marca, n in re.findall(r'/static/encarte_paginas/pagina_(\d{14})_(\d+)\.jpg', html):
        grupos.setdefault(marca, set()).add(int(n))
    saida = []
    for marca, paginas in sorted(grupos.items()):
        titulo = nomes.get(marca[:12]) or next((v for k, v in nomes.items() if abs(int(k) - int(marca[:12])) < 5), "Ofertas Lejon")
        periodo = re.search(r"\d{1,2}\s*a\s*\d{1,2}\s*de\s*\w+", titulo)
        saida.append({
            "mercado": "lejon", "titulo": titulo, "inicio": None, "fim": None,
            "periodo": periodo.group(0) if periodo else None,
            "imagens": [urljoin(SITE, f"/static/encarte_paginas/pagina_{marca}_{i}.jpg") for i in sorted(paginas)],
        })
    return saida
