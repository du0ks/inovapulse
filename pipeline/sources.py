"""Veri toplayıcılar: RSS, Google News, Tavily, Drewry WCI, Bigpara takvimi."""

import calendar
import html
import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import requests

from . import config

session = requests.Session()
session.headers["User-Agent"] = config.USER_AGENT


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def clean_text(s, limit=600):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def norm_title(t):
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(w for w in t.split() if len(w) > 2)


def _entry_time(e):
    for k in ("published_parsed", "updated_parsed"):
        if e.get(k):
            return datetime.fromtimestamp(calendar.timegm(e[k]), tz=timezone.utc)
    return None


def _parse_feed(url, source, region, since):
    try:
        r = session.get(url, timeout=25)
        r.raise_for_status()
    except Exception as ex:  # tek kaynak düşerse akış devam etsin
        log(f"  ! {source}: {ex}")
        return []
    feed = feedparser.parse(r.content)
    out = []
    for e in feed.entries:
        ts = _entry_time(e)
        if ts and ts < since:
            continue
        title = clean_text(e.get("title", ""), 300)
        src = source
        # Google News başlıkları "Başlık - Kaynak" biçiminde gelir
        if e.get("source") and e["source"].get("title"):
            src = e["source"]["title"]
            title = re.sub(r"\s+-\s+" + re.escape(src) + r"$", "", title)
        out.append({
            "title": title,
            "url": e.get("link", ""),
            "source": src,
            "published": ts.isoformat() if ts else None,
            "snippet": clean_text(e.get("summary", "")),
            "region": region,
        })
    return out


def fetch_rss(since):
    items = []
    for source, url, region in config.RSS_FEEDS:
        got = _parse_feed(url, source, region, since)
        log(f"  RSS {source}: {len(got)}")
        items += got
    return items


def fetch_gnews(queries, region, since, lang="tr", window="7d"):
    if lang == "tr":
        params = "hl=tr&gl=TR&ceid=TR:tr"
    else:
        params = "hl=en-US&gl=US&ceid=US:en"
    items = []
    for q in queries:
        url = f"https://news.google.com/rss/search?q={quote_plus(q + ' when:' + window)}&{params}"
        got = _parse_feed(url, "Google News", region, since)
        items += got[:25]
        time.sleep(1)
    log(f"  Google News ({region}): {len(items)}")
    return items


def tavily_search(query, topic="news", days=7, max_results=8):
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return []
    body = {"query": query, "max_results": max_results, "search_depth": "basic"}
    if topic == "news":
        body.update(topic="news", days=days)
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json=body,
            headers={"Authorization": f"Bearer {key}"},
            timeout=40,
        )
        r.raise_for_status()
    except Exception as ex:
        log(f"  ! Tavily '{query}': {ex}")
        return []
    out = []
    for x in r.json().get("results", []):
        host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*", r"\1", x.get("url", "")))
        out.append({
            "title": clean_text(x.get("title"), 300),
            "url": x.get("url"),
            "source": host,
            "published": x.get("published_date"),
            "snippet": clean_text(x.get("content"), 900),
        })
    return out


def fetch_tavily(queries, region, topic="news"):
    items = []
    for q in queries:
        for it in tavily_search(q, topic=topic):
            it["region"] = region
            items.append(it)
    if os.getenv("TAVILY_API_KEY"):
        log(f"  Tavily ({region}/{topic}): {len(items)}")
    return items


def dedupe(items):
    """Aynı başlığın kopyalarını ve aynı URL'leri ayıklar (anlamsal birleştirmeyi LLM yapar)."""
    seen_urls, seen_titles, out = set(), [], []
    for it in items:
        if not it.get("title") or it["url"] in seen_urls:
            continue
        nt = set(norm_title(it["title"]).split())
        dup = False
        for st in seen_titles:
            if nt and len(nt & st) / max(1, min(len(nt), len(st))) > 0.8:
                dup = True
                break
        if dup:
            continue
        seen_urls.add(it["url"])
        seen_titles.append(nt)
        out.append(it)
    return out


# --- Drewry WCI ------------------------------------------------------------

def _html_to_text(d):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", d, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t)


