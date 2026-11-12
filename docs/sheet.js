// PDF çıktısı: bülteni A4 sayfalara dizer, önizletir ve yazdırır. 1. sayfa sabittir;
// sonrası (etkinlik, podcast, haberler, takvim, yasal uyarı) içeriğe göre gerektiği kadar sayfaya akar.
// app.js'teki doc, h, icon, link, host, save, toast, dialog, history yardımcılarını kullanır.

const SHEET_TEXT = {
  disclaimerTitle: "YASAL UYARI VE SORUMLULUK SINIRLANDIRMASI",
  disclaimer: "Bu bültende yer alan her türlü veri, analiz, grafik, haber ve değerlendirmeler, kamuya açık ve güvenilirliğine inanılan kaynaklardan derlenerek yalnızca genel bilgilendirme amacıyla hazırlanmıştır. İşbu bültende sunulan içerikler hiçbir şekilde yatırım, finans, mevzuat, vergi veya ticari danışmanlık faaliyeti kapsamında değerlendirilemez ve herhangi bir yatırım veya ticari karar için yönlendirici bir tavsiye niteliği taşımaz. Bültendeki veriler her Cuma günü saat 11:30 itibarıyla mevcut olan durum esas alınarak güncellenmekte olup, bu tarihten sonra piyasa koşullarında, mevzuatta veya küresel konjonktürde meydana gelebilecek değişikliklerden ötürü İNOVAKADEMİ’nin içeriği güncelleme veya düzeltme yükümlülüğü bulunmamaktadır. İNOVAKADEMİ, bültende yer alan bilgilerin eksiksizliği, doğruluğu veya güncelliği hususunda açık ya da zımni hiçbir garanti vermemektedir. Bültende yer alan bilgilerin, görüşlerin veya analizlerin doğrudan ya da dolaylı olarak kullanılması, uygulanması veya bu bilgilere dayanılarak karar alınması neticesinde doğabilecek kâr kaybı dahil her türlü maddi, manevi, doğrudan veya dolaylı zararlardan İNOVAKADEMİ, yöneticileri, çalışanları ve bülten hazırlayıcıları hiçbir hukuki veya cezai sorumluluk kabul etmemektedir. Bu bültenin tüm telif hakları İNOVAKADEMİ’ye ait olup izinsiz çoğaltılamaz, kopyalanamaz veya ticari amaçlarla üçüncü kişilerle paylaşılamaz.",
  address: "Cevizli Mahallesi Mustafa Kemal Caddesi Hukukçular Towers A Blok Kartal/İstanbul",
  phone: "0216 709 73 32",
  email: "info@inovakademi.com",
};

const EVENT_FALLBACK = {
  text: "Bu hafta için ileri tarihli, çevrim içi ve ücretsiz bir etkinlik duyurusu bulunmuyor. T.C. Ticaret Bakanlığı'nın güncel ücretsiz eğitim ve e-sohbet takvimini aşağıdaki bağlantıdan takip edebilirsiniz.",
  url: "https://dtybs.ticaret.gov.tr/e-sohbetler/takvim/",
};

const PODCAST_KEY = "bulten:podcast";

// ---- yardımcılar ----------------------------------------------------------

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function podcast() {
  try { return JSON.parse(localStorage.getItem(PODCAST_KEY) || "null"); } catch { return null; }
}

// Yüklenen görseli küçültüp JPEG data URL'e çevirir (tarayıcı deposu sınırlı)
function readImage(file, maxSide = 1400) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, maxSide / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      const ctx = c.getContext("2d");
      ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, c.width, c.height);
      ctx.drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(img.src);
      resolve(c.toDataURL("image/jpeg", 0.88));
    };
    img.onerror = () => reject(new Error("Görsel okunamadı"));
    img.src = URL.createObjectURL(file);
  });
}

// Dosya seçtirip görseli onDone(dataUrl) ile döndürür
function pickImage(onDone) {
  const inp = h("input", { type: "file", accept: "image/*" });
  inp.addEventListener("change", async () => {
    const f = inp.files?.[0];
    if (!f) return;
    try { onDone(await readImage(f)); } catch (e) { toast(e.message); }
  });
  inp.click();
}

function uploadButton(label, onDone) {
  return h("button", { class: "btn small", type: "button", onclick: () => pickImage(onDone) }, label);
}

