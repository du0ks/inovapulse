"""Haftalık bülten taslağını üretir ve docs/data/ altına JSON olarak yazar.

Kullanım:  python -m pipeline.build [--date 2026-10-23] [--no-llm]
"""

import argparse
import json
import re
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from . import config, llm, prompts
from .sources import (
    dedupe, fetch_bigpara, fetch_drewry, fetch_gnews, fetch_rss, fetch_tavily, fetch_ticaret,
    issue_number, log, shortlist_calendar, article_text, resolve_gnews,
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
    out = llm.ask_json(
        prompts.NEWS_SYSTEM,
        prompts.NEWS_USER.format(
            section=section, today=today, since=since, count=count, reserve=reserve,
            candidates=fmt_candidates(candidates),
        ),
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
            "also_reported_by": [{"source": a["source"], "url": a["url"]} for a in alts if a],
        }

    items = [r for r in map(resolve, out.get("items", [])) if r]
    res = [r for r in map(resolve, out.get("reserve", [])) if r]
    return {"items": items, "reserve": res}


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
    out = llm.ask_json(prompts.REFINE_SYSTEM, prompts.REFINE_USER.format(items="\n\n".join(blocks)))
    for x in out.get("items", []):
        it = refs.get(x.get("key"))
        if it and x.get("summary"):
            it["summary"] = x["summary"]
            it["title"] = x.get("title") or it["title"]


def build_wci(raw):
    out = llm.ask_json(prompts.WCI_SYSTEM, prompts.WCI_USER.format(text=raw["text_en"]), max_tokens=4000)
    return {
        **raw,
        "paragraphs": out.get("paragraphs", []),
        "routes": out.get("routes", []),
        "outlook": out.get("outlook"),
        "composite_usd_40ft": raw["composite_usd_40ft"] or out.get("composite_usd_40ft"),
        "change_pct": raw["change_pct"] if raw["change_pct"] is not None else out.get("change_pct"),
    }


def build_trade(candidates, today):
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
        max_tokens=3000,
    )
    srcs = [pick(candidates, i) for i in out.pop("source_ids", []) or []]
    out["sources"] = [{"title": s["title"], "source": s["source"], "url": s["url"]} for s in srcs if s]
    out["official_url"] = "https://ticaret.gov.tr/istatistikler/dis-ticaret-istatistikleri"
    return out


def build_event(candidates, today):
    out = llm.ask_json(
        prompts.EVENT_SYSTEM,
        prompts.EVENT_USER.format(today=today, candidates=fmt_candidates(candidates, 600)),
        max_tokens=4000,
    )

    def resolve(x):
        if not x:
            return None
        c = pick(candidates, x.get("id")) or {}
        x["source_url"] = resolve_gnews(c.get("url"))
        x["source"] = c.get("source")
        x["register_url"] = x.get("register_url") or x["source_url"]
        return x

    return {"selected": resolve(out.get("selected")),
            "alternatives": [a for a in map(resolve, out.get("alternatives", [])) if a]}


def build_calendar(days, events):
    short = shortlist_calendar(events)
    lines = "\n".join(
        f"{e['date']} | {e['time']} | {e['country']} | {e['indicator']} | {e['priority']} | "
        f"{e['previous'] or '-'} | {e['consensus'] or '-'}" for e in short
    )
    out = llm.ask_json(prompts.CAL_SYSTEM, prompts.CAL_USER.format(days=", ".join(days), events=lines),
                       max_tokens=3000)
    for d in out.get("days", []):
        try:
            d["weekday"] = WEEKDAYS[date.fromisoformat(d["date"]).weekday()]
            d["date_tr"] = tr_date(date.fromisoformat(d["date"]))
        except (KeyError, ValueError):
            pass
    return out


# --- Ana akış --------------------------------------------------------------