def fetch_drewry():
    r = session.get(config.DREWRY_URL, timeout=40)
    r.raise_for_status()
    d = r.text
    t = _html_to_text(d)
    start = t.find("Our detailed assessment for")
    end = t.find("Spot freight rates by major route", start)
    if start < 0:
        raise RuntimeError("Drewry sayfasında değerlendirme metni bulunamadı")
    body = t[start:end if end > 0 else start + 6000]
    body = re.sub(r"\n(?=[a-z,.;])|(?<=[’'a-z])\n", " ", body)  # link kırılmalarını birleştir
    body = re.sub(r"\s*\n\s*", "\n", body).strip()

    headline = ""
    m = re.search(r"\n(WCI [^\n]{10,200})\n", t)
    if m:
        headline = m.group(1).strip()

    assess_date = None
    m = re.search(r"assessment for \w+, (\d{1,2} \w{3,9} \d{4})", body)
    if m:
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                assess_date = datetime.strptime(m.group(1), fmt).date().isoformat()
                break
            except ValueError:
                pass

    composite = change_pct = None
    m = re.search(
        r"World Container Index \(WCI\).*?(increased|decreased|rose|fell|declined|dropped|grew|"
        r"remained|was stable|inched up|edged down|slipped|surged|jumped)\s*(?:by\s*)?(\d+(?:\.\d+)?)?%?"
        r"[^$]*\$([\d,]+(?:\.\d+)?) per 40ft",
        body, flags=re.S,
    )
    if m:
        composite = float(m.group(3).replace(",", ""))
        if m.group(2):
            sign = -1 if m.group(1) in ("decreased", "fell", "declined", "dropped", "edged down", "slipped") else 1
            change_pct = sign * float(m.group(2))
        elif m.group(1) in ("remained", "was stable"):
            change_pct = 0.0

    canva = [html.unescape(u) for u in re.findall(r'<iframe[^>]+src="(https://www\.canva\.com/design/[^"]+)"', d)]
    return {
        "source_url": config.DREWRY_URL,
        "headline": headline,
        "assessment_date": assess_date,
        "composite_usd_40ft": composite,
        "change_pct": change_pct,
        "text_en": body,
        "chart_embed_url": canva[0] if canva else None,
        "routes_embed_url": canva[1] if len(canva) > 1 else None,
    }


# --- Bigpara gelecek hafta takvimi -----------------------------------------

def next_week_days(today):
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    return [monday + timedelta(days=i) for i in range(6)]  # Pzt-Cmt


def fetch_bigpara(today):
    days = next_week_days(today)
    tr_tz = timezone(timedelta(hours=3))
    events = []
    for day in days:
        try:
            r = session.get(
                config.BIGPARA_API,
                params={"StartDate": day.isoformat(), "PageSize": 1000,
                        "OrderByColumn": "date", "OrderByDirection": "asc"},
                headers={"Referer": "https://bigpara.hurriyet.com.tr/",
                         "Origin": "https://bigpara.hurriyet.com.tr"},
                timeout=25,
            )
            r.raise_for_status()
            data = r.json().get("data") or []
        except Exception as ex:
            log(f"  ! Bigpara {day}: {ex}")
            continue
        for x in data:
            dt = datetime.fromtimestamp(x["ts"], tz=tr_tz)
            if dt.date() != day:
                continue
            events.append({
                "date": day.isoformat(),
                "time": dt.strftime("%H:%M"),
                "country": x.get("country"),
                "indicator": x.get("indicator"),
                "priority": int(x.get("priority") or 1),
                "previous": x.get("previous"),
                "consensus": x.get("consensus"),
            })
        time.sleep(0.5)
    log(f"  Bigpara: {len(events)} etkinlik ({days[0]} - {days[-1]})")
    return [d.isoformat() for d in days], events


TRADE_WORDS = re.compile(
    r"ithalat|ihracat|dış ticaret|ticaret dengesi|ticaret açığı|cari|PMI|GSYH|büyüme|"
    r"enflasyon|TÜFE|ÜFE|faiz|sanayi üretimi|rezerv|kapasite kullanım|güven endeksi|MKK",
    re.I,
)


def shortlist_calendar(events):
    """LLM'e gitmeden önce dış ticaretle ilgili/önemli olayları süzer."""
    keep = [e for e in events
            if e["country"] == "Türkiye" or TRADE_WORDS.search(e["indicator"] or "") or e["priority"] >= 3]
    keep.sort(key=lambda e: (e["date"], -e["priority"], e["time"]))
    return keep[:250]


