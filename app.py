"""
Flask web app for the Contract Clause Explainer.

Run:  python app.py   ->  open http://localhost:5000

Flow:
  1. User uploads a contract PDF; we ingest it into clauses and build an agent.
  2. We immediately run a proactive RISK SCAN and show flagged clauses.
  3. User asks questions (in English or Urdu); each answer shows the outcome
     (answer / clarify / escalate), clause citations, confidence, the source
     clause text, the decision trail, and a standing legal disclaimer.
"""

import os
import uuid
import tempfile

from flask import Flask, request, jsonify, session, render_template_string

import config
from llm_client import health_check
from ingest import ingest_pdf
from agent import ContractAgent, DISCLAIMER, EN, UR

app = Flask(__name__)
app.secret_key = os.environ.get("CCE_SECRET", "dev-secret-change-me")

_AGENTS: dict[str, ContractAgent] = {}
_UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "cce_uploads")
os.makedirs(_UPLOAD_DIR, exist_ok=True)
MAX_BYTES = 15 * 1024 * 1024


def _sid():
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    return session["sid"]


@app.route("/")
def index():
    ok, status = health_check()
    model = (config.GROQ["model"] if config.PROVIDER == "groq"
             else config.OPENAI["model"] if config.PROVIDER == "openai"
             else config.OLLAMA["model"])
    return render_template_string(PAGE, provider=config.PROVIDER, model=model,
                                  llm_ok=ok, llm_status=status,
                                  disc_en=DISCLAIMER[EN], disc_ur=DISCLAIMER[UR])


@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file provided."}), 400
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Please upload a .pdf file."}), 400
    raw = f.read()
    if len(raw) > MAX_BYTES:
        return jsonify({"error": "File too large (max 15 MB)."}), 400

    sid = _sid()
    path = os.path.join(_UPLOAD_DIR, f"{sid}.pdf")
    with open(path, "wb") as out:
        out.write(raw)

    result = ingest_pdf(path, source_name=f.filename)
    _AGENTS[sid] = ContractAgent(result)

    return jsonify({
        "filename": f.filename,
        "clauses": len(result.clauses),
        "pages": result.page_count,
        "chars": result.total_chars,
        "is_scanned": result.is_scanned,
        "looks_like_contract": result.looks_like_contract,
        "warnings": result.warnings,
    })


@app.route("/scan", methods=["POST"])
def scan():
    """Run the proactive risk scan. Separate endpoint so the UI can show the
    upload result instantly, then stream the (slower) risk flags after."""
    sid = _sid()
    agent = _AGENTS.get(sid)
    if agent is None:
        return jsonify({"error": "Upload a contract first."}), 400
    lang = (request.json or {}).get("lang", "en")
    flags = agent.scan_risks(UR if lang == "ur" else EN)
    return jsonify({"flags": flags})


@app.route("/ask", methods=["POST"])
def ask():
    sid = _sid()
    agent = _AGENTS.get(sid)
    if agent is None:
        return jsonify({"error": "Upload a contract first."}), 400
    body = request.json or {}
    question = body.get("question", "")
    lang = body.get("lang", "en")
    resp = agent.ask(question, UR if lang == "ur" else EN)
    return jsonify(resp.to_dict())


