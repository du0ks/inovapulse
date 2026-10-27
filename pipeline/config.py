"""Bülten kaynakları, arama sorguları ve ayarlar.

Bu dosya, e-postadaki "Haber Takip ve Keyword Haritası"nın koda dökülmüş hâlidir.
Kaynak / sorgu eklemek için sadece bu dosyayı düzenlemek yeterli.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"

# Bülten sayı numarası: 23.10.2026 = 213 (yayımlanmış bülten). Her hafta +1.
# Yayın atlanan bir hafta olursa buradaki tarih/numara son yayımlanan sayıya göre güncellenir.
ISSUE_ANCHOR_DATE = "2026-10-23"
ISSUE_ANCHOR_NUMBER = 213

LOOKBACK_DAYS = 7

# Bültendeki "<yıl> Türkiye İhracatı" kutusu. Ticaret Bakanlığı'nın aralık ayı öncü verisi otomatik
# okunur; kesinleşmiş (TÜİK nihai) rakam farklıysa buraya yazılır ve öncelikli kullanılır.
ANNUAL_EXPORTS_OVERRIDE = {2025: 275.844}

# Yerel çalıştırmada .env dosyasındaki anahtarları yükle (repoya eklenmez)
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# --- LLM ayarları ----------------------------------------------------------
# LLM_PROVIDER: "openrouter" (ücretsiz modeller), "claude-cli" (Claude aboneliği), "anthropic"
# (Claude API) veya "gemini". Boş bırakılırsa tanımlı anahtara göre otomatik seçilir.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "").strip().lower()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
# OpenRouter: sırayla denenir; yanıt geçersizse (bozuk JSON, Türkçe değil) sıradakine geçilir.
# Ücretsiz modeller zamanla değişebilir: openrouter.ai/models?q=free
OPENROUTER_MODELS = [m.strip() for m in (
    os.getenv("OPENROUTER_MODELS")
    or "google/gemma-4-31b-it:free,nvidia/nemotron-3.5-super-vl:free,"
       "nvidia/nemotron-3-super-120b-a12b:free,google/gemma-4-26b-a4b-it:free,"
       "nvidia/nemotron-3-ultra-550b-a55b:free"
).split(",") if m.strip()]
CLAUDE_CLI_MODEL = os.getenv("CLAUDE_CLI_MODEL", "claude-opus-5-5")
# Gemini: her modelin ayrı ücretsiz günlük kotası var; ilki dolarsa ikincisine geçilir
GEMINI_MODELS = [m.strip() for m in (
    os.getenv("GEMINI_MODELS") or "gemini-flash-latest,gemini-flash-lite-latest"
).split(",") if m.strip()]
# Aynı anda kaç LLM isteği (Gemini ücretsiz katmanında dakika limiti düşük, 1-2 önerilir)
LLM_PARALLEL = int(os.getenv("LLM_PARALLEL") or (2 if os.getenv("OPENROUTER_API_KEY") else 6))

# --- RSS kaynakları (anahtar gerektirmez) -----------------------------------
# (kaynak adı, url, bölge) bölge: "tr" | "intl"
RSS_FEEDS = [
    ("Anadolu Ajansı", "https://www.aa.com.tr/tr/rss/default?cat=ekonomi", "tr"),
    ("Dünya", "https://www.dunya.com/rss", "tr"),
    ("Ekonomim", "https://www.ekonomim.com/export/rss", "tr"),
    ("Bloomberg HT", "https://www.bloomberght.com/rss", "tr"),
    ("Foreks", "https://www.foreks.com/rss", "tr"),
    ("TRT Haber", "https://www.trthaber.com/ekonomi_articles.rss", "tr"),
    ("Hürriyet", "https://www.hurriyet.com.tr/rss/ekonomi", "tr"),
    ("Anadolu Agency", "https://www.aa.com.tr/en/rss/default?cat=economy", "intl"),
    ("WTO", "https://www.wto.org/library/rss/latest_news_e.xml", "intl"),
]

# --- Google News RSS sorguları (anahtar gerektirmez) ------------------------
GNEWS_TR = [
    '"Türkiye ihracat" OR "Türkiye\'nin ihracatı" OR "ihracat rakamları"',
    '"Türkiye ithalat" OR "ithalat rakamları" OR "ithalat düzenlemesi"',
    '"dış ticaret açığı" OR "dış ticaret verileri" OR "dış ticaret hacmi"',
    'Ticaret Bakanlığı ihracat OR ithalat OR gümrük',
    'TİM ihracat OR "ihracatçı birlikleri"',
    'gümrük vergisi OR "serbest ticaret anlaşması" OR "gümrük birliği"',
    'lojistik OR liman OR "konteyner navlun" OR "tedarik zinciri" Türkiye',
    '"ihracat anlaşması" OR "fabrika yatırımı" OR "kapasite artırımı" OR "yeni tesis"',
    'e-ihracat OR "sınırda karbon" OR "yeşil mutabakat" ihracatçı',
    'TCMB OR enflasyon OR "sanayi üretimi" OR "cari açık" OR PMI',
]
GNEWS_INTL = [
    '"trade deficit" OR "trade surplus" OR "exports rose" OR "exports fell"',
    'tariffs OR "customs duties" OR "trade agreement" OR "free trade agreement"',
    'USTR OR "Commerce Department" tariff',
    '"European Commission" trade OR CBAM OR "anti-dumping"',
    'China exports OR imports customs data',
    '"container freight" OR "ocean freight" OR "shipping rates" OR "Red Sea" shipping',
    '"global trade" OR "world trade" OR WTO OR UNCTAD',
    'Eurostat OR "euro area" trade balance',
    '"export deal" OR "factory investment" OR "international expansion"',
]

# --- Tavily sorguları (TAVILY_API_KEY varsa; ücretsiz 1000 kredi/ay) ---------
TAVILY_NEWS_TR = [
    "Türkiye ihracat ithalat dış ticaret bu hafta",
    "Ticaret Bakanlığı yeni düzenleme ihracatçı gümrük",
    "Türkiye sektör ihracatı rekor yatırım",
]
TAVILY_NEWS_INTL = [
    "global trade policy tariffs this week",
    "major economies exports imports data released this week",
    "container shipping freight rates news this week",
]
# {ay}: bülten ayı ve sonraki ay (ör. "Ekim 2026", "Kasım 2026")
TAVILY_EVENTS = [
    "ücretsiz online ihracat webinarı {ay}",
    "ücretsiz çevrim içi dış ticaret eğitimi {ay}",
    "ihracatçı birlikleri ticaret odası ücretsiz webinar {ay}",
]
TAVILY_TRADE_DATA = [
    "Ticaret Bakanlığı {ay} ayı dış ticaret verileri ihracat ithalat milyar dolar",
]

# Etkinlik araması için Google News sorguları
GNEWS_EVENTS = [
    '"ücretsiz" webinar ihracat OR "dış ticaret" OR e-ihracat',
    '"ücretsiz eğitim" ihracat OR "dış ticaret" OR gümrük',
    'online OR çevrimiçi eğitim ihracat "{ay}"',
]

# {ay} yerine bir önceki ayın adı yazılır (ör. "Eylül")
GNEWS_TRADE_DATA = [
    '"{ay} ayı" ihracat "milyar dolar"',
    '"{ay}" ihracat ithalat Bolat',
    '"dış ticaret açığı" "{ay}"',
]

# Genel RSS akışlarında (borsa, siyaset vb. de içerir) yalnızca bu kelimeleri içerenler aday olur
RELEVANCE_TR = (
    r"ihracat|ihracatç|ithalat|dış ticaret|ticaret açığı|gümrük|tarife|navlun|lojistik|liman|konteyner|"
    r"tedarik zinciri|serbest ticaret|ticaret anlaşma|Ticaret Bakan|TİM|TOBB|ihracatçı birli|e-ihracat|"
    r"yatırım|fabrika|tesis|kapasite|sanayi üretimi|PMI|enflasyon|cari|TCMB|faiz|büyüme|GSYH|kur|"
    r"sürdürülebil|karbon|yeşil|SKDM|Eximbank|KOSGEB|teşvik|destek|fuar|pazar|anlaşma|sipariş"
)
RELEVANCE_EN = (
    r"export|import|trade|tariff|customs|freight|shipping|port|container|supply chain|WTO|"
    r"duty|duties|sanction|investment|factory|manufactur|PMI|inflation|GDP|central bank|CBAM|deal"
)

# Kaynak güvenilirlik sırası (LLM'e ipucu olarak verilir)
SOURCE_PRIORITY = (
    "Resmî kurum (Ticaret Bakanlığı, TÜİK, TİM, TOBB, TCMB, Hazine, Sanayi Bak., KOSGEB) > "
    "uluslararası kuruluş (WTO, IMF, Dünya Bankası, OECD, UNCTAD, Eurostat, AB Komisyonu, ECB, "
    "US Census, USTR, Fed, ONS, BoE, Çin Gümrük/NBS/MOFCOM) > "
    "güvenilir ekonomi basını (AA, Reuters, Bloomberg HT, Dünya, Ekonomim, Foreks, CNBC-e, Ekonomist) > diğer"
)

DREWRY_URL = "https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry"
BIGPARA_API = "https://api-bigpara.hurriyet.com.tr/api/calendar/filter"
BIGPARA_PAGE = "https://bigpara.hurriyet.com.tr/haberler/gunluk-piyasa-takvimi/gelecek-hafta/"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)

# Grafik haberleri (bültendeki iki görselli haber) için kaynak
CHARTS_FEED = "https://www.visualcapitalist.com/feed/"
