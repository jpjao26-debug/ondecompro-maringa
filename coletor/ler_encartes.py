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

from .comparar import _RE_LEVE, _RE_MULTI, _RE_TAM, tamanho
from .comum import DADOS, SITE_DADOS, hoje, ler_json, log, salvar_json, sem_acento, sessao

MODELO_CLAUDE = os.getenv("MODELO_ENCARTE_CLAUDE", "claude-sonnet-5-5")
# os modelos "lite" leem uma página em ~8 s e quase nunca estão lotados no plano grátis;
# o 3.8-flash fica por último porque vive ocupado (503) e demora minutos
USO_MODELOS = {}  # modelo -> páginas lidas nesta coleta (vai para o log)
MODELOS_GEMINI = [m for m in [os.getenv("MODELO_ENCARTE_GEMINI"), "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
                              "gemini-flash-lite-latest", "gemini-3.8-flash"] if m]
LIMITE_MINUTOS = float(os.getenv("ENCARTES_MINUTOS", "25"))  # o que não der tempo fica para a próxima coleta
API_CLAUDE = "https://api.anthropic.com/v1/messages"
API_GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
CACHE = DADOS / "cache_encartes.json"
FOTOS = SITE_DADOS / "fotos"          # fotos recortadas do encarte (vão junto com o app)
VERSAO_LEITURA = 3                    # 2 = posição de cada produto na página; 3 = preço de clube separado
RECORTAR = {"assai", "lejon", "max"}  # mercados sem loja online: a foto vem do próprio encarte

INSTRUCAO = """Você está lendo a imagem de um encarte (folheto de ofertas) de supermercado brasileiro.
Liste TODAS as ofertas de produtos que aparecem, uma por item, no formato JSON abaixo, e responda SÓ com o JSON:
[{"produto": "nome do produto como aparece", "marca": "marca ou null", "tamanho": "ex.: 5kg, 900ml, 12un ou null",
  "preco": 12.90, "preco_normal": null, "condicao": "ex.: 'leve 3 pague 2', 'no cartão da loja', 'a partir de 3 un', 'preço por kg' ou null",
  "preco_clube": null, "clube": null, "caixa": [ymin, xmin, ymax, xmax]}]
Regras: preço em número com ponto decimal; se houver "de R$ X por R$ Y", preco = Y e preco_normal = X;
"preco" é sempre o preço que vale para qualquer cliente. Se o encarte mostrar também um preço só para
clube, cartão ou app da loja (ex.: MáxClube, Meu Assaí, cartão Tenda, "cadastrado no app"), coloque esse
valor em "preco_clube" e o nome do clube/condição em "clube" — nunca no lugar de "preco";
se o preço for por kg, coloque isso em condicao; não invente itens que não estejam legíveis.
"caixa" é o retângulo em volta da FOTO do produto (só a embalagem/foto, sem o preço e sem o texto),
em coordenadas de 0 a 1000 relativas à imagem inteira; use null se não houver foto do produto."""


def _chave():
    return os.getenv("GEMINI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")


def _extrair_lista(texto):
    m = re.search(r"\[.*\]", texto or "", re.S)
    return json.loads(m.group(0)) if m else []


def _baixar(url, s, arquivo=None):
    if arquivo and os.path.exists(arquivo):
        # imagem já baixada pelo navegador do coletor (caso do Assaí)
        with open(arquivo, "rb") as f:
            dados = f.read()
        return dados, ("image/png" if dados[:4] == b"\x89PNG" else "image/jpeg")
    r = s.get(url, timeout=90)
    r.raise_for_status()
    return r.content, r.headers.get("content-type", "image/jpeg").split(";")[0]


def _imagem_b64(url, s, arquivo=None, dados=None, tipo=None):
    if dados is None:
        dados, tipo = _baixar(url, s, arquivo)
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


