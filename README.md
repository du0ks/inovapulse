# İnovaPulse: Haftalık Dış Ticaret Bülteni otomasyonu

Her hafta perşembeyi cumaya bağlayan gece bülten taslağını otomatik hazırlar ve web panelinde yayınlar
(cuma 00:17 TSİ; eksik kalan bölümler 04:47 ve 07:23'te yeniden denenir, taslak 10:00'dan önce hazırdır):

| # | Bölüm | Kaynak | Nasıl |
|---|-------|--------|-------|
| 1 | Drewry WCI (US$/40ft) | drewry.co.uk (perşembe verisi) | Sayfa metni çekilir, Türkçe 2 paragraf özet + hat tablosu, Drewry grafikleri panelde gömülü |
| 2 | Türkiye ihracat / ithalat | Ticaret Bakanlığı "<Ay> Ayı Dış Ticaret Verileri" haberi | Rakamlar doğrudan resmî metinden okunur (LLM yok); yıllık kutu `config.ANNUAL_EXPORTS_OVERRIDE` |
| 3 | Grafik haberleri (2) | Visual Capitalist RSS | Ekonomi/ticaret konulu iki infografik, görsel linki + Türkçe paragraf |
| 4 | Ücretsiz etkinlik | Ticaret Bakanlığı duyuruları ve TAGM müşavir toplantıları, UİB Akademi, İTO etkinlikleri, Tavily, Google News | Sayfalar açılır; yalnızca ileri tarihli, online, ücretsiz, tek bir etkinliğe ait (liste sayfası değil) olanlar seçilir. Link, okuyucu gibi tek denemede açılmalı; cuma sabahı tekrar denenir, açılmıyorsa başka etkinlik seçilir |
| 5 | Türkiye'deki gelişmeler (10) | Ticaret Bakanlığı, AA, Dünya, Ekonomim, Bloomberg HT, Foreks, TRT, Hürriyet, Google News, Tavily | Tekrarlar birleştirilir; her link açılıp içerik ve tarih kontrol edilir (abonelik duvarlı, kısa veya eski haberler elenir); aynı siteden en fazla 2 haber |
| 6 | Yurt dışı gelişmeler (10) | AA English, WTO, Google News (EN), Tavily | Aynı |
| 7 | Gelecek hafta | Bigpara ekonomik takvim API + resmî tatiller | Kodla seçilir: o gün Türkiye açıklaması varsa o, yoksa başka ülkenin dış ticaret açıklaması, o da yoksa en önemli makro veri. Metin ülke adıyla başlar; bayram günleri otomatik yazılır |

Kaynak ve anahtar kelimeler `pipeline/config.py`, editoryal kurallar `pipeline/prompts.py` içinde.

## PDF çıktısı

