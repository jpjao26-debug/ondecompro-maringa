"""Roda tudo: coleta os mercados, lê os encartes, compara e gera os dados do app.

Uso:  python -m coletor.rodar            (todos os mercados)
      MERCADOS=tenda python -m coletor.rodar
"""
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import hashlib
import re

from . import amigao, assai, atacadao, comparar, condor, ler_encartes, lejon, maxatac, muffato
from .comum import DADOS, RAIZ, ler_json, log, salvar_json, sem_acento

COLETORES = {"muffato": muffato, "atacadao": atacadao, "amigao": amigao, "condor": condor,
             "assai": assai, "lejon": lejon, "max": maxatac}
SO_ENCARTE = {"assai", "lejon", "max"}  # não vendem online: o preço vem só do encarte


LOCAIS_CHAVES = [
    RAIZ / "chaves.env",
    RAIZ.parent / "ondecompro" / "chaves.env",   # a mesma chave do OndeCompro de Ubatuba
    Path.home() / "Desktop" / "Canal Ocean" / "chaves.env",
    Path.home() / "OneDrive" / "Desktop" / "Canal Ocean" / "chaves.env",
    Path.home() / "chaves.env",
]
NOMES_CHAVE_CLAUDE = ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "ANTHROPIC_KEY", "CLAUDE_KEY")
NOMES_CHAVE_GEMINI = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_KEY")


def carregar_chaves():
    """Lê o chaves.env (nunca mostra os valores). Aceita a chave do Claude com nomes comuns."""
    extra = os.getenv("CHAVES_ENV")
    for caminho in ([Path(extra)] if extra else []) + LOCAIS_CHAVES:
        if caminho.exists():
            for linha in caminho.read_text(encoding="utf-8-sig").splitlines():
                linha = linha.strip()
                if linha.lower().startswith("export "):
                    linha = linha[7:]
                if linha and not linha.startswith("#") and "=" in linha:
                    k, v = linha.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break
    if not os.getenv("GEMINI_API_KEY"):
        for nome in NOMES_CHAVE_GEMINI[1:]:
            if os.getenv(nome):
                os.environ["GEMINI_API_KEY"] = os.environ[nome]
                break
    if not os.getenv("ANTHROPIC_API_KEY"):
        for nome in NOMES_CHAVE_CLAUDE[1:]:
            if os.getenv(nome):
                os.environ["ANTHROPIC_API_KEY"] = os.environ[nome]
                break


def aplicar_encartes(brutos, promos):
    """Oferta de encarte vale como preço do mercado durante a validade (quando não tem condição especial)."""
    por_id = {p["id"]: p for lista in brutos.values() for p in lista}
    for of in promos:
        p = por_id.get(of.get("id"))
        if not p or not of.get("preco"):
            continue
        preco = float(of["preco"])
        if preco >= p["preco"]:
            continue
        p["promo"] = {"preco": preco, "tipo": "Encarte", "ate": of.get("fim") or of.get("periodo"),
                      "preco_de": p["preco"], "condicao": of.get("condicao")}
        if not of.get("condicao"):
            p["preco"] = preco


def produtos_do_encarte(promos, mercado):
    """Para quem só tem encarte: cada oferta lida vira um produto, para comparar com os outros mercados."""
    saida, vistos = [], set()
    for of in promos:
        if of.get("m") != mercado or not of.get("preco"):
            continue
        partes = [of.get("produto") or ""]
        base = sem_acento(partes[0]).lower()
        for extra in (of.get("marca"), of.get("tamanho")):
            if extra and sem_acento(extra).lower() not in base:
                partes.append(extra)
        nome = re.sub(r"\s+", " ", " ".join(partes)).strip()
        if not nome:
            continue
        chave = hashlib.md5(sem_acento(nome).lower().encode()).hexdigest()[:12]
        of["id"] = f"{mercado}:enc:{chave}"  # liga a oferta do encarte ao item no app
        if chave in vistos:
            continue
        vistos.add(chave)
        cond = (of.get("condicao") or "").lower()
        por_kg = "kg" in cond or (of.get("tamanho") or "").strip().lower() in ("kg", "1kg", "o kg")
        promo = {"preco": float(of["preco"]), "tipo": "Encarte", "ate": of.get("fim") or of.get("periodo"),
                 "preco_de": float(of["preco_normal"]) if of.get("preco_normal") else None,
                 "condicao": of.get("condicao")}
        saida.append({
            "mercado": mercado, "id": f"{mercado}:enc:{chave}", "nome": nome, "marca": of.get("marca"),
            "ean": None, "preco": float(of["preco"]), "atacado": [], "promo": promo, "categoria": "Encarte",
            "unidade": "kg" if por_kg else None, "url": of.get("img"), "foto": None, "disponivel": True,
            "encarte": True,
        })
    return saida


def main():
    carregar_chaves()
    escolhidos = [m.strip() for m in os.getenv("MERCADOS", ",".join(COLETORES)).split(",") if m.strip()]
    brutos, encartes, falhas = {}, [], []

    def coletar_um(m):
        mod = COLETORES[m]
        log(f"Coletando {m}…")
        produtos = mod.coletar()
        salvar_json(DADOS / f"bruto_{m}.json", produtos)
        try:
            encs = mod.encartes()
        except Exception:
            traceback.print_exc()
            encs = []
        return produtos, encs

    # os mercados são sites diferentes, então coletamos todos ao mesmo tempo
    with ThreadPoolExecutor(max_workers=len(escolhidos) or 1) as pool:
        tarefas = {pool.submit(coletar_um, m): m for m in escolhidos}
        for t in as_completed(tarefas):
            m = tarefas[t]
            try:
                brutos[m], encs = t.result()
                encartes += encs
                log(f"{m}: {len(brutos[m])} produtos")
            except Exception:
                traceback.print_exc()
                falhas.append(m)
                antigo = ler_json(DADOS / f"bruto_{m}.json")
                if antigo:
                    log(f"{m}: usando a coleta anterior")
                    brutos[m] = antigo
    promos = ler_encartes.processar(encartes, brutos)
    aplicar_encartes(brutos, promos)
    for m in SO_ENCARTE & set(escolhidos):
        brutos[m] = produtos_do_encarte(promos, m)
        log(f"{m}: {len(brutos[m])} ofertas lidas do encarte")
    comparar.gerar(brutos, encartes, promos)
    if falhas:
        log(f"Atenção: falha na coleta de {', '.join(falhas)}")
        if len(falhas) == len(escolhidos):
            sys.exit(1)


if __name__ == "__main__":
    main()
