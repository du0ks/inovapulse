// Bülten paneli: docs/data/*.json dosyalarını okur, düzenlemeyi ve kopyalamayı sağlar.
// Düzenlemeler yalnızca bu tarayıcıda (localStorage) saklanır.

const $ = (s, el = document) => el.querySelector(s);
const app = $("#app");
let doc = null;       // ekranda gösterilen (düzenlenmiş) bülten
let storeKey = null;
let withSources = false;

// ---- yardımcılar ----------------------------------------------------------

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function safeUrl(u) {
  try {
    const url = new URL(u);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch { return null; }
}

function link(u, text) {
  const s = safeUrl(u);
  return s ? h("a", { href: s, target: "_blank", rel: "noopener noreferrer" }, text || s) : (text || "");
}

function host(u) {
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return ""; }
}

function save() {
  try { localStorage.setItem(storeKey, JSON.stringify(doc)); } catch {}
}

// Düzenlenebilir alan: obj[key] metnini günceller
function editable(tag, obj, key, attrs = {}) {
  const el = h(tag, { ...attrs, contenteditable: "plaintext-only", spellcheck: "true" }, obj?.[key] ?? "");
  el.addEventListener("input", () => { obj[key] = el.innerText.trim(); save(); });
  return el;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 1600);
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Panoya kopyalandı");
  } catch {
    const ta = h("textarea", {}, text);
    document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove();
    toast("Panoya kopyalandı");
  }
}

const fmtNum = (n, d = 0) => n == null || n === "" ? "—" :
  Number(n).toLocaleString("tr-TR", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtPct = (n) => n == null ? "" : `${n > 0 ? "+" : ""}${fmtNum(n, Math.abs(n) % 1 ? 1 : 0)}%`;

function card(id, title, copyFn, ...body) {
  return h("section", { class: "card", id },
    h("header", {}, h("h2", {}, title),
      copyFn && h("button", { class: "small", onclick: () => copy(copyFn()) }, "Kopyala")),
    ...body);
}

// ---- metin çıktıları ------------------------------------------------------

const T = {
  wci: () => {
    const w = doc.wci || {};
    return ["Drewry Dünya Konteyner Endeksi (WCI) (US$/40ft)", "",
      ...(w.paragraphs || []).flatMap((p) => [p, ""]), "Kaynak: www.drewry.co.uk"].join("\n");
  },
  trade: () => {
    const c = doc.trade_cards || [];
    const t = doc.trade_data || {};
    return [...c.map((k) => `${k.label}: ${k.value}`), "", t.summary || ""].join("\n").trim();
  },
  event: () => {
    const e = doc.event?.selected;
    if (!e) return "";
    return ["Haftanın Ücretsiz Etkinlik Duyurusu", e.title, e.description, "",
      `Eğitim Tarihi: ${e.date || "—"}${e.time ? `, Saat: ${e.time}` : ""}`, "",
      `Eğitim Yeri: ${[e.location, e.fee].filter(Boolean).join(", ")}`, "",
      `Kayıt için: ${e.register_url || ""}`].join("\n");
  },
  news: (key, heading) => {
    const items = (doc[key]?.items || []).filter((x) => x.include !== false);
    return [heading, ...items.map((x) => x.summary + (withSources ? `\n(Kaynak: ${x.source} – ${x.url})` : ""))]
      .join("\n\n");
  },
  nextWeek: () => {
    const nw = doc.next_week || {};
    return ["Gelecek Haftanın Bilgilendirmesi",
      ...(nw.days || []).map((d) => `${d.date_tr || d.date} ${d.weekday || ""}: ${d.text}`),
      nw.highlight?.text ? `\nÖne çıkan: ${nw.highlight.text}` : ""].join("\n").trim();
  },
  all: () => [
    `Haftalık Dış Ticaret Bülteni — ${doc.date_tr} — Sayı: ${doc.issue}`, "",
    T.wci(), "", T.trade(), "", T.event(), "",
    "Türkiye ve yurt dışında bu hafta hangi gelişmeler oldu? Birlikte bir göz atalım.", "",
    T.news("tr_news", "1- Türkiye'deki Gelişmeler;"), "",
    T.news("intl_news", "2- Yurt Dışındaki Gelişmeler;"), "", T.nextWeek(),
  ].join("\n"),
};

// ---- bölümler -------------------------------------------------------------

function wciSection(history) {
  const w = doc.wci;
  if (!w) return card("wci", "1. Drewry Dünya Konteyner Endeksi (WCI)", null,
    h("p", { class: "muted" }, "WCI verisi alınamadı."));
  const paras = w.paragraphs?.length ? w.paragraphs : null;
  return card("wci", "1. Drewry Dünya Konteyner Endeksi (WCI) – US$/40ft", T.wci,
    h("p", { class: "hint" },
      `Değerlendirme tarihi: ${w.assessment_date || "?"} · `, link(w.source_url, "Drewry kaynağı")),
    h("div", { class: "kpis" },
      h("div", { class: "kpi" }, h("div", { class: "label" }, "WCI kompozit"),
        h("div", { class: "value" }, `${fmtNum(w.composite_usd_40ft)} $`)),
      h("div", { class: "kpi" }, h("div", { class: "label" }, "Haftalık değişim"),
        h("div", { class: `value ${w.change_pct > 0 ? "up" : w.change_pct < 0 ? "down" : ""}` },
          fmtPct(w.change_pct) || "—"))),
    paras
      ? paras.map((_, i) => editable("p", w.paragraphs, i))
      : h("p", { class: "muted" }, w.text_en || ""),
    w.routes?.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Hat"), h("th", { class: "num" }, "US$/40ft"), h("th", { class: "num" }, "Değişim"))),
      h("tbody", {}, w.routes.map((r) => h("tr", {}, h("td", {}, r.route),
        h("td", { class: "num" }, fmtNum(r.usd_40ft)),
        h("td", { class: `num ${r.change_pct > 0 ? "up" : r.change_pct < 0 ? "down" : ""}` }, fmtPct(r.change_pct))))))) : null,
    h("h3", {}, "Grafikler (bülten için ekran görüntüsü alınabilir)"),
    h("div", { class: "two" },
      w.chart_embed_url && h("div", { class: "chart-frame" },
        h("iframe", { src: safeUrl(w.chart_embed_url), loading: "lazy", title: "Drewry WCI grafiği", allowfullscreen: true })),
      w.routes_embed_url && h("div", { class: "chart-frame" },
        h("iframe", { src: safeUrl(w.routes_embed_url), loading: "lazy", title: "WCI hat bazında grafik", allowfullscreen: true }))),
    history?.length > 1 ? historyChart(history) : null,
  );
}