def _recortar(dados, itens, url):
    """Recorta a foto de cada produto da página do encarte e guarda em site/dados/fotos/."""
    import hashlib
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(dados)).convert("RGB")
    except Exception:
        return
    W, H = img.size
    FOTOS.mkdir(parents=True, exist_ok=True)
    base = hashlib.md5(url.encode()).hexdigest()[:10]
    for n, of in enumerate(itens):
        cx = of.get("caixa") if isinstance(of, dict) else None
        if not (isinstance(cx, list) and len(cx) == 4 and all(isinstance(v, (int, float)) for v in cx)):
            continue
        y0, x0, y1, x1 = [max(0, min(1000, v)) for v in cx]
        if y1 - y0 < 25 or x1 - x0 < 25 or (y1 - y0) * (x1 - x0) > 450_000:
            continue  # caixa pequena demais ou quase a página inteira: não é a foto de um produto
        m = 0.005  # uma margem bem pequena em volta
        box = (int(max(0, x0 / 1000 - m) * W), int(max(0, y0 / 1000 - m) * H),
               int(min(1, x1 / 1000 + m) * W), int(min(1, y1 / 1000 + m) * H))
        foto = img.crop(box)
        foto.thumbnail((320, 320))
        nome = f"{base}-{n}.jpg"
        foto.save(FOTOS / nome, "JPEG", quality=80)
        of["foto"] = f"dados/fotos/{nome}"


def _ler_imagem(url, s, arquivo=None, recortar=False):
    dados, tipo = _baixar(url, s, arquivo)
    b64, tipo_env = _imagem_b64(url, s, dados=dados, tipo=tipo)
    if os.getenv("GEMINI_API_KEY"):
        itens = _ler_gemini(b64, tipo_env)
    else:
        itens = _ler_claude(b64, tipo_env)
    if recortar:
        _recortar(dados, itens, url)
    return itens


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
                USO_MODELOS[modelo] = USO_MODELOS.get(modelo, 0) + 1
                return _extrair_lista("".join(p.get("text", "") for p in partes))
            if r.status_code == 404:
                modelos.remove(modelo)  # modelo aposentado pelo Google
                if modelo in MODELOS_GEMINI:
                    MODELOS_GEMINI.remove(modelo)
                    log(f"Encartes: o modelo {modelo} não existe mais no Gemini; sigo com os outros")
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


# palavras que não dizem nada sobre o produto
_PARADA = {"de", "da", "do", "das", "dos", "em", "com", "e", "a", "o", "ou", "p", "c", "kg", "un", "und", "unid",
           "cada", "pct", "pacote", "sabores", "varios", "diversos", "tipos", "aprox"}
# palavras que mudam o produto (leite x leite em pó, creme de leite x zero lactose):
# FORMA: se o encarte diz e o site não, não é o mesmo (o encarte às vezes omite "pó", então só nesse sentido)
_FORMA = {"po", "liquido", "flocos", "ralado", "moido", "condensado", "creme", "fermentado", "empanado",
          "empanados", "temperado", "refil"}
# VARIANTE: se o site diz e o encarte não, é outra versão do produto
_VARIANTE = {"zero", "lactose", "light", "diet", "sem", "desnatado", "semidesnatado", "integral", "a2"}
# no Shibata o "kg" é a bandeja/peça com peso aproximado (preço da embalagem, não do quilo)
_KG_POR_EMBALAGEM = {"shibata"}


def _radical(w):
    return w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w  # pêssegos = pêssego


def _lista_palavras(t):
    """Palavras do nome, em ordem, sem os tamanhos (400g, 1L... são comparados à parte). Fica 'po', 'uht'..."""
    t = sem_acento(t or "").lower()
    t = _RE_MULTI.sub(" ", t)
    t = _RE_TAM.sub(" ", t)
    return [_radical(w) for w in re.findall(r"[a-z0-9]+", t) if len(w) >= 2 and w not in _PARADA]


def _palavras(t):
    return set(_lista_palavras(t))


def _por_kg_oferta(of):
    """Encarte com preço do quilo ('kg', 'o kg', '/kg') — sem número na frente."""
    tam = sem_acento(of.get("tamanho") or "").lower().strip(" .")
    return bool(re.fullmatch(r"(?:o\s*|/\s*|por\s*)?(?:kg|quilo|kilo)", tam))


