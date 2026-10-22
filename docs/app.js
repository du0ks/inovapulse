// Bülten paneli: docs/data/*.json dosyalarını okur; düzenleme, kopyalama ve yazdırmayı sağlar.
// Düzenlemeler yalnızca bu tarayıcıda (localStorage) saklanır.

const $ = (s, el = document) => el.querySelector(s);
const app = $("#app");
let doc = null;        // ekranda gösterilen (düzenlenmiş) bülten
let storeKey = null;
let history = [];
let isLatest = true;

// ---- ikonlar (Lucide çizgi ikonlarından) ---------------------------------

const ICONS = {
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  printer: '<path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
  more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  up: '<path d="m18 15-6-6-6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  ext: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
};

function icon(name) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("fill", "none");
  s.setAttribute("stroke", "currentColor");
  s.setAttribute("stroke-width", "2");
  s.setAttribute("stroke-linecap", "round");
  s.setAttribute("stroke-linejoin", "round");
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = ICONS[name];
  return s;
}

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
  return s ? h("a", { href: s, target: "_blank", rel: "noopener noreferrer" }, text || host(s)) : (text || "");
}

function host(u) {
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return ""; }
}

function sourceName(x) {
  const s = x.source || "";
  return s && s !== "Google News" ? s : host(x.url);
}

let saveTimer;
function save() {
  try { localStorage.setItem(storeKey, JSON.stringify(doc)); } catch {}
  const el = $(".saved");
  if (el) {
    el.textContent = "Kaydedildi";
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => { el.textContent = "Değişiklikleriniz bu tarayıcıda otomatik kaydedilir."; }, 1500);
  }
}

// Düzenlenebilir metin: obj[key] değerini günceller
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
  toast._t = setTimeout(() => t.classList.remove("show"), 2200);
}

async function copy(text, what = "Metin") {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = h("textarea", {}, text);
    document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  toast(`${what} panoya kopyalandı. Canva'ya yapıştırabilirsiniz.`);
}