function historyChart(hist) {
  const W = 640, H = 160, P = 28;
  const vals = hist.map((x) => x.composite);
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const pts = hist.map((x, i) => [P + (i * (W - 2 * P)) / (hist.length - 1), H - P - ((x.composite - min) / span) * (H - 2 * P)]);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "WCI kompozit geçmişi");
  svg.style.width = "100%";
  const path = document.createElementNS(ns, "polyline");
  path.setAttribute("points", pts.map((p) => p.join(",")).join(" "));
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "var(--accent)");
  path.setAttribute("stroke-width", "2.5");
  svg.append(path);
  for (const [i, [x, y]] of pts.entries()) {
    const c = document.createElementNS(ns, "circle");
    c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("r", 3.5); c.setAttribute("fill", "var(--accent)");
    const t = document.createElementNS(ns, "title");
    t.textContent = `${hist[i].date}: ${fmtNum(hist[i].composite)} $`;
    c.append(t); svg.append(c);
  }
  return h("div", {}, h("h3", {}, "WCI geçmişi (sistemin kaydettiği haftalar)"), svg);
}

function tradeSection() {
  const t = doc.trade_data || {};
  if (!doc.trade_cards) {
    doc.trade_cards = [
      { label: doc.annual_exports_card?.label || "Yıllık İhracat", value: doc.annual_exports_card?.value || "" },
      { label: `${t.month || "?"} Ayı Türkiye İhracatı`, value: t.exports_billion_usd != null ? `${fmtNum(t.exports_billion_usd, 3)} Milyar $` : "— (doldurun)" },
      { label: `${t.month || "?"} Ayı Türkiye İthalatı`, value: t.imports_billion_usd != null ? `${fmtNum(t.imports_billion_usd, 3)} Milyar $` : "— (doldurun)" },
    ];
  }
  return card("trade", "2. Türkiye İthalat ve İhracat Verileri", T.trade,
    h("p", { class: "hint" }, "Rakamları resmî kaynaktan teyit edin: ",
      link(t.official_url || "https://ticaret.gov.tr/istatistikler/dis-ticaret-istatistikleri", "Ticaret Bakanlığı dış ticaret istatistikleri"),
      t.confidence ? ` · Model güveni: ${t.confidence}` : ""),
    h("div", { class: "kpis" }, doc.trade_cards.map((k) => h("div", { class: "kpi" },
      editable("div", k, "label", { class: "label" }), editable("div", k, "value", { class: "value" })))),
    h("p", { class: "muted" },
      t.exports_yoy_pct != null ? `İhracat yıllık ${fmtPct(t.exports_yoy_pct)}` : "",
      t.imports_yoy_pct != null ? ` · İthalat yıllık ${fmtPct(t.imports_yoy_pct)}` : "",
      t.trade_deficit_billion_usd != null ? ` · Dış ticaret açığı ${fmtNum(t.trade_deficit_billion_usd, 2)} milyar $` : "",
      t.ytd_exports_billion_usd != null ? ` · Yılbaşından bu yana ihracat ${fmtNum(t.ytd_exports_billion_usd, 1)} milyar $` : ""),
    t.summary != null ? editable("p", t, "summary") : null,
    t.sources?.length ? h("div", { class: "news src" }, "Kaynaklar: ",
      t.sources.map((s, j) => [j ? " · " : "", link(s.url, s.source || host(s.url))])) : null);
}