// PDF'te tıklanabilir bağlantı (Chrome/Edge PDF'e bağlantı olarak yazar)
function pdfLink(url, text) {
  return h("a", { class: "sh-a", href: url, target: "_blank", rel: "noopener" }, text);
}

// Metindeki adresleri kısa, tıklanabilir bağlantıya çevirir (uzun adres satırı taşırmasın)
function linkify(text) {
  return text.split(/(https?:\/\/[^\s]+)/).map((part, i) => i % 2
    ? pdfLink(part.replace(/[.,;)]+$/, ""), `${shortHost(part).replace(/^www\./, "")} ↗`)
    : part);
}

function dmy(iso) {
  const [y, m, d] = String(iso).slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

function shortHost(u) {
  try { return new URL(u).hostname; } catch { return u || ""; }
}

// ---- WCI grafiği (son 12 ay) ------------------------------------------------

function wciChart(hist, uptoIso) {
  const pts = hist.filter((x) => x.composite && (!uptoIso || x.date <= uptoIso)).slice(-56);
  const first = pts.length ? new Date(pts[pts.length - 1].date) : null;
  const near = first ? pts.filter((x) => (first - new Date(x.date)) / 864e5 <= 380) : [];
  // Yanlış okunmuş tek bir değer (ör. hat fiyatı) iki komşusundan %40'tan fazla saparsa çizme
  const data = near.filter((x, i) => {
    const a = near[i - 1], b = near[i + 1];
    if (!a || !b) return true;
    const off = (v) => x.composite > v * 1.4 || x.composite < v / 1.4;
    return !(off(a.composite) && off(b.composite));
  });
  if (data.length < 3) return null;
  const W = 300, H = 230, L = 34, R = 6, T = 22, B = 46;
  const vals = data.map((x) => x.composite);
  const top = Math.ceil(Math.max(...vals) / 1000) * 1000;
  const t0 = new Date(data[0].date).getTime(), t1 = new Date(data[data.length - 1].date).getTime();
  const X = (d) => L + ((new Date(d).getTime() - t0) / (t1 - t0 || 1)) * (W - L - R);
  const Y = (v) => T + (1 - v / top) * (H - T - B);
  const s = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "wci-svg" });
  s.append(svgEl("text", { x: 0, y: 9, class: "ax" }));
  s.lastChild.textContent = "US$/40ft";
  const lg = svgEl("g");
  lg.append(svgEl("circle", { cx: 76, cy: 6, r: 2.6, fill: "#1f2a44" }));
  const lt = svgEl("text", { x: 82, y: 9, class: "ax" }); lt.textContent = "World Container Index (WCI) Composite Index";
  lg.append(lt); s.append(lg);
  for (let v = 0; v <= top; v += 1000) {
    s.append(svgEl("line", { x1: L, x2: W - R, y1: Y(v), y2: Y(v), class: "grid" }));
    const t = svgEl("text", { x: L - 4, y: Y(v) + 2.5, class: "ax", "text-anchor": "end" });
    t.textContent = `$${v.toLocaleString("en-US")}`;
    s.append(t);
  }
  s.append(svgEl("polyline", { points: data.map((x) => `${X(x.date)},${Y(x.composite)}`).join(" "), class: "line" }));
  // Yaklaşık ayda bir tarih etiketi
  const months = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];
  // Veri haftaları düzensiz olabildiğinden etiketler ayın ortasına, eşit aralıkla konur
  const d0 = new Date(t0);
  for (let d = new Date(d0.getFullYear(), d0.getMonth(), 15); d.getTime() <= t1; d.setMonth(d.getMonth() + 1)) {
    if (d.getTime() < t0) continue;
    const x = X(d);
    const t = svgEl("text", { x, y: H - B + 10, class: "ax", "text-anchor": "end", transform: `rotate(-45 ${x} ${H - B + 10})` });
    t.textContent = `${months[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`;
    s.append(t);
  }
  return s;
}

// ---- sayfalar ---------------------------------------------------------------

