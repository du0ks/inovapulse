"""Hattın yedek davranışları (ağ kapalı, sahte kaynaklarla): python -m unittest tests.test_pipeline"""

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from pipeline import build, config

TODAY = date(2026, 11, 13)  # cuma
TR_TZ = timezone(timedelta(hours=3))
SUMMARY = ("Ticaret Bakanlığı, ihracatçı firmalar için yeni destek paketini açıkladı. "
           "Düzenleme kapsamında lojistik ve fuar giderleri için ayrılan kaynak artırıldı.")
LONG_SUMMARY = " ".join([SUMMARY] * 5)
DAYS = [(date(2026, 11, 16) + timedelta(days=i)).isoformat() for i in range(6)]


WORDS = ["otomotiv", "tekstil", "gümrük", "lojistik", "tarım", "enerji", "çelik", "kimya", "savunma", "mobilya",
         "denizcilik", "turizm", "madencilik", "yazılım", "ilaç", "gıda", "makine", "cam", "kağıt", "deri",
         "elektronik", "plastik", "seramik", "hazırgiyim", "fındık", "zeytin", "balıkçılık", "yat", "demir", "kablo"]


def cand(i, region="tr"):
    w = WORDS[i % len(WORDS)]
    return {"title": f"{w} sektöründe {w} ihracatı {w} rekoru {i}", "source": f"Kaynak{i}", "url": f"https://site{i}.com/haber",
            "published": "2026-11-12", "snippet": "özet", "region": region}


def chart_cand(i):
    return {"title": f"Chart {i}", "url": f"https://vc.com/{i}", "image": f"https://vc.com/{i}.png", "source": "VC",
            "published": "2026-11-12", "tags": [], "text": "text"}


WCI_RAW = {"composite_usd_40ft": 4400.0, "change_pct": 1.0, "assessment_date": "2026-11-12", "text_en": "x",
           "source_url": "https://drewry.co.uk"}
TRADE_RAW = {"month": "Ekim", "year": 2026, "url": "https://ticaret.gov.tr/x", "published": "2026-11-03",
             "monthly": {"exports": {"billion_usd": 25.0, "yoy_pct": 3.0}, "imports": {"billion_usd": 30.0, "yoy_pct": 1.0}},
             "ytd": {"exports": {"billion_usd": 230.0, "yoy_pct": 2.0}}}
EVENT_LLM = {"id": 0, "is_event": True, "title": "Türkiye Eğitimi", "description": "Ücretsiz çevrim içi eğitim.",
             "start_date": "2026-11-20", "end_date": None, "time": "14:00", "online": True, "free": True, "relevance": 8}


