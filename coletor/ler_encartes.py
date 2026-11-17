"""Lê os encartes (imagens) com IA e transforma em lista de ofertas.

Usa o Gemini (Google), plano gratuito: chave GEMINI_API_KEY no chaves.env.
Se só houver chave do Claude (ANTHROPIC_API_KEY), usa o Claude.
Cada imagem é lida uma vez só (fica guardada em dados/cache_encartes.json).
"""
import base64
import io
import json
import os
import re
import time

import requests

from .comum import DADOS, hoje, ler_json, log, salvar_json, sem_acento, sessao

MODELO_CLAUDE = os.getenv("MODELO_ENCARTE_CLAUDE", "claude-sonnet-5-5")
# os modelos "lite" leem uma página em ~8 s e quase nunca estão lotados no plano grátis;
# o 3.8-flash fica por último porque vive ocupado (503) e demora minutos
MODELOS_GEMINI = [m for m in [os.getenv("MODELO_ENCARTE_GEMINI"), "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
                              "gemini-flash-lite-latest", "gemini-3.8-flash"] if m]
LIMITE_MINUTOS = float(os.getenv("ENCARTES_MINUTOS", "25"))  # o que não der tempo fica para a próxima coleta
API_CLAUDE = "https://api.anthropic.com/v1/messages"
API_GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
CACHE = DADOS / "cache_encartes.json"

INSTRUCAO = """Você está lendo a imagem de um encarte (folheto de ofertas) de supermercado brasileiro.
Liste TODAS as ofertas de produtos que aparecem, uma por item, no formato JSON abaixo, e responda SÓ com o JSON:
[{"produto": "nome do produto como aparece", "marca": "marca ou null", "tamanho": "ex.: 5kg, 900ml, 12un ou null",
  "preco": 12.90, "preco_normal": null, "condicao": "ex.: 'leve 3 pague 2', 'no cartão da loja', 'a partir de 3 un', 'preço por kg' ou null"}]
Regras: preço em número com ponto decimal; se houver "de R$ X por R$ Y", preco = Y e preco_normal = X;
se o preço for por kg, coloque isso em condicao; não invente itens que não estejam legíveis."""


def _chave():
    return os.getenv("GEMINI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")


def _extrair_lista(texto):
    m = re.search(r"\[.*\]", texto or "", re.S)
    return json.loads(m.group(0)) if m else []


def _imagem_b64(url, s, arquivo=None):
    if arquivo and os.path.exists(arquivo):
        # imagem já baixada pelo navegador do coletor (caso do Semar)
        with open(arquivo, "rb") as f:
            dados = f.read()
        tipo = "image/png" if dados[:4] == b"\x89PNG" else "image/jpeg"
    else:
        r = s.get(url, timeout=90)
        r.raise_for_status()
        dados, tipo = r.content, r.headers.get("content-type", "image/jpeg").split(";")[0]
    from PIL import Image
    img = Image.open(io.BytesIO(dados))
    if max(img.size) > 1600 or len(dados) > 1_500_000 or tipo not in ("image/jpeg", "image/png", "image/webp"):
        # imagem menor = leitura bem mais rápida, e ainda dá para ler os preços
        img = img.convert("RGB")
        img.thumbnail((1600, 1600))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        dados, tipo = buf.getvalue(), "image/jpeg"
    return base64.b64encode(dados).decode(), tipo


def _ler_imagem(url, s, arquivo=None):
    b64, tipo = _imagem_b64(url, s, arquivo)
    if os.getenv("GEMINI_API_KEY"):
        return _ler_gemini(b64, tipo)
    return _ler_claude(b64, tipo)


