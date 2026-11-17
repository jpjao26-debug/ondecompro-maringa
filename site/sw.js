/* Service worker: abre rápido e funciona sem internet com os últimos preços baixados. */
const VERSAO = "ocm-v1";
const BASE = ["./", "index.html", "estilo.css", "app.js", "manifest.webmanifest", "icones/icone-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSAO).then((c) => c.addAll(BASE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k.startsWith("ocm-") && k !== VERSAO).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return; // fotos dos mercados: direto da internet
  if (url.pathname.includes("/dados/")) {
    // preços: tenta a internet primeiro; sem rede, usa a última cópia
    e.respondWith(
      fetch(e.request).then((r) => {
        const copia = r.clone();
        caches.open(VERSAO).then((c) => c.put(e.request.url.split("?")[0], copia));
        return r;
      }).catch(() => caches.match(e.request.url.split("?")[0]))
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then((r) => r || fetch(e.request).then((resp) => {
      const copia = resp.clone();
      caches.open(VERSAO).then((c) => c.put(e.request, copia));
      return resp;
    }))
  );
});
