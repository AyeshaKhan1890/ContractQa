"""
The agent brain for the Contract Clause Explainer.

This is where the agentic, law-specific behaviour lives. For each question the
agent runs an explicit decision pipeline and returns one of these OUTCOMES:

    ANSWER    -> explains what the contract says, in plain language, citing
                 the relevant clause(s), with a confidence score.
    CLARIFY   -> the question is too vague; asks the user what they mean.
    ESCALATE  -> the question crosses into LEGAL ADVICE / prediction
                 ("should I sign?", "will I win?"), OR the contract doesn't
                 cover it, OR confidence is too low, OR the doc is unreadable.
                 The agent hands the judgement call to a real lawyer instead
                 of guessing.

Why the escalation logic is strict here: a confident wrong answer about a
contract clause can cause real harm to a real person. So the agent is built to
EXPLAIN documents, never to advise, predict outcomes, or tell the user what to
do. Every response carries a standing "information, not legal advice" notice.

Bilingual: answers can be produced in English or Urdu (user's choice). The
contract is read in its original language (usually English); only the
explanation language changes.
"""

import json

import config
from llm_client import chat, LLMError
from retriever import Retriever


ANSWER = "answer"
CLARIFY = "clarify"
ESCALATE = "escalate"

EN = "en"
UR = "ur"


# Standing disclaimers, shown with every answer. Kept simple and clear.
DISCLAIMER = {
    EN: ("This is general information to help you understand your document — "
         "not legal advice. I am not a lawyer. For decisions or anything "
         "important, consult a qualified lawyer."),
    UR: ("یہ آپ کی دستاویز کو سمجھنے میں مدد کے لیے عمومی معلومات ہیں — قانونی "
         "مشورہ نہیں۔ میں وکیل نہیں ہوں۔ کسی بھی فیصلے یا اہم معاملے کے لیے "
         "کسی مستند وکیل سے رجوع کریں۔"),
}


class AgentResponse:
    def __init__(self, outcome, message, citations=None, confidence=None,
                 sources=None, trail=None, disclaimer=None):
        self.outcome = outcome
        self.message = message
        self.citations = citations or []     # list[str] clause labels
        self.confidence = confidence
        self.sources = sources or []         # list[(label, snippet)]
        self.trail = trail or []
        self.disclaimer = disclaimer

    def to_dict(self):
        return {
            "outcome": self.outcome,
            "message": self.message,
            "citations": self.citations,
            "confidence": self.confidence,
            "sources": self.sources,
            "trail": self.trail,
            "disclaimer": self.disclaimer,
        }


# ---- Prompts --------------------------------------------------------------

_TRIAGE_SYSTEM = """You are a triage step in a tool that helps ordinary people \
understand contracts they have been given. Classify the user's question into \
exactly one category:

- "explain": asks what the contract SAYS or what something MEANS. Answerable \
from the document text. Examples: "what is the notice period?", "can they \
keep my deposit?", "what does clause 7 mean?", "am I allowed to sublet?".

- "advice": asks for a JUDGEMENT, RECOMMENDATION, PREDICTION, or what the user \
SHOULD DO. NOT answerable from the document alone — needs a lawyer. Examples: \
"should I sign this?", "will I win if I sue?", "is this contract legal?", "is \
this a good deal?", "what are my chances in court?", "can I get out of this?".

- "vague": too unclear to act on. Examples: "help", "tell me about this", \
"what do you think?".

Reply with ONLY a JSON object, no other text:
{"category": "explain" | "advice" | "vague",
 "clarifying_question": "<if vague, one short question to ask; else empty>"}"""


def _answer_system(lang: str) -> str:
    lang_name = "English" if lang == EN else "Urdu (اردو)"
    return f"""You help ordinary people (tenants, employees, freelancers) \
understand contracts they did NOT write. Answer the user's question USING ONLY \
the provided contract excerpts. Each excerpt is labelled with its clause \
reference.

Hard rules:
- Use ONLY information in the excerpts. Do NOT use outside legal knowledge, do \
NOT guess, and do NOT invent clauses or laws.
- If the excerpts do not contain the answer, set "found" to false. Do not make \
something up to be helpful.
- Do NOT give legal advice, do NOT predict outcomes, and do NOT tell the user \
what they should do. Only explain what the document says, in plain language.
- Explain like you're talking to someone with no legal training. Define jargon \
simply.
- Cite the clause reference(s) your answer comes from.
- Report your confidence (0.0-1.0) that the excerpts genuinely answer the \
question.
- Write your "answer" in {lang_name}.

Reply with ONLY a JSON object, no other text:
{{
  "found": true | false,
  "answer": "<plain-language explanation in {lang_name}, or empty if not found>",
  "clauses": ["<clause refs you used>"],
  "confidence": <0.0-1.0>
}}"""


