"""
Provider-agnostic LLM client for the Contract Clause Explainer.

Everything else calls chat(system, user) and gets back a string.

NOTE: We always send a User-Agent header. Without it, Cloudflare (which sits
in front of Groq's API) returns HTTP 403 error 1010 and blocks the request.
This bit us during development; the header fixes it.
"""

import json
import urllib.request
import urllib.error

import config


class LLMError(Exception):
    """Raised when the LLM provider is unreachable or returns an error."""
    pass


def _post_json(url, payload, headers, timeout=120):
    data = json.dumps(payload).encode("utf-8")
    # Always identify ourselves — Cloudflare blocks header-less clients (403/1010).
    headers = {**headers, "User-Agent": "contract-explainer/1.0"}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise LLMError(f"HTTP {e.code} from provider: {body[:300]}")
    except urllib.error.URLError as e:
        raise LLMError(
            f"Could not reach the LLM provider at {url}. "
            f"Is it running / is your key set? Underlying error: {e.reason}"
        )
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"Unexpected error talking to provider: {e}")


def chat(system: str, user: str) -> str:
    """Send system + user prompt to the configured provider, return text."""
    provider = config.PROVIDER.lower()

    if provider in ("groq", "openai"):
        cfg = config.GROQ if provider == "groq" else config.OPENAI
        if not cfg.get("api_key"):
            raise LLMError(
                f"{provider} selected but no API key set. Paste it into "
                f"config.py or set the {provider.upper()}_API_KEY env var."
            )
        url = f"{cfg['base_url']}/chat/completions"
        payload = {
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": config.TEMPERATURE,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        }
        out = _post_json(url, payload, headers)
        try:
            return out["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError):
            raise LLMError(f"Unexpected response shape: {str(out)[:300]}")

    elif provider == "ollama":
        cfg = config.OLLAMA
        url = f"{cfg['base_url']}/api/chat"
        payload = {
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": config.TEMPERATURE},
        }
        out = _post_json(url, payload, {"Content-Type": "application/json"})
        try:
            return out["message"]["content"].strip()
        except (KeyError, TypeError):
            raise LLMError(f"Unexpected Ollama response shape: {str(out)[:300]}")

    else:
        raise LLMError(f"Unknown PROVIDER '{config.PROVIDER}' in config.py")


def health_check() -> tuple[bool, str]:
    """Used by the web app to show provider status on load."""
    try:
        reply = chat("Reply with exactly: OK", "Say OK")
        return True, f"{config.PROVIDER} reachable"
    except LLMError as e:
        return False, str(e)
