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
import time

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
            "gemini": config.GEMINI_MODEL, "openrouter": config.OPENROUTER_MODELS[0]}.get(provider())


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


def _openrouter(system, user, max_tokens):
    """OpenRouter; ilk model hata verirse sıradakilere otomatik geçer (models listesi)."""
    body = {
        "models": config.OPENROUTER_MODELS[:3],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
               "HTTP-Referer": "https://github.com/inovapulse", "X-Title": "InovaPulse Bulten"}
    for attempt in range(5):
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", json=body,
                          headers=headers, timeout=600)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
        if r.ok and text:
            log(f"  OpenRouter modeli: {data.get('model')}")
            return text
        if attempt < 4:
            wait = 20 * (attempt + 1)
            log(f"  OpenRouter {r.status_code} {str(data.get('error', ''))[:160]}; {wait}s sonra tekrar")
            time.sleep(wait)
    raise RuntimeError(f"OpenRouter yanıt vermedi: {r.status_code} {r.text[:300]}")


def _gemini(system, user, max_tokens):
    key = os.environ["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_tokens},
    }
    for attempt in range(4):
        r = requests.post(url, params={"key": key}, json=body, timeout=300)
        if r.status_code in (429, 500, 503) and attempt < 3:
            wait = 30 * (attempt + 1)
            log(f"  Gemini {r.status_code}, {wait}s bekleniyor...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        cand = r.json()["candidates"][0]
        return "".join(p.get("text", "") for p in cand["content"]["parts"])
    raise RuntimeError("Gemini yanıt vermedi")


def ask_json(system, user, max_tokens=16000):
    p = provider()
    fn = {"anthropic": _anthropic, "claude-cli": _claude_cli, "gemini": _gemini,
          "openrouter": _openrouter}.get(p)
    if not fn:
        raise RuntimeError("LLM tanımlı değil (OPENROUTER_API_KEY, ANTHROPIC_API_KEY, "
                           "CLAUDE_CODE_OAUTH_TOKEN veya GEMINI_API_KEY)")
    last = None
    for attempt in range(2):
        text = fn(system, user, max_tokens)
        try:
            return _extract_json(text)
        except json.JSONDecodeError as ex:
            last = ex
            log(f"  JSON ayrıştırılamadı, tekrar deneniyor ({ex})")
    raise last
