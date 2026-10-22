"""LLM katmanı. JSON döndürür.

Sağlayıcılar:
  anthropic  - Claude API (ANTHROPIC_API_KEY), kullandıkça öde
  claude-cli - Claude Code CLI, Claude Pro/Max aboneliğiyle ek ücret yok (CLAUDE_CODE_OAUTH_TOKEN)
  gemini     - Google Gemini API ücretsiz katman (GEMINI_API_KEY)
  openrouter - OpenRouter ücretsiz modeller (OPENROUTER_API_KEY)
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

import json_repair
import requests

from . import config
from .sources import log


def provider():
    p = config.LLM_PROVIDER
    if p:
        return p
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("CLAUDE_CODE_OAUTH_TOKEN"):
        return "claude-cli"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    if shutil.which("claude"):
        return "claude-cli"
    return None


def model_name():
    return {"anthropic": config.ANTHROPIC_MODEL, "claude-cli": config.CLAUDE_CLI_MODEL,
            "gemini": config.GEMINI_MODELS[0], "openrouter": config.OPENROUTER_MODELS[0]}.get(provider())


def _extract_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=0)
    return json.loads(text[start:])


def _anthropic(system, user, max_tokens):
    import anthropic

    client = anthropic.Anthropic()
    resp = client.beta.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"Model isteği reddetti: {resp.stop_details}")
    return "".join(b.text for b in resp.content if b.type == "text")


def _claude_cli(system, user, max_tokens):
    """Claude Code CLI (abonelik ile çalışır; Actions'ta CLAUDE_CODE_OAUTH_TOKEN gerekir)."""
    cmd = ["claude", "-p", "--tools", "", "--output-format", "text", "--no-session-persistence",
           "--model", config.CLAUDE_CLI_MODEL, "--system-prompt",
           system + "\n\nYanıtın SADECE geçerli JSON olsun; açıklama veya kod bloğu ekleme."]
    with tempfile.TemporaryDirectory() as tmp:  # proje CLAUDE.md vb. okunmasın
        r = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=900, cwd=tmp)
    if r.returncode != 0:
        raise RuntimeError(f"claude CLI hata: {r.stderr[-500:] or r.stdout[-500:]}")
    return r.stdout


def _openrouter_call(model, system, user, max_tokens):
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        # Düşünme adımı çıktı limitini tüketmesin
        "reasoning": {"effort": "low", "exclude": True},
    }
    headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
               "HTTP-Referer": "https://github.com/inovapulse", "X-Title": "InovaPulse Bulten"}
    for attempt in range(3):
        try:
            r = requests.post("https://openrouter.ai/api/v1/chat/completions", json=body,
                              headers=headers, timeout=600)
            data = r.json()
        except (requests.RequestException, ValueError) as ex:
            r, data = None, {"error": str(ex)}
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
        if r is not None and r.ok and text:
            return text
        err = str(data.get("error", ""))[:160] or "boş yanıt"
        if attempt < 2:
            wait = 15 * (attempt + 1)
            log(f"  {model}: {err}; {wait}s sonra tekrar")
            time.sleep(wait)
    raise RuntimeError(f"{model}: {err}")


class QuotaExhausted(RuntimeError):
    """Model/sağlayıcının günlük kotası doldu; bu çalıştırmada tekrar denenmez."""


exhausted = set()


def _gemini(model, system, user, max_tokens):
    key = os.environ["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        # Düşünme tokenları da bu limite dahil; yanıt kesilmesin diye geniş tutuluyor
        "generationConfig": {"responseMimeType": "application/json",
                             "maxOutputTokens": max(max_tokens, 32768)},
    }
    for attempt in range(3):
        # Anahtar URL'de değil başlıkta: hata mesajlarına/loglara sızmasın
        r = requests.post(url, headers={"x-goog-api-key": key}, json=body, timeout=300)
        if r.status_code == 429 and "PerDay" in r.text:
            raise QuotaExhausted(f"{model}: günlük ücretsiz kota doldu")
        if r.status_code in (429, 500, 503) and attempt < 2:
            wait = 30 * (attempt + 1)
            log(f"  {model} {r.status_code}, {wait}s bekleniyor...")
            time.sleep(wait)
            continue
        if not r.ok:
            raise RuntimeError(f"{model}: HTTP {r.status_code}")
        cand = r.json()["candidates"][0]
        return "".join(p.get("text", "") for p in cand["content"]["parts"])
    raise RuntimeError(f"{model}: yanıt vermedi")


def _attempts():
    """Denenecek (ad, fonksiyon) zinciri: seçili sağlayıcı önce, sonra anahtarı olan diğerleri."""
    chains = {}
    if os.getenv("GEMINI_API_KEY"):
        chains["gemini"] = [(f"gemini:{m}", lambda s, u, t, m=m: _gemini(m, s, u, t))
                            for m in config.GEMINI_MODELS]
    if os.getenv("OPENROUTER_API_KEY"):
        chains["openrouter"] = [(f"openrouter:{m}", lambda s, u, t, m=m: _openrouter_call(m, s, u, t))
                                for m in config.OPENROUTER_MODELS]
    if os.getenv("ANTHROPIC_API_KEY"):
        chains["anthropic"] = [(f"anthropic:{config.ANTHROPIC_MODEL}", _anthropic)]
    if os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or (not chains and shutil.which("claude")):
        chains["claude-cli"] = [(f"claude-cli:{config.CLAUDE_CLI_MODEL}", _claude_cli)]
    first = provider()
    order = [first] + [k for k in chains if k != first]
    return [a for k in order for a in chains.get(k, [])]


used_models = set()
_lock = threading.Lock()


def _parse(text):
    try:
        return _extract_json(text)
    except (json.JSONDecodeError, ValueError):
        fixed = json_repair.loads(text)  # küçük biçim hatalarını onar
        if not isinstance(fixed, (dict, list)) or not fixed:
            raise ValueError("JSON ayrıştırılamadı")
        return fixed


def ask_json(system, user, max_tokens=16000, check=None):
    """LLM'den JSON alır. Yanıt alınamazsa veya check(obj) ValueError atarsa
    zincirdeki sıradaki model/sağlayıcı denenir."""
    attempts = _attempts()
    if not attempts:
        raise RuntimeError("LLM tanımlı değil (GEMINI_API_KEY, OPENROUTER_API_KEY, "
                           "ANTHROPIC_API_KEY veya CLAUDE_CODE_OAUTH_TOKEN)")
    errors = []
    for name, fn in attempts:
        if name in exhausted:
            continue
        try:
            obj = _parse(fn(system, user, max_tokens))
            if check:
                check(obj)
        except QuotaExhausted as ex:
            with _lock:
                exhausted.add(name)
            errors.append(str(ex))
            log(f"  ✗ {ex}; sıradaki modele geçiliyor")
            continue
        except Exception as ex:
            errors.append(f"{name}: {ex}")
            log(f"  ✗ {name} kullanılamadı: {str(ex)[:160]}")
            continue
        with _lock:
            used_models.add(name)
        log(f"  ✓ yanıt: {name}")
        return obj
    raise RuntimeError("Hiçbir model geçerli yanıt vermedi: " + " | ".join(errors)[:600])


TR_CHARS = re.compile(r"[ğışĞİŞçÇöÖüÜ]")


def require_turkish(texts, min_ratio=0.8):
    texts = [t for t in texts if t]
    if not texts:
        raise ValueError("boş içerik")
    ok = sum(1 for t in texts if TR_CHARS.search(t))
    if ok / len(texts) < min_ratio:
        raise ValueError(f"metinler Türkçe değil ({ok}/{len(texts)})")
