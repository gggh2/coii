from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# Prices are in $/M tokens (input, output)
# Sources: provider pricing pages, April 2025
BUILTIN_PRICING = [
    # ── OpenAI ────────────────────────────────────────────────────────────────
    # GPT-4.1 family (Apr 2025)
    ("openai/gpt-4.1",       2.00,   8.00),
    ("openai/gpt-4.1-mini",  0.40,   1.60),
    ("openai/gpt-4.1-nano",  0.10,   0.40),
    # GPT-4o family
    ("openai/gpt-4o",        2.50,  10.00),
    ("openai/gpt-4o-mini",   0.15,   0.60),
    # Reasoning
    ("openai/o4-mini",       1.10,   4.40),
    ("openai/o3",           10.00,  40.00),
    ("openai/o3-mini",       1.10,   4.40),
    # Legacy
    ("openai/gpt-4-turbo",  10.00,  30.00),
    ("openai/gpt-3.5-turbo", 0.50,   1.50),

    # ── Anthropic ─────────────────────────────────────────────────────────────
    ("anthropic/claude-opus-4",     15.00,  75.00),
    ("anthropic/claude-sonnet-4-6",  3.00,  15.00),
    ("anthropic/claude-sonnet-4-5",  3.00,  15.00),
    ("anthropic/claude-sonnet-3-7",  3.00,  15.00),
    ("anthropic/claude-sonnet-3-5",  3.00,  15.00),
    ("anthropic/claude-haiku-4-5",   0.80,   4.00),
    ("anthropic/claude-haiku-3-5",   0.80,   4.00),

    # ── Google ────────────────────────────────────────────────────────────────
    ("google/gemini-2.5-pro",   1.25,  10.00),
    ("google/gemini-2.5-flash", 0.15,   0.60),
    ("google/gemini-2.0-flash", 0.10,   0.40),
    ("google/gemini-1.5-pro",   1.25,   5.00),
    ("google/gemini-1.5-flash", 0.075,  0.30),

    # ── DeepSeek ──────────────────────────────────────────────────────────────
    ("deepseek/deepseek-r1",       0.55,  2.19),
    ("deepseek/deepseek-v3",       0.27,  1.10),
    ("deepseek/deepseek-r1-0528",  0.55,  2.19),

    # ── OpenRouter paid pass-through ──────────────────────────────────────────
    ("openrouter/openai/gpt-4.1",                    2.00,   8.00),
    ("openrouter/openai/gpt-4o",                     2.50,  10.00),
    ("openrouter/anthropic/claude-sonnet-4-6",        3.00,  15.00),
    ("openrouter/anthropic/claude-opus-4",           15.00,  75.00),
    ("openrouter/google/gemini-2.5-flash",            0.15,   0.60),
    ("openrouter/google/gemini-2.5-pro",              1.25,  10.00),
    ("openrouter/deepseek/deepseek-r1",               0.55,   2.19),

    # ── OpenRouter free models ────────────────────────────────────────────────
    ("openrouter/meta-llama/llama-3.3-70b-instruct:free", 0.0, 0.0),
    ("openrouter/meta-llama/llama-3.2-3b-instruct:free",  0.0, 0.0),
    ("openrouter/deepseek/deepseek-r1:free",              0.0, 0.0),
    ("openrouter/google/gemma-3-27b-it:free",             0.0, 0.0),
    ("openrouter/google/gemma-3-12b-it:free",             0.0, 0.0),
    # Legacy free (keep for existing data)
    ("openrouter/google/gemma-3-4b-it:free",              0.0, 0.0),
    ("openrouter/liquid/lfm-2.5-1.2b-instruct:free",      0.0, 0.0),
    ("openrouter/nvidia/nemotron-nano-9b-v2:free",         0.0, 0.0),
]


async def seed_pricing(session: AsyncSession):
    for key, inp, out in BUILTIN_PRICING:
        await session.execute(
            text(
                """
                INSERT INTO model_pricing (pricing_key, input_cost_per_mtok, output_cost_per_mtok, source)
                VALUES (:key, :inp, :out, 'builtin')
                ON CONFLICT (pricing_key) DO UPDATE SET
                  input_cost_per_mtok  = excluded.input_cost_per_mtok,
                  output_cost_per_mtok = excluded.output_cost_per_mtok,
                  source = 'builtin'
                WHERE model_pricing.source = 'builtin'
                """
            ),
            {"key": key, "inp": inp, "out": out},
        )