function eventSection() {
  const ev = doc.event || {};
  const e = ev.selected;
  const field = (label, key) => h("div", {}, h("strong", {}, `${label}: `), editable("span", e, key));
  return card("event", "3. Haftanın Ücretsiz Etkinlik Duyurusu", T.event,
    h("p", { class: "hint" }, "Tarih, saat, ücretsiz katılım ve kayıt linkini etkinlik sayfasından mutlaka kontrol edin."),
    e ? h("div", {},
      editable("div", e, "title", { class: "title", style: "font-weight:600;font-size:16px" }),
      e.organizer ? h("div", { class: "muted" }, e.organizer) : null,
      editable("p", e, "description"),
      field("Eğitim Tarihi", "date"), field("Saat", "time"), field("Eğitim Yeri", "location"),
      field("Ücret", "fee"), field("Kayıt için", "register_url"),
      h("div", { class: "news src", style: "margin-top:6px" }, "Kaynak: ", link(e.source_url, e.source || host(e.source_url))))
      : h("p", { class: "muted" }, "Uygun ücretsiz etkinlik bulunamadı. Alternatiflere veya aday listesine bakın."),
    ev.alternatives?.length ? h("div", { class: "alts" }, h("h3", {}, "Alternatifler"),
      h("ul", { class: "news" }, ev.alternatives.map((a, i) => h("li", {},
        h("span", {}, ""),
        h("div", { class: "body" },
          h("div", { class: "title" }, a.title),
          h("div", { class: "src" }, [a.organizer, a.date, a.time, a.location].filter(Boolean).join(" · "), " ",
            link(a.source_url, "kaynak"),
            h("button", { class: "small", onclick: () => {
              const cur = ev.selected; ev.selected = a;
              ev.alternatives.splice(i, 1, ...(cur ? [cur] : [])); save(); render();
            } }, "Bunu seç"))))))) : null);
}