function sheetPage(...body) {
  return h("section", { class: "sh-page" },
    h("div", { class: "sh-frame" },
      h("header", { class: "sh-head" },
        h("img", { class: "sh-logo", src: "assets/globby-logo.png", alt: "Globby" }),
        h("div", { class: "sh-title" }, "Haftalık Dış Ticaret Bülteni"),
        h("div", { class: "sh-meta" },
          h("div", { class: "sh-date" }, doc.date_tr),
          h("div", { class: "sh-issue" }, `Sayı: ${doc.issue}`))),
      h("main", { class: "sh-body" }, ...body),
      h("footer", { class: "sh-foot" },
        h("span", {}, h("b", {}, "İnovakademi"), " · ", SHEET_TEXT.address, " · ", SHEET_TEXT.phone, " · ", SHEET_TEXT.email),
        h("b", { class: "sh-pno" }))));
}

// Başlık + altındaki ince çizgi
const heading = (text, tag = "h3") => h(tag, { class: "sh-h" }, h("span", {}, text));

function fitBox(name, max, min, cls, ...body) {
  return h("div", { class: `fit ${cls || ""}`, "data-fit": name, "data-max": max, "data-min": min }, ...body);
}

function page1(problems) {
  const w = doc.wci || {};
  const chart = w.chart_image ? h("img", { src: w.chart_image, alt: "WCI grafiği" }) : wciChart(history, w.assessment_date);
  const hasWci = (w.paragraphs || []).length > 0;
  if (!hasWci) problems.push("WCI metni boş; bölüm PDF'e alınmadı.");
  else if (!chart) problems.info.push("WCI grafiği için yeterli veri yok; metin tam genişlikte gösteriliyor.");
  const allCards = tradeCards();
  for (const k of allCards) if (!k.value) problems.push(`"${k.label}" kutusu boş; PDF'e alınmadı.`);
  const cards = allCards.filter((k) => k.value);

  const charts = (doc.charts?.items || []).slice(0, 2);
  if (charts.length < 2) problems.info.push(`Bu hafta ${charts.length} grafik haberi var; düzen buna göre ayarlandı.`);
  charts.forEach((c, i) => {
    if (!c.image) problems.info.push(`${i + 1}. grafik haberinin görseli yok; metin tam genişlikte gösteriliyor.`);
    if (!(c.summary || "").trim()) problems.push(`${i + 1}. grafik haberinin metni boş.`);
  });

  return sheetPage(
    hasWci ? h("section", { class: `sh-wci${charts.length ? "" : " grow"}` },
      heading("Drewry Dünya Konteyner Endeksi (WCI) (US$/40ft)"),
      h("div", { class: "sh-wci-row" },
        fitBox("WCI metni", 10.5, 8, "sh-text", w.paragraphs.map((p) => h("p", {}, p))),
        chart ? h("figure", { class: "sh-wci-chart" },
          h("div", { class: "sh-chart-box" }, chart),
          h("figcaption", { class: "sh-src" }, "Kaynak: ", pdfLink(w.source_url || "https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry", "www.drewry.co.uk"))) : null)) : null,
    cards.length ? h("section", { class: "sh-figs" }, cards.map((k) => h("div", { class: "sh-fig" },
      h("div", { class: "sh-fig-lbl" }, k.label),
      h("div", { class: "sh-fig-val" }, k.value)))) : null,
    charts.length ? h("section", { class: "sh-charts" }, charts.map((c, i) => h("article", { class: "sh-chart" },
      heading(c.title || ""),
      h("div", { class: `sh-chart-row${c.image ? "" : " noimg"}` },
        h("figure", { class: "sh-chart-img" },
          c.image ? h("img", { src: c.image, alt: "" }) : null,
          h("figcaption", { class: "sh-src" }, "Kaynak: ", pdfLink(c.url || "https://www.visualcapitalist.com", "www.visualcapitalist.com"))),
        fitBox(`${i + 1}. grafik haberi metni`, 10, 7.5, "sh-text", h("p", {}, c.summary || "")))))) : null);
}

function newsItems(key) {
  return (doc[key]?.items || []).filter((x) => (x.summary || "").trim());
}

