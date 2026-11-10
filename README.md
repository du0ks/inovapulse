# İnovaPulse

A weekly pipeline that drafts İnovakademi's foreign-trade bulletin (in Turkish) from public sources, plus a web panel where editors review the draft and export it as a PDF.

Panel: https://du0ks.github.io/inovapulse/

## The problem

İnovakademi sends exporters a weekly foreign-trade bulletin: container freight rates, Turkey's export/import figures, two infographic stories, a free training event, ten Turkish and ten international news items, and next week's economic calendar. Collecting all of that by hand means going through a dozen sites every week. This project prepares the draft overnight so that on Friday morning an editor only has to check it, fix what needs fixing and send it.

## How it works

A GitHub Actions workflow (`.github/workflows/bulletin.yml`) runs `python -m pipeline.build` on the night from Thursday to Friday: 00:17 Turkey time, with two more runs at 04:47 and 07:23 that only retry sections that are missing or failed. The result is saved as `docs/data/bulletins/YYYY-MM-DD.json`, committed back to the repo, and `docs/` is deployed to GitHub Pages. An optional email tells the editors the draft is ready (or that the run failed).

| Section | Sources | How |
|---|---|---|
| Drewry World Container Index | drewry.co.uk | Page text is parsed for the index and route rates; an LLM writes a two-paragraph Turkish summary. A figure more than ±40% away from the last value is rejected. |
| Turkey exports / imports | Ministry of Trade monthly "Dış Ticaret Verileri" release | Figures are read directly from the official text with regexes, no LLM. Falls back to news + LLM, then to the previous bulletin. |
| Infographic news (2) | Visual Capitalist RSS and WordPress API | Two economy/trade infographics, image link and a Turkish paragraph. Skips ones used last week. |
| Free event | Ministry of Trade announcements, TAGM, UİB Akademi, İTO events, Google News, Tavily | Pages are opened and only future, online, free, single events (not listing pages) are kept. The registration link must open on the first try. |
| Turkey news (10) | Ministry of Trade, AA, Dünya, Ekonomim, Bloomberg HT, Foreks, TRT Haber, Hürriyet, Google News, Tavily | Duplicates merged; every link is opened to check the content and the date (paywalled, short or old articles are dropped); at most 2 items per site. |
| International news (10) | AA English, WTO, Google News (EN), Tavily | Same checks. |
| Next week | Bigpara economic calendar API, Turkish public holidays (`holidays`) | Picked by code, not by the LLM: Turkey's release that day if any, otherwise another country's trade release, otherwise the most important macro release. Always Monday to Saturday. |

The LLM does not gather news; RSS feeds and APIs do that. It is used to choose and deduplicate stories, write Turkish summaries, translate international news and write the WCI text. Every response must be valid JSON (repaired with `json-repair` if slightly broken) and must actually be in Turkish, otherwise the next model is tried. News summaries are capped at 340 characters so ten items fit on a PDF page.

Each section has fallbacks (wider date window, other candidates, last week's content, plain template text). When a fallback is used, a note is added to the draft so the editor sees it in the panel's checklist and in the PDF preview. A scheduled run that starts after 11:00 on Friday does not touch existing content; it only fills sections that are completely empty, so a late run cannot overwrite an editor's work.

Sources, search queries and keywords live in `pipeline/config.py`; editorial rules for the LLM are in `pipeline/prompts.py`.

### LLM backends

`pipeline/llm.py` picks the first provider with a key, in this order, and the others act as a fallback chain:

1. OpenRouter free models (`OPENROUTER_API_KEY`), several models tried in sequence
2. Anthropic API (`ANTHROPIC_API_KEY`)
3. Google Gemini API (`GEMINI_API_KEY`), Flash and Flash-Lite

`LLM_PROVIDER` forces one. Tavily search (`TAVILY_API_KEY`) is optional but makes the event section much better.

## The editor panel

`docs/` is a static site (plain JavaScript, no build) that reads the JSON drafts.

- Pick a bulletin from the archive dropdown. Click any text to edit it. Edits are saved in the browser's localStorage, so they are per person and per browser.
- Remove news items, reorder them with the arrows, or add one from the list of suggested extra stories.
- A checklist at the top lists what still needs attention before sending (fallbacks used, missing calendar days, and so on).
- Copy one section or the whole bulletin as text for Canva.
- Upload a Drewry chart image or replace an infographic image. The podcast image and description are entered once and reused every week until changed.
- **PDF indir** opens a three-page A4 preview (`docs/sheet.js`, `docs/sheet.css`): page 1 WCI, trade figures and infographics; page 2 the event, podcast and Turkey news; page 3 international news, calendar and legal notice. Text shrinks to fit its box; news is laid out in two measured columns; anything that still doesn't fit is listed by name in the preview instead of being dropped silently. Saving uses the browser's print dialog ("Save as PDF").
- The WCI chart in the PDF is drawn from `docs/data/wci_history.json`. `python -m scripts.backfill_wci` fills about a year of history from the Wayback Machine.
- "Taslağı yeniden oluştur" links to the Actions page to rerun the workflow.

## Tech stack

- Python 3.12: `requests`, `feedparser`, `trafilatura` (article text), `holidays`, `json-repair`, `anthropic`
- LLMs: OpenRouter, Anthropic API, Gemini
- GitHub Actions (schedule, commit, Pages deploy, email via `dawidd6/action-send-mail`)
- Vanilla JavaScript and CSS for the panel and the print layout
- Playwright for the PDF layout tests

## Running it locally

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env                            # add OPENROUTER_API_KEY and optionally TAVILY_API_KEY
.venv/bin/python -m pipeline.build              # today's bulletin
.venv/bin/python -m pipeline.build --no-llm     # collect data only, no LLM calls
python3 -m http.server -d docs 8000             # panel at http://localhost:8000
```

Other flags: `--date YYYY-MM-DD`, `--fill-missing` (keep the existing draft, redo only missing sections), `--scheduled`.

The workflow can also be started by hand from the Actions tab with a date, fill-missing, dry-run (draft uploaded as an artifact, nothing published) or deploy-only.

## Tests

```bash
python -m unittest tests.test_pipeline           # fallback behaviour with fake sources, no network
uvx --with playwright python tests/pdf_matrix.py # PDF layout scenarios in a headless browser
```

## Project structure

```
pipeline/
  build.py     builds each section, fallbacks, link and date checks, saving
  sources.py   RSS, Google News, Tavily, Drewry, Bigpara, Ministry of Trade, event sites
  llm.py       provider selection and fallback chain, JSON parsing, Turkish check
  prompts.py   editorial rules
  config.py    sources, queries, models, settings
docs/          editor panel and PDF layout (GitHub Pages); data/ holds the generated drafts
scripts/       backfill_wci.py
tests/         unit tests and PDF layout tests
```

## Limitations

- Edits made in the panel live only in that browser. Two editors don't see each other's changes, and clearing site data loses them.
- The panel is a public URL (marked `noindex`), because GitHub Pages on a free plan needs a public repo.
- Sources are scraped from HTML in several places (Drewry, ministry pages, event sites), so a site redesign can break a section until the parser is updated. The fallbacks keep the draft complete in the meantime.
- The issue number is counted from a fixed anchor in `config.py` and has to be adjusted by hand if a week is skipped.
