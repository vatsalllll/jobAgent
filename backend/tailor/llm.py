import json
import re
import os
from typing import Optional


class LLMProvider:
    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float = 0.3) -> str:
        raise NotImplementedError


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float = 0.3) -> str:
        message = self.client.messages.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature,
            system=system_prompt, messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text


class HuggingFaceProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, endpoint_url: str = ""):
        from huggingface_hub import InferenceClient
        provider = os.getenv("HF_PROVIDER", "groq")
        self.client = InferenceClient(provider=provider, api_key=api_key)
        self.model = model
        self.endpoint_url = endpoint_url

    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float = 0.3) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        completion = self.client.chat.completions.create(
            model=self.model, messages=messages, max_tokens=max_tokens, temperature=temperature,
        )
        content = completion.choices[0].message.content
        content = _strip_thinking(content)
        return content


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float = 0.3) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        response = await self.client.chat.completions.create(
            model=self.model, messages=messages, max_tokens=max_tokens, temperature=temperature,
        )
        return response.choices[0].message.content


def _strip_thinking(text: str) -> str:
    if "<｜end▁of▁thinking｜>now let me run the real test" in text:
        text = text.split(" responsenow let me run the real test")[0]
    if "<｜end▁of▁thinking｜>" in text and "" in text:
        parts = text.split("")
        if len(parts) > 1:
            text = parts[-1]
    return text.strip()


_provider: Optional[LLMProvider] = None


def get_llm() -> LLMProvider:
    global _provider
    if _provider is not None:
        return _provider

    from config import settings

    provider_type = os.getenv("LLM_PROVIDER", "huggingface").lower()

    if provider_type == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        _provider = AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.claude_model)

    elif provider_type == "huggingface":
        hf_key = os.getenv("HF_API_KEY") or settings.hf_api_key
        if not hf_key:
            raise ValueError("HF_API_KEY not set in .env or environment")
        hf_model = os.getenv("HF_MODEL") or settings.hf_model
        _provider = HuggingFaceProvider(api_key=hf_key, model=hf_model)

    elif provider_type == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY not set")
        _provider = OpenAIProvider(api_key=settings.openai_api_key, model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider_type}")

    return _provider


def reset_provider():
    global _provider
    _provider = None


def extract_json(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    matches = re.findall(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    for match in matches:
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass
    return None
