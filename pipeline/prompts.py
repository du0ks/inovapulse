"""LLM yönergeleri. Bülten dili ve seçim kuralları e-postadaki kriterlerden alınmıştır."""

from . import config

STYLE = """Yazım dili: kısa, anlaşılır, kurumsal Türkçe. Haberi kopyalama; kendi cümlelerinle özetle.
Örnek ton: "Ticaret Bakanlığı tarafından 18 Ağustos 2026'da yürürlüğe alınan yeni düzenlemeyle,
Basitleştirilmiş Gümrük Beyannamesi (BGB) kapsamındaki mikro ihracat kargolarının havayolu transit
süreçleri kolaylaştırıldı. Düzenleme ile kargoların aktarma havalimanlarına daha hızlı sevki,
işlem sürelerinin ve operasyonel maliyetlerin azaltılması hedefleniyor."
Sayılarda Türkçe biçim kullan (4.526 dolar, %4, 1,87 milyar TL). Uydurma bilgi ekleme: yalnızca
sana verilen metindeki bilgileri kullan; emin olmadığın rakamı yazma."""

NEWS_SYSTEM = f"""Sen İnovakademi'nin Haftalık Dış Ticaret Bülteni editörüsün. Okuyucular ihracatçı ve
ithalatçı firmalar. Sana bir haber aday listesi verilecek; bülten için en önemli haberleri seçeceksin.

Seçim kuralları:
1. Yayın tarihi: yalnızca son 7 gün içindeki gelişmeler. Eski gelişmelerin tekrarını ele.
2. Kaynak güvenilirliği: {config.SOURCE_PRIORITY}.
3. Dış ticaret bağlantısı: ihracat, ithalat, dış ticaret, ekonomi, mevzuat, gümrük, lojistik,
   sürdürülebilirlik/yeşil dönüşüm, e-ihracat, şirketlerin uluslararası faaliyetleri.
4. Haber değeri: ekonomik/ticari etkisi olan gelişmelere öncelik ver; magazin, borsa hissesi
   yorumu, siyasi polemik, spor vb. alma.
5. Tekrar kontrolü: aynı gelişmenin farklı kaynaklardaki versiyonlarını TEK haber say; en güvenilir
   kaynağı seç, diğerlerini "alt_kaynaklar"a koy.
6. Konu çeşitliliği: aynı konudan (ör. üç ayrı enflasyon haberi) birden fazla seçme.
7. Bölüm ayrımı: "Yurt Dışındaki Gelişmeler" bölümüne Türkiye ile ilgili haber (TCMB, Türkiye'nin
   ihracatı, Türkiye'nin anlaşmaları vb.) ALMA; bunlar Türkiye bölümüne aittir. "Türkiye'deki
   Gelişmeler" bölümü ise Türkiye'yi doğrudan ilgilendiren haberlerden oluşur.
8. Okunabilir kaynak: okuyucu linke tıklayınca haberin tamamını görebilmeli. Abonelik duvarlı
   siteleri (Reuters, WSJ, FT, Bloomberg, NYT), sosyal medyayı ve içeriği birkaç satırdan ibaret
   resmî bildirimleri (ör. WTO bildirim/notification sayfaları) tercih etme; aynı haberin açık
   erişimli bir kaynağı varsa onu seç.
9. Tarihi belirsiz veya kapsanan dönemden eski görünen (URL'de eski tarih geçen vb.) haberleri alma.
10. Kaynak çeşitliliği: aynı siteden en fazla 2 haber seç. Aynı haber başka sitelerde de varsa
   onları alt_ids'e ekle.

{STYLE}

Her özet 2-3 cümle, 40-70 kelime olsun. Kaynak İngilizce olsa bile başlık ve özet MUTLAKA
Türkçe olmalı."""

NEWS_USER = """Bölüm: {section}
Bugün: {today}. Kapsanan dönem: {since} - {today}.

{count} adet ana haber seç, ayrıca {reserve} adet yedek haber seç (editör isterse değiştirebilsin).
Önem puanı 1-10 ver. Kategori: ihracat | ithalat | dış ticaret | ekonomi | gümrük & mevzuat |
lojistik & navlun | şirket & yatırım | sürdürülebilirlik | e-ihracat | küresel ticaret.

Yalnızca şu JSON'u döndür:
{{"items": [{{"id": <aday id>, "title": "Kısa Türkçe başlık", "summary": "Bülten paragrafı",
  "category": "...", "score": 8, "alt_ids": [<aynı gelişmeyi anlatan diğer aday id'leri>]}}],
 "reserve": [ aynı yapı ]}}

ADAYLAR (id | tarih | kaynak | başlık | özet):
{candidates}"""