def _ler_gemini(b64, tipo):
    corpo = {
        "contents": [{"parts": [{"inline_data": {"mime_type": tipo, "data": b64}}, {"text": INSTRUCAO}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    cab = {"x-goog-api-key": os.getenv("GEMINI_API_KEY"), "content-type": "application/json"}
    modelos = list(MODELOS_GEMINI)
    ultimo = ""
    for rodada in range(2):
        for modelo in list(modelos):
            try:
                r = requests.post(API_GEMINI.format(modelo=modelo), headers=cab, json=corpo, timeout=90)
            except requests.RequestException as e:
                ultimo = f"{modelo}: {e.__class__.__name__}"
                continue
            if r.status_code == 200:
                partes = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                return _extrair_lista("".join(p.get("text", "") for p in partes))
            if r.status_code == 404:
                modelos.remove(modelo)  # modelo aposentado pelo Google
                continue
            if r.status_code in (429, 500, 502, 503):
                ultimo = f"{modelo}: ocupado ({r.status_code})"
                continue  # plano grátis cheio: tenta o próximo modelo
            raise RuntimeError(f"Gemini respondeu {r.status_code}: {r.text[:200]}")
        time.sleep(20)
    raise RuntimeError(f"Gemini ocupado agora, tento de novo na próxima coleta ({ultimo})")


def _ler_claude(b64, tipo):
    corpo = {
        "model": MODELO_CLAUDE,
        "max_tokens": 8000,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": tipo, "data": b64}},
            {"type": "text", "text": INSTRUCAO},
        ]}],
    }
    cab = {"x-api-key": os.getenv("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01", "content-type": "application/json"}
    for tentativa in range(3):
        r = requests.post(API_CLAUDE, headers=cab, json=corpo, timeout=180)
        if r.status_code == 200:
            return _extrair_lista("".join(b.get("text", "") for b in r.json().get("content", [])))
        if r.status_code in (429, 500, 502, 503, 529):
            time.sleep(20 * (tentativa + 1))
            continue
        raise RuntimeError(f"Claude respondeu {r.status_code}: {r.text[:200]}")
    raise RuntimeError("Claude indisponível depois de 3 tentativas")


def _palavras(t):
    return set(w for w in re.findall(r"[a-z0-9]+", sem_acento(t or "").lower()) if len(w) > 2)


def _casar(oferta, itens_do_mercado):
    """Procura no catálogo do mesmo mercado o produto mais parecido com a oferta do encarte."""
    alvo = _palavras(" ".join(filter(None, [oferta.get("produto"), oferta.get("marca"), oferta.get("tamanho")])))
    if not alvo:
        return None
    melhor, nota = None, 0.0
    for it in itens_do_mercado:
        p = _palavras(it["nome"])
        if not p:
            continue
        inter = len(alvo & p)
        n = inter / len(alvo | p)
        if n > nota:
            melhor, nota = it, n
    return melhor if nota >= 0.5 else None


def processar(encartes, brutos):
    """Lê as imagens novas e devolve a lista de ofertas de encarte (com o produto do catálogo, se achar)."""
    cache = ler_json(CACHE, {})
    if not _chave():
        log("Encartes: sem GEMINI_API_KEY no chaves.env — imagens ficam só para ver no app, sem leitura de preços")
        return []
    s = sessao()
    saida = []
    inicio, avisou = time.time(), False
    for enc in encartes:
        arquivos = enc.get("arquivos") or []
        for n, url in enumerate(enc.get("imagens", [])):
            if url not in cache and time.time() - inicio > LIMITE_MINUTOS * 60:
                if not avisou:
                    log(f"Encartes: passou de {LIMITE_MINUTOS:.0f} min; o resto fica para a próxima coleta")
                    avisou = True
                continue
            if url not in cache:
                try:
                    log(f"Encartes: lendo {enc['mercado']} · {enc.get('titulo', '')[:40]} · página {n + 1}")
                    arq = arquivos[n] if n < len(arquivos) else None
                    cache[url] = {"lido": hoje(), "itens": _ler_imagem(url, s, arq)}
                    salvar_json(CACHE, cache)
                    time.sleep(4)  # o plano grátis do Gemini aceita poucos pedidos por minuto
                except Exception as e:
                    log(f"Encartes: falhou {url}: {e}")
                    continue
            for of in cache[url]["itens"]:
                if not isinstance(of, dict) or not of.get("preco"):
                    continue
                # "pct", "un", "cada"... não são condições de verdade, só a embalagem
                if (of.get("condicao") or "").strip().lower().strip(".") in ("pct", "pacote", "un", "unid", "unidade", "cada", "lata", "cx", "caixa", "fardo", "pç", "pc"):
                    of["condicao"] = None
                casado = _casar(of, brutos.get(enc["mercado"], []))
                saida.append({
                    "m": enc["mercado"],
                    "produto": of.get("produto"), "marca": of.get("marca"), "tamanho": of.get("tamanho"),
                    "preco": of.get("preco"), "preco_normal": of.get("preco_normal"), "condicao": of.get("condicao"),
                    "fim": enc.get("fim"), "periodo": enc.get("periodo"), "img": url,
                    "id": casado["id"] if casado else None,
                })
    # limpa do cache imagens que já não estão em nenhum encarte atual
    atuais = {u for e in encartes for u in e.get("imagens", [])}
    salvar_json(CACHE, {u: v for u, v in cache.items() if u in atuais})
    return saida
