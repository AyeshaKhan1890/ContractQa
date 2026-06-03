# Contract Clause Explainer — Workflow Automation Case Study

**Live agent:** _[paste your deployed link — see README "Deploy". If demoing
locally, write "Local demo (see README + screen recording)".]_

---

### Why this problem?

Ordinary people sign contracts they didn't write and can't fully read — a
tenancy agreement, an employment offer, a freelance contract, an NDA. The
documents are long, dense, and written in legalese precisely where the stakes
are highest: the auto-renewal clause, the penalty for paying late, the clause
that quietly shifts liability onto you. Hiring a lawyer to read a routine lease
is expensive and slow, so most people just sign and hope. The work of
*reading and understanding a contract* is repetitive, text-heavy, and done
manually by people who often aren't equipped to do it well.

I picked this because it's a genuinely common, high-cost-of-error problem
_[add one concrete sentence: a contract you or someone you know signed without
fully understanding — a specific moment makes this section land]_. The
bilingual angle came directly from the user: in Pakistan, formal contracts are
usually in English, but the person signing is often far more comfortable
understanding things explained in Urdu. So the agent reads the (English)
contract and can explain it in **English or Urdu** — a real accommodation for
the actual user, not a gimmick.

### Who is the user?

A tenant, employee, or freelancer holding a contract full of legalese, who
can't justify a lawyer for a quick read-through and just wants to understand:
*what am I agreeing to, what are the risky parts, what does this clause mean?*
They need plain-language understanding **with the actual clause shown**, so they
can verify it and — for anything that matters — take it to a professional.

### Architecture — what it decides, what it escalates

On upload, the contract PDF is split into **clauses** (not just pages, so it can
cite "Clause 7.2" — far more useful than "page 3"). Then two things happen:

1. **Proactive risk scan (autonomous).** The agent walks the clauses and flags
   the ones a normal person would want warned about — auto-renewal, large
   penalties, indemnity shifted onto them, non-competes — each with a
   one-sentence plain-language reason and a severity. This is the agent acting
   *without being asked*.
2. **Q&A.** For each question it runs an explicit pipeline: **triage** (is this
   answerable from the document, or is it legal advice?), **retrieve** the most
   relevant clauses (TF-IDF plus a plain-English→legalese synonym map, so "can
   they kick me out?" finds the termination clause), then **answer from those
   clauses only**, citing them, in the user's chosen language.

**What it escalates to a human — the centrepiece for a legal tool:**
- **Legal advice or prediction** ("should I sign?", "will I win in court?",
  "is this legal?") → it refuses to advise and routes the user to a lawyer.
  This is the single most important guard: the agent explains documents, it does
  not counsel people.
- **Not in the contract** → it says so and refuses to invent a clause or a law.
- **Low confidence** → it answers but flags the answer for the user to verify.
- **Unreadable (scanned) PDF** → it detects this and says it can't read it,
  rather than returning nonsense.
- A **standing "information, not legal advice" disclaimer** accompanies every
  response, in both languages.

This roughly meets the "≈80% autonomous, escalate the rest" goal: routine
"what does this clause say" questions and risk-spotting are handled end-to-end,
while judgement calls (what to *do*) are deliberately handed to a professional.
Every response exposes a **decision trail** so the user — and an evaluator — can
see exactly why it answered, clarified, or escalated.

### What I learned / ideas

- **The hardest, most important part was the refusal logic, not the answering.**
  For a legal tool, a confident wrong answer is worse than no answer, so the
  triage that separates "explain this clause" from "tell me what to do" — and
  reliably refuses the latter — is where most of the design effort went.
- **Structure matters more than horsepower.** Splitting the contract into
  clauses (and merging stray heading lines so they don't dominate retrieval)
  improved citation quality more than any model change would have.
- **Designing for the real user changed the product.** The Urdu option wasn't
  in my first sketch; thinking concretely about *who is stuck with this
  contract* in Pakistan made it obviously necessary.
- **Honest infra lessons:** the API client was initially blocked by Cloudflare
  (HTTP 403 / error 1010) for sending no `User-Agent` header — a reminder that
  "the model is down" is often really a plumbing problem. And an API key in a
  committed file gets auto-revoked, so secrets belong in environment variables.
- **Where I'd take it next:** OCR so scanned contracts work; extracting key
  terms (dates, amounts, notice periods) into a structured summary; comparing a
  contract against a "standard" template to highlight what's unusual; and
  letting the user ask follow-ups that remember the earlier conversation.
