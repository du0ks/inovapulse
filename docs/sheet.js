// PDF çıktısı: bülteni Canva'daki iki sayfalık A4 düzeninde dizer, önizletir ve yazdırır.
// app.js'teki doc, h, icon, link, host, save, toast, dialog, history yardımcılarını kullanır.

const SHEET_TEXT = {
  disclaimer: [
    ["b", "***Uyarı: "], ["", "Okuduğunuz bu bülten güvenilir olduğuna inanılan, kamuya açık kaynaklardan elde edilen veriler derlenerek sadece bilgilendirme amaçlı hazırlanmıştır. İNOVAKADEMİ bülten içinde yer alan bilgilerin doğrudan veya dolaylı olarak kullanılması nedeni ile oluşabilecek zararlardan ötürü sorumluluk kabul etmemektedir. Bültende yer alan bilgiler her Cuma günü saat 11:30 itibariyle güncellenmektedir. Yatırım tavsiyesi değildir."],
  ],
  address: "Cevizli Mahallesi Mustafa Kemal Caddesi Hukukçular Towers A Blok Kartal/İstanbul",
  phone: "0216 709 73 32",
  email: "info@inovakademi.com",
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

function sheetHeader() {
  return h("header", { class: "sh-head" },
    h("img", { class: "sh-logo", src: "assets/globby-logo.png", alt: "Globby" }),
    h("div", { class: "sh-title" }, "Haftalık Dış Ticaret Bülteni"),
    h("div", { class: "sh-meta" },
      h("div", { class: "sh-date" }, doc.date_tr),
      h("div", { class: "sh-issue" }, `Sayı: ${doc.issue}`)),
    h("div", { class: "sh-bar" }));
}

function page1(problems) {
  const w = doc.wci || {};
  const chart = w.chart_image ? h("img", { src: w.chart_image, alt: "WCI grafiği" }) : wciChart(history, w.assessment_date);
  if (!chart) problems.push("WCI grafiği için yeterli veri yok; panelde WCI bölümünden grafik görseli yükleyin.");
  if (!(w.paragraphs || []).length) problems.push("WCI metni boş.");

  const cards = tradeCards();
  for (const k of cards) if (!k.value) problems.push(`"${k.label}" kutusu boş.`);
  const label = (s) => {
    const i = s.indexOf("Türkiye");
    return i > 0 ? [s.slice(0, i).trim(), h("br"), s.slice(i)] : s;
  };

  const charts = (doc.charts?.items || []).slice(0, 2);
  if (charts.length < 2) problems.push("Grafik haberleri bölümünde iki grafik olmalı.");
  charts.forEach((c, i) => {
    if (!c.image) problems.push(`${i + 1}. grafik haberinin görseli yok.`);
    if (!(c.summary || "").trim()) problems.push(`${i + 1}. grafik haberinin metni boş.`);
  });

  const e = doc.event?.selected;
  if (!e?.title) problems.push("Ücretsiz etkinlik seçilmedi.");
  else {
    if (!e.date) problems.push("Etkinlik tarihi boş.");
    if (!e.time) problems.push("Etkinlik saati boş.");
  }
  const pod = podcast();
  if (!pod?.image) problems.push("Podcast görseli yüklenmedi (panelde Podcast bölümü).");
  if (!pod?.text) problems.push("Podcast açıklaması boş (panelde Podcast bölümü).");

  return h("section", { class: "sh-page" },
    h("div", { class: "sh-frame" },
      sheetHeader(),
      h("div", { class: "sh-wci" },
        h("div", { class: "sh-wci-text" },
          h("h3", {}, "Drewry Dünya Konteyner Endeksi (WCI) (US$/40ft)"),
          h("div", { class: "fit", "data-fit": "WCI metni", "data-max": "10", "data-min": "7.5" },
            (w.paragraphs || []).map((p) => h("p", {}, p)))),
        h("div", { class: "sh-wci-chart" },
          h("div", { class: "sh-chart-box" }, chart || h("div", { class: "sh-missing" }, "Grafik yok")),
          h("div", { class: "sh-src" }, h("b", {}, "Kaynak: "), "www.drewry.co.uk"))),
      h("div", { class: "sh-figs" }, cards.map((k) => h("div", { class: "sh-fig" },
        h("div", { class: "sh-fig-lbl" }, label(k.label)),
        h("div", { class: "sh-fig-val" }, k.value || "—")))),
      h("div", { class: "sh-charts" }, [0, 1].map((i) => {
        const c = charts[i];
        return h("div", { class: "sh-cell" },
          h("h3", {}, c?.title || ""),
          h("div", { class: "sh-chart-row" },
            h("div", { class: "sh-chart-img" },
              c?.image ? h("img", { src: c.image, alt: "" }) : h("div", { class: "sh-missing" }, "Görsel yok"),
              h("div", { class: "sh-src" }, h("b", {}, "Kaynak: "), "www.visualcapitalist.com")),
            h("div", { class: "sh-chart-text fit", "data-fit": `${i + 1}. grafik haberi metni`, "data-max": "9.5", "data-min": "7" },
              h("p", {}, c?.summary || ""))));
      })),
      h("div", { class: "sh-bottom" },
        h("div", { class: "sh-cell sh-event" },
          h("h3", {}, "Haftanın Ücretsiz Etkinlik Duyurusu"),
          h("div", { class: "fit", "data-fit": "Etkinlik metni", "data-max": "10", "data-min": "7.5" },
            e?.title ? [
              h("p", { class: "sh-ev-title" }, e.title),
              h("p", {}, e.description || ""),
              h("p", {}, h("b", {}, "Eğitim Tarihi: "), e.date || "", e.time ? [", ", h("b", {}, "Saat: "), e.time] : ""),
              h("p", {}, h("b", {}, "Eğitim Yeri: "), [e.location, e.fee].filter(Boolean).join(", ")),
              h("p", {}, h("b", {}, "Kayıt için: "), shortHost(e.register_url)),
            ] : h("p", {}, ""))),
        h("div", { class: "sh-cell sh-podcast" },
          h("h3", {}, "İhracat Muhabbetleri Podcast"),
          h("div", { class: "sh-pod-row" },
            h("div", { class: "sh-pod-img" }, pod?.image ? h("img", { src: pod.image, alt: "" }) : h("div", { class: "sh-missing" }, "Podcast görseli yok")),
            pod?.text ? h("div", { class: "sh-pod-text fit", "data-fit": "Podcast açıklaması", "data-max": "10", "data-min": "7" },
              pod.text.split(/\n+/).map((p) => h("p", {}, p))) : null)))),
    h("div", { class: "sh-foot1" }, "İnovakademi tarafından hazırlanmaktadır."));
}

function page2(problems) {
  const news = (key) => (doc[key]?.items || []).map((x) => x.summary).filter(Boolean);
  const tr = news("tr_news"), intl = news("intl_news");
  if (!tr.length) problems.push("Türkiye haberleri boş.");
  if (!intl.length) problems.push("Yurt dışı haberleri boş.");

  // Takvim: bülten tarihinden sonraki pazartesi-cumartesi; eksik gün varsa boş kutu
  const days = doc.next_week?.days || [];
  const base = new Date(doc.date + "T12:00:00");
  base.setDate(base.getDate() + ((8 - base.getDay()) % 7 || 7));
  const week = [...Array(6)].map((_, i) => {
    const d = new Date(base); d.setDate(base.getDate() + i);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const x = days.find((y) => y.date === iso);
    return { date_tr: `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`, weekday: DAYS[d.getDay()], text: x?.text || "" };
  });
  if (week.some((d) => !d.text)) problems.push("Gelecek hafta takviminde boş gün var.");

  return h("section", { class: "sh-page" },
    h("div", { class: "sh-frame" },
      sheetHeader(),
      h("div", { class: "sh-news fit", "data-fit": "Haberler (2. sayfa)", "data-max": "9", "data-min": "7" },
        h("h2", {}, "Türkiye ve yurt dışında bu hafta hangi gelişmeler oldu? Birlikte bir göz atalım."),
        h("h4", {}, "1- Türkiye'deki Gelişmeler;"),
        h("ul", {}, tr.map((t) => h("li", {}, t))),
        h("h4", {}, "2- Yurt Dışındaki Gelişmeler;"),
        h("ul", {}, intl.map((t) => h("li", {}, t)))),
      h("p", { class: "sh-disc" }, SHEET_TEXT.disclaimer.map(([b, t]) => b ? h("b", {}, t) : t)),
      h("div", { class: "sh-cal" }, week.map((d, i) => h("div", { class: "sh-day" },
        h("div", { class: "sh-day-h" }, d.date_tr, h("br"), d.weekday),
        h("div", { class: "sh-day-b fit", "data-fit": `Takvim (${d.weekday})`, "data-max": "7.5", "data-min": "6" }, d.text))))),
    h("div", { class: "sh-foot2" },
      h("span", {}, h("b", {}, "İnovakademi: "), SHEET_TEXT.address, " ", h("b", {}, "Tel: "), SHEET_TEXT.phone, " ",
        h("b", {}, "E-posta: "), SHEET_TEXT.email),
      h("b", {}, "Sayfa2")));
}

// Yazı boyutunu kutuya sığana kadar küçültür; sığmayanları döndürür
function fitAll(root) {
  const over = [];
  for (const el of root.querySelectorAll(".fit")) {
    const max = parseFloat(el.dataset.max), min = parseFloat(el.dataset.min);
    let size = max;
    el.style.fontSize = `${size}pt`;
    while (el.scrollHeight > el.clientHeight + 1 && size > min) {
      size = Math.round((size - 0.25) * 100) / 100;
      el.style.fontSize = `${size}pt`;
    }
    const bad = el.scrollHeight > el.clientHeight + 1;
    el.classList.toggle("overflow", bad);
    if (bad) over.push(el.classList.contains("sh-news")
      ? "Haberler 2. sayfaya sığmıyor; birkaç haberi × ile çıkarın veya kısaltın."
      : `${el.dataset.fit} kutuya sığmıyor; metni kısaltın.`);
  }
  return over;
}

async function waitAssets(root) {
  try { await document.fonts.ready; } catch {}
  await Promise.all([...root.querySelectorAll("img")].map((im) =>
    im.complete ? null : new Promise((r) => { im.onload = im.onerror = r; setTimeout(r, 8000); })));
}

async function buildSheet() {
  const root = document.getElementById("sheet");
  const problems = [];
  root.replaceChildren(page1(problems), page2(problems));
  await waitAssets(root);
  problems.push(...fitAll(root));
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
      ? h("div", { class: "pv-warn" }, h("b", {}, "Kaydetmeden önce bakın:"), h("ul", {}, problems.map((p) => h("li", {}, p))))
      : h("div", { class: "pv-ok" }, icon("check"), "Eksik görünmüyor."),
    h("p", { class: "pv-hint" }, "“PDF olarak kaydet”e bastığınızda açılan pencerede Hedef olarak “PDF olarak kaydet”i seçin. ",
      "Chrome veya Edge önerilir; “Üstbilgi ve altbilgi” kapalı, kenar boşlukları “Yok” olmalı."));
}

function closePreview() {
  document.getElementById("preview").hidden = true;
  document.body.classList.remove("previewing");
}

// Ctrl+P ile doğrudan yazdırılırsa da güncel bülten basılsın
window.addEventListener("beforeprint", () => {
  if (!document.body.classList.contains("previewing") && doc) {
    const root = document.getElementById("sheet");
    const problems = [];
    root.replaceChildren(page1(problems), page2(problems));
    fitAll(root);
  }
});