def run(today: date, use_llm=True):
    since_dt = datetime.combine(today - timedelta(days=config.LOOKBACK_DAYS), datetime.min.time(), TR_TZ)
    warnings = []
    bulletin = {
        "date": today.isoformat(),
        "date_tr": tr_date(today),
        "issue": f"{today.year} / {issue_number(today)}",
        "generated_at": datetime.now(TR_TZ).isoformat(timespec="seconds"),
        "llm": None,
        "annual_exports_card": {"label": "2025 Türkiye İhracatı", "value": "275.844 Milyar $"},
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
    prev_month = MONTHS[(today.replace(day=1) - timedelta(days=1)).month - 1]
    event_c = dedupe(
        fetch_tavily(config.TAVILY_EVENTS, "tr", topic="general")
        + fetch_gnews(config.GNEWS_EVENTS, "tr", since_dt - timedelta(days=21), "tr", "30d")
    )
    trade_c = dedupe(
        fetch_tavily([q.format(ay=prev_month) for q in config.TAVILY_TRADE_DATA], "tr")
        + fetch_gnews([q.format(ay=prev_month) for q in config.GNEWS_TRADE_DATA], "tr",
                      since_dt - timedelta(days=30), "tr", "30d")
    )
    log(f"Adaylar: TR {len(tr_c)}, yurt dışı {len(intl_c)}, etkinlik {len(event_c)}, veri {len(trade_c)}")

    log("Drewry WCI çekiliyor...")
    wci_raw = step("Drewry WCI", fetch_drewry)
    log("Bigpara gelecek hafta takvimi çekiliyor...")
    cal = step("Bigpara takvim", lambda: fetch_bigpara(today)) or ([], [])

    bulletin["candidates"] = {"tr": tr_c, "intl": intl_c, "events": event_c, "trade": trade_c}
    bulletin["wci"] = wci_raw
    bulletin["calendar_raw"] = shortlist_calendar(cal[1])

    if use_llm and llm.provider():
        bulletin["llm"] = f"{llm.provider()}:{llm.model_name()}"
        since_s = (today - timedelta(days=config.LOOKBACK_DAYS)).isoformat()
        log(f"LLM ({bulletin['llm']}) ile bölümler hazırlanıyor (paralel)...")
        jobs = {
            "tr_news": ("Türkiye haberleri",
                        lambda: build_news("Türkiye'deki Gelişmeler", tr_c, 10, 6, today, since_s)),
            "intl_news": ("Yurt dışı haberleri",
                          lambda: build_news("Yurt Dışındaki Gelişmeler", intl_c, 10, 6, today, since_s)),
            "trade_data": ("Dış ticaret verisi", lambda: build_trade(trade_c, today)),
            "event": ("Etkinlik", lambda: build_event(event_c, today)),
        }
        if wci_raw:
            jobs["wci"] = ("WCI özeti", lambda: build_wci(wci_raw))
        if cal[1]:
            jobs["next_week"] = ("Gelecek hafta", lambda: build_calendar(*cal))
        with ThreadPoolExecutor(max_workers=config.LLM_PARALLEL) as ex:
            futs = {k: ex.submit(step, name, fn) for k, (name, fn) in jobs.items()}
            for k, f in futs.items():
                res = f.result()
                if res is not None or k != "wci":
                    bulletin[k] = res
                log(f"  ✓ {jobs[k][0]}" if res is not None else f"  ✗ {jobs[k][0]}")
        secs = {k: bulletin[k] for k in ("tr_news", "intl_news") if bulletin.get(k)}
        if secs:
            log("Seçilen haberlerin tam metinleri ile özetler doğrulanıyor...")
            with ThreadPoolExecutor(max_workers=2) as ex:
                for k, sec in secs.items():
                    ex.submit(step, f"Özet doğrulama ({k})", lambda k=k, sec=sec: refine_news({k: sec}))
    else:
        warnings.append("LLM anahtarı tanımlı değil: yalnızca ham adaylar üretildi.")

    for sec in ("tr_news", "intl_news"):
        for it in (bulletin.get(sec) or {}).get("items", []) + (bulletin.get(sec) or {}).get("reserve", []):
            it.pop("fulltext", None)
    for lst in bulletin["candidates"].values():
        for c in lst:
            c.pop("fulltext", None)
    bulletin["warnings"] = warnings
    save(bulletin)
    return bulletin


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
    a = ap.parse_args()
    today = date.fromisoformat(a.date) if a.date else datetime.now(TR_TZ).date()
    b = run(today, use_llm=not a.no_llm)
    if b["warnings"]:
        log("Uyarılar:\n  - " + "\n  - ".join(b["warnings"]))


if __name__ == "__main__":
    main()