// 1. sayfadan sonra sırayla yerleşecek bloklar. Haber blokları ({news}) sayfalar arasında bölünebilir.
function flowBlocks(problems) {
  const e = doc.event?.selected;
  if (!e?.title) problems.info.push("Bu hafta etkinlik yok; yerine ücretsiz eğitim takvimi yönlendirmesi gösteriliyor.");
  else {
    if (!e.date) problems.push("Etkinlik tarihi boş.");
    if (!e.time) problems.info.push("Etkinlik saati yok; saat satırı PDF'te gösterilmiyor.");
  }
  const pod = podcast();
  if (!pod?.image) problems.push("Podcast görseli yüklenmedi (panelde Podcast bölümü).");
  if (!pod?.text) problems.push("Podcast açıklaması boş (panelde Podcast bölümü).");
  const tr = newsItems("tr_news"), intl = newsItems("intl_news");
  if (!tr.length) problems.push("Türkiye haberleri boş; bölüm PDF'e alınmadı.");
  if (!intl.length) problems.push("Yurt dışı haberleri boş; bölüm PDF'e alınmadı.");

  normalizeWeek(doc);
  const week = doc.next_week.days.map((d) => {
    const x = new Date(d.date + "T12:00:00");
    return { day: x.getDate(), month: MONTHS[x.getMonth()], weekday: DAYS[x.getDay()], text: d.text || NO_RELEASE };
  });
  if (doc.next_week.days.some((d) => d.unavailable)) problems.push("Takvim verisi alınamayan gün var; o günleri panelden kontrol edin.");

  const fact = (k, v) => v ? [h("dt", {}, k), h("dd", {}, v)] : null;
  const fb = doc.event?.fallback || {};
  return [
    h("div", { class: "sh-duo" },
      h("section", { class: "sh-event" },
        heading("Haftanın Ücretsiz Etkinlik Duyurusu"),
        fitBox("Etkinlik metni", 9.5, 8, "sh-text", e?.title ? [
          h("p", { class: "sh-ev-title" }, e.title),
          h("p", {}, e.description || ""),
          h("dl", { class: "sh-facts" },
            fact("Tarih", e.date), fact("Saat", e.time),
            fact("Yer", [e.location, e.fee].filter(Boolean).join(", ")),
            fact("Kayıt", e.register_url ? pdfLink(e.register_url, shortHost(e.register_url)) : "")),
        ] : [
          h("p", {}, fb.text || EVENT_FALLBACK.text),
          h("dl", { class: "sh-facts" },
            fact("Takvim", pdfLink(fb.url || EVENT_FALLBACK.url, shortHost(fb.url || EVENT_FALLBACK.url)))),
        ])),
      pod?.image || pod?.text ? h("section", { class: "sh-podcast" },
        heading("İhracat Muhabbetleri Podcast"),
        // Açıklama varsa görsel sola yaslanır, metin görselin yanından ve altından akar
        pod?.text
          ? fitBox("Podcast açıklaması", 9.5, 7, "sh-pod-text",
            pod.image ? h("img", { class: "sh-pod-float", src: pod.image, alt: "" }) : null,
            pod.text.split(/\n+/).map((p) => h("p", {}, linkify(p))))
          : h("div", { class: "sh-pod-img" }, h("img", { src: pod.image, alt: "" }))) : null),
    tr.length ? { news: { title: "Türkiye'deki Gelişmeler", items: tr,
      lead: "Türkiye ve yurt dışında bu hafta hangi gelişmeler oldu? Birlikte bir göz atalım." } } : null,
    intl.length ? { news: { title: "Yurt Dışındaki Gelişmeler", items: intl } } : null,
    h("section", { class: "sh-week" },
      heading("Gelecek Haftanın Bilgilendirmesi"),
      h("div", { class: "sh-cal" }, week.map((d) => h("div", { class: "sh-day" },
        h("div", { class: "sh-day-h" }, h("b", {}, `${d.day} ${d.month}`), h("span", {}, d.weekday)),
        fitBox(`Takvim (${d.weekday})`, 8.5, 6.5, "sh-day-b", d.text))))),
    h("section", { class: "sh-disc" },
      h("h4", {}, SHEET_TEXT.disclaimerTitle),
      h("p", {}, SHEET_TEXT.disclaimer)),
  ].filter(Boolean);
}

// Yazı boyutunu kutuya sığana kadar küçültür; sığmayanları döndürür
function fitAll(root) {
  const out = [];
  for (const el of root.querySelectorAll(".fit")) {
    const max = parseFloat(el.dataset.max), min = parseFloat(el.dataset.min);
    let size = max;
    el.style.fontSize = `${size}pt`;
    const over = () => el.scrollHeight > el.clientHeight + 1;
    while (over() && size > min) {
      size = Math.round((size - 0.25) * 100) / 100;
      el.style.fontSize = `${size}pt`;
    }
    const bad = over();
    el.classList.toggle("overflow", bad);
    if (bad) out.push(`${el.dataset.fit} kutuya sığmıyor; metni kısaltın.`);
  }
  return out;
}

