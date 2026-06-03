"""End-to-end test of the agent's DECISION pipeline with a fake LLM."""
import json, llm_client, agent as agent_mod, ingest
from agent import ContractAgent, ANSWER, CLARIFY, ESCALATE, EN

def fake_chat(system, user):
    s = system.lower()
    if "triage" in s:
        q = user.lower()
        if any(p in q for p in ["should i","will i win","is this legal","good deal","chances","can i get out"]):
            return json.dumps({"category":"advice","clarifying_question":""})
        if any(p in q for p in ["help","tell me about","what do you think"]):
            return json.dumps({"category":"vague","clarifying_question":"Which part?"})
        return json.dumps({"category":"explain","clarifying_question":""})
    if "scanning one clause" in s:
        u = user.lower()
        if "automatically renew" in u:
            return json.dumps({"flag":True,"reason":"This lease renews itself unless you cancel 60 days early.","severity":"high"})
        if "indemnify" in u:
            return json.dumps({"flag":True,"reason":"You take on responsibility for some claims against the landlord.","severity":"high"})
        if "late fee" in u:
            return json.dumps({"flag":True,"reason":"Late rent adds up fast at PKR 2,000 per day.","severity":"medium"})
        return json.dumps({"flag":False,"reason":"","severity":"low"})
    # answer prompt — branch on the QUESTION line, not the whole prompt
    qline = ""
    for ln in user.split("\n"):
        if ln.lower().startswith("question:"):
            qline = ln.lower()
    u = qline
    if "deposit" in u:
        return json.dumps({"found":True,"answer":"Your security deposit is PKR 160,000. The landlord can deduct for damage beyond normal wear and tear, and must return the rest within 30 days after you leave.","clauses":["Clause 3.1","Clause 3.2"],"confidence":0.9})
    if "terminate" in u or "notice" in u or "end the lease" in u:
        return json.dumps({"found":True,"answer":"You (the tenant) must give 60 days written notice to end the lease.","clauses":["Clause 5.2"],"confidence":0.85})
    # pet: excerpts (use-of-premises) don't mention pets -> model says not found
    if "pet" in u or "dog" in u or "private residence" in u:
        return json.dumps({"found":False,"answer":"","clauses":[],"confidence":0.1})
    return json.dumps({"found":True,"answer":"See the relevant clause.","clauses":["Clause 1.1"],"confidence":0.7})

llm_client.chat=fake_chat; agent_mod.chat=fake_chat

res = ingest.ingest_pdf("test_contract.pdf","Lease.pdf")
print(f"Ingested: {len(res.clauses)} clauses, scanned={res.is_scanned}, contract={res.looks_like_contract}")
assert not res.is_scanned and res.looks_like_contract
print("Clause refs:", [c.ref for c in res.clauses if c.ref])

a = ContractAgent(res)
def run(q, exp=None, lang=EN):
    r=a.ask(q, lang)
    print(f"\nQ: {q}\n -> {r.outcome.upper()} (conf={r.confidence}) cites={r.citations}")
    print(f"    {r.message[:95]}")
    if exp: assert r.outcome==exp, f"expected {exp}, got {r.outcome}"
    return r

print("\n"+"="*60+"\nQ&A DECISION TESTS\n"+"="*60)
run("How much is my security deposit and when do I get it back?", ANSWER)
run("Should I sign this lease?", ESCALATE)
run("Will I win if I take my landlord to court?", ESCALATE)
run("Can I get out of this contract early?", ESCALATE)   # advice
run("can I have a pet dog here?", ESCALATE)               # model: not in contract
run("help", CLARIFY)
run("How much notice do I give to end the lease?", ANSWER)

r = a.ask("How much is the deposit?", EN)
assert r.disclaimer and "not legal advice" in r.disclaimer.lower()
print("\n  ✓ English disclaimer attached")

# Urdu path: disclaimer + advice refusal both in Urdu
ru = a.ask("Should I sign this?", "ur")
assert ru.outcome==ESCALATE and ru.disclaimer and "وکیل" in ru.disclaimer
print("  ✓ Urdu advice-refusal + Urdu disclaimer work")

print("\n"+"="*60+"\nRISK SCAN TEST\n"+"="*60)
flags = a.scan_risks(EN)
for f in flags:
    print(f"  [{f['severity'].upper():6}] {f['ref']}: {f['reason']}")
refs=" ".join(f['ref'] for f in flags)
assert "1.2" in refs and "7.1" in refs
print(f"\n  ✓ {len(flags)} risky clauses flagged (auto-renew + indemnity caught)")

print("\n\nALL CONTRACT-AGENT TESTS PASSED ✅")
