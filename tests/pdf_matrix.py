"""PDF düzeni senaryo testi. Yerelde çalışır:
  uvx --with playwright python tests/pdf_matrix.py [çıktı-klasörü]
Tarayıcı yolu gerekiyorsa CHROME=/yol/chrome ile verilir."""

import functools
import http.server
import json
import os
import re
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = Path(__file__).resolve().parent.parent / "docs"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else None
LONG = ("Ticaret Bakanlığı, ihracatçı firmaların yeni pazarlara açılmasını kolaylaştırmak amacıyla hazırladığı destek "
        "paketini açıkladı. Düzenleme kapsamında lojistik giderleri, fuar katılımları ve dijital pazarlama harcamaları "
        "için ayrılan kaynak artırılırken başvuru süreçleri de sadeleştirildi. Yetkililer, adımın özellikle küçük ve "
        "orta ölçekli işletmelerin dış ticaret hacmine önemli katkı sağlamasını beklediklerini belirtti ve uygulamanın "
        "yıl sonuna kadar bütün sektörleri kapsayacak şekilde genişletileceğini duyurdu.")
BUDGET = "Ticaret Bakanlığı, ihracatçı firmaların yeni pazarlara açılmasını kolaylaştıracak destek paketini açıkladı. " \
         "Düzenleme kapsamında lojistik, fuar ve dijital pazarlama giderleri için ayrılan kaynak artırılırken başvuru " \
         "süreçleri sadeleştirildi; adımın küçük ve orta ölçekli işletmelerin dış ticaret hacmine katkı sağlaması bekleniyor."
POD = ("#142 Ukrayna ile Yeni Ticaret Dönemi ve Fırsatlar\nTürkiye - Ukrayna Serbest Ticaret Anlaşması, ihracatçılar için "
       "hangi fırsatları sunuyor? 🇹🇷🇺🇦\nYeni podcast bölümümüzde Ukrayna pazarındaki fırsatları, savaş sonrası yeniden inşa "
       "sürecini, öne çıkan sektörleri ve ihracatçıların dikkat etmesi gereken stratejik konuları ele alıyor.\n🎧 Podcast'i "
       "Spotify'da dinlemek için tıklayınız.\nhttps://open.spotify.com/episode/5YvXq9ZtEw1abcDEF?si=_ZhvCJk3SnO")
FILL = "(s) => { for (const k of ['tr_news','intl_news']) doc[k].items = doc[k].items.slice(0,10).map(x => ({...x, summary: s})); }"

# (ad, doc'u değiştiren JS, argüman, beklenen en küçük punto, gizlenmesine izin var mı)
CASES = [
    ("gercek-6-kasim", None, None, None),
    ("butce-siniri", FILL, BUDGET, 8.5),
    ("azami-uzunluk", FILL, LONG, None),
    ("1-haber", "() => { doc.tr_news.items = doc.tr_news.items.slice(0,1); doc.intl_news.items = doc.intl_news.items.slice(0,1); }", None, 8.5),
    ("haber-yok", "() => { doc.tr_news.items = []; doc.intl_news = null; }", None, None),
    ("etkinlik-yok", "() => { doc.event = {selected:null, alternatives:[]}; }", None, None),
    ("saat-yok", "() => { doc.event.selected.time = null; }", None, None),
    ("1-grafik", "() => { doc.charts.items = doc.charts.items.slice(0,1); }", None, None),
    ("0-grafik", "() => { doc.charts = null; }", None, None),
    ("gorsel-404", "() => { doc.charts.items[0].image = 'http://127.0.0.1:1/yok.png'; doc.charts.items[1].image = null; }", None, None),
    ("takvim-yok", "() => { doc.next_week = null; }", None, None),
    ("takvim-5-gun", "() => { doc.next_week.days = doc.next_week.days.slice(0,5); }", None, None),
    ("wci-yok", "() => { doc.wci = null; }", None, None),
    ("rakam-yok", "() => { doc.trade_cards = [{label:'A',value:''},{label:'B',value:''},{label:'C',value:''}]; }", None, None),
    ("uzun-adres", "() => { doc.tr_news.items[0].summary = 'https://ornek.com/' + 'a'.repeat(600); }", None, None),
]

