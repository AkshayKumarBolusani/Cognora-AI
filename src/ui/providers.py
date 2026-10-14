"""Provider adapters for Cognora's language models."""

import os
import base64
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _setting(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def generate_answer(system_prompt: str, user_prompt: str) -> str:
    """Generate an answer using the provider configured in .env."""
    provider = _setting("LLM_PROVIDER", "ollama").lower()
    model = _setting("LLM_MODEL", "qwen2.5vl:7b")
    api_key = _setting("LLM_API_KEY")
    base_url = _setting("LLM_BASE_URL").rstrip("/")

    timeout = httpx.Timeout(180.0, connect=15.0)

    if provider == "ollama":
        base_url = base_url or "http://localhost:11434"
        response = httpx.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]

    if provider == "openai":
        if not api_key:
            raise ValueError("LLM_API_KEY is required for the OpenAI provider.")
        base_url = base_url if base_url and not base_url.startswith("http://localhost:11434") else "https://api.openai.com/v1"
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    if provider == "gemini":
        if not api_key:
            raise ValueError("LLM_API_KEY is required for the Gemini provider.")
        base_url = base_url if base_url and not base_url.startswith("http://localhost:11434") else "https://generativelanguage.googleapis.com/v1beta"
        endpoint = (
            f"{base_url}/models/{quote(model, safe='')}:generateContent"
        )
        response = httpx.post(
            endpoint,
            headers={"x-goog-api-key": api_key},
            json={
                "systemInstruction": {
                    "parts": [{"text": system_prompt}]
                },
                "contents": [
                    {"role": "user", "parts": [{"text": user_prompt}]}
                ],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        candidates = response.json().get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned no answer candidates.")
        parts = candidates[0].get("content", {}).get("parts", [])
        answer = "\n".join(part["text"] for part in parts if "text" in part)
        if not answer:
            raise RuntimeError("Gemini returned no text answer.")
        return answer

    raise ValueError(
        f"Unsupported LLM_PROVIDER '{provider}'. "
        "Choose ollama, openai, or gemini."
    )


def describe_image(image_bytes: bytes, prompt: str) -> str:
    """Describe a document figure using the independently configured vision model."""
    provider = _setting("VISION_PROVIDER", "").lower()
    if not provider:
        return ""
    model = _setting("VISION_MODEL")
    api_key = _setting("VISION_API_KEY")
    base_url = _setting("VISION_BASE_URL").rstrip("/")
    image_data = base64.b64encode(image_bytes).decode("ascii")
    timeout = httpx.Timeout(180.0, connect=15.0)
    if provider == "ollama":
        base_url = base_url or "http://localhost:11434"
        response = httpx.post(
            f"{base_url}/api/chat",
            json={"model": model, "stream": False, "messages": [{"role": "user", "content": prompt, "images": [image_data]}]},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "").strip()
    if provider == "openai":
        if not api_key:
            raise ValueError("VISION_API_KEY is required for OpenAI vision.")
        base_url = base_url if base_url and not base_url.startswith("http://localhost:11434") else "https://api.openai.com/v1"
        response = httpx.post(
            f"{base_url}/chat/completions", headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}},
            ]}]}, timeout=timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    if provider == "gemini":
        if not api_key:
            raise ValueError("VISION_API_KEY is required for Gemini vision.")
        base_url = base_url if base_url and not base_url.startswith("http://localhost:11434") else "https://generativelanguage.googleapis.com/v1beta"
        response = httpx.post(
            f"{base_url}/models/{quote(model, safe='')}:generateContent", headers={"x-goog-api-key": api_key},
            json={"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": "image/png", "data": image_data}}]}]},
            timeout=timeout,
        )
        response.raise_for_status()
        parts = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "\n".join(part.get("text", "") for part in parts).strip()
    raise ValueError("Unsupported VISION_PROVIDER. Choose ollama, openai, or gemini.")