// ---- sayfalama --------------------------------------------------------------

// Sayfa gövdesinin içerik alt sınırı (px)
function bodyBottom(body) {
  return body.getBoundingClientRect().bottom - parseFloat(getComputedStyle(body).paddingBottom);
}

function fits(body) {
  const last = body.lastElementChild;
  return !last || last.getBoundingClientRect().bottom <= bodyBottom(body) + 0.5;
}

// Haberleri sırayı bozmadan iki sütuna en dengeli şekilde böler
function splitCols(hs, gap) {
  const col = (from, to) => to > from ? hs.slice(from, to).reduce((t, v) => t + v, 0) + gap * (to - from - 1) : 0;
  // eşitlikte soldaki sütun dolu olsun (tek haber solda durur)
  let at = hs.length, best = Infinity;
  for (let k = hs.length; k >= 0; k--) {
    const tall = Math.max(col(0, k), col(k, hs.length));
    if (tall < best) { best = tall; at = k; }
  }
  return { at, height: best };
}

// Listeye sayfada kalan yere sığan en çok haberi yerleştirir, kaç tane olduğunu döndürür.
// force: boş sayfadaysa en az bir haber konur.
function fillNews(list, items, body, force) {
  const [a, b] = list.children;
  a.replaceChildren(...items.map((x) => h("li", {}, x.summary)));
  b.replaceChildren();
  const lis = [...a.children];
  const hs = lis.map((li) => li.getBoundingClientRect().height);
  const gap = lis.length > 1 ? parseFloat(getComputedStyle(lis[0]).marginBottom) : 0;
  const room = bodyBottom(body) - list.getBoundingClientRect().top - 0.5;
  let n = items.length;
  while (n > 0 && splitCols(hs.slice(0, n), gap).height > room) n--;
  if (!n && force) n = 1;
  lis.slice(n).forEach((li) => li.remove());
  b.append(...lis.slice(splitCols(hs.slice(0, n), gap).at, n));
  return n;
}

function addPage(root) {
  const page = sheetPage();
  root.append(page);
  return page.querySelector(".sh-body");
}

// Blokları sırayla sayfalara yerleştirir; sığmayan blok yeni sayfaya geçer, haberler sayfalar arasında bölünür
function paginate(root, blocks) {
  let body = addPage(root);
  const place = (el) => {
    body.append(el);
    fitAll(el);
    if (!fits(body) && body.children.length > 1) {
      // Yasal uyarı son sayfada tek başına kalmasın: takvimle birlikte geçer
      const prev = el.previousElementSibling;
      const move = el.matches(".sh-disc") && prev?.matches(".sh-week") && body.children.length > 2 ? [prev, el] : [el];
      body = addPage(root);
      body.append(...move);
    }
  };
  for (const blk of blocks) {
    if (!blk.news) { place(blk); continue; }
    const { title, items, lead } = blk.news;
    let rest = items, first = true;
    while (rest.length) {
      const list = h("div", { class: "sh-list" }, h("ul", { class: "sh-col" }), h("ul", { class: "sh-col" }));
      const sec = h("section", { class: "sh-news" },
        first && lead ? h("h2", { class: "sh-lead" }, lead) : null,
        heading(first ? title : `${title} (devam)`), list);
      body.append(sec);
      const fresh = body.children.length === 1;
      const n = fillNews(list, rest, body, fresh);
      // Başlığın altında tek başına kalacak haber varsa bölüm yeni sayfadan başlar
      if (!fresh && n < Math.min(2, rest.length)) { sec.remove(); body = addPage(root); continue; }
      rest = rest.slice(n);
      first = false;
      if (rest.length) body = addPage(root);
    }
  }
}

function layoutSheet(root, blocks, problems) {
  fitAll(root.firstElementChild);
  paginate(root, blocks);
  problems.push(...fitAll(root));
  const pages = root.querySelectorAll(".sh-page");
  pages.forEach((p, i) => { p.querySelector(".sh-pno").textContent = `${i + 1} / ${pages.length}`; });
}

// Açılamayan grafik görselleri kaldırılır, metin tam genişliğe geçer
function dropBrokenImages(root, problems) {
  for (const im of root.querySelectorAll(".sh-chart-img > img")) {
    if (im.naturalWidth) continue;
    im.closest(".sh-chart-row").classList.add("noimg");
    im.remove();
    problems.info.push("Bir grafik görseli açılamadı; metin tam genişlikte gösteriliyor.");
  }
}