Paneldeki **PDF indir** bülteni Canva'daki iki sayfalık A4 düzeninde (`docs/sheet.js`, `docs/sheet.css`)
önizletir; **PDF olarak kaydet** tarayıcının yazdırma penceresini açar (Chrome/Edge, Hedef: "PDF olarak
kaydet"). Dosya adı `Inovakademi-Haftalik-Dis-Ticaret-Bulten-GG.AA.YYYY.pdf` olarak önerilir.

- Paneldeki tüm düzenlemeler PDF'e yansır. Metin kutulara sığmazsa yazı boyutu küçülür; yine sığmazsa
  önizlemede uyarı çıkar.
- WCI grafiği `docs/data/wci_history.json`'dan çizilir (geçmiş veri: `python -m scripts.backfill_wci`);
  istenirse panelden Drewry grafiği görsel olarak yüklenebilir.
- Podcast görseli panelden yüklenir, tarayıcıda saklanır ve değiştirilene kadar her hafta kullanılır.
- Logo: `docs/assets/globby-logo.png` (daha yüksek çözünürlüklü dosya ile değiştirilebilir).

## Mimari (ücretsiz)

```
GitHub Actions (cuma 00:17 TSİ + 2 yeniden deneme)
  └─ python -m pipeline.build
       ├─ toplayıcılar: RSS, Google News, Ticaret Bakanlığı, Drewry, Bigpara, (Tavily)
       ├─ LLM: OpenRouter ücretsiz / Claude / Gemini
       └─ docs/data/bulletins/YYYY-AA-GG.json  → repoya commit
  └─ GitHub Pages: docs/ = panel (düzenle, kopyala, yazdır)
  └─ (isteğe bağlı) e-posta bildirimi
```

## LLM seçenekleri

LLM haberleri toplamaz (bunu RSS/API yapar). Seçim, tekrar birleştirme, Türkçe özet, çeviri ve WCI metni için kullanılır.

| Seçenek | Secret | Maliyet |
|---------|--------|---------|
| **OpenRouter ücretsiz modeller (varsayılan)** | `OPENROUTER_API_KEY` | Ücretsiz (openrouter.ai → Keys). Ücretsiz katman günde 50 istek; sistem haftada ~8 kullanır. Modeller `OPENROUTER_MODELS` değişkeniyle değiştirilebilir |
| Claude aboneliği | `CLAUDE_CODE_OAUTH_TOKEN` | Claude Pro/Max aboneliği varsa ek ücret yok. Token: bir bilgisayarda `claude setup-token` |
| Claude API | `ANTHROPIC_API_KEY` | Kullandıkça öde, haftada yaklaşık 0,5 $ (Opus 5.5); `ANTHROPIC_MODEL` ile değiştirilebilir |
| Gemini | `GEMINI_API_KEY` | aistudio.google.com ücretsiz katman |

Birden fazla tanımlıysa sıra: OpenRouter → Anthropic API → Claude aboneliği → Gemini. Zorlamak için repo değişkeni `LLM_PROVIDER` = `claude-cli` / `anthropic` / `gemini`.

**Tavily** (`TAVILY_API_KEY`, tavily.com, ayda 1000 ücretsiz kredi; bu sistem ayda yaklaşık 60 kullanır): isteğe bağlı ama özellikle **etkinlik** bölümünün kalitesini çok artırır.

## Kurulum

1. Bu klasörü GitHub'a gönderin (ör. `inovakademi/inovapulse`).
2. **Settings → Secrets and variables → Actions**: yukarıdaki secret'lardan en az birini ekleyin (+ isteğe bağlı `TAVILY_API_KEY`).
3. **Settings → Pages → Source: GitHub Actions**.
4. **Actions → Haftalık bülten → Run workflow** ile ilk çalıştırma. Panel: `https://<kullanıcı>.github.io/<repo>/`
5. (İsteğe bağlı) E-posta bildirimi: değişken `NOTIFY_EMAIL`, secret `SMTP_USERNAME`, `SMTP_PASSWORD` (Gmail uygulama şifresi).

> GitHub Pages ücretsiz planda yalnızca **public** repoda çalışır. Panel herkese açık bir URL olur (arama motorlarına kapalı). Gizli olması gerekirse repo private yapılıp `docs/` klasörü Cloudflare Pages'e (ücretsiz, Access ile şifrelenebilir) veya şirket sunucusuna konabilir.

## Yerelde çalıştırma

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env                            # anahtarları yazın
.venv/bin/python -m pipeline.build              # bugünün bülteni
.venv/bin/python -m pipeline.build --no-llm     # sadece veri toplama
python3 -m http.server -d docs 8000             # panel: http://localhost:8000
```

## Şirket sunucusunda çalıştırma

GitHub yerine bir Linux sunucuda: repoyu klonlayın, crontab'a ekleyin ve `docs/` klasörünü nginx ile sunun:

```
15 9 * * 5  cd /opt/inovapulse && .venv/bin/python -m pipeline.build >> build.log 2>&1
```

## Panel

- Metinlere tıklayıp düzenleyin. Düzenlemeler tarayıcıda saklanır (kişiye özel).
- Haber kutucuğuyla çıkarın, ↑↓ ile sıralayın, yedeklerden "+" ile ekleyin.
- Bölüm bazında veya "Tümünü kopyala" ile Canva'ya yapıştırın; "Yazdır / PDF" sade bir çıktı verir.
- "Tüm aday haberler" bölümünde sistemin taradığı her şey aranabilir.
