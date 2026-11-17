/* OndeCompro em Maringá? — app de comparação de preços dos mercados de Maringá */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const R = (v) => (v == null ? "—" : brl.format(v));
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const norm = (t) => String(t || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

const estado = {
  aba: "inicio",
  busca: "",
  cat: { mercado: "todos", categoria: "", ordem: "preco", mostrar: 40 },
  buscaMostrar: 40,
};
let FEED = null, ITENS = [], MAPA = new Map(), MERCADOS = {};

/* ---------------------------------------------------------------- favoritos */
const FAV_CHAVE = "ocm_favoritos";  // separado do app de Ubatuba (mesmo endereço base)
const favs = new Set(lerFavs());
function lerFavs() { try { return JSON.parse(localStorage.getItem(FAV_CHAVE) || "[]"); } catch { return []; } }
function salvarFavs() { try { localStorage.setItem(FAV_CHAVE, JSON.stringify([...favs])); } catch {} }
function alternarFav(k) { favs.has(k) ? favs.delete(k) : favs.add(k); salvarFavs(); }

/* ---------------------------------------------------------------- dados */
async function carregar() {
  try {
    const f = await fetch("dados/feed.json", { cache: "no-cache" });
    FEED = await f.json();
    const i = await fetch("dados/itens.json?d=" + encodeURIComponent(FEED.atualizado));
    const dados = await i.json();
    ITENS = dados.itens;
  } catch (e) {
    $("#conteudo").innerHTML = `<p class="vazio">Não consegui carregar os preços. Confira a internet e abra de novo.</p>`;
    return;
  }
  MERCADOS = FEED.mercados || {};
  for (const it of ITENS) {
    it._busca = norm(it.n + " " + it.c);
    it._min = Math.min(...Object.values(it.o).map((o) => o.p));
    MAPA.set(it.k, it);
  }
  $("#atualizado").textContent = "Atualizado " + FEED.atualizado;
  desenhar();
}

const nomeMercado = (m) => (MERCADOS[m] && MERCADOS[m].nome) || m;
function ofertasOrdenadas(it) { return Object.entries(it.o).sort((a, b) => a[1].p - b[1].p); }
function precoUnit(it, preco) {
  if (!it.q || !it.b || it.b === "un" && it.q === 1) return "";
  const v = preco / it.q;
  const rot = it.b === "kg" ? "kg" : it.b === "l" ? "litro" : "un";
  return `${R(v)}/${rot}`;
}
function unitario(it) { return it.q ? it._min / it.q : Infinity; }

/* ---------------------------------------------------------------- componentes */
const SVG_CORACAO = `<svg viewBox="0 0 24 24"><path d="M12 20.5s-7-4.3-8.9-8.6C1.7 8.5 3.8 5 7.2 5c1.9 0 3.4 1 4.8 2.6C13.4 6 14.9 5 16.8 5c3.4 0 5.5 3.5 4.1 6.9-1.9 4.3-8.9 8.6-8.9 8.6z"/></svg>`;

function foto(it, cls = "foto") {
  return it.f ? `<img class="${cls}" src="${esc(it.f)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<div class="sem-foto"></div>`;
}

function card(it, opcoes = {}) {
  const ofs = ofertasOrdenadas(it);
  const multi = ofs.length > 1;
  let selo = "";
  if (multi && it.eco >= 0.01) selo = `<span class="selo">economize ${R(it.eco)}</span>`;
  else {
    const pr = ofs[0][1].pr;
    if (pr && pr.preco_de) selo = `<span class="selo vermelho">-${Math.round((pr.preco_de - ofs[0][1].p) / pr.preco_de * 100)}%</span>`;
  }
  const linhas = ofs.map(([m, o], idx) => `
    <div class="linha-preco ${multi && idx === 0 ? "melhor" : ""}">
      <span class="mk">${esc(nomeMercado(m))}</span>
      <span class="v">${o.pr && o.pr.preco_de ? `<span class="de">${R(o.pr.preco_de)}</span>` : ""}${R(o.p)}</span>
    </div>`).join("");
  const u = precoUnit(it, ofs[0][1].p);
  return `
  <div class="card" data-k="${esc(it.k)}" role="button" tabindex="0">
    ${selo}
    <button class="coracao ${favs.has(it.k) ? "on" : ""}" data-fav="${esc(it.k)}" aria-label="Favoritar">${SVG_CORACAO}</button>
    ${foto(it)}
    <div class="nome">${esc(it.n)}</div>
    <div class="precos">${linhas}</div>
    ${u ? `<div class="unit">${u} no mais barato</div>` : ""}
  </div>`;
}

function itemLista(it, m, direita, sub) {
  return `
  <button class="item-lista" data-k="${esc(it.k)}">
    ${it.f ? `<img src="${esc(it.f)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<div class="sem-foto"></div>`}
    <span class="meio"><div class="t">${esc(it.n)}</div><div class="s">${esc(sub || nomeMercado(m))}</div></span>
    <span class="dir">${direita}</span>
  </button>`;
}

/* ---------------------------------------------------------------- telas */
function telaInicio() {
  const partes = [];
  const hojeISO = new Date().toISOString().slice(0, 10);
  if (FEED.data && FEED.data < hojeISO && (new Date(hojeISO) - new Date(FEED.data)) > 36 * 3600e3) {
    partes.push(`<div class="aviso">Os preços são de ${esc(FEED.atualizado)}. A coleta de hoje ainda não rodou.</div>`);
  }
  const soEncarte = (m) => /só encarte/.test((MERCADOS[m] || {}).obs || "");
  const chips = Object.entries(FEED.totais || {}).map(([m, n]) => `<span class="chip-info">${esc(nomeMercado(m))}: ${n.toLocaleString("pt-BR")} ${soEncarte(m) ? "ofertas do encarte" : "produtos"}</span>`).join("");
  partes.push(`<div class="resumo">${chips}<span class="chip-info">${(FEED.comparaveis || 0).toLocaleString("pt-BR")} comparados</span></div>`);

  const favItens = [...favs].map((k) => MAPA.get(k)).filter(Boolean);
  if (favItens.length) {
    partes.push(`<section class="secao"><h2>Seus favoritos <small>${favItens.length}</small></h2><div class="trilho">${favItens.map((it) => card(it)).join("")}</div></section>`);
  }

  const baratos = (FEED.mais_baratos || []).map((k) => MAPA.get(k)).filter(Boolean).slice(0, 20);
  if (baratos.length) {
    partes.push(`<section class="secao"><h2>Onde está mais barato hoje <small>mesmo produto</small></h2><div class="trilho">${baratos.map((it) => card(it)).join("")}</div></section>`);
  }

  const baixaram = (FEED.baixaram || []).filter((b) => MAPA.has(b.k)).slice(0, 12);
  if (baixaram.length) {
    partes.push(`<section class="secao"><h2>Baixou de preço <small>desde a última coleta</small></h2><div class="lista">${
      baixaram.map((b) => itemLista(MAPA.get(b.k), b.m, `<div class="queda">-${b.pct}%</div><div class="s"><span class="de">${R(b.de)}</span>${R(b.por)}</div>`)).join("")
    }</div></section>`);
  }

  const promos = (FEED.promocoes || []).filter((p) => MAPA.has(p.k)).slice(0, 12);
  if (promos.length) {
    partes.push(`<section class="secao"><h2>Promoções nos sites <small>maior desconto</small></h2><div class="lista">${
      promos.map((p) => itemLista(MAPA.get(p.k), p.m, `<div class="queda">-${p.pct}%</div><div class="s"><span class="de">${R(p.de)}</span>${R(p.por)}</div>`)).join("")
    }</div></section>`);
  }

  const enc = (FEED.promos_encarte || []).slice(0, 15);
  if (enc.length) {
    partes.push(`<section class="secao"><h2>Ofertas dos encartes <small>lidas por IA</small></h2><div class="lista">${
      enc.map((e) => {
        const it = e.k ? MAPA.get(e.k) : null;
        const nome = [e.produto, e.marca, e.tamanho].filter(Boolean).join(" · ");
        return `<button class="item-lista" ${it ? `data-k="${esc(it.k)}"` : `data-encarte="${esc(e.img)}"`}>${it && it.f ? `<img src="${esc(it.f)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<span class="sem-foto"></span>`}<span class="meio"><div class="t">${esc(nome)}</div><div class="s">${esc(nomeMercado(e.m))}${e.condicao ? " · " + esc(e.condicao) : ""}</div></span><span class="dir"><div class="queda">${R(e.preco)}</div>${e.preco_normal ? `<div class="s"><span class="de">${R(e.preco_normal)}</span></div>` : ""}</span></button>`;
      }).join("")
    }</div></section>`);
  }
  if (!baratos.length && !baixaram.length && !promos.length) partes.push(`<p class="vazio">Ainda não há comparações. Elas aparecem depois da primeira coleta completa.</p>`);
  return partes.join("");
}

function filtrarCatalogo() {
  const { mercado, categoria, ordem } = estado.cat;
  let lista = ITENS.filter((it) => {
    if (categoria && it.c !== categoria) return false;
    if (mercado === "todos") return true;
    if (mercado === "comparados") return Object.keys(it.o).length > 1;
    return !!it.o[mercado];
  });
  const precoDe = (it) => (mercado !== "todos" && mercado !== "comparados" && it.o[mercado] ? it.o[mercado].p : it._min);
  const ord = {
    preco: (a, b) => precoDe(a) - precoDe(b),
    unit: (a, b) => unitario(a) - unitario(b),
    eco: (a, b) => b.eco - a.eco,
    nome: (a, b) => a.n.localeCompare(b.n, "pt-BR"),
  }[ordem];
  return lista.sort(ord);
}

function telaCatalogo() {
  const { mercado, categoria, ordem, mostrar } = estado.cat;
  const cats = [...new Set(ITENS.map((i) => i.c))].sort((a, b) => a.localeCompare(b, "pt-BR"));
  const chipsM = [["todos", "Todos"], ...Object.keys(FEED.totais || {}).map((m) => [m, nomeMercado(m)]), ["comparados", "Em 2+ mercados"]]
    .map(([v, t]) => `<button class="chip ${mercado === v ? "on" : ""}" data-mercado="${v}">${esc(t)}</button>`).join("");
  const lista = filtrarCatalogo();
  return `
    <div class="filtros">${chipsM}</div>
    <div class="seletores">
      <select id="sel-categoria" aria-label="Categoria"><option value="">Todas as categorias</option>${cats.map((c) => `<option ${c === categoria ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
      <select id="sel-ordem" aria-label="Ordenar">
        ${[["preco", "Menor preço"], ["unit", "Preço por kg/litro"], ["eco", "Maior economia"], ["nome", "A–Z"]].map(([v, t]) => `<option value="${v}" ${v === ordem ? "selected" : ""}>${t}</option>`).join("")}
      </select>
    </div>
    <p class="contagem">${lista.length.toLocaleString("pt-BR")} produtos</p>
    <div class="grade">${lista.slice(0, mostrar).map((it) => card(it)).join("")}</div>
    ${lista.length > mostrar ? `<button class="mais" data-mais="cat">Mostrar mais</button>` : ""}`;
}

function telaFavoritos() {
  const lista = [...favs].map((k) => MAPA.get(k)).filter(Boolean);
  const sumidos = favs.size - lista.length;
  if (!lista.length) return `<p class="vazio">Toque no coração de um produto para acompanhar o preço dele aqui.</p>`;
  return `<p class="contagem">${lista.length} favoritos${sumidos ? ` · ${sumidos} sem preço hoje` : ""}</p><div class="grade">${lista.map((it) => card(it)).join("")}</div>`;
}

function telaEncartes() {
  const encs = FEED.encartes || [];
  if (!encs.length) return `<p class="vazio">Nenhum encarte encontrado hoje.</p>`;
  return encs.map((e) => {
    const validade = e.inicio && e.fim ? `Válido de ${e.inicio.split("-").reverse().slice(0, 2).join("/")} a ${e.fim.split("-").reverse().slice(0, 2).join("/")}` : (e.periodo ? `Válido ${e.periodo}` : "");
    return `<div class="encarte"><h3>${esc(nomeMercado(e.mercado))} · ${esc(e.titulo)}</h3><p>${esc(validade)} · toque para ampliar</p>
      <div class="paginas">${e.imagens.map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener"><img src="${esc(u)}" alt="Página do encarte" loading="lazy" referrerpolicy="no-referrer"></a>`).join("")}</div></div>`;
  }).join("");
}

function telaBusca() {
  const termos = norm(estado.busca).split(/\s+/).filter(Boolean);
  const res = ITENS.filter((it) => termos.every((t) => it._busca.includes(t)))
    .sort((a, b) => (Object.keys(b.o).length - Object.keys(a.o).length) || (a._min - b._min));
  if (!res.length) return `<p class="vazio">Nada encontrado para “${esc(estado.busca)}”.</p>`;
  return `<p class="contagem">${res.length.toLocaleString("pt-BR")} resultados · comparados primeiro</p>
    <div class="grade">${res.slice(0, estado.buscaMostrar).map((it) => card(it)).join("")}</div>
    ${res.length > estado.buscaMostrar ? `<button class="mais" data-mais="busca">Mostrar mais</button>` : ""}`;
}

function detalhe(k) {
  const it = MAPA.get(k);
  if (!it) return;
  const ofs = ofertasOrdenadas(it);
  const linhas = ofs.map(([m, o], idx) => {
    const extras = [];
    if (o.pr) {
      const p = o.pr;
      extras.push(`${esc(p.tipo || "Promoção")}${p.preco_de ? ` (de ${R(p.preco_de)})` : ""}${p.ate ? ` · até ${esc(p.ate)}` : ""}${p.condicao ? ` · ${esc(p.condicao)}` : ""}`);
    }
    if (o.at && o.at.length) extras.push("Atacado: " + o.at.map((a) => `${a.qtd}+ un por ${R(a.preco)}`).join(", "));
    if (o.a) extras.push(`Antes: ${R(o.a)}`);
    if (o.m30 != null && o.p <= o.m30 && o.a) extras.push("Menor preço dos últimos 30 dias");
    if (o.d === false) extras.push("Sem estoque em Maringá no site");
    if ((MERCADOS[m] || {}).obs) extras.push(esc(MERCADOS[m].obs));
    const u = precoUnit(it, o.p);
    return `<div class="det-mercado ${ofs.length > 1 && idx === 0 ? "melhor" : ""}">
      <div class="l1"><span class="nm">${esc(nomeMercado(m))}${ofs.length > 1 && idx === 0 ? " · mais barato" : ""}</span><span class="pr">${R(o.p)}</span></div>
      ${u ? `<div class="extra">${u}</div>` : ""}
      ${extras.map((x) => `<div class="extra">${x}</div>`).join("")}
      ${o.n && o.n !== it.n ? `<div class="extra">No site: ${esc(o.n)}</div>` : ""}
      ${o.u ? `<div class="extra"><a href="${esc(o.u)}" target="_blank" rel="noopener">${/\.(jpe?g|png|webp)(\?|$)/i.test(o.u) ? "Ver a página do encarte" : "Ver no site do " + esc(nomeMercado(m))}</a></div>` : ""}
    </div>`;
  }).join("");
  $("#folha-conteudo").innerHTML = `
    <div class="det-topo">${it.f ? `<img src="${esc(it.f)}" alt="" referrerpolicy="no-referrer">` : `<div class="sem-foto"></div>`}
      <div><h3>${esc(it.n)}</h3><div class="unit">${esc(it.c)}</div></div></div>
    ${ofs.length === 1 ? `<p class="unit">Só encontrado no ${esc(nomeMercado(ofs[0][0]))} hoje.</p>` : ""}
    ${linhas}
    <button class="botao-fav ${favs.has(k) ? "on" : ""}" data-fav="${esc(k)}">${favs.has(k) ? "♥ Nos favoritos" : "♡ Adicionar aos favoritos"}</button>`;
  $("#folha").hidden = false;
}

/* ---------------------------------------------------------------- desenho e eventos */
function desenhar() {
  if (!FEED) return;
  const c = $("#conteudo");
  if (estado.busca.trim()) c.innerHTML = telaBusca();
  else c.innerHTML = { inicio: telaInicio, catalogo: telaCatalogo, favoritos: telaFavoritos, encartes: telaEncartes }[estado.aba]();
  document.querySelectorAll(".abas button").forEach((b) => b.classList.toggle("ativa", !estado.busca.trim() && b.dataset.aba === estado.aba));
}

document.addEventListener("click", (ev) => {
  const t = ev.target;
  const fav = t.closest("[data-fav]");
  if (fav) {
    ev.stopPropagation();
    const k = fav.dataset.fav;
    alternarFav(k);
    if (!$("#folha").hidden) detalhe(k);
    desenhar();
    return;
  }
  if (t.closest("[data-fechar]")) { $("#folha").hidden = true; return; }
  const aba = t.closest("[data-aba]");
  if (aba) {
    estado.aba = aba.dataset.aba;
    estado.busca = ""; $("#campo-busca").value = "";
    desenhar(); window.scrollTo(0, 0); return;
  }
  const merc = t.closest("[data-mercado]");
  if (merc) { estado.cat.mercado = merc.dataset.mercado; estado.cat.mostrar = 40; desenhar(); return; }
  const mais = t.closest("[data-mais]");
  if (mais) { if (mais.dataset.mais === "cat") estado.cat.mostrar += 40; else estado.buscaMostrar += 40; desenhar(); return; }
  const enc = t.closest("[data-encarte]");
  if (enc) { window.open(enc.dataset.encarte, "_blank", "noopener"); return; }
  const item = t.closest("[data-k]");
  if (item) detalhe(item.dataset.k);
});

document.addEventListener("change", (ev) => {
  if (ev.target.id === "sel-categoria") { estado.cat.categoria = ev.target.value; estado.cat.mostrar = 40; desenhar(); }
  if (ev.target.id === "sel-ordem") { estado.cat.ordem = ev.target.value; desenhar(); }
});

let espera;
$("#campo-busca").addEventListener("input", (ev) => {
  clearTimeout(espera);
  espera = setTimeout(() => { estado.busca = ev.target.value; estado.buscaMostrar = 40; desenhar(); window.scrollTo(0, 0); }, 180);
});
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") $("#folha").hidden = true; });

// foto que não carrega vira um quadradinho cinza (em vez do ícone de imagem quebrada)
document.addEventListener("error", (ev) => {
  const img = ev.target;
  if (img && img.tagName === "IMG" && !img.dataset.falhou) {
    img.dataset.falhou = "1";
    const d = document.createElement("div");
    d.className = img.className === "foto" ? "sem-foto" : "sem-foto";
    if (img.closest(".item-lista")) { d.style.width = "48px"; d.style.height = "48px"; d.style.flex = "none"; }
    img.replaceWith(d);
  }
}, true);

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
carregar();
