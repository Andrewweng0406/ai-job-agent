from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import subprocess
import sys
from urllib.parse import urlparse

from app.database.repository import JobAgentRepository
from app.resumes.profile import CandidateProfile, profile_completeness_gate


class DashboardHandler(BaseHTTPRequestHandler):
    repo: JobAgentRepository
    profile_path: Path

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/api/state":
            self._json(self._state())
        elif route == "/":
            self._html()
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/api/discover":
            # Discovery is read-only; application submission has no dashboard route.
            result = subprocess.run([sys.executable, "apply company.py", "--discover"],
                                    capture_output=True, text=True, check=False)
            self._json({"returncode": result.returncode, "output": result.stdout[-4000:]})
        elif route in {"/api/queue", "/api/prepare", "/api/dry-run"}:
            command = {"/api/queue": "--queue-eligible", "/api/prepare": "--prepare-next",
                       "/api/dry-run": "--dry-run-next"}[route]
            result = subprocess.run([sys.executable, "apply company.py", command],
                                    capture_output=True, text=True, check=False)
            self._json({"returncode": result.returncode, "output": (result.stdout + result.stderr)[-4000:]})
        else:
            self.send_error(404)

    def _state(self) -> dict:
        profile = CandidateProfile.from_yaml(self.profile_path)
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
                "jobs": jobs, "applications": applications, "human_tasks": tasks,
                "safety": {"real_submission_enabled": False, "submit_endpoint": False}}

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self) -> None:
        body = DASHBOARD_HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


DASHBOARD_HTML = """<!doctype html><html><head><meta charset=utf-8><title>Job Agent</title>
<style>body{font:15px system-ui;margin:32px;background:#f5f6f8;color:#17202a}main{max-width:1100px;margin:auto}header{display:flex;justify-content:space-between;align-items:center}button{padding:9px 14px;border:1px solid #87909a;border-radius:6px;background:white;cursor:pointer}section{background:white;border:1px solid #d8dde3;border-radius:6px;padding:18px;margin:16px 0}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:9px;border-bottom:1px solid #e5e8eb}.status{font-weight:650}.safe{color:#147d45}.warn{color:#a45b00}</style></head>
<body><main><header><div><h1>Job Application Agent</h1><p>Discovery, review, and safe dry-runs</p></div><div><button onclick="discover()">Search jobs</button> <button onclick="run('queue')">Queue eligible</button> <button onclick="run('prepare')">Prepare next</button> <button onclick="run('dry-run')">Build dry-run</button></div></header>
<section id=profile>Loading profile...</section><section><h2>Jobs</h2><table id=jobs></table></section><section><h2>Applications</h2><table id=apps></table></section><section><h2>Human review queue</h2><table id=tasks></table></section>
<script>const esc=x=>String(x??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
async function load(){let s=await (await fetch('/api/state')).json();profile.innerHTML=`<h2>Profile</h2><p class="${s.profile.complete?'safe':'warn'}">${s.profile.complete?'Ready for review':'Missing: '+s.profile.missing.join(', ')}</p><p>Submission is permanently disabled in this dashboard.</p>`; jobs.innerHTML='<tr><th>Company</th><th>Role</th><th>Location</th><th>ATS</th><th>Status</th></tr>'+s.jobs.map(j=>`<tr><td>${esc(j.company_name)}</td><td>${esc(j.title)}</td><td>${esc(j.location)}</td><td>${esc(j.source)}</td><td class=status>${esc(j.status)}</td></tr>`).join('');apps.innerHTML='<tr><th>Company</th><th>Role</th><th>Status</th><th>Reason</th></tr>'+s.applications.map(a=>`<tr><td>${esc(a.company)}</td><td>${esc(a.position)}</td><td>${esc(a.status)}</td><td>${esc(a.human_required_reason)}</td></tr>`).join('');tasks.innerHTML='<tr><th>Category</th><th>Task</th><th>Status</th></tr>'+s.human_tasks.map(t=>`<tr><td>${esc(t.category)}</td><td>${esc(t.title)}</td><td>${esc(t.status)}</td></tr>`).join('')}
async function discover(){await fetch('/api/discover',{method:'POST'});await load()}async function run(x){await fetch('/api/'+x,{method:'POST'});await load()}load();</script></main></body></html>"""


def serve(*, host: str = "127.0.0.1", port: int = 8765,
          database: str = "data/job_agent.sqlite3",
          profile: str = "config/candidate_profile.local.yaml") -> None:
    handler = DashboardHandler
    handler.repo = JobAgentRepository(database)
    handler.repo.initialize()
    handler.profile_path = Path(profile if Path(profile).exists() else "config/candidate_profile.yaml")
    ThreadingHTTPServer((host, port), handler).serve_forever()