function newsSection(key, num, title, heading) {
  const sec = doc[key];
  if (!sec) return card(key, `${num}. ${title}`, null, h("p", { class: "muted" }, "Bu bölüm üretilemedi."));
  const sel = sec.items.filter((x) => x.include !== false).length;
  const item = (x, i, reserve) => h("li", { class: x.include === false && !reserve ? "off" : "" },
    reserve
      ? h("button", { class: "small", title: "Ana listeye ekle", onclick: () => {
          sec.reserve.splice(i, 1); x.include = true; sec.items.push(x); save(); render();
        } }, "+")
      : h("input", { type: "checkbox", checked: x.include !== false, title: "Bültene dahil et",
          onchange: (ev) => { x.include = ev.target.checked; save(); render(); } }),
    h("div", { class: "body" },
      editable("div", x, "title", { class: "title" }),
      editable("div", x, "summary", { class: "summary" }),
      h("div", { class: "src" },
        link(x.url, x.source || host(x.url)),
        x.published ? h("span", {}, x.published.slice(0, 10)) : null,
        x.category ? h("span", { class: "tag" }, x.category) : null,
        x.score != null ? h("span", {}, `önem ${x.score}/10`) : null,
        x.also_reported_by?.length ? h("span", {}, "ayrıca: ",
          x.also_reported_by.slice(0, 5).map((a, j) => [j ? ", " : "", link(a.url, host(a.url) || a.source)])) : null,
        !reserve && h("span", {},
          h("button", { class: "small", title: "Yukarı taşı", disabled: i === 0, onclick: () => move(sec.items, i, -1) }, "↑"), " ",
          h("button", { class: "small", title: "Aşağı taşı", disabled: i === sec.items.length - 1, onclick: () => move(sec.items, i, 1) }, "↓")))));
  return card(key, `${num}. ${title}`, () => T.news(key, heading),
    h("p", { class: "hint" }, `${sel} haber seçili. Metinlere tıklayıp düzenleyebilir, kutucukla çıkarabilir, yedeklerden ekleyebilirsiniz.`),
    h("ul", { class: "news" }, sec.items.map((x, i) => item(x, i, false))),
    sec.reserve?.length ? h("details", {}, h("summary", {}, `Yedek haberler (${sec.reserve.length})`),
      h("ul", { class: "news" }, sec.reserve.map((x, i) => item(x, i, true)))) : null);
}

function move(arr, i, d) {
  const [x] = arr.splice(i, 1);
  arr.splice(i + d, 0, x);
  save(); render();
}

function nextWeekSection() {
  const nw = doc.next_week;
  if (!nw) return card("next", "6. Gelecek Haftanın Bilgilendirmesi", null,
    h("p", { class: "muted" }, "Takvim üretilemedi. "), link("https://bigpara.hurriyet.com.tr/haberler/gunluk-piyasa-takvimi/gelecek-hafta/", "Bigpara takvimi"));
  return card("next", "6. Gelecek Haftanın Bilgilendirmesi", T.nextWeek,
    h("p", { class: "hint" }, "Kaynak: ", link("https://bigpara.hurriyet.com.tr/haberler/gunluk-piyasa-takvimi/gelecek-hafta/", "Hürriyet Bigpara – Gelecek Hafta Piyasa Takvimi")),
    h("div", { class: "days" }, (nw.days || []).map((d) => h("div", { class: "day" },
      h("div", { class: "d" }, `${d.date_tr || d.date} ${d.weekday || ""}`), editable("div", d, "text")))),
    nw.highlight ? h("p", {}, h("strong", {}, "Öne çıkan: "), editable("span", nw.highlight, "text")) : null);
}

function candidatesSection() {
  const c = doc.candidates || {};
  const groups = [["tr", "Türkiye"], ["intl", "Yurt dışı"], ["events", "Etkinlik"], ["trade", "Dış ticaret verisi"]];
  const list = (arr) => {
    const ol = h("ol", {}, arr.map((x) => h("li", { "data-q": `${x.title} ${x.source}`.toLocaleLowerCase("tr") },
      link(x.url, x.title), h("span", { class: "muted" }, ` — ${x.source}${x.published ? ", " + x.published.slice(0, 10) : ""}`))));
    const input = h("input", { type: "search", placeholder: "Ara…", oninput: (e) => {
      const q = e.target.value.toLocaleLowerCase("tr");
      for (const li of ol.children) li.hidden = q && !li.dataset.q.includes(q);
    } });
    return [input, ol];
  };
  return h("section", { class: "card cand no-print" },
    h("header", {}, h("h2", {}, "Tüm aday haberler"),
      h("span", { class: "chip" }, groups.map(([k]) => (c[k] || []).length).reduce((a, b) => a + b, 0) + " aday")),
    h("p", { class: "hint" }, "Sistemin taradığı tüm haberler. Seçimde gözden kaçan bir şey varsa buradan bulabilirsiniz."),
    groups.map(([k, label]) => h("details", {}, h("summary", {}, `${label} (${(c[k] || []).length})`), list(c[k] || []))));
}

