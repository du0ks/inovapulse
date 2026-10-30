"""Haftalık bülten taslağını üretir ve docs/data/ altına JSON olarak yazar.

Kullanım:  python -m pipeline.build [--date 2026-10-23] [--no-llm]
"""

import argparse
import json
import re
import traceback
from collections import Counter
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from . import config, llm, prompts
from .sources import (
    PAYWALLED, article_info, article_text, page_text, dedupe, fetch_bigpara, fetch_charts, fetch_drewry,
    fetch_event_listings, fetch_gnews, fetch_rss, fetch_tavily, fetch_ticaret, fetch_trade_official,
    TRADE_WORDS, issue_number, log, reader_check, register_link, resolve_gnews, shortlist_calendar,
    tr_holidays, vc_main_image,
)

TR_TZ = timezone(timedelta(hours=3))
WEEKDAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
          "Eylül", "Ekim", "Kasım", "Aralık"]


def tr_date(d):
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def fmt_candidates(items, snippet_len=280):
    lines = []
    for i, it in enumerate(items):
        pub = (it.get("published") or "")[:10]
        lines.append(f"{i} | {pub} | {it['source']} | {it['title']} | {(it.get('snippet') or '')[:snippet_len]}")
    return "\n".join(lines)


def interleave(a, b):
    out = []
    for i in range(max(len(a), len(b))):
        out += a[i:i + 1] + b[i:i + 1]
    return out


def pick(items, idx):
    try:
        return items[int(idx)]
    except (ValueError, TypeError, IndexError):
        return None


# --- Bölümler --------------------------------------------------------------

def build_news(section, candidates, count, reserve, today, since):
    def check(o):
        items = o.get("items") or []
        if len(items) < count // 2:
            raise ValueError(f"yetersiz haber ({len(items)})")
        llm.require_turkish([x.get("summary") for x in items] + [x.get("title") for x in items])

    out = llm.ask_json(
        prompts.NEWS_SYSTEM,
        prompts.NEWS_USER.format(
            section=section, today=today, since=since, count=count, reserve=reserve,
            candidates=fmt_candidates(candidates),
        ),
        check=check,
    )

    def resolve(x):
        c = pick(candidates, x.get("id"))
        if not c:
            return None
        alts = [pick(candidates, a) for a in x.get("alt_ids") or []]
        return {
            "title": x.get("title") or c["title"],
            "summary": x.get("summary", ""),
            "category": x.get("category"),
            "score": x.get("score"),
            "source": c["source"],
            "url": c["url"],
            "published": c.get("published"),
            "original_title": c["title"],
            "fulltext": c.get("fulltext"),
            "also_reported_by": [{"source": a["source"], "url": a["url"], "published": a.get("published")}
                                 for a in alts if a],
        }

    picked = [r for r in map(resolve, out.get("items", []) + out.get("reserve", [])) if r]
    ok = verify_news(picked, since)
    if len(ok) < count:
        log(f"  ! {section}: doğrulanan haber sayısı {len(ok)}")
    items, rest = diversify(ok, count, since)
    return {"items": items, "reserve": rest}


def site(url):
    """Haberin geldiği site (ör. trthaber.com, ticaret.gov.tr)."""
    parts = urlparse(url or "").netloc.lower().removeprefix("www.").split(".")
    n = 3 if len(parts) >= 3 and parts[-1] == "tr" and parts[-2] in ("gov", "com", "org", "edu", "net", "bel") else 2
    return ".".join(parts[-n:])


MAX_PER_SITE = 2


def diversify(news, count, since):
    """Aynı siteden en fazla MAX_PER_SITE haber. Sınırı aşan haber için önce aynı haberin başka bir
    sitedeki versiyonu denenir; yoksa yedeğe kalır. Haber sayısı yine dolmazsa eksik kadar haber
    bir üst sınırla eklenir."""
    items, rest, used = [], [], Counter()
    for it in news:
        if len(items) < count and used[site(it["url"])] >= MAX_PER_SITE:
            for a in it.get("also_reported_by", []):
                if used[site(a["url"])] >= MAX_PER_SITE:
                    continue
                url, good, _ = check_link(a["url"], a.get("published"), since)
                if good:
                    it = {**it, "url": url, "source": a["source"], "published": good["date"],
                          "also_reported_by": [x for x in it["also_reported_by"] if x["url"] != a["url"]]}
                    break
        if len(items) < count and used[site(it["url"])] < MAX_PER_SITE:
            items.append(it)
            used[site(it["url"])] += 1
        else:
            rest.append(it)
    for it in list(rest):
        if len(items) >= count:
            break
        if used[site(it["url"])] <= MAX_PER_SITE:
            log(f"  ! kaynak çeşitliliği: eksik yer {site(it['url'])} kaynağından dolduruldu")
            items.append(it)
            rest.remove(it)
            used[site(it["url"])] += 1
    return items, rest