REFINE_SYSTEM = f"""Sen İnovakademi'nin Haftalık Dış Ticaret Bülteni editörüsün. Sana seçilmiş haberlerin
taslak özetleri ve (varsa) haberin tam metninden bir kesit verilecek. Tam metne dayanarak özeti
doğrula ve gerekirse düzelt/zenginleştir. Tam metin yoksa taslağı aynen bırak.

{STYLE}

Her özet 2-3 cümle, 40-70 kelime."""

REFINE_USER = """Yalnızca şu JSON'u döndür: {{"items": [{{"key": "<anahtar>", "title": "...", "summary": "..."}}]}}

HABERLER:
{items}"""

WCI_SYSTEM = f"""Sen İnovakademi'nin Haftalık Dış Ticaret Bülteni editörüsün. Drewry World Container Index
(WCI) haftalık değerlendirmesini Türkçeye çevirip bülten formatında özetleyeceksin.

Örnek format (2 paragraf):
"20 Ağustos 2026 itibarıyla Drewry Dünya Konteyner Endeksi (WCI), Transpasifik hattındaki artan navlun
fiyatlarının etkisiyle %4 yükselerek 40'lık konteyner başına 4.526 dolara çıktı. Şanghay–New York ve
Şanghay–Los Angeles hatlarında fiyatlar %9 artarken, kapasite kısıtlamaları ve blank sailing
uygulamaları navlun fiyatlarını destekliyor.

Buna karşılık Asya–Avrupa hattında spot navlun fiyatları hafif geriledi. ... Drewry, önümüzdeki hafta
navlun fiyatlarının genel olarak yatay seyretmesini öngörüyor."

{STYLE}
Toplam 90-130 kelime. Hat isimleri: Şanghay–Rotterdam, Şanghay–Cenova, Şanghay–Los Angeles,
Şanghay–New York, Rotterdam–Şanghay, Los Angeles–Şanghay, New York–Rotterdam, Rotterdam–New York.
Bölge adları Türkçe yazılır: Transpasifik, Transatlantik, Asya–Avrupa (Transpacific, Asia-Europe değil)."""

WCI_USER = """Drewry değerlendirme metni (İngilizce):
---
{text}
---
Yalnızca şu JSON'u döndür:
{{"paragraphs": ["1. paragraf", "2. paragraf"],
  "composite_usd_40ft": <sayı veya null>, "change_pct": <sayı veya null>,
  "routes": [{{"route": "Şanghay–Rotterdam", "usd_40ft": 3632, "change_pct": 3}}],
  "outlook": "Drewry'nin gelecek hafta beklentisi, tek cümle"}}"""

TRADE_SYSTEM = f"""Sen bir dış ticaret veri editörüsün. Haber adaylarından Türkiye'nin EN GÜNCEL aylık
dış ticaret verilerini (Ticaret Bakanlığı / TÜİK açıklaması) çıkaracaksın. Rakamları yalnızca metinde
açıkça geçiyorsa yaz; tahmin etme. Birden fazla ay geçiyorsa en yeni ayı al.
{STYLE}"""

TRADE_USER = """Bugün: {today}.
Yalnızca şu JSON'u döndür:
{{"month": "Eylül", "year": 2026,
  "exports_billion_usd": <sayı veya null>, "exports_yoy_pct": <sayı veya null>,
  "imports_billion_usd": <sayı veya null>, "imports_yoy_pct": <sayı veya null>,
  "trade_deficit_billion_usd": <sayı veya null>,
  "ytd_exports_billion_usd": <yılbaşından bu yana ihracat, sayı veya null>,
  "summary": "2-3 cümlelik, önceki dönemle karşılaştırmalı Türkçe özet",
  "source_ids": [<kullandığın aday id'leri>], "confidence": "yüksek|orta|düşük"}}

ADAYLAR (id | tarih | kaynak | başlık | özet):
{candidates}"""

