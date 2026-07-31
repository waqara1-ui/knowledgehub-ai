# llm.py
"""
# Handles LLM providers for LogLensAI. Handling generation part of RAG here.
# Falls back to the mock response if the selected provider fails.
"""
import asyncio
from dataclasses import dataclass
from typing import Optional
 
import httpx
 
from config import settings
 
 
@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    degraded: bool = False           # True if we fell back to mock
    error: Optional[str] = None
 
 
# --------------------------------------------------------------------------
# Provider defaults
# --------------------------------------------------------------------------
_DEFAULT_MODELS = {
    "ollama": "llama3.2:3b",
    "gemini": "gemini-2.0-flash",
    "openai_compatible": "llama-3.3-70b-versatile",  # Groq's free tier model
}
 
_DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434",
    "openai_compatible": "https://api.groq.com/openai/v1",
}
 
 
def _model() -> str:
    return settings.LLM_MODEL or _DEFAULT_MODELS.get(settings.LLM_PROVIDER, "mock")
 
 
def _base_url() -> str:
    return (
        settings.LLM_BASE_URL
        or _DEFAULT_BASE_URLS.get(settings.LLM_PROVIDER, "")
    ).rstrip("/")
 
 
# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------
async def _generate_ollama(system: str, user: str) -> str:
    url = f"{_base_url()}/api/chat"
    payload = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {
            "temperature": settings.LLM_TEMPERATURE,
            "num_predict": settings.LLM_MAX_TOKENS,
        },
    }
    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return (data.get("message") or {}).get("content", "").strip()
 
 
async def _generate_gemini(system: str, user: str) -> str:
    if not settings.LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY is required for the gemini provider.")
 
    base = _base_url() or "https://generativelanguage.googleapis.com/v1beta"
    url = f"{base}/models/{_model()}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": settings.LLM_TEMPERATURE,
            "maxOutputTokens": settings.LLM_MAX_TOKENS,
        },
    }
    headers = {"x-goog-api-key": settings.LLM_API_KEY}
    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
 
    candidates = data.get("candidates") or []
    if not candidates:
        # Usually means the prompt tripped a safety filter.
        raise RuntimeError(f"Gemini returned no candidates: {data.get('promptFeedback')}")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts).strip()
 
 
async def _generate_openai_compatible(system: str, user: str) -> str:
    base = _base_url()
    if not base:
        raise RuntimeError("LLM_BASE_URL is required for the openai_compatible provider.")
 
    url = f"{base}/chat/completions"
    payload = {
        "model": _model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": settings.LLM_TEMPERATURE,
        "max_tokens": settings.LLM_MAX_TOKENS,
    }
    headers = {}
    if settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
 
    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
 
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"Provider returned no choices: {data}")
    return (choices[0].get("message") or {}).get("content", "").strip()
 
 
async def _generate_mock(system: str, user: str) -> str:
    """The original placeholder behaviour, preserved for offline runs."""
    await asyncio.sleep(0.05)
    prompt = f"{system}\n{user}".lower()
 
    if "database timeout" in prompt and "connection pool" in prompt:
        return (
            "Based on the provided context, a common cause for database timeouts is "
            "connection pool exhaustion. Consider increasing the connection pool size "
            "or restarting the affected services."
        )
    if "restart" in prompt and "service" in prompt:
        return (
            "The context suggests that restarting the relevant service is a common "
            "troubleshooting step for many issues."
        )
    if "no extractable text" in prompt:
        return (
            "The document indicates it contains no extractable text, suggesting it "
            "might be an image-only PDF or corrupted."
        )
    return (
        "[mock response] Based on the provided context, review the referenced runbook "
        "sections and the surrounding log entries for specific remediation steps."
    )
 
 
_PROVIDERS = {
    "ollama": _generate_ollama,
    "gemini": _generate_gemini,
    "openai_compatible": _generate_openai_compatible,
    "mock": _generate_mock,
}
 
 
# Prompts
GROUNDED_SYSTEM_PROMPT = (
    "You are an incident response assistant for an engineering team.\n"
    "Answer using ONLY the runbook context provided by the user. Do not use outside "
    "knowledge and do not guess.\n"
    "If the context does not contain the answer, say plainly that the runbooks do not "
    "cover it, and suggest what an engineer should check instead.\n"
    "Cite your sources inline using the bracketed source numbers given in the context, "
    "for example [1] or [2].\n"
    "Be concise and practical. Prefer concrete steps over general advice."
)
 
UNGROUNDED_SYSTEM_PROMPT = (
    "You are an incident response assistant for an engineering team.\n"
    "No runbook context was retrieved for this question, so you must open your answer "
    "by stating that no relevant internal documentation was found.\n"
    "You may then offer general troubleshooting guidance, clearly labelled as general "
    "guidance rather than something from the team's runbooks.\n"
    "Be concise."
)
 
 
def build_context_block(relevant_chunks: list[dict]) -> tuple[str, list[dict]]:
    """
    Turning ranked chunks into a numbered context block and matching citations.
 
    Note to self: Numbering the sources is what makes inline citation work: the model is told
    to write [1], and [1] maps back to a real document and chunk.
    """
    lines = []
    citations = []
    for i, c in enumerate(relevant_chunks, start=1):
        lines.append(
            f"[{i}] Source: {c['document_title']} (section {c['chunk_order']})\n"
            f"{c['chunk_text']}"
        )
        citations.append(
            {
                "source_number": i,
                "document_id": c["document_id"],
                "document_title": c["document_title"],
                "chunk_id": c["chunk_id"],
                "chunk_order": c["chunk_order"],
                "similarity": round(float(c["similarity"]), 4),
            }
        )
    return "\n\n".join(lines), citations
 
 
# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
async def generate(system: str, user: str) -> LLMResult:
    """
    Generate an answer with the configured provider.
 
    I'm not raising on provider failure. It will fall back to the mock and mark the
    result as degraded so callers can surface that to the user.
    """
    provider = settings.LLM_PROVIDER
    fn = _PROVIDERS.get(provider)
 
    if fn is None:
        text = await _generate_mock(system, user)
        return LLMResult(
            text=text, provider="mock", model="mock", degraded=True,
            error=f"Unknown LLM_PROVIDER '{provider}'.",
        )
 
    if provider == "mock":
        text = await _generate_mock(system, user)
        return LLMResult(text=text, provider="mock", model="mock")
 
    try:
        text = await fn(system, user)
        if not text:
            raise RuntimeError("Provider returned an empty response.")
        return LLMResult(text=text, provider=provider, model=_model())
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all
        detail = f"{type(exc).__name__}: {exc}"
        print(f"[llm] {provider} failed, falling back to mock. {detail}")
        text = await _generate_mock(system, user)
        return LLMResult(
            text=text, provider="mock", model="mock", degraded=True, error=detail,
        )
 
 
async def health_check() -> dict:
    """Lightweight probe so /health can report whether the LLM is actually reachable."""
    if settings.LLM_PROVIDER == "mock":
        return {"provider": "mock", "model": "mock", "reachable": True}
 
    result = await generate(
        "You are a health check.", "Reply with the single word: ok"
    )
    return {
        "provider": settings.LLM_PROVIDER,
        "model": _model(),
        "reachable": not result.degraded,
        "error": result.error,
    }
 