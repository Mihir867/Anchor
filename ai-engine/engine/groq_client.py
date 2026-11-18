"""
Groq API Client Helper
Provides a resilient, self-healing interface to invoke models on Groq.
Includes automatic 429 rate-limit backoff and smart model cascade (120B -> 20B -> Qwen).
"""

import os
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from groq import Groq, RateLimitError

logger = logging.getLogger("groq_client")

# Search for .env in current directory and parent directories
curr_dir = Path(__file__).resolve().parent
search_paths = [
    curr_dir / ".env",
    curr_dir.parent / ".env",
    curr_dir.parent.parent / ".env",
]
for env_path in search_paths:
    if env_path.exists():
        load_dotenv(env_path)
        logger.info(f"Loaded environment variables from: {env_path}")
        break

# Primary model and resilient fallback cascade
PRIMARY_MODEL = "openai/gpt-oss-120b"
FALLBACK_MODELS = ["openai/gpt-oss-20b", "qwen/qwen3.8-27b"]


def get_groq_client() -> Groq:
    """Initializes and returns Groq client using GROQ_API_KEY or GROQ_KEY."""
    api_key = os.getenv("GROQ_API_KEY") or os.getenv("GROQ_KEY")
    if not api_key:
        raise ValueError(
            "Groq API key not found. Please ensure GROQ_KEY or GROQ_API_KEY is set in your .env file or environment."
        )
    return Groq(api_key=api_key)


def call_groq_json(
    system_prompt: str,
    user_prompt: str,
    model: str = PRIMARY_MODEL,
    temperature: float = 0.5,
    max_retries: int = 4,
) -> Dict[str, Any]:
    """
    Calls Groq with JSON mode enabled.
    Handles 429 RateLimitError automatically by parsing the exact sleep duration
    suggested by Groq, waiting, and cascading to fallback models if needed.
    """
    client = get_groq_client()

    messages = [
        {
            "role": "system",
            "content": system_prompt + "\n\nCRITICAL: Output must be valid raw JSON only. Do not wrap in markdown quotes.",
        },
        {"role": "user", "content": user_prompt},
    ]

    current_model = model
    models_to_try = [current_model] + [m for m in FALLBACK_MODELS if m != current_model]

    for model_idx, target_model in enumerate(models_to_try):
        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    model=target_model,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    max_tokens=4096,
                )
                content = response.choices[0].message.content
                return json.loads(content)

            except RateLimitError as rle:
                # Parse exact wait time suggested by Groq (e.g. "Please try again in 2.69s")
                err_msg = str(rle)
                match = re.search(r"try again in ([\d.]+)s", err_msg)
                wait_time = float(match.group(1)) + 1.0 if match else (3.0 * (attempt + 1))

                # If wait time is short (under 10s), sleep and retry the same model
                if wait_time <= 10.0 and attempt < (max_retries - 1):
                    logger.info(f"⏳ Groq TPM limit on `{target_model}`. Auto-waiting {wait_time:.1f}s before retry...")
                    time.sleep(wait_time)
                    continue
                else:
                    # If wait is long or retries exhausted, cascade to the next model in pool
                    if model_idx < len(models_to_try) - 1:
                        next_model = models_to_try[model_idx + 1]
                        logger.warning(f"Switching from `{target_model}` to higher-quota fallback `{next_model}`...")
                        break
                    else:
                        logger.info(f"Waiting {wait_time:.1f}s on last fallback...")
                        time.sleep(wait_time)

            except Exception as e:
                logger.error(f"Groq API Call Error on `{target_model}`: {e}")
                # Try JSON markdown cleanup if text wrapped in ```json
                if 'response' in locals() and hasattr(response, 'choices') and response.choices:
                    text = response.choices[0].message.content
                    clean = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                    try:
                        return json.loads(clean)
                    except Exception:
                        pass
                if attempt == max_retries - 1 and model_idx == len(models_to_try) - 1:
                    raise e
                time.sleep(2.0)

    raise RuntimeError("All Groq models and retries exhausted.")