MIN_ARTICLE_CHARS = 1200


def check_link(url, published, since):
    """Linkin açılabilir, yeterince içerikli ve kapsanan döneme ait olduğunu doğrular.
    Dönüş: (url, {"text", "date"} | None, ret nedeni)"""
    url = resolve_gnews(url)
    if PAYWALLED.search(url or ""):
        return url, None, "erişim kısıtlı site"
    if re.search(r"wto\.org/.*/(safe|tbt|sps|ad|cv)_", url or ""):
        return url, None, "resmî bildirim sayfası"
    m = re.search(r"/(20\d\d)/(\d\d)/", url or "")
    if m and f"{m.group(1)}-{m.group(2)}" < since[:7]:
        return url, None, "eski tarih (URL)"
    info = article_info(url)
    if len(info["text"]) < MIN_ARTICLE_CHARS:
        return url, None, f"içerik yetersiz ({len(info['text'])} karakter)"
    dates = [d[:10] for d in (published, info["date"]) if d]
    if any(d < since for d in dates):
        return url, None, f"eski tarih ({min(dates)})"
    if any(d > date.today().isoformat() for d in dates):
        dates = [d for d in dates if d <= date.today().isoformat()]
    return url, {"text": info["text"], "date": max(dates) if dates else None}, None


def verify_news(items, since):
    """Her haberin linkini açıp kontrol eder; geçmeyen link yerine aynı haberin diğer
    kaynaklarını dener. Hiçbiri geçmezse haber elenir."""
    def one(it):
        tries = [(it["url"], it.get("published"), it["source"])] + [
            (a["url"], a.get("published"), a["source"]) for a in it.get("also_reported_by", [])]
        reasons = []
        for url, pub, src in tries:
            url, good, why = check_link(url, pub, since)
            if good:
                it.update(url=url, source=src, published=good["date"], fulltext=good["text"][:4000])
                it["also_reported_by"] = [a for a in it.get("also_reported_by", []) if a["url"] != url]
                return it
            reasons.append(f"{src}: {why}")
        log(f"    – elendi: {it['title'][:60]} ({'; '.join(reasons)})")
        return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        return [x for x in ex.map(one, items) if x]


def refine_news(sections):
    """Seçilen haberlerin tam metnini çekip özetleri doğrular."""
    blocks, refs = [], {}
    for name, sec in sections.items():
        for i, it in enumerate(sec["items"]):
            key = f"{name}-{i}"
            it["url"] = resolve_gnews(it["url"])
            for a in it.get("also_reported_by", []):
                a["url"] = resolve_gnews(a["url"])
            text = it.pop("fulltext", None) or article_text(it["url"])
            refs[key] = it
            blocks.append(
                f"### {key}\nBaşlık: {it['title']}\nTaslak: {it['summary']}\n"
                f"Tam metin: {text or '(alınamadı)'}"
            )
    if not blocks:
        return
    out = llm.ask_json(prompts.REFINE_SYSTEM, prompts.REFINE_USER.format(items="\n\n".join(blocks)),
                       check=lambda o: llm.require_turkish([x.get("summary") for x in o.get("items", [])]))
    for x in out.get("items", []):
        it = refs.get(x.get("key"))
        if it and x.get("summary"):
            it["summary"] = x["summary"]
            it["title"] = x.get("title") or it["title"]


def build_wci(raw):
    out = llm.ask_json(prompts.WCI_SYSTEM, prompts.WCI_USER.format(text=raw["text_en"]), max_tokens=8000,
                       check=lambda o: llm.require_turkish(o.get("paragraphs") or [], 1.0))
    return {
        **raw,
        "paragraphs": out.get("paragraphs", []),
        "routes": out.get("routes", []),
        "outlook": out.get("outlook"),
        "composite_usd_40ft": raw["composite_usd_40ft"] or out.get("composite_usd_40ft"),
        "change_pct": raw["change_pct"] if raw["change_pct"] is not None else out.get("change_pct"),
    }


def tr_num(v, d=2):
    s = f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return re.sub(r",0+$", "", s)


