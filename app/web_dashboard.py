from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import re
import subprocess
import sys
from urllib.parse import urlparse, parse_qs

from app.applications.assisted_answers import AnswersError, load_answers
from app.applications.batch_prepare import BatchRecord
from app.applications.review_packet import ReviewPacket
from app.database.repository import JobAgentRepository
from app.llm.budget import SQLiteDailyBudget
from app.llm.runtime import runtime_status
from app.resumes.profile import CandidateProfile, profile_completeness_gate
from app.utils.config import load_yaml

_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class DashboardHandler(BaseHTTPRequestHandler):
    repo: JobAgentRepository
    profile_path: Path
    settings_path: Path
    review_root: Path = Path("review")

    # ---------------------------------------------------------------- routing
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route, query = parsed.path, parse_qs(parsed.query)
        if route == "/api/state":
            self._json(self._state())
        elif route == "/api/packets":
            self._json({"packets": self._list_packets()})
        elif route == "/api/packet":
            self._packet_detail(query.get("dir", [""])[0])
        elif route == "/api/batch":
            self._json({"items": self._list_batch()})
        elif route == "/api/batch/item":
            self._batch_detail(query.get("dir", [""])[0])
        elif route.startswith("/batch/") and route.endswith("/filled.png"):
            self._batch_screenshot(route[len("/batch/"):-len("/filled.png")])
        elif route == "/":
            self._html()
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        simple = {"/api/discover": ["--discover"], "/api/queue": ["--queue-eligible"],
                  "/api/prepare": ["--prepare-next"], "/api/dry-run": ["--dry-run-next"]}
        if route in simple:
            self._run(simple[route])
        elif route == "/api/packet/create":
            self._packet_create(self._body())
        elif route == "/api/packet/answers":
            self._packet_answers(self._body())
        elif route == "/api/packet/fill":
            self._packet_fill(self._body())
        elif route == "/api/batch/prepare":
            self._batch_prepare(self._body())
        elif route == "/api/batch/approve":
            self._batch_approve(self._body())
        elif route == "/api/batch/skip":
            self._batch_skip(self._body())
        else:
            self.send_error(404)

    # ---------------------------------------------------------------- batch review
    def _batch_root(self) -> Path:
        return self.review_root / "batch"

    def _safe_batch_dir(self, name: str) -> Path | None:
        if not name or not _SLUG_RE.match(name):
            return None
        d = (self._batch_root() / name).resolve()
        if self._batch_root().resolve() not in d.parents:
            return None
        return d

    def _list_batch(self) -> list[dict]:
        out: list[dict] = []
        root = self._batch_root()
        if not root.exists():
            return out
        for d in sorted(root.iterdir()):
            rj = d / "record.json"
            if not rj.is_file():
                continue
            try:
                raw = json.loads(rj.read_text())
            except json.JSONDecodeError:
                continue
            fields = raw.get("fields", [])
            resolved_sources = {"profile", "standard_answer", "essay"}
            required_fields = [field for field in fields if field.get("required")]
            required_resolved = sum(
                1 for field in required_fields if field.get("source") in resolved_sources
            )
            total_resolved = sum(
                1 for field in fields if field.get("source") in resolved_sources
            )
            out.append({
                "dir": d.name,
                "company": raw.get("company", "?"),
                "role": raw.get("role", "?"),
                "blocked": bool(raw.get("blocked")),
                "reasons": raw.get("reasons", []),
                "ready": bool(raw.get("ready")) and not raw.get("blocked"),
                "skipped": (d / ".skipped").is_file(),
                "auto_count": sum(1 for f in fields if f.get("source") in {"profile", "standard_answer", "essay"}),
                "required_count": len(required_fields),
                "required_resolved": required_resolved,
                "required_coverage": round(100 * required_resolved / len(required_fields)) if required_fields else 0,
                "total_coverage": round(100 * total_resolved / len(fields)) if fields else 0,
                "blocker_count": len(raw.get("blockers", [])),
                "has_essay": bool(raw.get("essay_text")),
                "has_shot": (d / "filled.png").is_file(),
            })
        return out

    def _batch_detail(self, name: str) -> None:
        d = self._safe_batch_dir(name)
        if d is None or not (d / "record.json").is_file():
            self.send_error(404)
            return
        self._json({"dir": name, "has_shot": (d / "filled.png").is_file(),
                    "record": json.loads((d / "record.json").read_text())})

    def _batch_screenshot(self, name: str) -> None:
        d = self._safe_batch_dir(name)
        if d is None or not (d / "filled.png").is_file():
            self.send_error(404)
            return
        blob = (d / "filled.png").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def _batch_prepare(self, body: dict) -> None:
        limit = max(1, min(40, int(body.get("limit") or 10)))
        resume_pdf = str(body.get("resume_pdf") or "data/resumes/andrew_weng_master.pdf")
        cmd = [sys.executable, "scripts/batch_prepare.py", "--limit", str(limit),
               "--profile", str(self.profile_path), "--resume-pdf", resume_pdf]
        subprocess.Popen(cmd)
        self._json({"ok": True, "message": f"Preparing up to {limit} applications — refresh in ~1 min."})

    def _batch_approve(self, body: dict) -> None:
        d = self._safe_batch_dir(str(body.get("dir") or ""))
        if d is None or not (d / "record.json").is_file():
            self._json({"ok": False, "error": "unknown record"})
            return
        raw = json.loads((d / "record.json").read_text())
        if raw.get("blocked"):
            self._json({"ok": False, "error": "record is blocked"})
            return
        if not BatchRecord.from_dict(raw).ready:
            self._json({"ok": False, "error": "record has unresolved or failed fields"})
            return
        keep = max(60, min(3600, int(body.get("keep_open_seconds") or 900)))
        subprocess.Popen([sys.executable, "scripts/batch_fill.py", "--record", str(d),
                          "--keep-open-seconds", str(keep)])
        self._json({"ok": True, "message": "A browser window is opening — review and click Submit yourself."})

    def _batch_skip(self, body: dict) -> None:
        d = self._safe_batch_dir(str(body.get("dir") or ""))
        if d is None:
            self._json({"ok": False, "error": "unknown record"})
            return
        (d / ".skipped").write_text("")
        self._json({"ok": True})

    # ---------------------------------------------------------------- review packets
    def _safe_dir(self, name: str) -> Path | None:
        if not name or not _SLUG_RE.match(name):
            return None
        d = (self.review_root / name).resolve()
        if self.review_root.resolve() not in d.parents:
            return None
        return d

    def _list_packets(self) -> list[dict]:
        out: list[dict] = []
        if not self.review_root.exists():
            return out
        for d in sorted(self.review_root.iterdir()):
            pj = d / "packet.json"
            if not pj.is_file():
                continue
            try:
                raw = json.loads(pj.read_text())
            except json.JSONDecodeError:
                continue
            out.append({
                "dir": d.name,
                "company": raw.get("company", "?"),
                "role": raw.get("role", "?"),
                "blocked": bool(raw.get("blocked")),
                "safe_count": len(raw.get("safe_prefill", [])),
                "question_count": len(raw.get("needs_your_answer", [])),
                "answers_present": (d / "answers.yaml").is_file(),
                "ready": bool(raw.get("ready_for_assisted_fill")) and not raw.get("blocked"),
            })
        return out

    def _packet_detail(self, name: str) -> None:
        d = self._safe_dir(name)
        if d is None or not (d / "packet.json").is_file():
            self.send_error(404)
            return
        raw = json.loads((d / "packet.json").read_text())
        existing = (d / "answers.yaml").read_text() if (d / "answers.yaml").is_file() else ""
        self._json({"dir": name, "packet": raw, "answers_yaml": existing})

    def _packet_create(self, body: dict) -> None:
        url = str(body.get("url") or "").strip()
        company = str(body.get("company") or "").strip()
        ats = str(body.get("ats") or "greenhouse").strip()
        resume_pdf = str(body.get("resume_pdf") or "").strip()
        if not url.startswith("https://") or not company or ats not in {"greenhouse", "lever", "ashby"}:
            self._json({"ok": False, "error": "need https url, company, and ats in {greenhouse,lever,ashby}"})
            return
        slug = re.sub(r"[^A-Za-z0-9]+", "-", f"{company}-{url.rsplit('/', 1)[-1]}").strip("-").lower()[:80]
        cmd = [sys.executable, "scripts/assisted_apply.py", "packet", "--url", url,
               "--company", company, "--ats", ats, "--profile", str(self.profile_path),
               "--out", str(self.review_root / slug)]
        if resume_pdf:
            cmd += ["--resume-pdf", resume_pdf]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self._json({"ok": result.returncode == 0, "dir": slug,
                    "output": (result.stdout + result.stderr)[-4000:]})

    def _packet_answers(self, body: dict) -> None:
        d = self._safe_dir(str(body.get("dir") or ""))
        if d is None or not (d / "packet.json").is_file():
            self._json({"ok": False, "error": "unknown packet"})
            return
        raw = json.loads((d / "packet.json").read_text())
        if raw.get("blocked"):
            self._json({"ok": False, "error": "packet is blocked"})
            return
        doc = {
            "approved_by": str(body.get("approved_by") or "").strip(),
            "approved_at": str(body.get("approved_at") or "").strip(),
            "answers": {str(k): str(v) for k, v in (body.get("answers") or {}).items() if str(v).strip()},
        }
        (d / "answers.yaml").write_text(_dump_yaml(doc), encoding="utf-8")
        try:
            load_answers(d / "answers.yaml", ReviewPacket.from_dict(raw))
        except AnswersError as exc:
            self._json({"ok": False, "saved": True, "error": str(exc)})
            return
        self._json({"ok": True, "saved": True, "message": "answers valid and approved"})

    def _packet_fill(self, body: dict) -> None:
        d = self._safe_dir(str(body.get("dir") or ""))
        if d is None or not (d / "answers.yaml").is_file():
            self._json({"ok": False, "error": "save & validate your answers first"})
            return
        resume_pdf = str(body.get("resume_pdf") or "").strip()
        keep_open = max(60, min(3600, int(body.get("keep_open_seconds") or 900)))
        cmd = [sys.executable, "scripts/assisted_apply.py", "fill", "--packet", str(d),
               "--profile", str(self.profile_path), "--headed", "--keep-open-seconds", str(keep_open)]
        if resume_pdf:
            cmd += ["--resume-pdf", resume_pdf]
        subprocess.Popen(cmd)  # headed browser opens on this machine for the human
        self._json({"ok": True, "message": "A browser window is opening — review the form and click Submit yourself."})

    # ---------------------------------------------------------------- pipeline + state
    def _run(self, args: list[str]) -> None:
        result = subprocess.run([sys.executable, "apply company.py", *args],
                                capture_output=True, text=True, check=False)
        self._json({"returncode": result.returncode, "output": (result.stdout + result.stderr)[-4000:]})

    def _state(self) -> dict:
        profile = CandidateProfile.from_yaml(self.profile_path)
        settings = load_yaml(self.settings_path)
        llm_status = runtime_status(settings)
        llm_config = settings.get("llm") or {}
        ledger_path = Path(str(llm_config.get("usage_ledger_path", "data/llm_usage.sqlite3")))
        spent_today = SQLiteDailyBudget(ledger_path).spent_today() if ledger_path.exists() else 0.0
        with self.repo.connect() as conn:
            jobs = [dict(row) for row in conn.execute(
                "SELECT id, company_name, title, location, status, source, apply_url FROM jobs ORDER BY discovered_at DESC LIMIT 100"
            )]
            applications = [dict(row) for row in conn.execute(
                "SELECT application_id, company, position, status, human_required_reason FROM applications ORDER BY COALESCE(queued_at, discovered_at) DESC LIMIT 100"
            )]
            tasks = [dict(row) for row in conn.execute(
                "SELECT task_id, category, status, prompt AS title FROM human_tasks WHERE status != 'DONE' ORDER BY created_at DESC LIMIT 100"
            )]
        return {"profile": {"candidate_id": profile.candidate_id,
                             "complete": profile_completeness_gate(profile).complete,
                             "missing": profile.required_missing_fact_ids()},
                "llm": {"enabled": llm_status.enabled, "configured": llm_status.configured,
                        "status": llm_status.reason, "cheap_model": llm_status.cheap_model,
                        "strong_model": llm_status.strong_model,
                        "send_candidate_pii": llm_status.send_candidate_pii,
                        "spent_today_usd": spent_today,
                        "daily_limit_usd": float(llm_config.get("daily_cost_limit_usd", 5.0))},
                "jobs": jobs, "applications": applications, "human_tasks": tasks,
                "safety": {"real_submission_enabled": False, "submit_endpoint": False}}

    # ---------------------------------------------------------------- io helpers
    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _json(self, payload: dict) -> None:
        blob = json.dumps(payload, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def _html(self) -> None:
        blob = DASHBOARD_HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def log_message(self, *args) -> None:  # keep the console quiet
        pass


def _dump_yaml(doc: dict) -> str:
    lines = [f"approved_by: {json.dumps(doc['approved_by'])}",
             f"approved_at: {json.dumps(doc['approved_at'])}", "answers:"]
    for key, value in doc["answers"].items():
        lines.append(f"  {key}: {json.dumps(value)}")
    return "\n".join(lines) + "\n"


DASHBOARD_HTML = r"""<!doctype html><html><head><meta charset=utf-8><title>Job Agent</title>
<style>
body{font:15px system-ui;margin:28px;background:#f5f6f8;color:#17202a}main{max-width:1080px;margin:auto}
header{display:flex;justify-content:space-between;align-items:center}
button{padding:8px 13px;border:1px solid #87909a;border-radius:6px;background:#fff;cursor:pointer}
button.primary{background:#12603a;color:#fff;border-color:#12603a}
button:disabled{background:#e5e7eb;color:#7a828a;border-color:#c9ced4;cursor:not-allowed}
.button-link{display:inline-block;padding:8px 13px;border:1px solid #87909a;border-radius:6px;color:#17202a;text-decoration:none;background:#fff}
section{background:#fff;border:1px solid #d8dde3;border-radius:6px;padding:18px;margin:16px 0}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:8px;border-bottom:1px solid #e5e8eb;vertical-align:top}
.status{font-weight:650}.safe{color:#147d45}.warn{color:#a45b00}
.pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;background:#eef1f4}
label{display:block;margin:10px 0 3px;font-weight:600}
input[type=text],textarea,select{width:100%;padding:7px;border:1px solid #b7bec6;border-radius:5px;font:inherit}
textarea{min-height:70px}.q{border-top:1px solid #eee;padding-top:10px;margin-top:10px}
.hint{color:#5b6670;font-size:13px}#detail{display:none}#bDetail{display:none}
.pill.safe{background:#d8f0e2;color:#12603a}
.notice{background:#fff8e6;border:1px solid #e6cf87;padding:8px 12px;border-radius:5px;margin:8px 0}
</style></head>
<body><main>
<header><div><h1>Job Application Agent</h1><p>Discovery → review → assisted apply. Submission is always your click.</p></div>
<div><button onclick="discover()">Search jobs</button> <button onclick="run('queue')">Queue eligible</button> <button onclick="run('prepare')">Prepare next</button></div></header>

<section id=profile>Loading…</section>
<section id=llm></section>

<section>
  <h2>New review packet</h2>
  <div class=hint>Paste a job's application URL. The agent loads the form and lists what it can pre-fill vs. what needs you.</div>
  <label>Application URL</label><input id=cUrl type=text placeholder="https://boards.greenhouse.io/acme/jobs/123">
  <div style="display:flex;gap:10px">
    <div style="flex:2"><label>Company</label><input id=cCompany type=text placeholder="Acme"></div>
    <div style="flex:1"><label>ATS</label><select id=cAts><option>greenhouse</option><option>lever</option><option>ashby</option></select></div>
  </div>
  <label>Résumé PDF path (optional)</label><input id=cResume type=text placeholder="data/resumes/…_resume.pdf">
  <p><button class=primary onclick="createPacket()">Build packet</button> <span id=cMsg class=hint></span></p>
</section>

<section><h2>Review packets</h2><table id=packets></table></section>

<section id=detail>
  <h2 id=dTitle></h2>
  <div id=dSafe></div>
  <h3>Your answers</h3>
  <div id=dQuestions></div>
  <div style="display:flex;gap:10px;margin-top:12px">
    <div style="flex:1"><label>Approved by</label><input id=dBy type=text placeholder="your name"></div>
    <div style="flex:1"><label>Approved at (ISO-8601)</label><input id=dAt type=text></div>
  </div>
  <p>
    <button class=primary onclick="saveAnswers()">Save &amp; validate</button>
    <button onclick="fillNow()">Open browser &amp; fill (you submit)</button>
    <span id=dMsg class=hint></span>
  </p>
  <div class=notice>Nothing here submits. “Open browser &amp; fill” pre-fills the form in a visible window; you review it and click Submit.</div>
</section>

<section>
  <h2>Batch review</h2>
  <div class=hint>Prepare fills every mappable field + an essay draft for queued applications and screenshots the form. You review each and click Submit.</div>
  <p>
    Résumé: <input id=bResume type=text value="data/resumes/andrew_weng_master.pdf" style="width:340px">
    &nbsp;<button class=primary onclick="batchPrepare()">Prepare 10</button>
    <span id=bMsg class=hint></span>
  </p>
  <table id=batch></table>
</section>
<section id=bDetail>
  <h2 id=bTitle></h2>
  <p id=bBlockers class=warn></p>
  <div id=bEssay></div>
  <img id=bShot alt="filled form" style="max-width:100%;border:1px solid #ccc;margin:8px 0">
  <div id=bFields class=hint></div>
  <p>
    <a id=bVisit class=button-link target="_blank" rel="noopener noreferrer">Open application website</a>
    <button id=bApprove class=primary onclick="batchApprove()">Open browser &amp; fill (you submit)</button>
    <button onclick="batchSkip()">Skip</button>
    <span id=bDMsg class=hint></span>
  </p>
  <div class=notice>Nothing here submits. The browser opens pre-filled; you review and click Submit.</div>
</section>

<section><h2>Applications</h2><table id=apps></table></section>
<section><h2>Human review queue</h2><table id=tasks></table></section>

<script>
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let CUR=null;
async function load(){
  const s=await (await fetch('/api/state')).json();
  profile.innerHTML=`<h2>Profile</h2><p class="${s.profile.complete?'safe':'warn'}">${s.profile.complete?'Complete':'Missing: '+s.profile.missing.join(', ')}</p><p class=hint>Candidate: ${esc(s.profile.candidate_id)} · submission is permanently disabled in this dashboard.</p>`;
  llm.innerHTML=`<h2>AI cost control</h2><p class="${s.llm.status==='READY'?'safe':'warn'}">${esc(s.llm.status)}</p><p class=hint>$${Number(s.llm.spent_today_usd).toFixed(4)} / $${Number(s.llm.daily_limit_usd).toFixed(2)} today · candidate PII ${s.llm.send_candidate_pii?'ALLOWED':'blocked'}</p>`;
  apps.innerHTML='<tr><th>Company</th><th>Role</th><th>Status</th><th>Reason</th></tr>'+s.applications.map(a=>`<tr><td>${esc(a.company)}</td><td>${esc(a.position)}</td><td class=status>${esc(a.status)}</td><td>${esc(a.human_required_reason)}</td></tr>`).join('');
  tasks.innerHTML='<tr><th>Category</th><th>Task</th><th>Status</th></tr>'+s.human_tasks.map(t=>`<tr><td>${esc(t.category)}</td><td>${esc(t.title)}</td><td>${esc(t.status)}</td></tr>`).join('');
  loadPackets(); loadBatch();
}
let BCUR=null;
async function loadBatch(){
  const {items}=await (await fetch('/api/batch')).json();
  batch.innerHTML='<tr><th>Company</th><th>Role</th><th>Required coverage</th><th>Total coverage</th><th>Needs you</th><th>Status</th><th></th></tr>'+
    (items.map(it=>`<tr><td>${esc(it.company)}</td><td>${esc(it.role)}</td><td>${it.blocked?'—':it.required_coverage+'% ('+it.required_resolved+'/'+it.required_count+')'}</td><td>${it.blocked?'—':it.total_coverage+'%'}</td>
      <td>${it.blocked?'—':it.blocker_count}</td>
      <td>${it.skipped?'<span class=pill>skipped</span>':it.blocked?('<span class=pill>'+esc((it.reasons||['blocked'])[0])+'</span>'):it.ready?'<span class="pill safe">ready</span>':'<span class=pill>attention</span>'}</td>
      <td><button onclick="openBatch('${esc(it.dir)}')">Open</button></td></tr>`).join('') || '<tr><td>No prepared applications. Click “Prepare 10”.</td></tr>');
}
async function batchPrepare(){
  bMsg.textContent='preparing… (loads each live form, ~6s each)';
  const r=await (await fetch('/api/batch/prepare',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({limit:10,resume_pdf:bResume.value})})).json();
  bMsg.textContent=r.message||JSON.stringify(r);
  setTimeout(loadBatch,4000);
}
async function openBatch(dir){
  const x=await (await fetch('/api/batch/item?dir='+encodeURIComponent(dir))).json();
  const rec=x.record;
  BCUR=dir; bDetail.style.display='block'; bDetail.scrollIntoView({behavior:'smooth'});
  bTitle.textContent=`${rec.role||'?'} @ ${rec.company||'?'}`;
  bVisit.href=String(rec.apply_url||'').startsWith('https://')?rec.apply_url:'#';
  bApprove.disabled=true;
  if(rec.blocked){bBlockers.textContent='Blocked: '+((rec.reasons||[]).join(', '));bEssay.innerHTML='';bShot.removeAttribute('src');bShot.style.display='none';bFields.innerHTML='';return;}
  bBlockers.textContent=(rec.blockers||[]).length?('Still needs you in the browser: '+rec.blockers.join('; ')):'';
  const drafts=(rec.fields||[]).filter(f=>f.source==='essay'&&f.value);
  bEssay.innerHTML=drafts.length?('<h3>AI drafts — read before submitting</h3>'+drafts.map(f=>
    `<p class=hint style="margin:6px 0 2px">${esc(f.label)}</p><p style="white-space:pre-wrap;background:#f6f8fa;padding:10px;border-radius:5px">${esc(f.value)}</p>`).join('')):'';
  if(x.has_shot){bShot.src='/batch/'+encodeURIComponent(dir)+'/filled.png?t='+Date.now();bShot.style.display='block';}
  else{bShot.removeAttribute('src');bShot.style.display='none';}
  const need=(rec.fields||[]).filter(f=>['unresolved','must_queue'].includes(f.source));
  bFields.innerHTML=(need.length?('<h3 class=warn>You finish these in the browser</h3>'+need.map(f=>`• ${esc(f.label)} <span class=hint>(${esc(f.reason||f.source)})</span>`).join('<br>')+'<br><br>'):'')
    +'<h3>All fields</h3>'+(rec.fields||[]).map(f=>`<span class=hint>${esc(f.source)}</span> · ${esc(f.label)} → ${esc(f.display||'')}`).join('<br>');
  bApprove.disabled=!rec.ready;
}
async function batchApprove(){
  if(!confirm('Open a browser and pre-fill this application? It will NOT be submitted — you review and click Submit.'))return;
  bDMsg.textContent='opening browser…';
  const r=await (await fetch('/api/batch/approve',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({dir:BCUR})})).json();
  bDMsg.textContent=r.ok?r.message:('✗ '+r.error);
}
async function batchSkip(){
  await fetch('/api/batch/skip',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({dir:BCUR})});
  bDetail.style.display='none'; loadBatch();
}
async function loadPackets(){
  const {packets:ps}=await (await fetch('/api/packets')).json();
  packets.innerHTML='<tr><th>Company</th><th>Role</th><th>Pre-fill</th><th>You answer</th><th>Answers</th><th></th></tr>'+
    (ps.map(p=>`<tr><td>${esc(p.company)}</td><td>${esc(p.role)}</td><td>${p.safe_count}</td><td>${p.question_count}</td>
      <td>${p.blocked?'<span class=pill>blocked</span>':p.answers_present?'<span class=pill>saved</span>':'—'}</td>
      <td><button onclick="openPacket('${esc(p.dir)}')">Open</button></td></tr>`).join('') || '<tr><td>No packets yet.</td></tr>');
}
async function createPacket(){
  cMsg.textContent='building… loads the live form, ~10s';
  const r=await (await fetch('/api/packet/create',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({url:cUrl.value,company:cCompany.value,ats:cAts.value,resume_pdf:cResume.value})})).json();
  cMsg.textContent=r.ok?('created: '+r.dir):('failed — '+String(r.error||r.output||'').slice(0,200));
  loadPackets(); if(r.ok) openPacket(r.dir);
}
async function openPacket(dir){
  const r=await (await fetch('/api/packet?dir='+encodeURIComponent(dir))).json();
  CUR={dir,packet:r.packet};
  detail.style.display='block'; detail.scrollIntoView({behavior:'smooth'});
  dTitle.textContent=`${r.packet.role} @ ${r.packet.company}`;
  if(r.packet.blocked){dSafe.innerHTML=`<p class=warn>Blocked: ${esc((r.packet.reasons||[]).join(', '))}</p>`;dQuestions.innerHTML='';return;}
  dSafe.innerHTML='<h3>The agent pre-fills these from your profile</h3><ul>'+
    r.packet.safe_prefill.map(s=>`<li><b>${esc(s.label)}</b> <span class=hint>${esc(s.canonical_key||s.kind)} · e.g. ${esc(s.value_hint)}</span></li>`).join('')+'</ul>';
  const prev={};
  (r.answers_yaml.match(/^\s{2}\S+:.*$/gm)||[]).forEach(l=>{const m=l.match(/^\s{2}(\S+):\s*"?(.*?)"?\s*$/);if(m)prev[m[1]]=m[2];});
  dQuestions.innerHTML=r.packet.needs_your_answer.map(q=>{
    const cur=prev[q.field_id]||'';
    const ctl=(q.options&&q.options.length)
      ? `<select id="a_${q.field_id}"><option value="">— choose —</option>`+q.options.map(o=>`<option${o===cur?' selected':''}>${esc(o)}</option>`).join('')+`</select>`
      : (q.kind==='long_text'?`<textarea id="a_${q.field_id}">${esc(cur)}</textarea>`:`<input type=text id="a_${q.field_id}" value="${esc(cur)}">`);
    return `<div class=q><label>${esc(q.label)} ${q.required?'<span class=warn>*</span>':''}</label>${ctl}<div class=hint>${esc(q.why)}</div></div>`;
  }).join('');
  dBy.value=(r.answers_yaml.match(/approved_by:\s*"?(.*?)"?\s*$/m)||[])[1]||'';
  dAt.value=(r.answers_yaml.match(/approved_at:\s*"?(.*?)"?\s*$/m)||[])[1]||new Date().toISOString();
}
function collect(){
  const a={};
  (CUR.packet.needs_your_answer||[]).forEach(q=>{const el=document.getElementById('a_'+q.field_id);if(el&&el.value.trim())a[q.field_id]=el.value.trim();});
  return a;
}
async function saveAnswers(){
  dMsg.textContent='saving…';
  const r=await (await fetch('/api/packet/answers',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({dir:CUR.dir,approved_by:dBy.value,approved_at:dAt.value,answers:collect()})})).json();
  dMsg.textContent=r.ok?'✓ valid and approved':('✗ '+r.error);
  loadPackets();
}
async function fillNow(){
  if(!confirm('Open a browser window and pre-fill this form? It will NOT be submitted — you review and click Submit.'))return;
  dMsg.textContent='opening browser…';
  const r=await (await fetch('/api/packet/fill',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({dir:CUR.dir,resume_pdf:cResume.value})})).json();
  dMsg.textContent=r.ok?r.message:('✗ '+r.error);
}
async function discover(){await fetch('/api/discover',{method:'POST'});load();}
async function run(x){await fetch('/api/'+x,{method:'POST'});load();}
load();
</script>
</main></body></html>"""


def serve(*, host: str = "127.0.0.1", port: int = 8765,
          database: str = "data/job_agent.sqlite3",
          profile: str = "config/candidate_profile.local.yaml",
          settings: str = "config/settings.yaml") -> None:
    from app.utils.env import load_dotenv
    load_dotenv()
    handler = DashboardHandler
    handler.repo = JobAgentRepository(database)
    handler.repo.initialize()
    handler.profile_path = Path(profile if Path(profile).exists() else "config/candidate_profile.yaml")
    handler.settings_path = Path(settings)
    print(f"Dashboard on http://{host}:{port}  (submission disabled; assisted-apply opens a browser you drive)")
    ThreadingHTTPServer((host, port), handler).serve_forever()


if __name__ == "__main__":
    serve()
