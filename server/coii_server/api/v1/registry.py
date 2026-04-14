"""Model registry — drives Dashboard dropdowns."""
from fastapi import APIRouter

router = APIRouter(prefix="/registry")

MODEL_REGISTRY = {
    "openai": {
        "label": "OpenAI",
        "models": [
            # GPT-4.1 family (Apr 2025)
            {"id": "gpt-4.1",       "label": "GPT-4.1"},
            {"id": "gpt-4.1-mini",  "label": "GPT-4.1 mini"},
            {"id": "gpt-4.1-nano",  "label": "GPT-4.1 nano"},
            # GPT-4o family
            {"id": "gpt-4o",        "label": "GPT-4o"},
            {"id": "gpt-4o-mini",   "label": "GPT-4o mini"},
            # Reasoning models
            {"id": "o4-mini",       "label": "o4-mini"},
            {"id": "o3",            "label": "o3"},
            {"id": "o3-mini",       "label": "o3-mini"},
            # Legacy
            {"id": "gpt-4-turbo",   "label": "GPT-4 Turbo"},
            {"id": "gpt-3.5-turbo", "label": "GPT-3.5 Turbo"},
        ],
    },
    "anthropic": {
        "label": "Anthropic",
        "models": [
            # Claude 4 family
            {"id": "claude-opus-4",    "label": "Claude Opus 4"},
            {"id": "claude-sonnet-4-6","label": "Claude Sonnet 4.6"},
            {"id": "claude-sonnet-4-5","label": "Claude Sonnet 4.5"},
            # Claude 3.7
            {"id": "claude-sonnet-3-7","label": "Claude Sonnet 3.7"},
            # Claude 3.5
            {"id": "claude-sonnet-3-5","label": "Claude Sonnet 3.5"},
            {"id": "claude-haiku-3-5", "label": "Claude Haiku 3.5"},
            # Claude 3 Haiku (cheap)
            {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5"},
        ],
    },
    "google": {
        "label": "Google",
        "models": [
            {"id": "gemini-2.5-pro",   "label": "Gemini 2.5 Pro"},
            {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
            {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash"},
            {"id": "gemini-1.5-pro",   "label": "Gemini 1.5 Pro"},
            {"id": "gemini-1.5-flash", "label": "Gemini 1.5 Flash"},
        ],
    },
    "deepseek": {
        "label": "DeepSeek",
        "models": [
            {"id": "deepseek-r1",   "label": "DeepSeek R1"},
            {"id": "deepseek-v3",   "label": "DeepSeek V3"},
            {"id": "deepseek-r1-0528", "label": "DeepSeek R1 0528"},
        ],
    },
    "openrouter": {
        "label": "OpenRouter",
        "models": [
            # Paid via OpenRouter
            {"id": "openai/gpt-4.1",                    "label": "GPT-4.1 (via OR)"},
            {"id": "openai/gpt-4o",                     "label": "GPT-4o (via OR)"},
            {"id": "anthropic/claude-sonnet-4-6",        "label": "Claude Sonnet 4.6 (via OR)"},
            {"id": "anthropic/claude-opus-4",            "label": "Claude Opus 4 (via OR)"},
            {"id": "google/gemini-2.5-flash",            "label": "Gemini 2.5 Flash (via OR)"},
            {"id": "google/gemini-2.5-pro",              "label": "Gemini 2.5 Pro (via OR)"},
            {"id": "deepseek/deepseek-r1",               "label": "DeepSeek R1 (via OR)"},
            # Free models
            {"id": "meta-llama/llama-3.3-70b-instruct:free",  "label": "Llama 3.3 70B (free)"},
            {"id": "meta-llama/llama-3.2-3b-instruct:free",   "label": "Llama 3.2 3B (free)"},
            {"id": "deepseek/deepseek-r1:free",               "label": "DeepSeek R1 (free)"},
            {"id": "google/gemma-3-27b-it:free",              "label": "Gemma 3 27B (free)"},
            {"id": "google/gemma-3-12b-it:free",              "label": "Gemma 3 12B (free)"},
        ],
    },
}


@router.get("/providers")
async def list_providers():
    return [
        {"id": k, "label": v["label"]}
        for k, v in MODEL_REGISTRY.items()
    ]


@router.get("/models")
async def list_models(provider: str | None = None):
    if provider:
        if provider not in MODEL_REGISTRY:
            return []
        return MODEL_REGISTRY[provider]["models"]
    # Return all with provider tag
    result = []
    for p, v in MODEL_REGISTRY.items():
        for m in v["models"]:
            result.append({"provider": p, **m})
    return result
