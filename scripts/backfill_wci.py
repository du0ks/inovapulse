"""Bir kerelik: Drewry WCI sayfasının Wayback Machine arşivinden son ~1 yılın haftalık bileşik
endeks değerlerini toplayıp docs/data/wci_history.json'a ekler (PDF'teki WCI grafiği için).

Kullanım:  python -m scripts.backfill_wci [--since 20251001]
"""

import argparse
import json
import time

from pipeline import config
from pipeline.sources import log, parse_drewry, session


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="20251001")
    a = ap.parse_args()
    cdx = session.get("https://web.archive.org/cdx/search/cdx", params={
        "url": config.DREWRY_URL.split("://")[1], "from": a.since, "output": "json",
        "filter": "statuscode:200", "collapse": "timestamp:8", "fl": "timestamp"}, timeout=60).json()
    path = config.DATA_DIR / "wci_history.json"
    hist = {x["date"]: x for x in (json.loads(path.read_text()) if path.exists() else [])}
    for (ts,) in cdx[1:]:
        try:
            for wait in (0, 20, 60, 120):  # arşiv sık isteklerde 429 döner
                time.sleep(wait)
                r = session.get(f"https://web.archive.org/web/{ts}id_/{config.DREWRY_URL}", timeout=60)
                if r.status_code != 429:
                    break
            w = parse_drewry(r.text)
        except Exception as ex:
            log(f"  ! {ts}: {ex}")
            continue
        if w["assessment_date"] and w["composite_usd_40ft"] and w["assessment_date"] not in hist:
            hist[w["assessment_date"]] = {"date": w["assessment_date"], "composite": w["composite_usd_40ft"],
                                          "change_pct": w["change_pct"], "routes": []}
            log(f"  {w['assessment_date']}: {w['composite_usd_40ft']}")
        time.sleep(5)
    out = sorted(hist.values(), key=lambda x: x["date"])
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    log(f"Toplam {len(out)} hafta")


if __name__ == "__main__":
    main()