// ---- yükleme ve çizim -----------------------------------------------------

let history = [];

function render() {
  const gen = doc.generated_at ? new Date(doc.generated_at).toLocaleString("tr-TR") : "";
  app.replaceChildren(...[
    h("div", { class: "meta" },
      h("h1", {}, `${doc.date_tr} · Sayı ${doc.issue}`),
      h("span", { class: "chip" }, `Oluşturuldu: ${gen}`),
      doc.llm ? h("span", { class: "chip" }, `Model: ${doc.llm}`) : null,
      h("label", { class: "chip", style: "cursor:pointer" },
        h("input", { type: "checkbox", checked: withSources, onchange: (e) => { withSources = e.target.checked; } }),
        " Kopyalarken haber kaynaklarını ekle")),
    doc.warnings?.length ? h("div", { class: "warn" }, h("strong", {}, "Uyarılar"),
      h("ul", {}, doc.warnings.map((w) => h("li", {}, w)))) : null,
    wciSection(history),
    tradeSection(),
    eventSection(),
    newsSection("tr_news", 4, "Türkiye'deki Gelişmeler", "1- Türkiye'deki Gelişmeler;"),
    newsSection("intl_news", 5, "Yurt Dışındaki Gelişmeler", "2- Yurt Dışındaki Gelişmeler;"),
    nextWeekSection(),
    candidatesSection(),
  ].filter(Boolean));
}

async function load(date) {
  const url = date ? `data/bulletins/${date}.json` : "data/latest.json";
  const fresh = await (await fetch(url, { cache: "no-store" })).json();
  storeKey = `bulten:${fresh.date}:${fresh.generated_at}`;
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(storeKey) || "null"); } catch {}
  doc = saved || fresh;
  for (const k of ["tr_news", "intl_news"]) if (doc[k]) doc[k].reserve ||= [];
  render();
  return fresh;
}

async function init() {
  const sel = $("#archive");
  try {
    const idx = await (await fetch("data/index.json", { cache: "no-store" })).json();
    sel.replaceChildren(...idx.map((x) => h("option", { value: x.date }, `${x.date} · Sayı ${x.issue}`)));
  } catch {}
  try { history = await (await fetch("data/wci_history.json", { cache: "no-store" })).json(); } catch {}

  sel.addEventListener("change", () => load(sel.value));
  $("#copyAll").addEventListener("click", () => copy(T.all()));
  $("#print").addEventListener("click", () => window.print());
  $("#reset").addEventListener("click", async () => {
    if (!confirm("Bu bülten için yaptığınız tüm düzenlemeler silinsin mi?")) return;
    try { localStorage.removeItem(storeKey); } catch {}
    await load(doc.date);
    toast("Orijinal taslak yüklendi");
  });

  // GitHub Pages adresinden Actions sayfasını türet (kullanici.github.io/repo)
  const rerun = $("#rerun");
  const m = location.hostname.match(/^([^.]+)\.github\.io$/);
  const repo = location.pathname.split("/").filter(Boolean)[0];
  if (m && repo) rerun.href = `https://github.com/${m[1]}/${repo}/actions/workflows/bulletin.yml`;
  else rerun.hidden = true;

  try {
    const b = await load();
    sel.value = b.date;
  } catch (e) {
    app.replaceChildren(h("p", { class: "warn" }, "Henüz bülten verisi yok. GitHub Actions iş akışını çalıştırın."));
  }
}

init();