def trade_from_official(t):
    """Ticaret Bakanlığı açıklamasındaki rakamlardan bölüm verisini ve özet metnini üretir."""
    mo, ytd = t["monthly"], t["ytd"]
    ex, im = mo.get("exports") or {}, mo.get("imports") or {}

    def phrase(x):
        if x.get("yoy_pct") is None:
            return f"{tr_num(x['billion_usd'])} milyar dolar"
        verb = "artarak" if x["yoy_pct"] >= 0 else "azalarak"
        return f"%{tr_num(abs(x['yoy_pct']), 1)} {verb} {tr_num(x['billion_usd'])} milyar dolar"

    parts = [f"Ticaret Bakanlığı verilerine göre {t['year']} yılı {t['month']} ayında ihracat geçen yılın "
             f"aynı ayına göre {phrase(ex)}"]
    if im:
        parts.append(f", ithalat ise {phrase(im)}")
    parts.append(" oldu.")
    deficit = round(im["billion_usd"] - ex["billion_usd"], 3) if im else None
    if deficit is not None:
        parts.append(f" Aylık dış ticaret {'açığı' if deficit > 0 else 'fazlası'} "
                     f"{tr_num(abs(deficit))} milyar dolar olarak gerçekleşti.")
    yx, yi = ytd.get("exports"), ytd.get("imports")
    if yx:
        parts.append(f" Ocak-{t['month']} döneminde ihracat {phrase(yx)} seviyesine ulaştı")
        if yi:
            parts.append(f", ithalat {tr_num(yi['billion_usd'])} milyar dolar oldu")
        parts.append(".")
    return {
        "month": t["month"], "year": t["year"],
        "exports_billion_usd": ex.get("billion_usd"), "exports_yoy_pct": ex.get("yoy_pct"),
        "imports_billion_usd": im.get("billion_usd"), "imports_yoy_pct": im.get("yoy_pct"),
        "trade_deficit_billion_usd": deficit,
        "ytd_exports_billion_usd": (yx or {}).get("billion_usd"),
        "summary": "".join(parts),
        "confidence": "yüksek",
        "sources": [{"title": f"{t['year']} Yılı {t['month']} Ayı Dış Ticaret Verileri",
                     "source": "T.C. Ticaret Bakanlığı", "url": t["url"]}],
        "official_url": t["url"],
        "published": t.get("published"),
    }


def build_trade(candidates, today):
    """Resmî sayfa bulunamazsa yedek: haberlerden LLM ile çıkarım."""
    # İlk adayların tam metnini ekle (ithalat rakamı genelde sadece metinde geçer)
    candidates = [dict(c) for c in candidates]
    for c in candidates[:6]:
        c["url"] = resolve_gnews(c["url"])
        text = article_text(c["url"], 2500)
        if text:
            c["snippet"] = text
    out = llm.ask_json(
        prompts.TRADE_SYSTEM,
        prompts.TRADE_USER.format(today=today, candidates=fmt_candidates(candidates, 500)),
        max_tokens=8000,
        check=lambda o: llm.require_turkish([o.get("summary")]),
    )
    srcs = [pick(candidates, i) for i in out.pop("source_ids", []) or []]
    out["sources"] = [{"title": s["title"], "source": s["source"], "url": s["url"]} for s in srcs if s]
    out["official_url"] = "https://ticaret.gov.tr/istatistikler/dis-ticaret-istatistikleri"
    return out


def build_charts(cands, today):
    if len(cands) < 2:
        raise ValueError("yeterli grafik adayı yok")
    lines = "\n".join(
        f"{i} | {(c.get('published') or '')[:10]} | {c['title']} | etiketler: {', '.join(c['tags'])} | "
        f"{c['text'][:1200]}" for i, c in enumerate(cands))

    def check(o):
        if len(o.get("items") or []) < 2:
            raise ValueError("iki grafik seçilmedi")
        if any(len(x.get("summary") or "") < 150 for x in o["items"]):
            raise ValueError("grafik metni boş veya çok kısa")
        llm.require_turkish([x.get("summary") for x in o["items"]] + [x.get("title") for x in o["items"]])

    out = llm.ask_json(prompts.CHARTS_SYSTEM, prompts.CHARTS_USER.format(today=today, candidates=lines),
                       max_tokens=6000, check=check)

    def card(c, x=None):
        return {"title": (x or {}).get("title") or c["title"], "summary": (x or {}).get("summary", ""),
                "original_title": c["title"], "url": c["url"], "image": c.get("image"),
                "image_share": c.get("image_share"),
                "source": c["source"], "published": c.get("published")}

    items = [card(pick(cands, x.get("id")), x) for x in out["items"] if pick(cands, x.get("id"))][:2]
    used = {i["url"] for i in items}
    reserve = [card(c) for c in (pick(cands, i) for i in out.get("reserve_ids") or []) if c and c["url"] not in used]
    for c in items + reserve:  # akıştaki görsel çoğu zaman yatay paylaşım görseli; dikey infografiği tercih et
        c["image"] = vc_main_image(c["url"]) or c["image"]
    return {"items": items, "reserve": reserve}


