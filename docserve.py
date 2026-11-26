"""
docserve.py - serve the system map and accept edits from it.

    python3 tools/doc.py serve [--port 8765] [--no-push] [--interval 60]

Binds to 127.0.0.1 only. Share it with your own devices through Tailscale:
    tailscale serve --bg 8765

What it does while running:
  - every --interval seconds: pulls from GitHub (fast-forward only), rebuilds the
    model when any input changed, refreshes GitHub issues every 5 minutes;
  - serves the page, docs/media files, and /api/version (the page polls it and
    offers a reload when something changed);
  - accepts the forms on the page: each one writes the same files the terminal
    commands write (shared functions in doc.py), then commits and pushes.

It refuses to write a file that has uncommitted changes in this working copy,
so it never commits half of your own edits.
"""

import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import docmodel

doc = sys.modules.get("__main__")  # doc.py, which imports this module


class Server:
    def __init__(self, root, push=True, interval=60):
        self.root, self.push, self.interval = root, push, interval
        self.lock = threading.RLock()
        self.model, self.page, self.version, self.error = None, b"", "", None
        self.issues, self.issue_error, self.issues_at = [], "not fetched yet", 0
        self.inputs = None
        self.log = []

    # ---------------------------------------------------------------- git
    def git(self, *args, check=False):
        r = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True)
        if check and r.returncode:
            raise doc.OpError(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip()}")
        return r

    def note(self, msg):
        stamp = time.strftime("%H:%M:%S")
        self.log = (self.log + [f"{stamp} {msg}"])[-50:]
        print(f"  {stamp} {msg}", flush=True)

    def pull(self):
        if not self.git("remote").stdout.strip():
            return
        self.git("fetch", "--quiet")
        behind = self.git("rev-list", "--count", "HEAD..@{u}").stdout.strip()
        if behind and behind != "0":
            r = self.git("pull", "--ff-only", "--quiet")
            self.note(f"pulled {behind} commit(s)" if r.returncode == 0 else
                      f"could not fast-forward ({r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'local changes'})")

    # ---------------------------------------------------------------- model
    def _fingerprint(self):
        h = hashlib.sha1()
        for base in ("docs", "firmware", "ros2_ws", "tools"):
            top = os.path.join(self.root, base)
            for dirpath, dirs, files in os.walk(top):
                dirs[:] = [d for d in dirs if d not in (".git", "build", "install", "log", "Debug", "Release", "Drivers", "Middlewares")]
                for f in files:
                    if f in ("system.html", "report.html") or f.endswith((".o", ".elf", ".bin", ".map")):
                        continue
                    try:
                        st = os.stat(os.path.join(dirpath, f))
                    except OSError:
                        continue
                    h.update(f"{dirpath}/{f}:{st.st_mtime_ns}:{st.st_size}".encode())
        return h.hexdigest()

    def rebuild(self, force=False):
        with self.lock:
            fp = self._fingerprint()
            due = time.time() - self.issues_at > 300
            if not force and fp == self.inputs and not due:
                return False
            if due:
                self.issues, self.issue_error = docmodel.fetch_issues(self.root)
                self.issues_at = time.time()
            try:
                m = docmodel.build(self.root)
                docmodel.collect_extras(self.root, m, with_issues=False)
                m["issues"], m["issue_error"] = self.issues, self.issue_error
                docmodel.collect_extras_link_issues(m)
                m["served"] = {"push": self.push, "commit": self.git("rev-parse", "--short", "HEAD").stdout.strip(),
                               "firmware": self.git("describe", "--always", "--dirty").stdout.strip(),
                               "labels": doc.subsystems(), "prefixes": doc.req_prefixes()}
                data = json.dumps({k: v for k, v in m.items() if k != "built"}, sort_keys=True, default=list)
                version = hashlib.sha1(data.encode()).hexdigest()[:12]
                if version != self.version:
                    m["version"] = version
                    self.model, self.version, self.error = m, version, None
                    self.page = docmodel.page(m).encode()
                    self.note(f"model rebuilt (version {version})")
            except docmodel.ModelError as e:
                self.error = str(e)
                self.note(f"model error: {e}")
            self.inputs = fp
            return True

    def loop(self):
        while True:
            time.sleep(self.interval)
            try:
                self.pull()
                self.rebuild()
            except Exception as e:  # keep serving whatever happens
                self.note(f"background update failed: {e}")

    # ---------------------------------------------------------------- writes
    def guard(self, paths):
        for pth in paths:
            relp = os.path.relpath(pth, self.root)
            if os.path.exists(pth) and self.git("status", "--porcelain", "--", relp).stdout.strip():
                raise doc.OpError(f"{relp} has uncommitted changes in {self.root}. Commit or stash them first, "
                                  f"so the page does not commit half of your edit.")

    def commit(self, paths, message):
        rels = [os.path.relpath(x, self.root) for x in paths]
        self.git("add", "--", *rels, check=True)
        r = self.git("commit", "-m", message, "--", *rels)
        if r.returncode:
            raise doc.OpError("commit stopped: " + (r.stdout + r.stderr).strip()[-800:])
        pushed = None
        if self.push and self.git("remote").stdout.strip():
            pr = self.git("push", "--quiet")
            pushed = pr.returncode == 0
            if not pushed:
                self.note("push failed: " + pr.stderr.strip()[-200:])
        self.note(f"committed: {message}" + ("" if pushed is None else " (pushed)" if pushed else " (push FAILED)"))
        return pushed

    def apply(self, op, f, dry):
        """Run one form. dry=True returns the preview only."""
        D = doc
        lines = lambda k: [x.strip() for x in str(f.get(k, "")).splitlines() if x.strip()]
        need = lambda k: (str(f.get(k, "")).strip() or (_ for _ in ()).throw(D.OpError(f"'{k}' is required")))
        warnings, msg = [], ""
        if op == "idea" or op == "bug":
            if op == "idea":
                body, labels = D.issue_body("idea", {"what": lines("what"), "why": lines("why"), "sub": need("sub"),
                                                    "prio": f.get("prio") or "should", "questions": lines("questions")})
            else:
                body, labels = D.issue_body("bug", {"happened": lines("happened"), "expected": lines("expected"),
                                                   "steps": lines("steps"), "sub": need("sub"), "firmware": f.get("firmware", ""),
                                                   "evidence": lines("evidence")})
            title = need("title")
            preview = f"Title:  {title}\nLabels: {', '.join(labels)}\n\n{body}"
            if dry:
                return {"preview": preview, "warnings": warnings, "target": "GitHub issue"}
            num, url = D.gh_create_issue(title, body, labels)
            self.issues_at = 0
            return {"message": f"Created #{num}", "url": url}
        if op == "req":
            shall = need("shall")
            warnings = D.req_text_problems(shall)
            writes, preview, rid = D.op_requirement(need("prefix"), shall, need("rationale"), f.get("method") or "T",
                                                    f.get("status") or "Draft")
            msg = f"doc: add requirement {rid}"
        elif op == "test":
            writes, preview = D.op_test(need("rid"), need("result"), need("measured"), f.get("evidence", "").strip(),
                                        f.get("date") or D.today())
            msg = f"doc: test {f['rid'].upper()} {f['result'].lower()}"
        elif op == "fault":
            req = f.get("req", "").strip()
            if req and D.req_link_problem(req):
                warnings.append(D.req_link_problem(req))
            writes, preview, fid = D.op_fault(need("failure"), need("effect"), need("detection"), need("response"),
                                              need("recovery"), need("sev"), req)
            msg = f"doc: add fault {fid}"
        elif op == "decision":
            opts = []
            for o in f.get("options") or []:
                if str(o.get("name", "")).strip():
                    opts.append((o["name"].strip(), [x.strip() for x in o.get("pros", "").splitlines() if x.strip()],
                                 [x.strip() for x in o.get("cons", "").splitlines() if x.strip()]))
            writes, preview, notes = D.op_decision(need("title"), f.get("status") or "Accepted", f.get("related", "").strip(),
                                                   f.get("supersedes", "").strip(), lines("context"), opts,
                                                   need("decision"), need("factor"), lines("consequences"))
            warnings += notes
            msg = f"doc: decision {os.path.basename(writes[0][0])[:3]}"
        elif op == "update_req":
            rid = need("rid").upper()
            row = D._req_row(rid)
            new, field = list(row), need("field")
            if field == "status":
                val = need("value")
                new[4] = val
                change = f"Status: {row[4]} -> {val}"
                if val == "Deleted":
                    change += f" ({need('why')})"
            elif field == "text":
                val = need("value")
                warnings = D.req_text_problems(val)
                new[1] = D.cell(val)
                change = f'Requirement: was "{row[1]}"'
                if row[4] == "Verified" and f.get("retest", True):
                    new[4] = "Approved"
                    change += "; status Verified -> Approved (retest needed)"
            elif field == "rationale":
                new[2] = D.cell(need("value"))
                change = f'Rationale: was "{row[2]}"'
            else:
                new[3] = need("value")
                change = f"Method: {row[3]} -> {new[3]}"
            if new == row:
                raise D.OpError("No change.")
            writes = D.op_update_requirement(rid, new, change)
            preview = f"before: {D.join_row(row)}\nafter:  {D.join_row(new)}\nlog:    {change}"
            msg = f"doc: update {rid} ({change[:60]})"
        elif op == "update_fault":
            fid = need("fid").upper()
            row = D._fault_row(fid)
            new = list(row)
            for i, k in enumerate(["failure", "effect", "detection", "response", "recovery"], 1):
                if k in f:
                    new[i] = D.cell(str(f[k]).strip())
            if "sev" in f:
                new[6] = f["sev"]
            if "req" in f:
                new[7] = str(f["req"]).strip().upper()
                if new[7] and D.req_link_problem(new[7]):
                    warnings.append(D.req_link_problem(new[7]))
            if new == row:
                raise D.OpError("No change.")
            writes = D.op_update_fault(fid, new)
            preview = f"before: {D.join_row(row)}\nafter:  {D.join_row(new)}"
            msg = f"doc: update {fid}"
        elif op == "update_decision":
            num, field = need("num"), need("field")
            value = need("value")
            if field == "status" and value == "Superseded":
                value = f"Superseded by {need('by').zfill(3)}"
            writes = D.op_update_decision(num, field, value)
            preview = f"{field}: -> {value}"
            msg = f"doc: decision {str(num).zfill(3)} {field} -> {value}"
        else:
            raise D.OpError(f"unknown form {op}")
        self.guard([w[0] for w in writes])
        if dry:
            return {"preview": preview, "warnings": warnings,
                    "target": ", ".join(os.path.relpath(w[0], self.root) for w in writes)}
        with self.lock:
            D.apply_writes(writes)
            pushed = self.commit([w[0] for w in writes], msg)
            self.rebuild(force=True)
        return {"message": msg.replace("doc: ", "Saved: ") + ("" if pushed is None else " · pushed" if pushed else " · push failed, commit kept locally"),
                "version": self.version}

    def upload(self, name, data):
        safe = re.sub(r"[^\w.\-]+", "_", os.path.basename(name)).strip("._") or "upload"
        stem, ext = os.path.splitext(safe)
        folder = os.path.join(self.root, "docs", "media")
        os.makedirs(folder, exist_ok=True)
        fname = f"{time.strftime('%Y-%m-%d')}_{stem}{ext.lower()}"
        n = 2
        while os.path.exists(os.path.join(folder, fname)):
            fname, n = f"{time.strftime('%Y-%m-%d')}_{stem}_{n}{ext.lower()}", n + 1
        path = os.path.join(folder, fname)
        with open(path, "wb") as fh:
            fh.write(data)
        with self.lock:
            pushed = self.commit([path], f"doc: add media {fname}")
            self.rebuild(force=True)
        return {"file": fname, "message": f"Uploaded {fname}" + (" · pushed" if pushed else "")}