_RISK_SYSTEM = """You are scanning ONE clause from a contract on behalf of an \
ordinary person who did not write it. Decide if this clause is one a normal \
person would want flagged because it is unusual, risky, costly, or easy to \
miss. Examples of things to flag: automatic renewal, large penalties or fees, \
broad liability or indemnity shifted onto the person, non-compete or \
non-solicit restrictions, very long notice periods, the company being able to \
change terms unilaterally, waiver of important rights, the person giving up \
intellectual property.

Be conservative: only flag genuinely notable clauses, not routine boilerplate.

Reply with ONLY a JSON object, no other text:
{"flag": true | false,
 "reason": "<if flagged, ONE short plain-language sentence on why it matters; \
else empty>",
 "severity": "high" | "medium" | "low"}"""


def _safe_json(raw: str):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e == -1 or e <= s:
        return None
    try:
        return json.loads(raw[s:e + 1])
    except json.JSONDecodeError:
        return None


class ContractAgent:
    def __init__(self, ingest_result):
        self.doc = ingest_result
        self.retriever = Retriever(ingest_result.clauses)

    # -- main Q&A entry point ----------------------------------------------
    def ask(self, question: str, lang: str = EN) -> AgentResponse:
        lang = UR if lang == UR else EN
        disc = DISCLAIMER[lang]
        trail = []

        if self.doc.is_scanned or not self.doc.clauses:
            trail.append("Doc check: no readable text -> escalate.")
            msg = ("I can't read this document — it looks scanned or image-only. "
                   "Please upload a text-based contract, or OCR it first.")
            return AgentResponse(ESCALATE, msg, trail=trail, disclaimer=disc)

        question = (question or "").strip()
        if not question:
            q = ("What would you like to understand about this contract?"
                 if lang == EN else "آپ اس معاہدے کے بارے میں کیا سمجھنا چاہتے ہیں؟")
            return AgentResponse(CLARIFY, q, trail=["Empty question."],
                                 disclaimer=disc)

        # STEP 1: triage — explain vs advice vs vague.
        try:
            triage = _safe_json(chat(_TRIAGE_SYSTEM, f"Question: {question}"))
        except LLMError as e:
            trail.append(f"LLM unreachable during triage -> escalate. ({e})")
            return AgentResponse(
                ESCALATE,
                f"I can't reach the language model right now, so I won't guess. "
                f"Detail: {e}",
                trail=trail, disclaimer=disc)

        category = (triage or {}).get("category", "explain")

        if category == "advice":
            trail.append("Triage: question asks for legal advice/prediction "
                         "-> escalate to a lawyer (no advice given).")
            if lang == EN:
                msg = ("That's a question about what you should do or how things "
                       "would turn out — which is legal advice, and I'm not able "
                       "to give that. I can only explain what your contract says. "
                       "For a question like this, please speak with a qualified "
                       "lawyer. If it helps, I can explain the specific clauses "
                       "that relate to your situation — just ask about them.")
            else:
                msg = ("یہ سوال اس بارے میں ہے کہ آپ کو کیا کرنا چاہیے یا نتیجہ کیا "
                       "ہوگا — یہ قانونی مشورہ ہے، جو میں نہیں دے سکتا۔ میں صرف یہ "
                       "بتا سکتا ہوں کہ آپ کے معاہدے میں کیا لکھا ہے۔ ایسے سوال کے "
                       "لیے براہِ کرم کسی مستند وکیل سے رابطہ کریں۔ اگر مفید ہو تو "
                       "میں متعلقہ شقیں سمجھا سکتا ہوں — بس ان کے بارے میں پوچھیں۔")
            return AgentResponse(ESCALATE, msg, trail=trail, disclaimer=disc)

        if category == "vague":
            cq = (triage or {}).get("clarifying_question") or (
                "Which part of the contract do you want to understand?"
                if lang == EN else "آپ معاہدے کا کون سا حصہ سمجھنا چاہتے ہیں؟")
            trail.append("Triage: question too vague -> clarify.")
            return AgentResponse(CLARIFY, cq, trail=trail, disclaimer=disc)

        trail.append("Triage: 'explain' — answerable from the document.")

        # STEP 2: retrieve relevant clauses.
        best = self.retriever.best_score(question)
        trail.append(f"Retrieval: best clause score = {best:.3f} "
                     f"(threshold {config.MIN_RETRIEVAL_SCORE}).")
        if best < config.MIN_RETRIEVAL_SCORE:
            trail.append("Below threshold -> not in this contract -> escalate.")
            if lang == EN:
                msg = ("I looked through the contract and couldn't find anything "
                       "about that. It may not be covered in this document. I "
                       "won't guess — if you expected it to be here, double-check "
                       "the contract or ask a lawyer.")
            else:
                msg = ("میں نے معاہدہ دیکھا لیکن اس بارے میں کچھ نہیں ملا۔ ممکن ہے "
                       "یہ اس دستاویز میں شامل نہ ہو۔ میں اندازہ نہیں لگاؤں گا — اگر "
                       "آپ کو یقین ہے کہ یہ یہاں ہونا چاہیے تو معاہدہ دوبارہ دیکھیں "
                       "یا کسی وکیل سے پوچھیں۔")
            return AgentResponse(ESCALATE, msg, trail=trail, disclaimer=disc)

        hits = self.retriever.search(question)
        sources, blocks = [], []
        for h in hits:
            snip = h.clause.text.strip()[:config.MAX_CLAUSE_CHARS]
            sources.append((h.clause.label(), snip[:500]))
            blocks.append(f"--- {h.clause.label()} ---\n{snip}")
        excerpts = "\n\n".join(blocks)

        # STEP 3: answer from excerpts, in the chosen language.
        user_prompt = (f"Contract: {self.doc.source_name}\n\n"
                       f"Excerpts:\n{excerpts}\n\nQuestion: {question}")
        try:
            ans = _safe_json(chat(_answer_system(lang), user_prompt))
        except LLMError as e:
            trail.append(f"LLM unreachable during answering -> escalate. ({e})")
            return AgentResponse(
                ESCALATE,
                f"I found relevant clauses but couldn't reach the model to read "
                f"them. I won't guess. Detail: {e}",
                sources=sources, trail=trail, disclaimer=disc)

        if not ans:
            trail.append("Model returned unparseable output -> escalate w/ sources.")
            msg = ("I had trouble producing a clean answer. Here are the most "
                   "relevant clauses so you can read them directly.")
            return AgentResponse(ESCALATE, msg, sources=sources, trail=trail,
                                 disclaimer=disc)

        found = bool(ans.get("found"))
        conf = float(ans.get("confidence", 0) or 0)
        clauses = [str(c) for c in (ans.get("clauses") or [])]
        answer_text = (ans.get("answer") or "").strip()

        if not found or not answer_text:
            trail.append("Model: answer not present in contract -> escalate.")
            if lang == EN:
                msg = ("The contract doesn't appear to address that directly. I "
                       "won't make something up. A lawyer can tell you how the "
                       "law applies where the contract is silent.")
            else:
                msg = ("معاہدے میں اس کا براہِ راست ذکر نہیں لگتا۔ میں خود سے کچھ "
                       "نہیں بناؤں گا۔ جہاں معاہدہ خاموش ہو، وہاں قانون کیا کہتا ہے "
                       "یہ کوئی وکیل بتا سکتا ہے۔")
            return AgentResponse(ESCALATE, msg, sources=sources, trail=trail,
                                 disclaimer=disc)

        cite = clauses or [h.clause.label() for h in hits[:2]]

        if conf < config.MIN_CONFIDENCE:
            trail.append(f"Confidence {conf:.2f} below {config.MIN_CONFIDENCE} "
                         f"-> answer but flag for review.")
            note = ("\n\n⚠️ I'm not fully confident here — please read the cited "
                    "clause(s) yourself and consider asking a lawyer."
                    if lang == EN else
                    "\n\n⚠️ میں مکمل طور پر پُریقین نہیں ہوں — براہِ کرم متعلقہ "
                    "شق خود پڑھیں اور کسی وکیل سے مشورہ کریں۔")
            return AgentResponse(ANSWER, answer_text + note, citations=cite,
                                 confidence=conf, sources=sources, trail=trail,
                                 disclaimer=disc)

        trail.append(f"Confident answer (conf {conf:.2f}) citing {cite}.")
        return AgentResponse(ANSWER, answer_text, citations=cite,
                             confidence=conf, sources=sources, trail=trail,
                             disclaimer=disc)

    # -- proactive risk scan (runs on upload) ------------------------------
    def scan_risks(self, lang: str = EN, max_clauses: int = None):
        """
        Walk through the contract's clauses and flag ones an ordinary person
        would want to be warned about. Returns a list of dicts. This is the
        proactive, agentic part: the agent surfaces risks without being asked.
        """
        lang = UR if lang == UR else EN
        if self.doc.is_scanned or not self.doc.clauses:
            return []
        if max_clauses is None:
            max_clauses = config.RISK_SCAN_MAX_CLAUSES

        flags = []
        # Prefer longer clauses (boilerplate one-liners rarely matter); cap count.
        candidates = sorted(self.doc.clauses, key=lambda c: len(c.text),
                            reverse=True)[:max_clauses]
        for clause in candidates:
            snippet = clause.text.strip()[:config.MAX_CLAUSE_CHARS]
            try:
                r = _safe_json(chat(_RISK_SYSTEM, snippet))
            except LLMError:
                # If the model dies mid-scan, return what we have so far.
                break
            if r and r.get("flag"):
                flags.append({
                    "ref": clause.label(),
                    "reason": (r.get("reason") or "").strip(),
                    "severity": r.get("severity", "medium"),
                    "snippet": snippet[:240],
                })

        order = {"high": 0, "medium": 1, "low": 2}
        flags.sort(key=lambda f: order.get(f["severity"], 1))
        return flags