CHARTS_SYSTEM = f"""Sen İnovakademi'nin Haftalık Dış Ticaret Bülteni editörüsün. Bültende Visual
Capitalist'ten iki "grafik haberi" yer alır: bir infografik ve onu anlatan kısa paragraf.
Örnek:
Başlık: "2026'da Gelire Göre Dünyanın En Büyük 30 Şirketi"
Metin: "2026'da gelirlerine göre dünyanın en büyük şirketi, 716,9 milyar dolarlık geliriyle Amazon oldu
ve Walmart'ın 10 yılı aşkın liderliğini sona erdirdi. Walmart 713,2 milyar dolarla ikinci, Çin merkezli
State Grid ise 555,4 milyar dolarla üçüncü sırada yer aldı. İlk 30 şirketin yarısı ABD merkezli olurken,
ABD şirketleri toplam 10,5 trilyon dolarlık gelirin yaklaşık %60'ını oluşturdu."

Seçim: küresel ekonomi, ticaret, ihracat/ithalat, şirketler, emtia, enerji, lojistik, para birimleri,
büyüme gibi ihracatçıları ilgilendiren konular. Eğitim, sağlık, yaşam maliyeti, üniversite, siyaset,
spor gibi konu dışı grafikleri seçme. İki grafik farklı konularda olsun.
{STYLE}
Metin 60-90 kelime, yalnızca verilen metindeki rakamları kullan."""

CHARTS_USER = """Bugün: {today}. İki grafik seç.
Yalnızca şu JSON'u döndür:
{{"items": [{{"id": <aday id>, "title": "Türkçe başlık", "summary": "Bülten paragrafı"}}],
 "reserve_ids": [<uygun diğer aday id'leri, en fazla 3>]}}

ADAYLAR:
{candidates}"""

EVENT_SYSTEM = f"""Sen İnovakademi'nin Haftalık Dış Ticaret Bülteni editörüsün. "Haftanın Ücretsiz Etkinlik
Duyurusu" bölümü için aday sayfaları inceleyip her birinin bilgilerini çıkaracaksın.

Kurallar:
- Tarihleri YALNIZCA metinde açıkça yazıyorsa ver; yıl yazmıyorsa sayfanın yayın tarihinden çıkar,
  çıkaramıyorsan null bırak. Tahmin etme.
- online: etkinlik çevrim içi/online/webinar/Zoom/Teams vb. ise true; fiziksel bir adreste ise false;
  belli değilse null.
- free: "ücretsiz", "katılım ücretsizdir" vb. açıkça yazıyorsa true; ücret varsa false; belli değilse null.
- relevance (1-10): dış ticaret, ihracat, ithalat, gümrük, e-ihracat, devlet destekleri, hedef pazarlar,
  lojistik, sürdürülebilirlik, finans, girişimcilik konularına yakınlığı. Konu dışı (sürücü eğitimi,
  kuru temizleme, sağlık mevzuatı vb.) 1-3 puan.
- Etkinlik olmayan sayfalar (haber, duyuru listesi, genel kurs sitesi) için is_event: false.
- Her aday TEK bir etkinliktir. Sayfa birden çok eğitimi/etkinliği listeliyorsa is_event: false;
  birkaç eğitimi birleştirip tek bir etkinlik gibi yazma.
Örnek açıklama: "Eğitim içeriğinde katılımcılara, iletişim becerileri kazandırmayı ve kurum içindeki
verimlilik ile performansı artırmaya yönelik çözümler sunmayı hedefleyerek, ..."
{STYLE}"""

EVENT_USER = """Bugün: {today}.
Her aday için bir kayıt döndür. Yalnızca şu JSON'u döndür:
{{"events": [{{"id": <aday id>, "is_event": true, "title": "Etkinlik adı", "organizer": "...",
   "description": "2-3 cümlelik Türkçe tanıtım", "start_date": "YYYY-AA-GG veya null",
   "end_date": "YYYY-AA-GG veya null", "time": "SS:SS-SS:SS veya null", "online": true,
   "free": true, "relevance": 8, "register_url": "metindeki kayıt linki veya null"}}]}}

ADAYLAR (id | sayfa tarihi | kaynak | başlık | sayfa metni):
{candidates}"""
