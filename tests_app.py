"""Exercise the real Flask routes with a patched LLM."""
import json, io, llm_client, agent as agent_mod

def fake_chat(system, user):
    s=system.lower()
    if "triage" in s:
        q=user.lower()
        if "should i" in q or "will i" in q: return json.dumps({"category":"advice","clarifying_question":""})
        if q.strip().endswith("help"): return json.dumps({"category":"vague","clarifying_question":"Which part?"})
        return json.dumps({"category":"explain","clarifying_question":""})
    if "scanning one clause" in s:
        u=user.lower()
        if "automatically renew" in u: return json.dumps({"flag":True,"reason":"Renews itself unless cancelled 60 days early.","severity":"high"})
        if "indemnify" in u: return json.dumps({"flag":True,"reason":"You cover certain claims against the landlord.","severity":"high"})
        return json.dumps({"flag":False,"reason":"","severity":"low"})
    qline=[l for l in user.split("\n") if l.lower().startswith("question:")]
    u=(qline[0].lower() if qline else "")
    if "deposit" in u: return json.dumps({"found":True,"answer":"Deposit is PKR 160,000, returned within 30 days minus damages.","clauses":["Clause 3.1"],"confidence":0.9})
    return json.dumps({"found":True,"answer":"See clause.","clauses":["Clause 1.1"],"confidence":0.7})

llm_client.chat=fake_chat; agent_mod.chat=fake_chat
import app as appmod
appmod.health_check=lambda:(True,"fake ok")
c=appmod.app.test_client()

r=c.get("/"); assert r.status_code==200 and b"Contract Clause Explainer" in r.data
print("✓ GET / ->",r.status_code)

r=c.post("/ask",json={"question":"hi","lang":"en"}); assert r.status_code==400
print("✓ ask-before-upload ->",r.status_code)

with open("test_contract.pdf","rb") as f: data=f.read()
r=c.post("/upload",data={"file":(io.BytesIO(data),"Lease.pdf")},content_type="multipart/form-data")
j=r.get_json(); print("✓ upload ->",r.status_code,"clauses:",j["clauses"],"contract:",j["looks_like_contract"])
assert r.status_code==200 and j["clauses"]>5

r=c.post("/scan",json={"lang":"en"}); j=r.get_json()
print("✓ scan ->",len(j["flags"]),"flags:",[f["ref"] for f in j["flags"]])
assert any("1.2" in f["ref"] or "7.1" in f["ref"] for f in j["flags"])

r=c.post("/ask",json={"question":"How much is my deposit?","lang":"en"}); j=r.get_json()
print("✓ ask(deposit,en) ->",j["outcome"],"cites",j["citations"])
assert j["outcome"]=="answer" and j["disclaimer"]

r=c.post("/ask",json={"question":"Should I sign this?","lang":"ur"}); j=r.get_json()
print("✓ ask(advice,ur) ->",j["outcome"]); assert j["outcome"]=="escalate" and "وکیل" in j["disclaimer"]

r=c.post("/upload",data={"file":(io.BytesIO(b"x"),"a.txt")},content_type="multipart/form-data")
assert r.status_code==400; print("✓ reject .txt ->",r.status_code)

print("\nWEB APP ROUTES PASSED ✅")
