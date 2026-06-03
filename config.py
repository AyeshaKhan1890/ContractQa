"""
Central configuration for the Contract Clause Explainer.

This is the ONLY file you edit to switch LLM providers or drop in your key.
The rest of the app talks to an abstract chat() function.

----------------------------------------------------------------------
QUICK START (local demo)
----------------------------------------------------------------------
1. Get a free Groq key at https://console.groq.com  (API Keys section)
2. Paste it into GROQ["api_key"] below, inside the quotes.
3. python app.py  ->  open http://localhost:5000

If you push this folder to GitHub, REMOVE the key from here first and set
the GROQ_API_KEY environment variable instead (see README). An exposed key
gets auto-revoked by the provider.
"""

import os

# ----------------------------------------------------------------------
# PROVIDER
# ----------------------------------------------------------------------
PROVIDER = os.environ.get("CCE_PROVIDER", "groq")  # "groq" | "openai" | "ollama"

GROQ = {
    "base_url": "https://api.groq.com/openai/v1",
    # If you get an error when asking a question, this model name may be
    # retired — check https://console.groq.com/docs/models and update it.
    "model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
    # Paste your key here (local demo), OR set the GROQ_API_KEY env var.
    "api_key": os.environ.get("GROQ_API_KEY", "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"),
}

OPENAI = {
    "base_url": "https://api.openai.com/v1",
    "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    "api_key": os.environ.get("OPENAI_API_KEY", ""),
}

OLLAMA = {
    "base_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
    "model": os.environ.get("OLLAMA_MODEL", "llama3.1:8b"),
}

# ----------------------------------------------------------------------
# Agent tuning knobs
# ----------------------------------------------------------------------
# How many of the most-relevant clauses to feed the model per question.
TOP_K_CLAUSES = 5

# Below this retrieval score, assume the contract doesn't cover the topic
# and escalate instead of guessing.
MIN_RETRIEVAL_SCORE = 0.03

# Below this self-reported confidence (0-1), flag the answer for review.
MIN_CONFIDENCE = 0.55

# LLM sampling temperature. Low = more deterministic / faithful to text.
TEMPERATURE = 0.1

# Max characters of a single clause passed to the model (truncation guard).
MAX_CLAUSE_CHARS = 2200

# How many clauses to scan for the proactive "risky clause" check on upload.
# (Caps the number of LLM calls so upload stays reasonably fast / cheap.)
RISK_SCAN_MAX_CLAUSES = 40
