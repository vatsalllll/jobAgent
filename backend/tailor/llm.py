"""
LLM abstraction layer — provider-agnostic with an automatic fallback chain.

Primary target (free): Groq (Llama 3.3 70B) → Gemini (2.5 Flash) → HuggingFace → Anthropic/OpenAI.
Groq, Gemini and OpenAI are all called via their OpenAI-compatible REST endpoints
using httpx (no extra SDK dependency, fully async, non-blocking).

Set LLM_PROVIDER to force a primary; the remaining configured providers are used as
fallbacks automatically, so a rate-limit (429) or outage on one provider transparently
falls through to the next.
"""

import asyncio
import json
import logging
import os
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
_RETRY_BACKOFF = [0.5, 1.5, 3.0]


class LLMProvider:
    name = "base"

    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float = 0.3) -> str:
        raise NotImplementedError


class OpenAICompatProvider(LLMProvider):
    """Any OpenAI-compatible /chat/completions endpoint (Groq, Gemini, OpenAI, OpenRouter…)."""

    def __init__(self, name: str, base_url: str, api_key: str, model: str, extra_headers: Optional[dict] = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.extra_headers = extra_headers or {}

    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float = 0.3) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        headers.update(self.extra_headers)
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        last_err: Optional[Exception] = None
        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(len(_RETRY_BACKOFF) + 1):
                try:
                    resp = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                    if resp.status_code in _RETRY_STATUS:
                        raise httpx.HTTPStatusError(f"{resp.status_code}", request=resp.request, response=resp)
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"] or ""
                    return _strip_thinking(content)
                except Exception as e:
                    last_err = e
                    if attempt < len(_RETRY_BACKOFF):
                        await asyncio.sleep(_RETRY_BACKOFF[attempt])
                    else:
                        raise
        raise last_err  # unreachable


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str):
        import anthropic
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float = 0.3) -> str:
        def _call():
            message = self.client.messages.create(
                model=self.model, max_tokens=max_tokens, temperature=temperature,
                system=system_prompt or "", messages=[{"role": "user", "content": user_prompt}],
            )
            return message.content[0].text
        # Run the blocking SDK call off the event loop.
        text = await asyncio.to_thread(_call)
        return _strip_thinking(text)


class HuggingFaceProvider(LLMProvider):
    name = "huggingface"

    def __init__(self, api_key: str, model: str):
        from huggingface_hub import InferenceClient
        provider = os.getenv("HF_PROVIDER", "groq")
        self.client = InferenceClient(provider=provider, api_key=api_key)
        self.model = model

    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float = 0.3) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        def _call():
            completion = self.client.chat.completions.create(
                model=self.model, messages=messages, max_tokens=max_tokens, temperature=temperature,
            )
            return completion.choices[0].message.content
        content = await asyncio.to_thread(_call)
        return _strip_thinking(content or "")


class FallbackProvider(LLMProvider):
    """Try each provider in order; on failure fall through to the next."""

    def __init__(self, providers: list[LLMProvider]):
        if not providers:
            raise ValueError("No LLM providers configured")
        self.providers = providers
        self.name = "fallback[" + ",".join(p.name for p in providers) + "]"

    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float = 0.3) -> str:
        last_err: Optional[Exception] = None
        for provider in self.providers:
            try:
                return await provider.generate(system_prompt, user_prompt, max_tokens, temperature)
            except Exception as e:
                last_err = e
                logger.warning(f"LLM provider '{provider.name}' failed ({e}); falling through to next.")
                continue
        raise RuntimeError(f"All LLM providers failed. Last error: {last_err}")