async function waitAssets(root) {
  // Emoji fontu yalnızca kullanılan karakterler için iner; yazdırmadan önce yüklensin
  try { await document.fonts.load('10pt "Noto Color Emoji"', root.textContent); await document.fonts.ready; } catch {}
  await Promise.all([...root.querySelectorAll("img")].map((im) =>
    im.complete ? null : new Promise((r) => { im.onload = im.onerror = r; setTimeout(r, 8000); })));
}

function newProblems() {
  const p = [];
  p.info = Object.values(doc.notices || {});
  if (isStale()) p.push(`Bu, ${doc.date_tr} tarihli bülten; bu haftanın bülteni henüz hazır değil.`);
  return p;
}

async function buildSheet() {
  const root = document.getElementById("sheet");
  const problems = newProblems();
  root.style.zoom = 1; // ölçüm gerçek boyutta yapılır
  const blocks = flowBlocks(problems);
  // Görseller ölçümden önce yüklensin diye akış blokları geçici bir sayfada bekler
  const stage = sheetPage(...blocks.filter((b) => !b.news));
  root.replaceChildren(page1(problems), stage);
  await waitAssets(root);
  dropBrokenImages(root, problems);
  stage.remove();
  layoutSheet(root, blocks, problems);
  return problems;
}

function pdfFileName() {
  return `Inovakademi-Haftalik-Dis-Ticaret-Bulten-${dmy(doc.date)}`;
}

function printSheet() {
  const old = document.title;
  document.title = pdfFileName(); // Chrome/Edge bunu dosya adı olarak önerir
  const restore = () => { document.title = old; window.removeEventListener("afterprint", restore); };
  window.addEventListener("afterprint", restore);
  window.print();
}

// ---- önizleme penceresi -----------------------------------------------------

async function openPreview() {
  const ov = document.getElementById("preview");
  const sheet = document.getElementById("sheet");
  const msg = h("div", { class: "pv-msg" }, "Hazırlanıyor…");
  ov.replaceChildren(
    h("div", { class: "pv-bar" },
      h("div", { class: "pv-title" }, "PDF önizleme"),
      h("button", { class: "btn", type: "button", onclick: closePreview }, "Kapat"),
      h("button", { class: "btn primary", type: "button", onclick: printSheet }, icon("download"), "PDF olarak kaydet")),
    msg, sheet);
  ov.hidden = false;
  document.body.classList.add("previewing");
  const problems = await buildSheet();
  // Dar ekranlarda sayfaları sığdır (yazdırırken 1'e döner)
  sheet.style.zoom = Math.min(1, (window.innerWidth - 24) / sheet.querySelector(".sh-page").offsetWidth);
  msg.replaceChildren(
    problems.length
      ? h("div", { class: "pv-warn" }, h("b", {}, "Göndermeden düzeltin:"), h("ul", {}, problems.map((p) => h("li", {}, p))))
      : h("div", { class: "pv-ok" }, icon("check"), "Eksik görünmüyor."),
    problems.info.length
      ? h("div", { class: "pv-info" }, h("b", {}, "Bilgi:"), h("ul", {}, problems.info.map((p) => h("li", {}, p))))
      : null,
    h("p", { class: "pv-hint" }, "“PDF olarak kaydet”e bastığınızda açılan pencerede Hedef olarak “PDF olarak kaydet”i seçin. ",
      "Chrome veya Edge önerilir; “Üstbilgi ve altbilgi” kapalı, kenar boşlukları “Yok” olmalı."));
}

function closePreview() {
  document.getElementById("preview").hidden = true;
  document.body.classList.remove("previewing");
}

// Ctrl+P ile doğrudan yazdırılırsa da güncel bülten sığdırılmış olarak basılsın
window.addEventListener("beforeprint", () => {
  if (document.body.classList.contains("previewing") || !doc) return;
  const ov = document.getElementById("preview"), root = document.getElementById("sheet");
  ov.hidden = false;
  document.body.classList.add("previewing");
  const problems = newProblems();
  root.style.zoom = 1;
  const blocks = flowBlocks(problems);
  root.replaceChildren(page1(problems));
  layoutSheet(root, blocks, problems);
  window.addEventListener("afterprint", closePreview, { once: true });
});