const num = (n, d = 0) => n == null || n === "" ? "" :
  Number(n).toLocaleString("tr-TR", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (n) => n == null ? "" : `${n > 0 ? "+" : n < 0 ? "−" : ""}%${num(Math.abs(n), Math.abs(n) % 1 ? 1 : 0)}`;
const dir = (n) => n > 0 ? "up" : n < 0 ? "down" : "";

const DAYS = ["Pazar", "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi"];
const MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"];
function longDate(iso) {
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${DAYS[d.getDay()]}, ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function section(no, title, copyFn, ...body) {
  return h("section", { class: "sec" },
    h("div", { class: "sec-head" },
      h("span", { class: "no" }, String(no).padStart(2, "0")),
      h("h2", {}, title),
      copyFn && h("button", { class: "btn ghost small", type: "button", title: "Bu bölümü kopyala",
        onclick: () => copy(copyFn(), "Bölüm") }, icon("copy"), "Kopyala")),
    ...body);
}

// ---- kopyalanacak metinler ------------------------------------------------

const T = {
  wci: () => {
    const w = doc.wci || {};
    return ["Drewry Dünya Konteyner Endeksi (WCI) (US$/40ft)", "",
      ...(w.paragraphs || []).flatMap((p) => [p, ""]), "Kaynak: www.drewry.co.uk"].join("\n");
  },
  trade: () => {
    const t = doc.trade_data || {};
    return [...tradeCards().map((k) => `${k.label}: ${k.value}`), "", t.summary || ""].join("\n").trim();
  },
  event: () => {
    const e = doc.event?.selected;
    if (!e) return "";
    return ["Haftanın Ücretsiz Etkinlik Duyurusu", e.title, e.description, "",
      `Eğitim Tarihi: ${e.date || ""}${e.time ? `, Saat: ${e.time}` : ""}`, "",
      `Eğitim Yeri: ${[e.location, e.fee].filter(Boolean).join(", ")}`, "",
      `Kayıt için: ${e.register_url || ""}`].join("\n");
  },
  news: (key, heading) => [heading, ...(doc[key]?.items || []).map((x) => x.summary)].join("\n\n"),
  week: () => {
    const nw = doc.next_week || {};
    return ["Gelecek Haftanın Bilgilendirmesi",
      ...(nw.days || []).map((d) => `${d.date_tr || d.date} ${d.weekday || ""}: ${d.text}`)].join("\n");
  },
  all: () => [
    `Haftalık Dış Ticaret Bülteni · ${doc.date_tr} · Sayı: ${doc.issue}`, "",
    T.wci(), "", T.trade(), "", T.event(), "",
    "Türkiye ve yurt dışında bu hafta hangi gelişmeler oldu? Birlikte bir göz atalım.", "",
    T.news("tr_news", "1- Türkiye'deki Gelişmeler;"), "",
    T.news("intl_news", "2- Yurt Dışındaki Gelişmeler;"), "", T.week(),
  ].join("\n"),
};

// ---- kontrol listesi -------------------------------------------------------

function checklist() {
  const t = doc.trade_data || {};
  const e = doc.event?.selected;
  const items = [];
  const month = t.month || "Son ay";
  const official = t.official_url || "https://ticaret.gov.tr/istatistikler/dis-ticaret-istatistikleri";
  if (t.exports_billion_usd == null || t.imports_billion_usd == null) {
    const miss = [t.exports_billion_usd == null && "ihracat", t.imports_billion_usd == null && "ithalat"].filter(Boolean).join(" ve ");
    items.push({ id: "trade", text: `${month} ${miss} rakamı bulunamadı. Resmî kaynaktan bakıp kutuya yazın.`, url: official, cta: "Ticaret Bakanlığı" });
  }
  if (!e) items.push({ id: "event", text: "Bu hafta otomatik olarak uygun bir ücretsiz etkinlik seçilemedi. Önerilerden birini seçin veya elle yazın." });
  else if (!e.date || !e.time) items.push({ id: "eventdate", text: "Etkinliğin tarih ve saatini kayıt sayfasından teyit edin.", url: e.register_url || e.source_url, cta: "Etkinlik sayfası" });
  for (const w of doc.warnings || []) {
    if (/korundu/.test(w)) items.push({ id: `w:${w}`, text: w.replace("bu çalıştırmada üretilemedi; önceki sürüm korundu.", "bu sabah güncellenemedi; bir önceki taslağın metni gösteriliyor.") });
  }
  items.push({ id: "figures", text: "Rakamları bir kez gözden geçirin (WCI ve dış ticaret verileri).", url: doc.wci?.source_url, cta: "Drewry" });
  return items;
}

function noticeBox() {
  doc.checks ||= {};
  const items = checklist();
  const left = items.filter((x) => !doc.checks[x.id]).length;
  if (!left) return h("div", { class: "notice ok" }, icon("check"), "Kontroller tamam. Bülten yayına hazır.");
  return h("div", { class: "notice" },
    h("h2", {}, `Yayından önce kontrol edin (${left})`),
    h("ul", {}, items.map((x) => h("li", { class: doc.checks[x.id] ? "done" : "" },
      h("input", { type: "checkbox", checked: !!doc.checks[x.id], "aria-label": "Tamamlandı",
        onchange: (ev) => { doc.checks[x.id] = ev.target.checked; save(); render(); } }),
      h("span", {}, x.text, x.url ? [" ", link(x.url, `${x.cta} ↗`)] : null)))));
}

// ---- bölümler -------------------------------------------------------------

function wciSection() {
  const w = doc.wci;
  if (!w) return section(1, "Drewry Dünya Konteyner Endeksi", null, h("p", { class: "empty" }, "Bu hafta WCI verisi alınamadı."));
  const view = w.chart_embed_url ? w.chart_embed_url.replace(/\?embed$/, "") : w.source_url;
  return section(1, "Drewry Dünya Konteyner Endeksi", T.wci,
    w.composite_usd_40ft ? h("div", { class: "figure-line" },
      h("span", { class: "big" }, `${num(w.composite_usd_40ft)} $`),
      h("span", { class: "meta" }, "40 ft konteyner başına"),
      w.change_pct != null ? h("span", { class: `chg ${dir(w.change_pct)}` }, `${pct(w.change_pct)} haftalık`) : null) : null,
    (w.paragraphs?.length ? w.paragraphs : []).map((_, i) => editable("p", w.paragraphs, i)),
    w.routes?.length ? h("table", { class: "routes" }, h("tbody", {}, w.routes.map((r) =>
      h("tr", {}, h("td", {}, r.route), h("td", {}, `${num(r.usd_40ft)} $`),
        h("td", { class: dir(r.change_pct) }, pct(r.change_pct)))))) : null,
    history.length > 2 ? spark(history) : null,
    h("div", { class: "meta" },
      `${w.assessment_date ? new Date(w.assessment_date).toLocaleDateString("tr-TR", { day: "numeric", month: "long" }) + " değerlendirmesi · " : ""}`,
      link(view, "Drewry grafiğini aç ↗")));
}

function spark(hist) {
  const W = 600, H = 56, vals = hist.map((x) => x.composite);
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const pts = hist.map((x, i) => `${(i * W) / (hist.length - 1)},${H - 4 - ((x.composite - min) / span) * (H - 8)}`).join(" ");
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", `0 0 ${W} ${H}`);
  s.setAttribute("preserveAspectRatio", "none");
  s.setAttribute("class", "spark");
  s.setAttribute("role", "img");
  s.setAttribute("aria-label", "WCI'nin son haftalardaki seyri");
  s.innerHTML = `<polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="2" vector-effect="non-scaling-stroke"/>`;
  return s;
}

function tradeCards() {
  const t = doc.trade_data || {};
  if (!doc.trade_cards) {
    const fmt = (v) => v != null ? `${Number(v).toLocaleString("tr-TR", { maximumFractionDigits: 3 })} Milyar $` : "";
    doc.trade_cards = [
      { label: doc.annual_exports_card?.label || "Yıllık İhracat", value: doc.annual_exports_card?.value || "" },
      { label: `${t.month || ""} Ayı Türkiye İhracatı`.trim(), value: fmt(t.exports_billion_usd) },
      { label: `${t.month || ""} Ayı Türkiye İthalatı`.trim(), value: fmt(t.imports_billion_usd) },
    ];
  }
  return doc.trade_cards;
}

function tradeSection() {
  const t = doc.trade_data || {};
  const cards = tradeCards();
  // Sosyal medya bağlantılarını ve aynı kaynağın tekrarlarını gösterme
  const seen = new Set();
  const srcs = (t.sources || []).filter((s) => {
    const k = s.source || host(s.url);
    if (/instagram|facebook|twitter|x\.com|linkedin|youtube/i.test(host(s.url)) || seen.has(k)) return false;
    seen.add(k); return true;
  }).slice(0, 3);
  return section(2, "Türkiye İthalat ve İhracat Verileri", T.trade,
    h("div", { class: "figures" }, cards.map((k) => h("div", {},
      editable("div", k, "label", { class: "lbl" }),
      editable("div", k, "value", { class: `val ${k.value ? "" : "missing"}`, "data-ph": "Rakamı yazın" })))),
    t.summary != null ? editable("p", t, "summary") : null,
    h("div", { class: "meta" }, "Kaynak: ",
      link(t.official_url || "https://ticaret.gov.tr/istatistikler/dis-ticaret-istatistikleri", "Ticaret Bakanlığı ↗"),
      srcs.map((s) => [" · ", link(s.url, s.source || host(s.url))])));
}

function eventSection() {
  doc.event ||= { selected: null, alternatives: [] };
  const ev = doc.event;
  const e = ev.selected;
  const fact = (label, key, ph) => [h("dt", {}, label), h("dd", {}, editable("span", e, key, { "data-ph": ph }))];
  const pickFrom = (list, isCand) => list.length ? h("details", { class: "more", open: !e },
    h("summary", {}, icon("chevron"), e ? `Başka bir etkinlik seç (${list.length})` : `Önerilen etkinlikler (${list.length})`),
    h("ul", {}, list.map((a, i) => h("li", {},
      h("div", {}, h("div", {}, a.title), h("div", { class: "src" },
        [a.organizer, a.date, a.location].filter(Boolean).join(" · "), (a.organizer || a.date || a.location) ? " · " : "",
        link(a.source_url || a.url, isCand ? sourceName(a) : "Sayfayı aç ↗"))),
      h("button", { class: "btn small", type: "button", onclick: () => {
        const chosen = isCand
          ? { title: a.title, description: a.snippet || "", date: "", time: "", location: "", fee: "Ücretsiz", register_url: a.url, source_url: a.url }
          : a;
        if (!isCand) ev.alternatives.splice(i, 1, ...(e ? [e] : []));
        ev.selected = chosen; save(); render();
      } }, "Seç"))))) : null;

  const alts = ev.alternatives || [];
  const cands = alts.length ? [] : (doc.candidates?.events || []).slice(0, 6);
  return section(3, "Haftanın Ücretsiz Etkinlik Duyurusu", e ? T.event : null,
    e ? h("div", {},
      editable("div", e, "title", { class: "event-title", "data-ph": "Etkinlik adı" }),
      editable("p", e, "description", { "data-ph": "Kısa açıklama" }),
      h("dl", { class: "facts" },
        fact("Tarih", "date", "GG.AA.YYYY"), fact("Saat", "time", "SS:SS-SS:SS"),
        fact("Yer", "location", "Online / şehir"), fact("Ücret", "fee", "Ücretsiz"),
        fact("Kayıt", "register_url", "Kayıt bağlantısı")))
      : h("div", { class: "empty" }, "Bu hafta otomatik seçim yapılamadı. Aşağıdan bir etkinlik seçin ya da ",
        h("button", { class: "btn small", type: "button", onclick: () => {
          ev.selected = { title: "", description: "", date: "", time: "", location: "", fee: "Ücretsiz", register_url: "" };
          save(); render();
        } }, icon("plus"), "Elle yazın"), "."),
    pickFrom(alts.length ? alts : cands, !alts.length));
}

function newsSection(no, key, title, heading) {
  const sec = doc[key];
  if (!sec) return section(no, title, null, h("p", { class: "empty" }, "Bu bölüm bu hafta hazırlanamadı."));
  sec.reserve ||= [];
  const move = (i, d) => { const [x] = sec.items.splice(i, 1); sec.items.splice(i + d, 0, x); save(); render(); };
  const remove = (i) => { const [x] = sec.items.splice(i, 1); sec.reserve.unshift(x); save(); render(); toast("Haber çıkarıldı. Önerilen haberler listesinden geri ekleyebilirsiniz."); };
  const add = (i) => { const [x] = sec.reserve.splice(i, 1); sec.items.push(x); save(); render(); };

  return section(no, title, () => T.news(key, heading),
    h("ol", { class: "news" }, sec.items.map((x, i) => h("li", {},
      editable("div", x, "title", { class: "t" }),
      editable("div", x, "summary", { class: "s" }),
      h("div", { class: "src" }, link(x.url, sourceName(x))),
      h("div", { class: "tools" },
        h("button", { class: "tool", type: "button", title: "Yukarı taşı", disabled: i === 0, onclick: () => move(i, -1) }, icon("up")),
        h("button", { class: "tool", type: "button", title: "Aşağı taşı", disabled: i === sec.items.length - 1, onclick: () => move(i, 1) }, icon("down")),
        h("button", { class: "tool rm", type: "button", title: "Bültenden çıkar", onclick: () => remove(i) }, icon("x")))))),
    sec.reserve.length ? h("details", { class: "more" },
      h("summary", {}, icon("chevron"), `Önerilen diğer haberler (${sec.reserve.length})`),
      h("ul", {}, sec.reserve.map((x, i) => h("li", {},
        h("div", {}, h("div", {}, x.title), h("div", { class: "src" }, link(x.url, sourceName(x)))),
        h("button", { class: "btn small", type: "button", onclick: () => add(i) }, icon("plus"), "Ekle"))))) : null);
}

function weekSection() {
  const nw = doc.next_week;
  const bigpara = "https://bigpara.hurriyet.com.tr/haberler/gunluk-piyasa-takvimi/gelecek-hafta/";
  if (!nw) return section(6, "Gelecek Haftanın Bilgilendirmesi", null,
    h("p", { class: "empty" }, "Takvim bu hafta hazırlanamadı. ", link(bigpara, "Bigpara takvimini açın ↗")));
  return section(6, "Gelecek Haftanın Bilgilendirmesi", T.week,
    h("table", { class: "week" }, h("tbody", {}, (nw.days || []).map((d) => h("tr", {},
      h("td", {}, h("span", { class: "d" }, (d.date_tr || d.date).replace(/ \d{4}$/, "")), h("span", { class: "w" }, d.weekday || "")),
      h("td", {}, editable("div", d, "text")))))),
    h("div", { class: "meta", style: "margin-top:10px" }, "Kaynak: ", link(bigpara, "Bigpara ekonomik takvim ↗")));
}

// ---- çizim ----------------------------------------------------------------

function render() {
  const scrollY = window.scrollY;
  const issueNo = String(doc.issue || "").split("/").pop().trim();
  app.replaceChildren(...[
    h("div", { class: "intro" },
      h("h1", {}, doc.date_tr, " ", h("span", { class: "issue-no" }, `· Sayı ${issueNo}`)),
      h("p", {}, isLatest
        ? `Taslak ${longDate(doc.generated_at)} itibarıyla hazırlandı. Metinlere tıklayarak düzenleyebilirsiniz.`
        : "Geçmiş bir bülteni görüntülüyorsunuz.")),
    isLatest ? noticeBox() : null,
    h("article", { class: "paper" },
      wciSection(),
      tradeSection(),
      eventSection(),
      newsSection(4, "tr_news", "Türkiye'deki Gelişmeler", "1- Türkiye'deki Gelişmeler;"),
      newsSection(5, "intl_news", "Yurt Dışındaki Gelişmeler", "2- Yurt Dışındaki Gelişmeler;"),
      weekSection()),
    h("p", { class: "foot" }, h("span", { class: "saved" }, "Değişiklikleriniz bu tarayıcıda otomatik kaydedilir.")),
  ].filter(Boolean));
  window.scrollTo(0, scrollY);
}

// ---- pencereler -----------------------------------------------------------

function dialog(title, body, actions) {
  const d = $("#dialog");
  $("#dialogBody").replaceChildren(h("div", { class: "dlg" }, h("h2", {}, title), body,
    h("div", { class: "dlg-actions" }, actions || h("button", { class: "btn", type: "button", onclick: () => d.close() }, "Kapat"))));
  d.showModal();
}

function actionsUrl() {
  const m = location.hostname.match(/^([^.]+)\.github\.io$/);
  const repo = location.pathname.split("/").filter(Boolean)[0];
  return m && repo ? `https://github.com/${m[1]}/${repo}/actions/workflows/bulletin.yml` : null;
}

const ACTIONS = {
  help: () => dialog("Nasıl kullanılır?", h("ol", {},
    h("li", {}, "Taslak her cuma sabah 06:30'da kendiliğinden hazırlanır."),
    h("li", {}, "Üstteki sarı kutudaki maddeleri kontrol edip işaretleyin."),
    h("li", {}, "Değiştirmek istediğiniz metne tıklayıp yazın. Haberleri oklarla sıralayabilir, × ile çıkarabilir, “Önerilen diğer haberler”den ekleyebilirsiniz."),
    h("li", {}, "“Bülteni kopyala” ile tüm metni alıp Canva'ya yapıştırın. Tek bir bölüm için o bölümdeki “Kopyala”yı kullanın."))),
  rerun: () => {
    const url = actionsUrl();
    const d = $("#dialog");
    dialog("Taslağı yeniden oluştur",
      h("p", {}, "Haberler baştan toplanır ve taslak yeniden yazılır; yaklaşık 10 dakika sürer. Açılacak GitHub sayfasında sağdaki “Run workflow” düğmesine, ardından yeşil “Run workflow” düğmesine basın. Bittiğinde bu sayfayı yenileyin."),
      [h("button", { class: "btn", type: "button", onclick: () => d.close() }, "Vazgeç"),
       url && h("a", { class: "btn primary", href: url, target: "_blank", rel: "noopener", onclick: () => d.close() }, "GitHub'da aç", icon("ext"))]);
  },
  reset: () => {
    const d = $("#dialog");
    dialog("Değişiklikleriniz geri alınsın mı?",
      h("p", {}, "Bu bülten için yaptığınız tüm düzenlemeler silinir ve otomatik hazırlanan taslak yeniden yüklenir."),
      [h("button", { class: "btn", type: "button", onclick: () => d.close() }, "Vazgeç"),
       h("button", { class: "btn primary", type: "button", onclick: async () => {
         d.close();
         try { localStorage.removeItem(storeKey); } catch {}
         await load(doc.date);
         toast("Otomatik taslak yeniden yüklendi.");
       } }, "Geri al")]);
  },
};

// ---- yükleme --------------------------------------------------------------

async function load(date) {
  const url = date ? `data/bulletins/${date}.json` : "data/latest.json";
  const fresh = await (await fetch(url, { cache: "no-store" })).json();
  storeKey = `bulten:${fresh.date}:${fresh.generated_at}`;
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(storeKey) || "null"); } catch {}
  doc = saved || fresh;
  render();
  return fresh;
}