def _por_kg_site(it):
    if it.get("mercado") in _KG_POR_EMBALAGEM:
        return False
    if (it.get("unidade") or "").lower() == "kg":
        return True
    n = sem_acento(it.get("nome") or "").lower()
    return bool(re.search(r"(?<![\d.,\s])\s*\b(?:kg|quilo)\b", n)) and not re.search(r"\d\s*(?:kg|g)\b", n)


def _tamanho_oferta(of):
    for t in (of.get("tamanho"), of.get("produto")):
        q, b = tamanho(t or "")
        if q:
            return q, b
    return None, None


def _tamanho_site(it):
    q, b = tamanho(it["nome"])
    leve = _RE_LEVE.search(sem_acento(it["nome"]).lower())
    if leve and (b in (None, "un")):
        return float(leve.group(1)), "un"  # "Leve 4 Pague 3 Unidades" são 4 unidades
    return q, b


def _rotulo_tamanho(q, b):
    return f"#{round(q, 3):g}{b}" if q else None


def _tem_marca(marca, it):
    mw = [w for w in re.findall(r"[a-z0-9]+", sem_acento(marca or "").lower()) if len(w) >= 2 and w not in _PARADA]
    if not mw:
        return True
    nome = sem_acento(f"{it.get('nome') or ''} {it.get('marca') or ''}").lower()
    if all(w in set(re.findall(r"[a-z0-9]+", nome)) for w in mw):
        return True
    return re.sub(r"[^a-z0-9]", "", "".join(mw)) in re.sub(r"[^a-z0-9]", "", nome)  # "Coca-Cola" x "CocaCola"


def _motivo_recusa(of, it, por_kg, tam_of):
    """Por que este produto do site NÃO é a oferta do encarte (None = pode ser)."""
    q, b = _tamanho_site(it)
    if por_kg:
        if not _por_kg_site(it):
            return "encarte é por kg e o site vende por unidade/peça"
    elif tam_of[0]:
        if not q:
            return "site sem tamanho"
        if b != tam_of[1] or abs(q - tam_of[0]) / max(q, tam_of[0]) > 0.05:
            return f"tamanho diferente ({tam_of[0]:g}{tam_of[1]} x {q:g}{b})"
    elif q and b != "un":
        return "encarte sem tamanho e o site tem"  # não dá para conferir (ex.: salsicha a granel x pacote 500g)
    if of.get("marca") and not _tem_marca(of["marca"], it):
        return "marca diferente"
    try:
        r = float(of["preco"]) / float(it["preco"])
    except (TypeError, ValueError, ZeroDivisionError):
        return "sem preço"
    if r < 0.6 or r > 1.6:
        return f"preço muito diferente ({r:.0%} do site)"  # promoção de encarte quase nunca passa de 40%
    return None


def _casar(oferta, itens_do_mercado):
    """Procura no catálogo do mesmo mercado o produto que é a oferta do encarte.
    Além das palavras parecidas, confere tamanho, quilo x unidade, marca, palavras decisivas e preço."""
    texto = " ".join(filter(None, [oferta.get("produto"), oferta.get("marca"), oferta.get("tamanho")]))
    alvo = _palavras(texto)
    if not alvo or not oferta.get("preco"):
        return None
    nucleo = (_lista_palavras(oferta.get("produto")) or _lista_palavras(texto))[0]  # o que é o produto: iogurte, leite...
    por_kg, tam_of = _por_kg_oferta(oferta), _tamanho_oferta(oferta)
    # o que descreve o produto além do nome e da marca (pão de mel, extra virgem...): pelo menos uma tem que bater
    descricao = alvo - {nucleo} - _palavras(oferta.get("marca"))
    if tam_of[0] and not por_kg:
        alvo = alvo | {_rotulo_tamanho(*tam_of)}  # tamanho igual conta como palavra em comum
    # com marca e tamanho conferidos (checados em _motivo_recusa), basta um pouco menos de palavras em comum
    minimo = 0.4 if (oferta.get("marca") and tam_of[0] and not por_kg) else 0.5
    melhor, nota = None, 0.0
    for it in itens_do_mercado:
        p = _palavras(it["nome"])
        if not p:
            continue
        rot = _rotulo_tamanho(*_tamanho_site(it))
        if rot:
            p = p | {rot}
        n = len(alvo & p) / len(alvo | p)
        if n < minimo or n <= nota:
            continue
        if nucleo not in p:
            continue  # iogurte x coalhada
        if descricao and not (descricao & p):
            continue  # biscoito pão de mel x biscoito sequilhos
        if (alvo - p) & _FORMA or (p - alvo) & _VARIANTE:
            continue
        if _motivo_recusa(oferta, it, por_kg, tam_of):
            continue
        melhor, nota = it, n
    return melhor


