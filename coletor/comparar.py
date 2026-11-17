"""Junta os catálogos, casa o mesmo produto entre mercados, guarda o histórico
e gera os arquivos que o app lê (site/dados/)."""
import re
from collections import defaultdict
from datetime import datetime, timedelta

from .comum import DADOS, SITE_DADOS, agora_br, hoje, ler_json, log, salvar_json, sem_acento

MERCADOS = {
    "muffato": {"nome": "Muffato", "cor": "#e2001a", "obs": "preço da loja online João Paulino"},
    "atacadao": {"nome": "Atacadão", "cor": "#f47920", "obs": "loja Fernão Dias"},
    "amigao": {"nome": "Amigão", "cor": "#0057a8", "obs": "loja online de Maringá"},
    "condor": {"nome": "Condor", "cor": "#00843d", "obs": "loja Av. Paraná"},
    "assai": {"nome": "Assaí", "cor": "#ff6b00", "obs": "só encarte · Av. Colombo"},
    "lejon": {"nome": "Lejon", "cor": "#1d3f8f", "obs": "só encarte · Fernão Dias"},
    "max": {"nome": "Max", "cor": "#c8102e", "obs": "só encarte · Av. Colombo"},
}

# ---------------------------------------------------------------- tamanho / unidade

_UNID = r"(kg|g|gr|mg|l|lt|litro|litros|ml|un|unid|unidades)"
_RE_TAM = re.compile(r"(\d+(?:[.,]\d+)?)\s*" + _UNID + r"\b", re.I)
_RE_MULTI = re.compile(r"(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*" + _UNID + r"\b", re.I)


def tamanho(nome):
    """Devolve (quantidade_em_unidade_base, base) — base 'kg', 'l' ou 'un'."""
    n = sem_acento(nome or "").lower()
    m = _RE_MULTI.search(n)
    if m:
        mult, qtd, un = float(m.group(1)), float(m.group(2).replace(",", ".")), m.group(3).lower()
    else:
        achados = [(float(q.replace(",", ".")), u.lower()) for q, u in _RE_TAM.findall(n)]
        pesos = [a for a in achados if a[1] not in ("un", "unid", "unidades", "mg")]
        escolhido = pesos[0] if pesos else (achados[0] if achados else None)
        if not escolhido:
            return None, None
        mult, (qtd, un) = 1.0, escolhido
    if un == "kg":
        return qtd * mult, "kg"
    if un in ("g", "gr"):
        return qtd * mult / 1000, "kg"
    if un == "mg":
        return None, None
    if un in ("l", "lt", "litro", "litros"):
        return qtd * mult, "l"
    if un == "ml":
        return qtd * mult / 1000, "l"
    return qtd * mult, "un"


# ---------------------------------------------------------------- chave de comparação

_RUIDO = {"de", "da", "do", "com", "sem", "e", "em", "para", "tipo", "pacote", "caixa", "garrafa",
          "lata", "frasco", "sache", "pouch", "pote", "bandeja", "unidade", "unidades", "un", "c", "pct",
          "pet", "long", "neck", "embalagem", "economica"}


def chave_nome(nome):
    """Chave de texto para casar produtos sem código de barras: palavras + tamanho."""
    q, base = tamanho(nome)
    n = sem_acento(nome or "").lower()
    n = _RE_MULTI.sub(" ", n)
    n = _RE_TAM.sub(" ", n)
    palavras = sorted(set(w for w in re.findall(r"[a-z0-9]+", n) if w not in _RUIDO and len(w) > 1))
    if not palavras or q is None:
        return None
    return " ".join(palavras) + f"|{round(q, 3)}{base}"


def _assinatura(nome):
    """(chave do tamanho, conjunto de palavras importantes)"""
    q, base = tamanho(nome)
    if q is None:
        return None, set()
    n = sem_acento(nome or "").lower()
    n = _RE_MULTI.sub(" ", n)
    n = _RE_TAM.sub(" ", n)
    pal = set(w for w in re.findall(r"[a-z0-9]+", n) if w not in _RUIDO and len(w) > 1 and not w.isdigit())
    return f"{round(q, 3)}{base}", pal


