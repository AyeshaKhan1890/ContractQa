# Contract Clause Explainer

An agent that helps **ordinary people** (tenants, employees, freelancers)
understand a contract they *didn't* write. Upload a contract PDF and:

1. it **proactively scans for risky/unusual clauses** (auto-renewal, heavy
   penalties, indemnity, non-competes…) and flags them in plain language;
2. you **ask questions in plain English or Urdu** ("how much notice must I
   give?") and get a plain-language answer **cited to the exact clause**;
3. crucially, it **knows the line between explaining and advising** — when you
   ask "should I sign?" or "will I win in court?", it refuses to give legal
   advice and tells you to see a lawyer, instead of guessing.

> **This is not legal advice and the agent is not a lawyer.** It explains what
> a document *says*; it does not advise, predict outcomes, or tell you what to
> do. Every answer carries this disclaimer in the app.

```
upload contract ─▶ split into clauses ─▶ ┌─ proactive RISK SCAN (flags clauses)
                                          └─ Q&A:
                                              triage (explain? advice? vague?)
                                                 │
              ┌──────────────────────────────────┼─────────────────────────┐
           ANSWER                              CLARIFY                   ESCALATE
       (plain language,                    (question too        (legal advice/prediction,
        cites clauses,                       vague)              OR not in contract,
        confidence)                                              OR low confidence,
                                                                 OR unreadable PDF)
```

## What makes it an agent (not just a summariser)

| Decision | Made by | Behaviour |
|---|---|---|
| Which clauses are relevant? | retriever (TF-IDF + legal synonyms) | feeds only top clauses to the model |
| Explain vs. legal advice? | LLM triage | **refuses advice/prediction**, routes to a lawyer |
| Is the answer in the contract? | retrieval score + LLM `found` flag | **escalates** rather than inventing a clause |
| Confident enough? | LLM self-reported confidence | flags low-confidence answers for review |
| Which clauses are risky? | proactive per-clause LLM scan | surfaces them **without being asked** |
| Readable PDF? | ingest layer | detects scanned/image-only docs and says so |

## Setup

```bash
pip install -r requirements.txt
```

### Add your Groq key (free)

1. Get a free key at https://console.groq.com → **API Keys**.
2. Open `config.py`, find the `GROQ` block, paste your key inside the quotes:
   ```python
   "api_key": os.environ.get("GROQ_API_KEY", "gsk_your_key_here"),
   ```

> ⚠️ **Do not commit this file to GitHub with your key in it.** Providers
> auto-revoke exposed keys. For deployment, leave `api_key` blank and set the
> `GROQ_API_KEY` environment variable instead.

## Run

```bash
python app.py
# open http://localhost:5000
```

Upload a contract (a sample `test_contract.pdf` lease is included). Try:
- "How much is my deposit and when do I get it back?" → cited answer
- "What happens if I pay rent late?" → cited answer
- "Should I sign this?" → **escalates** (refuses to advise)
- toggle to **اردو** and ask again to see Urdu answers

## Deploy (public link)

It's a single Flask process; any Python host works. Easiest with a public URL:

**Render (free)**
1. Push to GitHub (key NOT in config.py — see warning above).
2. New ▸ Web Service ▸ connect repo.
3. Build: `pip install -r requirements.txt` · Start: `python app.py`
4. Env vars: `CCE_PROVIDER=groq`, `GROQ_API_KEY=...`

> I haven't verified Render's current free-tier specifics — they change. Check
> their docs when deploying.

**Public link from your own machine (keeps key local):** `ngrok http 5000`.

## Files

```
config.py        provider + key + tuning knobs
llm_client.py    provider-agnostic chat() (includes the User-Agent fix
                 that avoids Cloudflare's 403/1010 block)
ingest.py        PDF -> clauses; detects scanned / non-contract docs
retriever.py     clause retrieval (TF-IDF + plain-English→legalese synonyms)
agent.py         the brain: advice/explain triage, bilingual answers,
                 risk scan, escalation guards, disclaimers
app.py           Flask web app + bilingual UI (RTL for Urdu)
```

## Honest limitations

- **Not legal advice.** By design it explains, never advises. It can be wrong
  or incomplete; users must verify and consult a lawyer for anything important.
- **Urdu quality:** the model is stronger in English; Urdu explanations are
  good but can read a little stiff. Urdu-script *contracts* may also extract
  imperfectly from PDF — the agent flags low-confidence cases.
- **Tables & scans:** specs/figures buried in tables extract as flowing text,
  which can reduce precision; scanned PDFs aren't read (no OCR).
- **Clause detection** relies on common numbering patterns (1, 1.2, Section 4,
  (a)). Unusually formatted contracts fall back to citing by page.
- Answer quality depends on the model behind `config.py`.