def processar(encartes, brutos):
    """Lê as imagens novas e devolve a lista de ofertas de encarte (com o produto do catálogo, se achar)."""
    cache = ler_json(CACHE, {})
    if not _chave():
        log("Encartes: sem GEMINI_API_KEY no chaves.env — imagens ficam só para ver no app, sem leitura de preços")
        return []
    s = sessao()
    saida = []
    inicio, avisou, lidas = time.time(), False, 0
    USO_MODELOS.clear()
    # o que ler hoje: primeiro páginas nunca lidas, depois as lidas antes sem recorte de foto;
    # dentro de cada grupo, página 1 de todos os encartes, depois página 2... (nenhum mercado fica sem nada)
    fila = []
    for enc in encartes:
        recortar = enc.get("mercado") in RECORTAR
        for n, url in enumerate(enc.get("imagens", [])):
            antigo = cache.get(url)
            if antigo is None:
                fila.append((0, n, enc, url))
            elif recortar and antigo.get("v", 1) < VERSAO_LEITURA:
                fila.append((1, n, enc, url))
    fila.sort(key=lambda x: (x[0], x[1]))
    for _, n, enc, url in fila:
        if time.time() - inicio > LIMITE_MINUTOS * 60:
            if not avisou:
                log(f"Encartes: passou de {LIMITE_MINUTOS:.0f} min; o resto fica para a próxima coleta (vale a leitura anterior, se houver)")
                avisou = True
            break
        try:
            log(f"Encartes: lendo {enc['mercado']} · {enc.get('titulo', '')[:40]} · página {n + 1}")
            arquivos = enc.get("arquivos") or []
            arq = arquivos[n] if n < len(arquivos) else None
            cache[url] = {"lido": hoje(), "v": VERSAO_LEITURA, "itens": _ler_imagem(url, s, arq, enc.get("mercado") in RECORTAR)}
            salvar_json(CACHE, cache)
            lidas += 1
            time.sleep(4)  # o plano grátis do Gemini aceita poucos pedidos por minuto
        except Exception as e:
            log(f"Encartes: falhou {url}: {e}" + (" (fica a leitura anterior)" if url in cache else ""))
    if fila:
        uso = ", ".join(f"{m} {q}" for m, q in sorted(USO_MODELOS.items(), key=lambda x: -x[1]))
        log(f"Encartes: {lidas} de {len(fila)} página(s) lida(s) em {(time.time() - inicio) / 60:.0f} min" + (f" · {uso}" if uso else ""))
    for enc in encartes:
        for url in enc.get("imagens", []):
            if url not in cache:
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
                    "fim": enc.get("fim"), "periodo": enc.get("periodo"), "img": url, "foto": of.get("foto"),
                    "preco_clube": of.get("preco_clube"), "clube": of.get("clube"),
                    "id": casado["id"] if casado else None,
                })
    # limpa do cache imagens que já não estão em nenhum encarte atual
    atuais = {u for e in encartes for u in e.get("imagens", [])}
    cache = {u: v for u, v in cache.items() if u in atuais}
    salvar_json(CACHE, cache)
    # apaga fotos recortadas de encartes que já saíram
    usadas = {os.path.basename(of.get("foto") or "") for v in cache.values() for of in v["itens"] if isinstance(of, dict)}
    if FOTOS.exists():
        for f in FOTOS.glob("*.jpg"):
            if f.name not in usadas:
                f.unlink()
    return saida