MEASURE = """() => {
  const out = {boxes: [], clipped: [], bodies: [], days: document.querySelectorAll('.sh-day').length};
  for (const box of document.querySelectorAll('.sh-list')) {
    const r = box.getBoundingClientRect();
    const lis = [...box.querySelectorAll('li')];
    out.boxes.push({name: box.dataset.fit, font: parseFloat(box.style.fontSize), expected: box.items.length, shown: lis.length,
      outside: lis.filter(l => { const b = l.getBoundingClientRect(); return b.bottom > r.bottom + 1 || b.right > r.right + 1; }).length});
  }
  for (const el of document.querySelectorAll('.fit')) if (el.scrollHeight > el.clientHeight + 1) out.clipped.push(el.dataset.fit);
  for (const b of document.querySelectorAll('.sh-body')) out.bodies.push(b.scrollHeight - b.clientHeight);
  out.warn = [...document.querySelectorAll('.pv-warn li')].map(x => x.textContent);
  out.info = [...document.querySelectorAll('.pv-info li')].map(x => x.textContent);
  out.outline = document.querySelectorAll('.fit.overflow').length;
  return out;
}"""


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def main():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(DOCS)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    fails = 0
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("CHROME") or None)
        for name, js, arg, min_font in CASES:
            for width in ([1300, 800, 1920] if name == "gercek-6-kasim" else [1300]):
                pg = b.new_page(viewport={"width": width, "height": 1000})
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(url)
                pg.evaluate("""(t) => { const c = document.createElement('canvas'); c.width = 800; c.height = 1000;
                  const x = c.getContext('2d'); x.fillStyle = '#1d3f7a'; x.fillRect(0, 0, 800, 1000);
                  localStorage.setItem('bulten:podcast', JSON.stringify({image: c.toDataURL('image/jpeg'), text: t})); }""", POD)
                pg.reload()
                pg.wait_for_selector(".paper")
                if js:
                    pg.evaluate(js, arg)
                    pg.evaluate("() => render()")
                pg.click("#print")
                pg.wait_for_selector(".pv-ok, .pv-warn", timeout=30000)
                if name == "gercek-6-kasim":  # ikinci açılışta zoom kalıntısı ölçümü bozmasın
                    pg.evaluate("() => closePreview()")
                    pg.click("#print")
                    pg.wait_for_timeout(1500)
                m = pg.evaluate(MEASURE)
                pdf = pg.pdf(prefer_css_page_size=True, print_background=True)
                pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf))
                bad = []
                if pages != 3:
                    bad.append(f"{pages} sayfa")
                if errs:
                    bad.append(f"JS hatası: {errs[0][:120]}")
                for x in m["boxes"]:
                    if x["outside"]:
                        bad.append(f"{x['name']}: {x['outside']} haber kutu dışında")
                    if x["shown"] != x["expected"] and not any("PDF'e alınmadı" in w for w in m["warn"]):
                        bad.append(f"{x['name']}: {x['expected'] - x['shown']} haber sessizce kayboldu")
                    if min_font and x["font"] < min_font:
                        bad.append(f"{x['name']}: {x['font']}pt < {min_font}pt")
                if any(v > 1 for v in m["bodies"]):
                    bad.append(f"sayfa gövdesi taşıyor: {m['bodies']}")
                if m["clipped"] and not any("sığmıyor" in w for w in m["warn"]):
                    bad.append(f"sessiz kırpılma: {m['clipped']}")
                if m["days"] != 6:
                    bad.append(f"takvim {m['days']} gün")
                fails += bool(bad)
                fonts = "/".join(str(x["font"]) for x in m["boxes"])
                print(f"{'HATA' if bad else 'ok  '} {name}@{width}: {pages}s font={fonts} gövde={m['bodies']} {'; '.join(bad)}")
                extra = [w for w in m["warn"] if "Podcast" not in w]
                if extra:
                    print("      uyarı:", " | ".join(extra)[:300])
                if OUT and width == 1300:
                    OUT.mkdir(parents=True, exist_ok=True)
                    (OUT / f"{name}.pdf").write_bytes(pdf)
                pg.close()
        b.close()
    srv.shutdown()
    print(f"\n{len(CASES)} senaryo, {fails} hata")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