async function init() {
  $("#copyAll").append(icon("copy"), h("span", { class: "lbl-long" }, "Bülteni kopyala"), h("span", { class: "lbl-short" }, "Kopyala"));
  $("#print").append(icon("printer"), h("span", { class: "lbl" }, "PDF"));
  $("#menuBtn").append(icon("more"));

  const sel = $("#archive");
  let idx = [];
  try {
    idx = await (await fetch("data/index.json", { cache: "no-store" })).json();
    sel.replaceChildren(...idx.map((x, i) => h("option", { value: x.date },
      `${new Date(x.date).toLocaleDateString("tr-TR", { day: "numeric", month: "long", year: "numeric" })}${i === 0 && idx.length > 1 ? " (son)" : ""}`)));
  } catch {}
  try { history = await (await fetch("data/wci_history.json", { cache: "no-store" })).json(); } catch {}

  sel.addEventListener("change", () => { isLatest = sel.selectedIndex === 0; load(sel.value); });
  $("#copyAll").addEventListener("click", () => copy(T.all(), "Bülten"));
  $("#print").addEventListener("click", () => window.print());

  const menu = $("#menu"), menuBtn = $("#menuBtn");
  const closeMenu = () => { menu.hidden = true; menuBtn.setAttribute("aria-expanded", "false"); };
  menuBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.hidden = !menu.hidden;
    menuBtn.setAttribute("aria-expanded", String(!menu.hidden));
  });
  document.addEventListener("click", closeMenu);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
  menu.addEventListener("click", (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act) { closeMenu(); ACTIONS[act](); }
  });
  if (!actionsUrl()) menu.querySelector('[data-act="rerun"]').hidden = true;

  try {
    const b = await load();
    sel.value = b.date;
  } catch {
    app.replaceChildren(h("div", { class: "empty" }, "Henüz hazırlanmış bir bülten yok. İlk taslak cuma sabahı oluşturulacak."));
  }
}

init();