# --------------------------------------------------------------------------
# UI — warm, paper-like, editorial/legal feel. Bilingual with RTL for Urdu.
# --------------------------------------------------------------------------
PAGE = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contract Clause Explainer</title>
<style>
  :root{
    --paper:#f5f1e8; --card:#fffdf7; --ink:#2b2620; --dim:#7a7268;
    --line:#e0d8c8; --line2:#d4c9b4; --accent:#8a5a2b; --accent-soft:#b8843f;
    --ok:#3f7d4f; --ok-bg:#eaf3ec; --clar:#2f6690; --clar-bg:#e8f0f5;
    --esc:#b06a1f; --esc-bg:#f7eede; --err:#a83232; --err-bg:#f6e7e7;
    --hi:#b3261e; --hi-bg:#f9e6e4; --med:#9a6a16; --med-bg:#f6eddb;
    --lo:#5a6a4a; --lo-bg:#eef0e8;
    --serif:Georgia,'Times New Roman',serif;
    --sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    --mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
    line-height:1.6;min-height:100vh}
  .wrap{max-width:860px;margin:0 auto;padding:30px 20px 90px}
  header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;
    border-bottom:2px solid var(--line2);padding-bottom:16px;margin-bottom:8px}
  h1{font-family:var(--serif);font-size:25px;margin:0;font-weight:700;
    letter-spacing:-.3px}
  h1 .dot{color:var(--accent)}
  .tag{font-family:var(--mono);font-size:11px;color:var(--dim);
    border:1px solid var(--line2);border-radius:999px;padding:3px 11px}
  .status{margin-left:auto;font-family:var(--mono);font-size:11px;
    display:flex;align-items:center;gap:7px;color:var(--dim)}
  .sdot{width:8px;height:8px;border-radius:50%}
  .sdot.on{background:var(--ok)} .sdot.off{background:var(--err)}
  .langbar{display:flex;gap:6px;margin:14px 0 4px;align-items:center}
  .langbar .lbl{font-size:12px;color:var(--dim);margin-right:4px}
  .lang{font-family:var(--sans);font-size:13px;border:1px solid var(--line2);
    background:var(--card);color:var(--ink);border-radius:8px;padding:6px 14px;
    cursor:pointer;transition:.15s}
  .lang.active{background:var(--accent);color:#fff;border-color:var(--accent)}
  .disclaimer{background:#fbf4e6;border:1px solid var(--line2);
    border-left:4px solid var(--accent-soft);border-radius:8px;padding:11px 15px;
    font-size:13px;color:#5c5448;margin:14px 0 22px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;
    padding:20px;margin-bottom:18px;box-shadow:0 1px 2px rgba(80,60,30,.04)}
  .errbox{border-color:var(--err);background:var(--err-bg)}
  .errbox b{color:var(--err);font-family:var(--mono)}
  .drop{border:2px dashed var(--line2);border-radius:10px;padding:30px;
    text-align:center;cursor:pointer;transition:.18s;background:#fcfaf3}
  .drop:hover,.drop.hot{border-color:var(--accent-soft);background:#fbf6ea}
  .drop b{color:var(--accent);font-family:var(--serif);font-style:italic}
  .meta{font-family:var(--mono);font-size:12px;color:var(--dim);margin-top:12px;
    display:none;gap:16px;flex-wrap:wrap}
  .meta.show{display:flex}
  .meta b{color:var(--ink)}
  .uwarn{font-size:12.5px;color:var(--esc);margin-top:10px;font-style:italic}
  h2{font-family:var(--serif);font-size:17px;margin:0 0 4px;font-weight:700}
  .risk-head{display:flex;align-items:center;gap:10px;margin-bottom:12px}
  .risk-sub{font-size:13px;color:var(--dim);margin:-2px 0 14px}
  .flag{border:1px solid var(--line);border-radius:9px;padding:12px 14px;
    margin-bottom:10px;background:#fefdfa}
  .flag .top{display:flex;align-items:center;gap:9px;margin-bottom:5px}
  .sev{font-family:var(--mono);font-size:10px;font-weight:700;padding:2px 8px;
    border-radius:5px;letter-spacing:.5px}
  .sev.high{background:var(--hi-bg);color:var(--hi)}
  .sev.medium{background:var(--med-bg);color:var(--med)}
  .sev.low{background:var(--lo-bg);color:var(--lo)}
  .flag .ref{font-family:var(--mono);font-size:12px;color:var(--accent);font-weight:600}
  .flag .reason{font-size:14.5px;color:var(--ink)}
  .flag .snip{font-size:12px;color:var(--dim);margin-top:6px;font-style:italic;
    border-left:2px solid var(--line2);padding-left:9px}
  .askrow{display:flex;gap:10px}
  input[type=text]{flex:1;background:#fcfaf3;border:1px solid var(--line2);
    color:var(--ink);border-radius:9px;padding:13px 15px;font-size:15px;outline:none}
  input[type=text]:focus{border-color:var(--accent-soft)}
  button.ask{background:var(--accent);color:#fff;border:none;border-radius:9px;
    padding:0 22px;font-weight:600;font-size:14px;cursor:pointer;transition:.15s}
  button.ask:hover{background:#74491f} button.ask:disabled{opacity:.45;cursor:not-allowed}
  .chips{margin-top:12px;display:flex;gap:8px;flex-wrap:wrap}
  .chip{font-size:12.5px;color:var(--dim);border:1px solid var(--line2);
    border-radius:8px;padding:6px 11px;cursor:pointer;background:#fcfaf3;transition:.15s}
  .chip:hover{border-color:var(--accent-soft);color:var(--ink)}
  .resp{margin-top:18px;border:1px solid var(--line);border-radius:11px;
    overflow:hidden;animation:rise .25s ease}
  @keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1}}
  .resp .bar{display:flex;align-items:center;gap:10px;padding:10px 16px;
    border-bottom:1px solid var(--line);font-size:12px}
  .resp .body{padding:16px;font-size:15.5px;white-space:pre-wrap;line-height:1.65}
  .pill{font-family:var(--mono);font-size:10.5px;font-weight:700;padding:3px 10px;
    border-radius:6px;letter-spacing:.5px}
  .o-answer .bar{background:var(--ok-bg)} .o-answer .pill{background:var(--ok);color:#fff}
  .o-escalate .bar{background:var(--esc-bg)} .o-escalate .pill{background:var(--esc);color:#fff}
  .o-clarify .bar{background:var(--clar-bg)} .o-clarify .pill{background:var(--clar);color:#fff}
  .o-error .bar{background:var(--err-bg)} .o-error .pill{background:var(--err);color:#fff}
  .conf{margin-left:auto;color:var(--dim);font-family:var(--mono)}
  .cites{font-family:var(--mono);font-size:12px;color:var(--accent);padding:0 16px 12px}
  .resp .disc{font-size:12px;color:#6b6356;padding:0 16px 12px;font-style:italic;
    border-top:1px dashed var(--line);padding-top:10px}
  details{margin:0 16px 14px;border:1px solid var(--line);border-radius:8px;background:#fcfaf3}
  summary{cursor:pointer;padding:9px 13px;font-family:var(--mono);font-size:11.5px;
    color:var(--dim);user-select:none}
  summary:hover{color:var(--ink)}
  .src{padding:0 14px 12px;font-size:13.5px;color:#5c5448}
  .src .ref{font-family:var(--mono);font-size:11px;color:var(--accent);font-weight:600}
  .trail{padding:4px 14px 12px;font-family:var(--mono);font-size:11.5px;
    color:var(--dim);line-height:1.7}
  .trail .n{color:var(--accent)}
  .spin{display:inline-block;width:13px;height:13px;border:2px solid var(--line2);
    border-top-color:var(--accent);border-radius:50%;animation:sp .7s linear infinite;
    vertical-align:middle}
  @keyframes sp{to{transform:rotate(360deg)}}
  .hide{display:none}
  /* RTL for Urdu answer text */
  .rtl{direction:rtl;text-align:right;font-size:16px;line-height:1.9}
  .footnote{color:var(--dim);font-size:12px;font-family:var(--mono);margin-top:6px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Contract Clause Explainer<span class="dot">.</span></h1>
    <span class="tag">explain &middot; flag risks &middot; escalate</span>
    <div class="status">
      <span class="sdot {{ 'on' if llm_ok else 'off' }}"></span>
      <span>{{ provider }} / {{ model }}</span>
    </div>
  </header>

  <div class="langbar">
    <span class="lbl">Answer language:</span>
    <button class="lang active" data-lang="en">English</button>
    <button class="lang" data-lang="ur">اردو</button>
  </div>

  {% if not llm_ok %}
  <div class="card errbox">
    <b>LLM not reachable.</b>
    <div class="footnote">{{ llm_status }}</div>
    <div class="footnote">Paste your Groq key into config.py (GROQ["api_key"]) and restart. If a question errors, the model name in config.py may need updating.</div>
  </div>
  {% endif %}

  <div class="disclaimer" id="disc">{{ disc_en }}</div>

  <div class="card">
    <div id="drop" class="drop">
      Drop a contract PDF here, or <b>click to browse</b>
      <input id="file" type="file" accept="application/pdf" class="hide">
    </div>
    <div id="meta" class="meta">
      <span>file: <b id="m-name">—</b></span>
      <span>clauses: <b id="m-clauses">—</b></span>
      <span>pages: <b id="m-pages">—</b></span>
    </div>
    <div id="uwarn" class="uwarn"></div>
  </div>

  <div id="riskcard" class="card hide">
    <div class="risk-head">
      <h2>⚑ Clauses worth a closer look</h2>
    </div>
    <div class="risk-sub" id="risksub">Scanning the contract for unusual or risky clauses…</div>
    <div id="flags"></div>
  </div>

  <div id="qa" class="card hide">
    <div class="askrow">
      <input id="q" type="text" placeholder="Ask in plain language — e.g. How much notice must I give to leave?" autocomplete="off">
      <button class="ask" id="askbtn">Ask</button>
    </div>
    <div class="chips">
      <button class="chip">How much is my deposit and when do I get it back?</button>
      <button class="chip">How much notice must I give to leave?</button>
      <button class="chip">What happens if I pay rent late?</button>
      <button class="chip">Should I sign this?</button>
    </div>
    <div id="out"></div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
const drop=$("#drop"),file=$("#file"),meta=$("#meta"),qa=$("#qa"),out=$("#out"),
  q=$("#q"),askbtn=$("#askbtn"),uwarn=$("#uwarn"),riskcard=$("#riskcard"),
  flagsEl=$("#flags"),risksub=$("#risksub"),disc=$("#disc");
const DISC = { en: {{ disc_en|tojson }}, ur: {{ disc_ur|tojson }} };
let LANG = "en";

document.querySelectorAll(".lang").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".lang").forEach(x=>x.classList.remove("active"));
  b.classList.add("active"); LANG=b.dataset.lang;
  disc.textContent = DISC[LANG];
  disc.className = "disclaimer" + (LANG==="ur" ? " rtl":"");
});

drop.onclick=()=>file.click();
["dragover","dragenter"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add("hot");}));
["dragleave","drop"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove("hot");}));
drop.addEventListener("drop",ev=>{ if(ev.dataTransfer.files[0]) upload(ev.dataTransfer.files[0]); });
file.onchange=()=>{ if(file.files[0]) upload(file.files[0]); };

function esc(s){return (s||"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}

async function upload(f){
  drop.innerHTML='<span class="spin"></span> &nbsp;reading <b>'+esc(f.name)+'</b>…';
  uwarn.textContent=""; out.innerHTML=""; flagsEl.innerHTML="";
  const fd=new FormData(); fd.append("file",f);
  try{
    const r=await fetch("/upload",{method:"POST",body:fd});
    const d=await r.json();
    if(!r.ok){ drop.innerHTML='Drop a contract PDF here, or <b>click to browse</b>';
      uwarn.textContent="⚠ "+(d.error||"upload failed"); return; }
    drop.innerHTML='✓ loaded <b>'+esc(d.filename)+'</b> — drop another to replace';
    $("#m-name").textContent=d.filename; $("#m-clauses").textContent=d.clauses;
    $("#m-pages").textContent=d.pages; meta.classList.add("show");
    if(d.warnings&&d.warnings.length) uwarn.textContent="⚠ "+d.warnings.join("  •  ");
    qa.classList.remove("hide"); q.focus();
    if(!d.is_scanned && d.clauses>0){ runScan(); }
  }catch(e){ drop.innerHTML='Drop a contract PDF here, or <b>click to browse</b>';
    uwarn.textContent="⚠ "+e; }
}

async function runScan(){
  riskcard.classList.remove("hide");
  risksub.innerHTML='<span class="spin"></span> &nbsp;Scanning the contract for unusual or risky clauses…';
  flagsEl.innerHTML="";
  try{
    const r=await fetch("/scan",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({lang:LANG})});
    const d=await r.json();
    if(!r.ok || !d.flags){ risksub.textContent="Couldn't complete the risk scan."; return; }
    if(d.flags.length===0){ risksub.textContent="No unusual clauses jumped out — but still read the contract fully."; return; }
    risksub.textContent="I flagged "+d.flags.length+" clause(s) a person might want to look at closely. This is not legal advice.";
    flagsEl.innerHTML = d.flags.map(f=>{
      const rtl = LANG==="ur" ? " rtl":"";
      return '<div class="flag"><div class="top"><span class="sev '+f.severity+'">'
        +f.severity.toUpperCase()+'</span><span class="ref">'+esc(f.ref)+'</span></div>'
        +'<div class="reason'+rtl+'">'+esc(f.reason)+'</div>'
        +'<div class="snip">'+esc(f.snippet)+'…</div></div>';
    }).join("");
  }catch(e){ risksub.textContent="Risk scan error: "+e; }
}

document.querySelectorAll(".chip").forEach(c=>c.onclick=()=>{ q.value=c.textContent.trim(); ask(); });
askbtn.onclick=ask;
q.addEventListener("keydown",e=>{ if(e.key==="Enter") ask(); });

const ICON={answer:"✓ ANSWER",escalate:"⇪ ESCALATE",clarify:"? CLARIFY",error:"× ERROR"};

async function ask(){
  const question=q.value.trim(); if(!question) return;
  askbtn.disabled=true;
  out.innerHTML='<div class="resp"><div class="body"><span class="spin"></span> &nbsp;reading the contract…</div></div>';
  try{
    const r=await fetch("/ask",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({question,lang:LANG})});
    const d=await r.json();
    if(!r.ok) render({outcome:"error",message:d.error||"error"});
    else render(d);
  }catch(e){ render({outcome:"error",message:String(e)}); }
  askbtn.disabled=false;
}

function render(d){
  const o=d.outcome||"error";
  const rtl = (LANG==="ur") ? " rtl":"";
  let h='<div class="resp o-'+o+'"><div class="bar"><span class="pill">'+(ICON[o]||o)+'</span>';
  if(d.confidence!=null) h+='<span class="conf">confidence '+Math.round(d.confidence*100)+'%</span>';
  h+='</div><div class="body'+rtl+'">'+esc(d.message)+'</div>';
  if(d.citations&&d.citations.length)
    h+='<div class="cites">↳ '+(LANG==="ur"?"حوالہ":"cited")+': '+d.citations.map(esc).join(", ")+'</div>';
  if(d.sources&&d.sources.length){
    h+='<details><summary>show the clause text I read ('+d.sources.length+')</summary><div class="src">';
    d.sources.forEach(s=>{ h+='<div style="margin:8px 0"><span class="ref">'+esc(s[0])+'</span><br>'+esc(s[1])+'…</div>'; });
    h+='</div></details>';
  }
  if(d.trail&&d.trail.length){
    h+='<details><summary>decision trail (why this outcome)</summary><div class="trail">';
    d.trail.forEach((t,i)=>{ h+='<div><span class="n">'+(i+1)+'.</span> '+esc(t)+'</div>'; });
    h+='</div></details>';
  }
  if(d.disclaimer) h+='<div class="disc'+rtl+'">'+esc(d.disclaimer)+'</div>';
  h+='</div>';
  out.innerHTML=h;
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Contract Clause Explainer  ->  http://localhost:{port}")
    print(f"  Provider: {config.PROVIDER}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