def make_handler(S):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/system.html", "/index.html"):
                if not S.page:
                    return self.send(500, f"<pre>doc model failed:\n{S.error}</pre>", "text/html")
                return self.send(200, S.page, "text/html; charset=utf-8")
            if path == "/api/version":
                return self.send(200, {"version": S.version, "error": S.error, "log": S.log[-8:]})
            if path.startswith("/media/"):
                rel_ = urllib.parse.unquote(path[len("/media/"):])
                base = os.path.realpath(os.path.join(S.root, "docs", "media"))
                full = os.path.realpath(os.path.join(base, rel_))
                if not full.startswith(base + os.sep) or not os.path.isfile(full):
                    return self.send(404, {"error": "not found"})
                with open(full, "rb") as fh:
                    return self.send(200, fh.read(), mimetypes.guess_type(full)[0] or "application/octet-stream")
            return self.send(404, {"error": "not found"})

        def do_POST(self):
            # a custom header forces browsers to ask first (CORS preflight), which this
            # server never answers, so other web pages cannot post here.
            if self.headers.get("X-Doc") != "1":
                return self.send(403, {"error": "missing X-Doc header"})
            path = urllib.parse.urlparse(self.path).path
            n = int(self.headers.get("Content-Length") or 0)
            if n > 200 * 1024 * 1024:
                return self.send(413, {"error": "file too large (200 MB max)"})
            raw = self.rfile.read(n)
            try:
                if path == "/api/upload":
                    return self.send(200, S.upload(urllib.parse.unquote(self.headers.get("X-Filename", "upload")), raw))
                m = re.match(r"^/api/(preview|apply)/(\w+)$", path)
                if not m:
                    return self.send(404, {"error": "not found"})
                return self.send(200, S.apply(m.group(2), json.loads(raw or b"{}"), dry=m.group(1) == "preview"))
            except doc.OpError as e:
                return self.send(400, {"error": str(e)})
            except Exception as e:
                return self.send(500, {"error": f"{type(e).__name__}: {e}"})
    return H


def serve(root, port=8765, push=True, interval=60):
    S = Server(root, push=push, interval=interval)
    print(f"doc serve: building the model for {root}", flush=True)
    S.rebuild(force=True)
    threading.Thread(target=S.loop, daemon=True).start()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(S))
    print(f"\n  open       http://127.0.0.1:{port}/")
    print(f"  share      tailscale serve --bg {port}   (your devices only)")
    print(f"  pushes     {'on' if push else 'off (--no-push)'} · checks GitHub every {interval} s · Ctrl+C stops\n", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