def dates_in(text):
    """Metindeki '27 Ekim 2026' ve '27.10.2026' biçimli tarihler."""
    out = []
    for d, m, y in re.findall(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(20\d\d)", text or ""):
        out.append(date(int(y), MONTHS.index(m) + 1, int(d)))
    for d, m, y in re.findall(r"\b(\d{1,2})[./](\d{1,2})[./](20\d\d)\b", text or ""):
        try:
            out.append(date(int(y), int(m), int(d)))
        except ValueError:
            pass
    return out


# Birden çok etkinliği listeleyen sayfalar tek bir etkinlik linki olarak kullanılamaz
LISTING_URL = re.compile(r"(uib\.org\.tr/tr/akademi-egitimler|ticaret\.gov\.tr/duyurular|"
                         r"tagm\.ticaret\.gov\.tr/haberler|ito\.org\.tr/tr/etkinlikler)/?(\?.*)?$")
LISTING_TITLE = re.compile(r"(^|[-–|:]\s*)(eğitimler|etkinlikler|duyurular|seminerler|webinarlar)\s*$", re.I)


def kamu(url):
    """Kamu kurumu sayfası: bakanlık toplantı/eğitimleri ücretsizdir, sayfada ayrıca yazmaz."""
    return urlparse(url or "").netloc.lower().endswith(".gov.tr")


def is_listing(c):
    return bool(LISTING_URL.search(c.get("url") or "") or LISTING_TITLE.search(c.get("title") or ""))


def build_event(candidates, today):
    """Adayların sayfalarını açar, LLM ile tarih/online/ücret bilgisini çıkarır ve kuralları kodla
    uygular: ileri tarihli, çevrim içi ve ücretsiz olmayan hiçbir etkinlik seçilmez."""
    # Başlık/özetteki tarihlerin hepsi geçmişteyse etkinlik bitmiştir; LLM'e hiç gönderme
    def past(c):
        ds = dates_in(f"{c['title']} {c.get('snippet') or ''}")
        return bool(ds) and max(ds) < today
    candidates = [dict(c) for c in candidates if not past(c) and not is_listing(c)][:35]

    def enrich(c):
        c["url"] = resolve_gnews(c["url"])
        info = article_info(c["url"])
        # Tarih/saat/ücret bilgisi çoğu zaman ana metnin dışında (başlık kutusunda) durur
        info["text"] = (info["text"][:1000] + " … " + page_text(c["url"], 1200)).strip(" …")
        c["page_date"] = info["date"]
        if len(info["text"]) > len(c.get("snippet") or ""):
            c["snippet"] = ((c.get("snippet") or "") + " " + info["text"]).strip()
        # Kayıt sayfası çoğu zaman saat bilgisini de içerir; okuyucuya da doğrudan o verilir
        reg = register_link(c["url"])
        if reg and reg.rstrip("/") != c["url"].rstrip("/"):
            c["register_hint"] = reg
            c["snippet"] = f"Kayıt linki: {reg} | Kayıt sayfası: {page_text(reg, 600)} | {c.get('snippet') or ''}"
        return c

    with ThreadPoolExecutor(max_workers=8) as ex:
        candidates = list(ex.map(enrich, candidates))
    # Sayfası 6 aydan eski olanlar neredeyse her zaman geçmiş etkinliktir
    old = (today - timedelta(days=180)).isoformat()
    candidates = [c for c in candidates if not (c.get("page_date") and c["page_date"] < old) and not is_listing(c)]
    lines = "\n".join(
        f"{i} | {c.get('page_date') or (c.get('published') or '')[:10] or '-'} | {c['source']} | {c['title']} | "
        f"{(c.get('snippet') or '')[:2000]}" for i, c in enumerate(candidates))

    def check(o):
        if not isinstance(o.get("events"), list):
            raise ValueError("'events' listesi yok")
        if len(o["events"]) < len(candidates) // 2:
            raise ValueError(f"adayların çoğu değerlendirilmedi ({len(o['events'])}/{len(candidates)})")
        llm.require_turkish([x.get("description") for x in o["events"] if x.get("is_event")] or ["ş"])

    out = llm.ask_json(prompts.EVENT_SYSTEM, prompts.EVENT_USER.format(today=today, candidates=lines),
                       max_tokens=12000, check=check)

    t = today.isoformat()
    limit = (today + timedelta(days=75)).isoformat()
    ok, seen = [], set()
    for x in out["events"]:
        c = pick(candidates, x.get("id"))
        if not c or not x.get("is_event"):
            continue
        start, end = x.get("start_date") or None, x.get("end_date") or None
        last = end or start
        why = (None if last and last >= t else "tarih yok/geçmiş") or \
              (None if not start or start >= t else "başlamış/devam eden program") or \
              (None if not (start and end) or (date.fromisoformat(end) - date.fromisoformat(start)).days <= 5
               else "çok günlü seri/program") or \
              (None if (start or last) <= limit else "çok ileri tarih") or \
              (None if x.get("online") is True else "çevrim içi değil") or \
              (None if x.get("free") is True or (x.get("free") is None and kamu(c["url"])) else "ücretsiz değil") or \
              (None if (x.get("relevance") or 0) >= 5 else "konu dışı")
        if why:
            log(f"    – etkinlik elendi: {(x.get('title') or c['title'])[:60]} ({why})")
            continue
        key = re.sub(r"\W+", "", (x.get("title") or "").lower())[:40]
        if key in seen:
            continue
        seen.add(key)
        fmt = lambda d: date.fromisoformat(d).strftime("%d.%m.%Y")
        ok.append({
            "title": x.get("title") or c["title"], "organizer": x.get("organizer"),
            "description": x.get("description", ""),
            "date": fmt(start) + (f"-{fmt(end)}" if end and end != start else "") if start else fmt(end),
            "start_date": start, "end_date": end,
            "time": x.get("time"), "location": "Online", "fee": "Ücretsiz",
            "register_url": x.get("register_url") or c.get("register_hint") or c["url"],
            "source_url": c["url"], "source": c["source"],
            "relevance": x.get("relevance"),
        })
    # Önce önümüzdeki 3 hafta içindekiler, sonra en ilgili, sonra en yakın tarihli
    soon = (today + timedelta(days=21)).isoformat()
    ok.sort(key=lambda e: ((e["start_date"] or e["end_date"]) > soon, -(e["relevance"] or 0),
                           e["start_date"] or e["end_date"]))
    ok = usable_event_links(ok)
    return {"selected": ok[0] if ok else None, "alternatives": ok[1:5]}


def usable_event_links(events):
    """Okuyucunun açabileceği linki olan etkinlikler. Kayıt linki açılmıyorsa etkinliğin kendi
    sayfasına düşülür; o da açılmıyorsa etkinlik elenir."""
    out = []
    for e in events:
        for url in dict.fromkeys(filter(None, (e.get("register_url"), e.get("source_url")))):
            if LISTING_URL.search(url):
                continue
            good, why = reader_check(url)
            if good:
                out.append({**e, "register_url": url})
                break
            log(f"    – etkinlik linki açılmıyor: {url} ({why})")
        if len(out) >= 5:
            break
    return out


FOREIGN_TRADE = re.compile(r"ithalat|ihracat|dış ticaret|ticaret dengesi|ticaret açığı", re.I)
PARTNERS = ["Almanya", "ABD", "Çin", "İngiltere", "Euro Bölgesi", "Rusya", "Irak", "İtalya", "Fransa",
            "İspanya", "Hollanda", "Japonya", "Hindistan", "Güney Kore", "Kanada", "Brezilya"]


def pick_release(events):
    """Bir günün açıklaması (editör kuralı): Türkiye açıklaması varsa o; yoksa başka bir ülkenin dış
    ticaret açıklaması (büyük ticaret ortakları önce); o da yoksa en önemli makro veri."""
    def rank(e):
        ind = e["indicator"] or ""
        return (not FOREIGN_TRADE.search(ind), not TRADE_WORDS.search(ind), -(e["priority"] or 0),
                PARTNERS.index(e["country"]) if e["country"] in PARTNERS else len(PARTNERS),
                "Aylık" in ind, e["time"] or "")
    tr = [e for e in events if e["country"] == "Türkiye"]
    trade = [e for e in events if FOREIGN_TRADE.search(e["indicator"] or "")]
    pool = tr or trade or [e for e in events if TRADE_WORDS.search(e["indicator"] or "") or e["priority"] >= 3]
    return min(pool, key=rank) if pool else None


def build_calendar(days, events):
    out = {"days": []}
    for day in days:
        e = pick_release([x for x in events if x["date"] == day])
        if e:
            ind = e["indicator"].replace("İstanbul Sanayi Odası (İSO)", "İSO")
            out["days"].append({"date": day, "text": f"{e['country']} {ind} açıklanacak.",
                                "country": e["country"], "time": e["time"]})
    add_holidays(out, days)
    for d in out["days"]:
        d["weekday"] = WEEKDAYS[date.fromisoformat(d["date"]).weekday()]
        d["date_tr"] = tr_date(date.fromisoformat(d["date"]))
    return out


def add_holidays(out, days):
    """Resmî tatil günlerinde o günün metni tatil adıyla başlar (ör. 29 Ekim Cumhuriyet Bayramı)."""
    hol = tr_holidays(days)
    by_date = {d.get("date"): d for d in out.get("days", [])}
    for day in days:
        name = hol.get(day)
        if not name:
            continue
        d = by_date.get(day)
        if not d:
            d = {"date": day, "text": ""}
            out.setdefault("days", []).append(d)
        d["text"] = name
        d["holiday"] = name
        for k in ("country", "time"):  # yerine geçen veri açıklamasından kalmasın
            d.pop(k, None)
    out["days"] = sorted(out.get("days", []), key=lambda d: d.get("date") or "")


# --- Ana akış --------------------------------------------------------------

SECTIONS = {"tr_news": "Türkiye haberleri", "intl_news": "Yurt dışı haberleri",
            "trade_data": "Dış ticaret verisi", "event": "Etkinlik", "next_week": "Gelecek hafta",
            "charts": "Grafik haberleri"}


def news_ok(x):
    items = x.get("items") or []
    per_site = Counter(site(i.get("url")) for i in items)
    return len(items) >= 8 and max(per_site.values(), default=0) <= MAX_PER_SITE + 1


def complete_sections(old, today):
    """Aynı tarihli mevcut taslakta eksiksiz olan bölümler (tekrar çalıştırmada yeniden üretilmez)."""
    warned = " ".join(old.get("warnings") or [])
    ok = set()
    checks = {
        "tr_news": news_ok,
        "intl_news": news_ok,
        "trade_data": lambda x: x.get("exports_billion_usd") is not None and x.get("imports_billion_usd") is not None,
        # Cuma sabahı link yeniden denenir: gece açılan sayfa sabah açılmıyorsa etkinlik yeniden seçilir
        "event": lambda x: bool(x.get("selected")) and not LISTING_URL.search(x["selected"].get("register_url") or "")
                           and reader_check(x["selected"].get("register_url") or "")[0],
        "next_week": lambda x: len(x.get("days") or []) >= 5 and all(
            d.get("holiday") or (d.get("country") and d.get("text", "").startswith(d["country"])) for d in x["days"]),
        "charts": lambda x: len(x.get("items") or []) >= 2,
        "wci": lambda x: bool(x.get("paragraphs")) and (x.get("assessment_date") or "") >= (
            today - timedelta(days=2)).isoformat(),
    }
    for key, fn in checks.items():
        name = SECTIONS.get(key, "WCI")
        if old.get(key) and fn(old[key]) and name not in warned:
            ok.add(key)
    return ok


def run(today: date, use_llm=True, fill_missing=False):
    since_dt = datetime.combine(today - timedelta(days=config.LOOKBACK_DAYS), datetime.min.time(), TR_TZ)
    warnings = []
    path = config.DATA_DIR / "bulletins" / f"{today.isoformat()}.json"
    old = json.loads(path.read_text()) if fill_missing and path.exists() else None
    done = complete_sections(old, today) if old and old.get("llm") else set()
    if done:
        missing = [k for k in list(SECTIONS) + ["wci"] if k not in done]
        if not missing:
            log(f"{today} taslağı eksiksiz; yeniden üretilmiyor.")
            return None
        log(f"Mevcut taslakta eksik bölümler yeniden üretilecek: {', '.join(missing)}")

    bulletin = {
        "date": today.isoformat(),
        "date_tr": tr_date(today),
        "issue": f"{today.year} / {issue_number(today)}",
        "generated_at": datetime.now(TR_TZ).isoformat(timespec="seconds"),
        "llm": None,
        "annual_exports_card": None,
    }

    def step(name, fn):
        try:
            return fn()
        except Exception as ex:
            log(f"!! {name} başarısız: {ex}")
            traceback.print_exc()
            warnings.append(f"{name}: {ex}")
            return None

    log("Haber adayları toplanıyor...")
    rss = fetch_rss(since_dt)
    official = fetch_ticaret(since_dt)
    rel_tr, rel_en = re.compile(config.RELEVANCE_TR, re.I), re.compile(config.RELEVANCE_EN, re.I)
    rss_tr = [x for x in rss if x["region"] == "tr" and rel_tr.search(x["title"] + " " + x["snippet"])]
    rss_intl = [x for x in rss if x["region"] == "intl" and rel_en.search(x["title"] + " " + x["snippet"])]
    tr_c = dedupe(
        official
        + fetch_tavily(config.TAVILY_NEWS_TR, "tr")
        + interleave(rss_tr, fetch_gnews(config.GNEWS_TR, "tr", since_dt, "tr"))
    )[:350]
    intl_c = dedupe(
        fetch_tavily(config.TAVILY_NEWS_INTL, "intl")
        + interleave(rss_intl, fetch_gnews(config.GNEWS_INTL, "intl", since_dt, "en"))
    )[:350]

    log("Etkinlik adayları toplanıyor...")
    next_m = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    months = [f"{MONTHS[today.month - 1]} {today.year}", f"{MONTHS[next_m.month - 1]} {next_m.year}"]
    event_c = dedupe(
        fetch_event_listings()
        + fetch_tavily([q.format(ay=m) for q in config.TAVILY_EVENTS for m in months], "tr", topic="general")
        + fetch_gnews([q.format(ay=months[-1]) for q in config.GNEWS_EVENTS], "tr",
                      since_dt - timedelta(days=21), "tr", "30d")
    )

    log("Dış ticaret verisi (Ticaret Bakanlığı) çekiliyor...")
    trade_off = step("Ticaret Bakanlığı verisi", lambda: fetch_trade_official(today))
    trade_c = []
    if not trade_off:
        prev_month = MONTHS[(today.replace(day=1) - timedelta(days=1)).month - 1]
        trade_c = dedupe(
            fetch_tavily([q.format(ay=prev_month) for q in config.TAVILY_TRADE_DATA], "tr")
            + fetch_gnews([q.format(ay=prev_month) for q in config.GNEWS_TRADE_DATA], "tr",
                          since_dt - timedelta(days=30), "tr", "30d")
        )
    annual = config.ANNUAL_EXPORTS_OVERRIDE.get(today.year - 1)
    annual_year = today.year - 1
    if annual is None and trade_off and trade_off.get("annual"):
        annual, annual_year = trade_off["annual"]["exports_billion_usd"], trade_off["annual"]["year"]
    if annual is not None:
        bulletin["annual_exports_card"] = {"label": f"{annual_year} Türkiye İhracatı",
                                           "value": f"{annual:.3f} Milyar $"}

    log("Grafik haberleri çekiliyor...")
    charts_c = step("Grafik haberleri", lambda: fetch_charts(since_dt)) or []
    log(f"Adaylar: TR {len(tr_c)}, yurt dışı {len(intl_c)}, etkinlik {len(event_c)}, grafik {len(charts_c)}")

    log("Drewry WCI çekiliyor...")
    wci_raw = step("Drewry WCI", fetch_drewry)
    log("Bigpara gelecek hafta takvimi çekiliyor...")
    cal = step("Bigpara takvim", lambda: fetch_bigpara(today)) or ([], [])

    bulletin["candidates"] = {"tr": tr_c, "intl": intl_c, "events": event_c, "trade": trade_c,
                              "charts": charts_c}
    bulletin["wci"] = wci_raw
    bulletin["calendar_raw"] = shortlist_calendar(cal[1])
    if trade_off:
        bulletin["trade_data"] = trade_from_official(trade_off)

    if use_llm and llm.provider():
        bulletin["llm"] = f"{llm.provider()}:{llm.model_name()}"
        since_s = (today - timedelta(days=config.LOOKBACK_DAYS)).isoformat()
        jobs = {
            "tr_news": ("Türkiye haberleri",
                        lambda: build_news("Türkiye'deki Gelişmeler", tr_c, 10, 10, today, since_s)),
            "intl_news": ("Yurt dışı haberleri",
                          lambda: build_news("Yurt Dışındaki Gelişmeler", intl_c, 10, 10, today, since_s)),
            "event": ("Etkinlik", lambda: build_event(event_c, today)),
            "charts": ("Grafik haberleri", lambda: build_charts(charts_c, today)),
        }
        if not trade_off:
            jobs["trade_data"] = ("Dış ticaret verisi", lambda: build_trade(trade_c, today))
        if wci_raw:
            jobs["wci"] = ("WCI özeti", lambda: build_wci(wci_raw))
        if cal[1]:
            jobs["next_week"] = ("Gelecek hafta", lambda: build_calendar(*cal))
        for k in done & set(jobs):
            bulletin[k] = old[k]
            del jobs[k]
        log(f"LLM ({bulletin['llm']}) ile bölümler hazırlanıyor: {', '.join(n for n, _ in jobs.values())}")
        with ThreadPoolExecutor(max_workers=config.LLM_PARALLEL) as ex:
            futs = {k: ex.submit(step, name, fn) for k, (name, fn) in jobs.items()}
            for k, f in futs.items():
                res = f.result()
                if res is not None or k != "wci":
                    bulletin[k] = res
                log(f"  ✓ {jobs[k][0]}" if res is not None else f"  ✗ {jobs[k][0]}")
        secs = {k: bulletin[k] for k in ("tr_news", "intl_news") if k in jobs and bulletin.get(k)}
        if secs:
            log("Seçilen haberlerin tam metinleri ile özetler doğrulanıyor...")
            with ThreadPoolExecutor(max_workers=2) as ex:
                for k, sec in secs.items():
                    ex.submit(step, f"Özet doğrulama ({k})", lambda k=k, sec=sec: refine_news({k: sec}))
    else:
        warnings.append("LLM anahtarı tanımlı değil: yalnızca ham adaylar üretildi.")

    if llm.used_models:
        bulletin["llm"] = ", ".join(sorted(llm.used_models | set(filter(None, [(old or {}).get("llm")]))))
    keep_previous_sections(bulletin, warnings)
    for sec in ("tr_news", "intl_news"):
        for it in (bulletin.get(sec) or {}).get("items", []) + (bulletin.get(sec) or {}).get("reserve", []):
            it.pop("fulltext", None)
    for lst in bulletin["candidates"].values():
        for c in lst:
            c.pop("fulltext", None)
            c.pop("text", None)
    bulletin["warnings"] = warnings
    save(bulletin)
    return bulletin


def keep_previous_sections(b, warnings):
    """Aynı tarihli önceki taslakta başarılı olan bir bölüm bu çalıştırmada üretilemediyse
    eskisini korur; böylece kota/ağ hatası iyi bir taslağın üzerine yazmaz."""
    path = config.DATA_DIR / "bulletins" / f"{b['date']}.json"
    if not path.exists():
        return
    old = json.loads(path.read_text())
    for key, name in SECTIONS.items():
        if not b.get(key) and old.get(key):
            b[key] = old[key]
            warnings.append(f"{name} bu çalıştırmada üretilemedi; önceki sürüm korundu.")
    new_wci, old_wci = b.get("wci") or {}, old.get("wci") or {}
    if (not new_wci.get("paragraphs") and old_wci.get("paragraphs")
            and new_wci.get("assessment_date") in (None, old_wci.get("assessment_date"))):
        b["wci"] = old_wci
        warnings.append("WCI özeti bu çalıştırmada üretilemedi; önceki sürüm korundu.")


def save(b):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (config.DATA_DIR / "bulletins").mkdir(exist_ok=True)
    path = config.DATA_DIR / "bulletins" / f"{b['date']}.json"
    path.write_text(json.dumps(b, ensure_ascii=False, indent=1))
    (config.DATA_DIR / "latest.json").write_text(json.dumps(b, ensure_ascii=False, indent=1))

    idx_path = config.DATA_DIR / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else []
    idx = [x for x in idx if x["date"] != b["date"]]
    idx.append({"date": b["date"], "issue": b["issue"], "generated_at": b["generated_at"]})
    idx.sort(key=lambda x: x["date"], reverse=True)
    idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=1))

    wci = b.get("wci") or {}
    if wci.get("composite_usd_40ft") and wci.get("assessment_date"):
        h_path = config.DATA_DIR / "wci_history.json"
        hist = json.loads(h_path.read_text()) if h_path.exists() else []
        hist = [x for x in hist if x["date"] != wci["assessment_date"]]
        hist.append({"date": wci["assessment_date"], "composite": wci["composite_usd_40ft"],
                     "change_pct": wci.get("change_pct"), "routes": wci.get("routes", [])})
        hist.sort(key=lambda x: x["date"])
        h_path.write_text(json.dumps(hist, ensure_ascii=False, indent=1))
    log(f"Kaydedildi: {path.relative_to(config.ROOT)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="Bülten tarihi (YYYY-AA-GG), varsayılan bugün")
    ap.add_argument("--no-llm", action="store_true", help="Sadece veri topla, LLM çağırma")
    ap.add_argument("--fill-missing", action="store_true",
                    help="Bu tarih için taslak varsa yalnızca eksik/başarısız bölümleri yeniden üret")
    a = ap.parse_args()
    today = date.fromisoformat(a.date) if a.date else datetime.now(TR_TZ).date()
    b = run(today, use_llm=not a.no_llm, fill_missing=a.fill_missing)
    if b and b["warnings"]:
        log("Uyarılar:\n  - " + "\n  - ".join(b["warnings"]))


if __name__ == "__main__":
    main()