def issue_number(d: date):
    anchor = date.fromisoformat(config.ISSUE_ANCHOR_DATE)
    return config.ISSUE_ANCHOR_NUMBER + (d - anchor).days // 7


# --- Ticaret Bakanlığı haberleri (birincil resmî kaynak) --------------------

TR_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
     "Eylül", "Ekim", "Kasım", "Aralık"])}


def ticaret_article(url):
    r = session.get(url, timeout=25)
    r.raise_for_status()
    d = r.text
    title = re.search(r'class="__header[^"]*">\s*<h2>(.*?)</h2>', d, flags=re.S)
    title = clean_text(title.group(1), 300) if title else ""
    title = re.sub(r"\s*\d{2}[.-]\d{2}[.-]\d{4}$", "", title)
    pub = None
    m = re.search(r"<span>(\d{1,2}) (\w+) (\d{4})</span>", d)
    if m and m.group(2) in TR_MONTHS:
        pub = datetime(int(m.group(3)), TR_MONTHS[m.group(2)], int(m.group(1)),
                       12, tzinfo=timezone(timedelta(hours=3)))
    i = d.find('class="__content"')
    j = d.find("foot-content", i)
    body = clean_text(d[d.find(">", i) + 1:j] if i > 0 else "", 4000)
    return title, pub, body


def tr_sentence_case(s):
    low = s.replace("I", "ı").replace("İ", "i").lower()
    return low[:1].replace("i", "İ").upper() + low[1:]


def fetch_ticaret(since, limit=20):
    base = "https://ticaret.gov.tr"
    try:
        r = session.get(base + "/haberler", timeout=25)
        r.raise_for_status()
    except Exception as ex:
        log(f"  ! Ticaret Bakanlığı: {ex}")
        return []
    links = list(dict.fromkeys(re.findall(r'href="(/haberler/[a-z0-9-]+)"', r.text)))[:limit]
    out = []
    for path in links:
        try:
            title, pub, body = ticaret_article(base + path)
        except Exception:
            continue
        if not title or (pub and pub < since):
            continue
        # Başlıklar çoğu zaman BÜYÜK HARF gelir
        out.append({"title": tr_sentence_case(title) if title.isupper() else title,
                    "url": base + path, "source": "T.C. Ticaret Bakanlığı",
                    "published": pub.isoformat() if pub else None,
                    "snippet": body[:900], "fulltext": body, "region": "tr"})
        time.sleep(0.3)
    log(f"  Ticaret Bakanlığı: {len(out)}")
    return out


# --- Google News bağlantısını gerçek haber URL'sine çevirme ------------------

_gn = requests.Session()
_gn.headers["User-Agent"] = config.USER_AGENT
_gn.cookies.set("CONSENT", "YES+cb", domain=".google.com")
_gn.cookies.set("SOCS", "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg", domain=".google.com")


def resolve_gnews(url):
    """news.google.com/rss/articles/... → kaynak URL. Başarısız olursa aynı URL döner."""
    m = re.search(r"news\.google\.com/rss/articles/([^?]+)", url or "")
    if not m:
        return url
    aid = m.group(1)
    try:
        r = _gn.get(f"https://news.google.com/rss/articles/{aid}", timeout=20)
        sg = re.search(r'data-n-a-sg="([^"]+)"', r.text)
        ts = re.search(r'data-n-a-ts="([^"]+)"', r.text)
        if not (sg and ts):
            return url
        req = ["Fbv4je",
               f'["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
               f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{aid}",{ts.group(1)},"{sg.group(1)}"]']
        r2 = _gn.post("https://news.google.com/_/DotsSplashUi/data/batchexecute",
                      data={"f.req": json.dumps([[req]])},
                      headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
                      timeout=20)
        return json.loads(json.loads(r2.text.split("\n\n")[1])[0][2])[1]
    except Exception:
        return url


def article_text(url, limit=3500):
    """Haber sayfasından düz metin çıkarır (en iyi çaba)."""
    if not url or "news.google.com" in url:
        return ""
    try:
        if "ticaret.gov.tr/haberler/" in url:
            return ticaret_article(url)[2][:limit]
        r = session.get(url, timeout=20)
        r.raise_for_status()
    except Exception:
        return ""
    paras = re.findall(r"<p[^>]*>(.*?)</p>", r.text, flags=re.S)
    text = " ".join(clean_text(p, 2000) for p in paras)
    return re.sub(r"\s+", " ", text)[:limit]