# ── thinking / reasoning stripping ───────────────────────────────────
_THINK_BLOCK = re.compile(r"<\s*(think|thinking|reasoning)\s*>.*?<\s*/\s*\1\s*>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK = re.compile(r"<\s*(think|thinking|reasoning)\s*>", re.IGNORECASE)
# DeepSeek-style special tokens, e.g. <｜end of thinking｜>
_DEEPSEEK_END = re.compile(r"<[｜|].*?(end).*?think.*?[｜|]>", re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    """Remove chain-of-thought so downstream JSON parsing sees only the answer.

    Handles Qwen3 <think>...</think>, generic <thinking>/<reasoning>, and
    DeepSeek <｜…thinking…｜> tokens. Safe on plain text (no-op).
    """
    if not text:
        return ""
    # Remove complete think blocks.
    text = _THINK_BLOCK.sub("", text)
    # DeepSeek end-of-thinking token: keep everything after it.
    m = list(_DEEPSEEK_END.finditer(text))
    if m:
        text = text[m[-1].end():]
    # An unclosed <think> (model truncated mid-thought): drop from it onward.
    open_m = _OPEN_THINK.search(text)
    if open_m:
        text = text[:open_m.start()]
    return text.strip()


_provider: Optional[LLMProvider] = None


def _build_provider(kind: str) -> Optional[LLMProvider]:
    """Construct a single provider by name from settings/env, or None if unconfigured."""
    from config import settings

    kind = kind.lower().strip()
    if kind == "groq":
        # Accept GROQ_API_KEY (canonical) or GROQ_API (common misname) or the settings field.
        key = os.getenv("GROQ_API_KEY") or os.getenv("GROQ_API") or getattr(settings, "groq_api_key", "")
        if not key:
            return None
        model = os.getenv("GROQ_MODEL") or getattr(settings, "groq_model", "llama-3.3-70b-versatile")
        return OpenAICompatProvider("groq", "https://api.groq.com/openai/v1", key, model)

    if kind == "gemini":
        key = os.getenv("GEMINI_API_KEY") or getattr(settings, "gemini_api_key", "")
        if not key:
            return None
        model = os.getenv("GEMINI_MODEL") or getattr(settings, "gemini_model", "gemini-2.5-flash")
        return OpenAICompatProvider(
            "gemini", "https://generativelanguage.googleapis.com/v1beta/openai", key, model
        )

    if kind == "openrouter":
        key = os.getenv("OPENROUTER_API_KEY") or getattr(settings, "openrouter_api_key", "")
        if not key:
            return None
        model = os.getenv("OPENROUTER_MODEL") or getattr(settings, "openrouter_model", "meta-llama/llama-3.3-70b-instruct:free")
        return OpenAICompatProvider("openrouter", "https://openrouter.ai/api/v1", key, model)

    if kind == "anthropic":
        if not settings.anthropic_api_key:
            return None
        return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.claude_model)

    if kind == "openai":
        if not settings.openai_api_key:
            return None
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        return OpenAICompatProvider("openai", "https://api.openai.com/v1", settings.openai_api_key, model)

    if kind == "huggingface":
        hf_key = os.getenv("HF_API_KEY") or settings.hf_api_key
        if not hf_key:
            return None
        hf_model = os.getenv("HF_MODEL") or settings.hf_model
        return HuggingFaceProvider(api_key=hf_key, model=hf_model)

    return None


# Preference order for fallbacks (best free → paid → weakest).
_DEFAULT_ORDER = ["groq", "gemini", "openrouter", "anthropic", "openai", "huggingface"]


def get_llm() -> LLMProvider:
    global _provider
    if _provider is not None:
        return _provider

    primary = os.getenv("LLM_PROVIDER", "").lower().strip()
    order = _DEFAULT_ORDER[:]
    if primary and primary in order:
        order.remove(primary)
        order.insert(0, primary)
    elif primary:
        # Unknown/legacy value — still honor it first if buildable.
        order.insert(0, primary)

    chain: list[LLMProvider] = []
    seen = set()
    for kind in order:
        if kind in seen:
            continue
        seen.add(kind)
        try:
            p = _build_provider(kind)
        except Exception as e:
            logger.warning(f"Could not build LLM provider '{kind}': {e}")
            p = None
        if p is not None:
            chain.append(p)

    if not chain:
        raise ValueError(
            "No LLM provider configured. Set at least one of GROQ_API_KEY, GEMINI_API_KEY, "
            "OPENROUTER_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, or HF_API_KEY."
        )

    _provider = chain[0] if len(chain) == 1 else FallbackProvider(chain)
    logger.info(f"LLM chain: {_provider.name}")
    return _provider


def reset_provider():
    global _provider
    _provider = None


# ── JSON extraction ──────────────────────────────────────────────────
def _repair_json(s: str) -> str:
    # Remove trailing commas before } or ]
    return re.sub(r",(\s*[}\]])", r"\1", s)


def extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = _strip_thinking(text)

    candidates: list[str] = [text]
    # Fenced ```json blocks first (most reliable).
    for m in re.findall(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL):
        candidates.insert(0, m.strip())
    # Greedy first-brace-to-last-brace span.
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        candidates.append(brace.group())

    for cand in candidates:
        for variant in (cand, _repair_json(cand)):
            try:
                obj = json.loads(variant)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
    return None