def _semelhanca(a, b):
    """Nota de 0 a 1; 0 quando não é o mesmo produto com segurança razoável."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    jac = inter / len(a | b)
    menor = min(len(a), len(b))
    contido = inter == menor and menor >= 2
    if jac >= 0.8 or (contido and jac >= 0.5):
        return jac
    return 0.0


# ---------------------------------------------------------------- histórico

def _atualizar_historico(itens_por_id, data):
    """Guarda só mudanças de preço: {id: [[data, preço], ...]} (últimos 120 dias)."""
    caminho = DADOS / "historico_precos.json"
    hist = ler_json(caminho, {})
    limite = (datetime.strptime(data, "%Y-%m-%d") - timedelta(days=120)).strftime("%Y-%m-%d")
    for pid, item in itens_por_id.items():
        serie = hist.get(pid, [])
        if not serie or serie[-1][1] != item["preco"]:
            if serie and serie[-1][0] == data:
                serie[-1][1] = item["preco"]
            else:
                serie.append([data, item["preco"]])
        # mantém um ponto anterior ao limite para saber o preço "de antes"
        while len(serie) > 2 and serie[1][0] < limite:
            serie.pop(0)
        hist[pid] = serie
    salvar_json(caminho, hist)
    return hist


def _preco_anterior(serie, data):
    """Último preço registrado antes de hoje."""
    anteriores = [p for d, p in serie if d < data]
    return anteriores[-1] if anteriores else None


def _minimo_30d(serie, data):
    corte = (datetime.strptime(data, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")
    precos = [p for d, p in serie if d >= corte]
    antes = [p for d, p in serie if d < corte]
    if antes:
        precos.append(antes[-1])
    return min(precos) if precos else None


# ---------------------------------------------------------------- montagem

def montar(brutos, encartes, promos_encarte=None):
    data = hoje()
    promos_encarte = promos_encarte or []
    # só entra o que está disponível na loja de Maringá (sem estoque costuma ter preço antigo parado no site)
    todos = [p for lista in brutos.values() for p in lista if p.get("disponivel", True)]
    por_id = {p["id"]: p for p in todos}
    hist = _atualizar_historico(por_id, data)

    # 1) agrupa por código de barras
    grupos, sem_ean = defaultdict(list), []
    for p in todos:
        if (p.get("unidade") or "") == "kg":
            grupos["id:" + p["id"]].append(p)  # vendido por quilo: cada mercado mede de um jeito, não compara
        elif p.get("ean"):
            grupos["ean:" + p["ean"]].append(p)
        else:
            sem_ean.append(p)
    # índice por tamanho para achar candidatos parecidos
    por_tamanho = defaultdict(list)   # chave de tamanho -> [(k_grupo, palavras, mercados)]
    for k, ps in grupos.items():
        tk, pal = _assinatura(ps[0]["nome"])
        if tk:
            por_tamanho[tk].append([k, pal, {p["mercado"] for p in ps}])
    # 2) quem não tem código de barras entra no grupo mais parecido (mesmo tamanho, outro mercado)
    sem_ean.sort(key=lambda p: p["mercado"])
    for p in sem_ean:
        tk, pal = _assinatura(p["nome"])
        if not tk or not pal:
            grupos["id:" + p["id"]].append(p)
            continue
        melhor, nota = None, 0.0
        for cand in por_tamanho[tk]:
            if p["mercado"] in cand[2]:
                continue
            n = _semelhanca(pal, cand[1])
            if n > nota:
                melhor, nota = cand, n
        if melhor and nota > 0:
            grupos[melhor[0]].append(p)
            melhor[2].add(p["mercado"])
        else:
            k = "nome:" + " ".join(sorted(pal)) + "|" + tk
            if k in grupos:
                k = "id:" + p["id"]
            grupos[k].append(p)
            por_tamanho[tk].append([k, pal, {p["mercado"]}])

    id_para_k = {p["id"]: k for k, ps in grupos.items() for p in ps}
    for e in promos_encarte:
        e["k"] = id_para_k.get(e.get("id"))

    itens, comparaveis = [], []
    for k, ps in grupos.items():
        # um preço por mercado (se houver duplicado no mesmo mercado, fica o menor)
        por_mercado = {}
        for p in ps:
            atual = por_mercado.get(p["mercado"])
            # entre dois do mesmo mercado: prefere o pacote fechado ao vendido por quilo; depois o mais barato
            chave_p = ((p.get("unidade") or "") == "kg", p["preco"])
            if not atual or chave_p < ((atual.get("unidade") or "") == "kg", atual["preco"]):
                por_mercado[p["mercado"]] = p
        ref = max(ps, key=lambda p: (bool(p.get("foto")), len(p["nome"])))
        q, base = tamanho(ref["nome"])
        if (ref.get("unidade") or "").lower() == "kg":
            q, base = 1.0, "kg"  # vendido por quilo: o preço já é por kg
        ofertas = {}
        for m, p in por_mercado.items():
            serie = hist.get(p["id"], [])
            ant = _preco_anterior(serie, data)
            ofertas[m] = {
                "p": p["preco"],
                "a": ant if ant and ant != p["preco"] else None,       # preço anterior
                "m30": _minimo_30d(serie, data),
                "pr": p.get("promo"),
                "at": p.get("atacado") or None,
                "u": p.get("url"),
                "d": p.get("disponivel", True),
                "n": p["nome"],
            }
        precos = sorted((o["p"], m) for m, o in ofertas.items())
        melhor = precos[0][1]
        economia = round(precos[-1][0] - precos[0][0], 2) if len(precos) > 1 else 0
        item = {
            "k": k,
            "n": ref["nome"],
            "f": ref.get("foto"),
            "c": ref.get("categoria") or "Outros",
            "q": round(q, 4) if q else None,
            "b": base,
            "o": ofertas,
            "best": melhor,
            "eco": economia,
        }
        itens.append(item)
        if len(ofertas) > 1:
            comparaveis.append(item)

    # ------------------------------------------------ feed
    def pct(a, b):
        return round((a - b) / a * 100) if a else 0

    def confiavel(i):
        ps = [o["p"] for o in i["o"].values()]
        return max(ps) / min(ps) <= 2.2  # diferença absurda costuma ser produto casado errado

    mais_baratos = sorted(
        (i for i in comparaveis if i["eco"] >= 0.5 and confiavel(i)),
        key=lambda i: -pct(max(o["p"] for o in i["o"].values()), min(o["p"] for o in i["o"].values())),
    )
    baixaram = []
    for i in itens:
        for m, o in i["o"].items():
            if o["a"] and o["p"] < o["a"]:
                baixaram.append({"k": i["k"], "m": m, "de": o["a"], "por": o["p"], "pct": pct(o["a"], o["p"])})
    baixaram.sort(key=lambda x: -x["pct"])
    menor30 = []
    for i in itens:
        for m, o in i["o"].items():
            if o["a"] and o["m30"] is not None and o["p"] <= o["m30"] and o["p"] < o["a"]:
                menor30.append({"k": i["k"], "m": m})
    promocoes = []
    for i in itens:
        for m, o in i["o"].items():
            pr = o.get("pr")
            if pr and pr.get("preco_de"):
                promocoes.append({"k": i["k"], "m": m, "de": pr["preco_de"], "por": o["p"], "pct": pct(pr["preco_de"], o["p"])})
    promocoes.sort(key=lambda x: -x["pct"])

    feed = {
        "atualizado": agora_br().strftime("%d/%m/%Y %H:%M"),
        "data": data,
        "mercados": {m: v for m, v in MERCADOS.items() if m in brutos},
        "totais": {m: sum(1 for p in v if p.get("disponivel", True)) for m, v in brutos.items()},
        "comparaveis": len(comparaveis),
        "mais_baratos": [i["k"] for i in mais_baratos[:60]],
        "baixaram": baixaram[:80],
        "menor30": menor30[:80],
        "promocoes": promocoes[:120],
        "encartes": encartes,
        "promos_encarte": promos_encarte,
    }
    return itens, feed


def gerar(brutos, encartes, promos_encarte=None):
    itens, feed = montar(brutos, encartes, promos_encarte)
    itens.sort(key=lambda i: (-len(i["o"]), i["c"], i["n"]))
    salvar_json(SITE_DADOS / "itens.json", {"data": feed["data"], "itens": itens})
    salvar_json(SITE_DADOS / "feed.json", feed)
    log(f"App: {len(itens)} itens, {feed['comparaveis']} comparáveis entre mercados")
    return itens, feed