def fake_llm(system, user, max_tokens=16000, check=None):
    if system == build.prompts.WCI_SYSTEM:
        return {"paragraphs": ["12 Kasım itibarıyla endeks yükseldi."], "routes": []}
    if system == build.prompts.CHARTS_SYSTEM:
        return {"items": [{"id": 0, "title": "Grafik bir", "summary": SUMMARY}, {"id": 1, "title": "Grafik iki", "summary": SUMMARY}]}
    if system == build.prompts.EVENT_SYSTEM:
        return {"events": [EVENT_LLM]}
    if system == build.prompts.REFINE_SYSTEM:
        return {"items": []}
    if system.startswith("Sen İnovakademi") and "kısalt" in system:
        raise RuntimeError("kısaltma yok")
    return {"items": [{"id": i, "title": f"Başlık {i}", "summary": SUMMARY, "alt_ids": []} for i in range(10)], "reserve": []}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "bulletins").mkdir()
        tr, intl = [cand(i) for i in range(12)], [cand(i + 20, "intl") for i in range(12)]
        self.src = {
            "fetch_rss": mock.Mock(return_value=[]), "fetch_ticaret": mock.Mock(return_value=tr),
            "fetch_tavily": mock.Mock(side_effect=lambda q, region, **k: intl if region == "intl" else []),
            "fetch_gnews": mock.Mock(return_value=[]), "fetch_event_listings": mock.Mock(return_value=[cand(50)]),
            "fetch_trade_official": mock.Mock(return_value=TRADE_RAW),
            "fetch_charts": mock.Mock(side_effect=lambda *a, **k: [chart_cand(i) for i in range(3)]),
            "fetch_drewry": mock.Mock(return_value=dict(WCI_RAW)),
            "fetch_bigpara": mock.Mock(return_value=(DAYS, [{"date": DAYS[0], "time": "10:00", "country": "Türkiye",
                                                             "indicator": "Sanayi Üretimi", "priority": 3}], [])),
        }
        patches = [mock.patch.object(build, k, v) for k, v in self.src.items()] + [
            mock.patch.object(config, "DATA_DIR", self.dir),
            mock.patch.object(config, "ROOT", self.dir),
            mock.patch.object(config, "LLM_PARALLEL", 1),
            mock.patch.object(build.llm, "provider", return_value="gemini"),
            mock.patch.object(build.llm, "model_name", return_value="m"),
            mock.patch.object(build.llm, "ask_json", side_effect=fake_llm),
            mock.patch.object(build, "article_info", return_value={"text": "Türkiye metin. " * 200, "date": "2026-11-12"}),
            mock.patch.object(build, "article_text", return_value=""),
            mock.patch.object(build, "page_text", return_value=""),
            mock.patch.object(build, "register_link", return_value=None),
            mock.patch.object(build, "resolve_gnews", side_effect=lambda u: u),
            mock.patch.object(build, "reader_check", return_value=(True, None)),
            mock.patch.object(build, "vc_main_image", return_value=None),
            mock.patch.object(build, "tr_holidays", return_value={}),
            mock.patch.object(build, "issue_number", return_value=216),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_bulletin(self, **kw):
        return build.run(TODAY, **kw)

    def write_prev(self, **fields):
        b = {"date": "2026-11-06", **fields}
        (self.dir / "bulletins" / "2026-11-06.json").write_text(json.dumps(b))


class SourceFailures(Base):
    def test_normal(self):
        b = self.run_bulletin()
        self.assertEqual(len(b["tr_news"]["items"]), 10)
        self.assertEqual(len(b["next_week"]["days"]), 6)
        self.assertEqual(b["notices"], {})

    def test_each_source_failure_keeps_running(self):
        for key in self.src:
            with self.subTest(key):
                old = self.src[key].side_effect, self.src[key].return_value
                self.src[key].side_effect = RuntimeError("kaynak düştü")
                b = self.run_bulletin()
                self.assertIsNotNone(b, key)
                self.assertTrue(any(w for w in b["warnings"]), key)
                self.src[key].side_effect, self.src[key].return_value = old

    def test_bigpara_down_marks_every_day(self):
        self.src["fetch_bigpara"].side_effect = RuntimeError("yok")
        b = self.run_bulletin()
        self.assertEqual([d["date"] for d in b["next_week"]["days"]], DAYS)
        self.assertTrue(all(d["unavailable"] and d["text"] == build.NO_RELEASE for d in b["next_week"]["days"]))
        self.assertNotIn("next_week", build.complete_sections(b, TODAY))

    def test_saturday_with_only_minor_data_is_filled(self):
        self.src["fetch_bigpara"].return_value = (DAYS, [{"date": DAYS[5], "time": "03:00", "country": "Çin",
                                                          "indicator": "Fiyat Açıklaması", "priority": 1}], [])
        b = self.run_bulletin()
        self.assertEqual(b["next_week"]["days"][5]["text"], "Çin Fiyat Açıklaması açıklanacak.")
        self.assertEqual(b["next_week"]["days"][4]["text"], build.NO_RELEASE)

    def test_llm_down_uses_fallbacks(self):
        build.llm.ask_json.side_effect = RuntimeError("Hiçbir model")
        b = self.run_bulletin()
        self.assertTrue(b["tr_news"]["items"], "modelsiz özet")
        self.assertIn("tr_news", b["notices"])
        self.assertTrue(b["wci"]["paragraphs"][0].startswith("12 Kasım 2026"))
        self.assertIsNone(b["event"]["selected"])
        self.assertIn("url", b["event"]["fallback"])
        self.assertTrue(all(len(x["summary"]) <= build.NEWS_ITEM_MAX or "." not in x["summary"][:-1]
                            for x in b["tr_news"]["items"]))

    def test_carry_forward_trade_wci_event(self):
        self.write_prev(
            trade_data={"month": "Eylül", "exports_billion_usd": 20.0, "imports_billion_usd": 25.0},
            annual_exports_card={"label": "2025 Türkiye İhracatı", "value": "275.844 Milyar $"},
            wci={"paragraphs": ["Eski."], "assessment_date": "2026-11-05", "composite_usd_40ft": 4300.0},
            event={"selected": {"title": "Eski etkinlik", "end_date": "2026-12-01", "register_url": "https://x.gov.tr"}})
        self.src["fetch_trade_official"].side_effect = RuntimeError("yok")
        self.src["fetch_drewry"].side_effect = RuntimeError("yok")
        build.llm.ask_json.side_effect = lambda s, *a, **k: (_ for _ in ()).throw(RuntimeError("yok")) \
            if s in (build.prompts.TRADE_SYSTEM, build.prompts.EVENT_SYSTEM) else fake_llm(s, *a, **k)
        b = self.run_bulletin()
        self.assertEqual(b["trade_data"]["month"], "Eylül")
        self.assertEqual(b["annual_exports_card"]["value"], "275.844 Milyar $")
        self.assertEqual(b["wci"]["paragraphs"], ["Eski."])
        self.assertEqual(b["event"]["selected"]["title"], "Eski etkinlik")
        self.assertTrue({"trade_data", "wci", "event"} <= set(b["notices"]))

    def test_suspect_wci_ignored_and_not_in_history(self):
        (self.dir / "wci_history.json").write_text(json.dumps([{"date": "2026-11-05", "composite": 4300.0}]))
        self.src["fetch_drewry"].return_value = {**WCI_RAW, "composite_usd_40ft": 7893.0}
        b = self.run_bulletin()
        self.assertIn("wci_suspect", b["notices"])
        hist = json.loads((self.dir / "wci_history.json").read_text())
        self.assertNotIn(7893.0, [x["composite"] for x in hist])

    def test_bad_trade_numbers_ignored(self):
        self.src["fetch_trade_official"].return_value = {**TRADE_RAW, "monthly": {"exports": {"billion_usd": 500.0}}}
        self.write_prev(trade_data={"month": "Eylül", "exports_billion_usd": 20.0, "imports_billion_usd": 25.0})
        build.llm.ask_json.side_effect = lambda s, *a, **k: (_ for _ in ()).throw(RuntimeError("yok")) \
            if s == build.prompts.TRADE_SYSTEM else fake_llm(s, *a, **k)
        self.assertEqual(self.run_bulletin()["trade_data"]["month"], "Eylül")

    def test_charts_skip_last_weeks_and_widen(self):
        self.write_prev(charts={"items": [{"url": "https://vc.com/0"}, {"url": "https://vc.com/1"}]})
        calls = []
        self.src["fetch_charts"].side_effect = lambda *a, **k: calls.append(k) or [chart_cand(i) for i in (0, 1, 2, 3)][:2 if not k else 4]
        b = self.run_bulletin()
        self.assertEqual(calls[-1].get("pages"), 5)
        self.assertEqual({c["url"] for c in b["charts"]["items"]}, {"https://vc.com/2", "https://vc.com/3"})

    def test_few_news_lowers_threshold_then_continues(self):
        short = {"text": "Türkiye metin. " * 50, "date": "2026-11-12"}  # 750 karakter: yalnızca gevşek eşikte geçer
        with mock.patch.object(build, "article_info", return_value=short):
            b = self.run_bulletin()
        self.assertEqual(len(b["tr_news"]["items"]), 10)


class Budget(Base):
    def test_trim_never_cuts_mid_sentence(self):
        out = build.trim_sentences(LONG_SUMMARY, build.NEWS_ITEM_MAX)
        self.assertLessEqual(len(out), build.NEWS_ITEM_MAX)
        self.assertTrue(out.endswith("."))
        self.assertTrue(LONG_SUMMARY.startswith(out))

    def test_long_summaries_shortened_keeping_selection(self):
        old = self.run_bulletin()
        for k in ("tr_news", "intl_news"):
            for x in old[k]["items"]:
                x["summary"] = LONG_SUMMARY
        urls = [x["url"] for x in old["tr_news"]["items"]]
        path = self.dir / "bulletins" / f"{TODAY}.json"
        path.write_text(json.dumps(old))
        b = build.run(TODAY, fill_missing=True)
        self.assertEqual([x["url"] for x in b["tr_news"]["items"]], urls)
        self.assertTrue(all(len(x["summary"]) <= build.NEWS_ITEM_MAX for x in b["tr_news"]["items"]))


class Timing(Base):
    def test_scheduled_date_is_friday(self):
        self.assertEqual(build.scheduled_date(datetime(2026, 11, 13, 0, 17, tzinfo=TR_TZ)), TODAY)
        self.assertEqual(build.scheduled_date(datetime(2026, 11, 14, 1, 0, tzinfo=TR_TZ)), TODAY)

    def test_is_late(self):
        self.assertFalse(build.is_late(datetime(2026, 11, 13, 10, 59, tzinfo=TR_TZ), TODAY))
        self.assertTrue(build.is_late(datetime(2026, 11, 13, 11, 0, tzinfo=TR_TZ), TODAY))

    def test_late_run_does_not_touch_content(self):
        old = self.run_bulletin()
        old["tr_news"]["items"][0]["summary"] = LONG_SUMMARY
        old["event"]["selected"]["register_url"] = "https://acilmayan.gov.tr"
        path = self.dir / "bulletins" / f"{TODAY}.json"
        path.write_text(json.dumps(old))
        with mock.patch.object(build, "reader_check", return_value=(False, "kapalı")):
            self.assertIsNone(build.run(TODAY, fill_missing=True, late=True))
        self.assertEqual(json.loads(path.read_text()), old)

    def test_late_run_fills_only_empty_section(self):
        old = self.run_bulletin()
        tr = old["tr_news"]
        old["charts"] = None
        path = self.dir / "bulletins" / f"{TODAY}.json"
        path.write_text(json.dumps(old))
        b = build.run(TODAY, fill_missing=True, late=True)
        self.assertTrue(b["charts"]["items"])
        self.assertEqual(b["tr_news"], tr)


if __name__ == "__main__":
    unittest.main()
