"""
docserve.py - serve the system map and accept edits from it.

    python3 tools/doc-kit/doc.py serve [--port 8765] [--no-push] [--interval 60] [--no-open]

Binds to 127.0.0.1 only. Share it with your own devices through Tailscale:
    tailscale serve --bg 8765

What it does while running:
  - every --interval seconds: pulls from GitHub (fast-forward only), rebuilds the
    model when any input changed, refreshes GitHub issues every 5 minutes;
  - serves the page, docs/media files, and /api/version (the page polls it and
    offers a reload when something changed);
  - accepts the forms on the page: records (doc.py op_* functions) and the model
    editor (docedit.py: Setup, parts, wiring), then commits and pushes.

It refuses to write a file that has uncommitted changes in this working copy,
so it never commits half of your own edits.
"""

import difflib
import hashlib
import json
import mimetypes
import queue
import os
import re
import shutil
import subprocess
import tempfile
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import docedit
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
        # network work (git push, GitHub calls) runs one job at a time in the background, so saving is instant
        self.jobs, self.pending, self.sync_error, self.push_wanted = queue.Queue(), 0, None, False
        self.model_json = b"{}"
        self.want_status, self.issue_jobs, self.repo = {}, 0, {}
        threading.Thread(target=self._repo_info, daemon=True).start()
        threading.Thread(target=self.worker, daemon=True).start()

    def _repo_info(self):
        try:
            r = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner,defaultBranchRef"], cwd=self.root,
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                j = json.loads(r.stdout)
                self.repo = {"slug": j.get("nameWithOwner", ""), "branch": (j.get("defaultBranchRef") or {}).get("name", "main")}
        except Exception:
            pass

    def later(self, label, fn):
        self.pending += 1
        self.jobs.put((label, fn))

    def worker(self):
        while True:
            label, fn = self.jobs.get()
            try:
                fn()
            except Exception as e:
                self.sync_error = f"{time.strftime('%H:%M:%S')} {label}: {e}"
                self.note(f"sync failed: {label}: {e}")
            finally:
                self.pending -= 1

    def want_push(self):
        if not (self.push and self.git("remote").stdout.strip()) or self.push_wanted:
            return
        self.push_wanted = True

        def job():
            self.push_wanted = False
            if self._push() is False:
                raise RuntimeError("git push failed; the commit is kept on this computer and is pushed with the next change")
        self.later("push", job)

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
        self.git("fetch", "--quiet")  # network, outside the lock
        behind = self.git("rev-list", "--count", "HEAD..@{u}").stdout.strip()
        if behind and behind != "0":
            with self.lock:
                r = self.git("merge", "--ff-only", "--quiet", "@{u}")
            self.note(f"pulled {behind} commit(s)" if r.returncode == 0 else
                      f"could not fast-forward ({r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'local changes'})")

    # ---------------------------------------------------------------- model
    def _fingerprint(self):
        h = hashlib.sha1()
        bases = ["docs", "firmware", "ros2_ws", "software", "tools"]
        try:
            cfg = docmodel.load_config(self.root)
            bases += list(cfg["ros"]["paths"]) + [os.path.dirname(b.get("ioc", "")) for b in cfg["board"]]
        except docmodel.ModelError:
            pass
        for base in dict.fromkeys(b for b in bases if b):
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

    def rebuild(self, force=False, issues=True):
        """issues=False: never wait for GitHub (used while a request waits for the answer)."""
        with self.lock:
            fp = self._fingerprint()
            due = issues and time.time() - self.issues_at > 300
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
                               "labels": doc.subsystems(), "prefixes": [(r[0], r[1]) for r in doc.subsystem_rows()],
                               "setup": docedit.setup_info(self.root, m), "checklist": doc.checklist_sections(),
                               "history": (lambda h: {"undo": [c["subj"] for c in h[0][-30:]][::-1], "redo": [c["subj"] for c in h[1][-30:]][::-1]})(self.history()),
                               "repo": self.repo,
                               "procedures": sorted(os.listdir(os.path.join(self.root, "docs", "procedures")))
                               if os.path.isdir(os.path.join(self.root, "docs", "procedures")) else []}
                data = json.dumps({k: v for k, v in m.items() if k != "built"}, sort_keys=True, default=list)
                here = os.path.dirname(os.path.abspath(docmodel.__file__))
                tpl = os.stat(os.path.join(here, "docmodel_page.html"))  # a newer page template also counts
                version = hashlib.sha1((data + str(tpl.st_mtime_ns)).encode()).hexdigest()[:12]
                if version != self.version:
                    m["version"] = version
                    self.model, self.version, self.error = m, version, None
                    self.page = docmodel.page(m).encode()
                    self.model_json = json.dumps(m, default=list).encode()
                    self.note(f"model rebuilt (version {version})")
            except (docmodel.ModelError, docedit.EditError) as e:
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

    def _facts(self):
        """Regenerate <name>_facts.sysml, as the pre-commit hook would; returns its path if it changed."""
        try:
            m = docmodel.build(self.root)
        except docmodel.ModelError:
            return None
        path = os.path.join(self.root, "docs", "model", f"{m['name']}_facts.sysml")
        text = docmodel.facts_sysml(m)
        if os.path.exists(path) and open(path, encoding="utf-8").read() == text:
            return None
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def commit(self, paths, message):
        facts = self._facts()
        if facts and facts not in paths:
            paths = list(paths) + [facts]
        rels = [os.path.relpath(x, self.root) for x in paths]
        self.git("add", "--", *rels, check=True)
        # the page has already shown the problems this change adds, so the commit check is not run again
        who = getattr(self, "who", None)
        author = ["--author", f"{who[0]} <{who[1] if '@' in who[1] else who[1] + '@tailscale'}>"] if who and who[1] else []
        r = self.git("commit", "--no-verify", *author, "-m", message, "--", *rels)
        if r.returncode:
            raise doc.OpError("commit stopped: " + (r.stdout + r.stderr).strip()[-800:])
        self.want_push()
        self.note(f"committed: {message}")
        return "queued" if self.push and self.git("remote").stdout.strip() else None

    def apply(self, op, f, dry, who=None):
        """Run one form. dry=True returns the preview only. who = (name, login) from Tailscale, if any."""
        D = doc
        self.who = who
        if op in ("undo", "redo"):
            return self.undo(dry, redo=op == "redo")
        lines = lambda k: [x.strip() for x in str(f.get(k, "")).splitlines() if x.strip()]
        need = lambda k: (str(f.get(k, "")).strip() or (_ for _ in ()).throw(D.OpError(f"'{k}' is required")))
        warnings, msg = [], ""
        if op.startswith("issue_"):
            return self.issue_op(op, f, dry)
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
            def job():
                num, url = D.gh_create_issue(title, body, labels)
                self.note(f"created issue #{num}")
                self.issues_at = 0
                self.rebuild(force=True)
            self.later("create issue", job)
            return {"message": "Issue added · creating it on GitHub", "version": self.version}
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
        elif op == "procedure":
            writes, preview = D.op_procedure(need("title"), f.get("applies", "").strip(), f.get("duration", "").strip(),
                                             lines("needs"), lines("steps"), lines("warnings"), f.get("photo", "").strip())
            msg = f"doc: procedure {need('title')}"
        elif op == "check":
            sec = (f.get("new_section") or "").strip() if f.get("section") == "+new" else f.get("section", "")
            writes, preview = D.op_check(need("item"), need("why"), sec or "")
            msg = f"doc: checklist line ({need('item')[:50]})"
        elif op == "log":
            writes, preview = D.op_log({k: lines(k) for k in ("done", "broke", "next", "media")})
            msg = "doc: devlog"
        elif op in docedit.LIB_OPS:
            writes, msg, notes = docedit.run_library(op, self.root, f)
            warnings += notes
            preview, _ = self._model_preview(writes, check=False)
            msg = "doc: " + msg
        elif op in docedit.OPS:
            writes, msg, notes = docedit.run(op, self.root, f, self.model)
            warnings += notes
            preview, extra = self._model_preview(writes)
            warnings += extra
            msg = "doc: " + msg
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
        inside = [w for w in writes if self._inside(w[0])]
        self.guard([w[0] for w in inside])
        if dry:
            return {"preview": preview, "warnings": warnings, "commit": bool(inside),
                    "target": ", ".join(self._show(w[0]) for w in writes)}
        with self.lock:
            for path, text in writes:
                if text is None:
                    if os.path.exists(path):
                        os.remove(path)
                else:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(text)
            if inside:  # files git ignores (e.g. a parts folder listed in .gitignore) are written but not committed
                rels = [os.path.relpath(w[0], self.root) for w in inside]
                ign = set(self.git("check-ignore", "--", *rels).stdout.split())
                if ign:
                    warnings.append(f"{', '.join(sorted(ign))}: ignored by .gitignore, so saved on this computer only (not committed)")
                    inside = [w for w in inside if os.path.relpath(w[0], self.root) not in ign]
            pushed = self.commit([w[0] for w in inside], msg) if inside else None
            self.rebuild(force=True, issues=False)
            self.inputs = None
        tail = "" if not inside or pushed else " · not pushed (--no-push)"
        if writes and not inside:
            tail = " · outside the project, so not committed"
        return {"message": msg.replace("doc: ", "Saved: ") + tail, "version": self.version, "warnings": warnings}

    def gh(self, *args):
        r = subprocess.run(["gh", *args], cwd=self.root, capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise doc.OpError("GitHub: " + ((r.stderr or r.stdout).strip().splitlines() or ["failed"])[-1])
        return r.stdout

    def issue_op(self, op, f, dry):
        """Status, comments and deletion of GitHub issues (through gh; nothing is committed)."""
        n = int(f.get("number") or 0)
        iss = next((i for i in self.issues if i["number"] == n), None)
        if not n or iss is None:
            raise doc.OpError(f"no issue #{n}")
        api = f"repos/{{owner}}/{{repo}}/issues/{n}"
        if dry:
            return {"preview": f"#{n} {iss['title']}", "warnings": [], "target": "GitHub"}

        def set_status(st):
            cur = next((i for i in self.issues if i["number"] == n), iss)
            labels = [l for l in cur["labels"] if l.startswith("status: ")]
            if st in docmodel.ISSUE_OPEN:
                if cur.get("gh_state", cur["state"]) == "closed":
                    self.gh("api", "-X", "PATCH", api, "-f", "state=open")
                cur["gh_state"] = "open"
                new = [] if st == "backlog" else [f"status: {st}"]
                doc.ensure_labels(new)
                args = [x for l in labels if l not in new for x in ("--remove-label", l)] + [x for l in new if l not in labels for x in ("--add-label", l)]
                if args:
                    self.gh("issue", "edit", str(n), *args)
                cur["labels"] = [l for l in cur["labels"] if not l.startswith("status: ")] + new
            else:
                if labels:
                    self.gh("issue", "edit", str(n), *[x for l in labels for x in ("--remove-label", l)])
                    cur["labels"] = [l for l in cur["labels"] if not l.startswith("status: ")]
                reason = {"done": "completed", "not planned": "not_planned", "duplicate": "duplicate"}[st]
                try:
                    self.gh("api", "-X", "PATCH", api, "-f", "state=closed", "-f", f"state_reason={reason}")
                except doc.OpError:
                    if reason != "duplicate":
                        raise
                    doc.ensure_labels(["duplicate"])
                    self.gh("issue", "edit", str(n), "--add-label", "duplicate")
                    self.gh("api", "-X", "PATCH", api, "-f", "state=closed", "-f", "state_reason=not_planned")
                cur["gh_state"] = "closed"
        if op == "issue_status":
            st = f.get("status")
            if st not in docmodel.ISSUE_OPEN and st not in ("done", "not planned", "duplicate"):
                raise doc.OpError("unknown status")
            self.want_status[n] = st

            def work():  # several quick changes: only the latest one is sent
                latest = self.want_status.pop(n, None)
                if latest:
                    set_status(latest)
            msg, then = f"#{n} → {st}", st
        elif op == "issue_comment":
            body = str(f.get("body") or "").strip()
            then = f.get("then") or ""
            if not body and not then:
                raise doc.OpError("Write a comment first")

            if then:
                self.want_status[n] = then

            def work():
                if body:
                    self.gh("issue", "comment", str(n), "--body", body)
                latest = self.want_status.pop(n, None)
                if latest:
                    set_status(latest)
            msg = f"#{n}: " + ", ".join(x for x in ("commented" if body else "", f"→ {then}" if then else "") if x)
        elif op == "issue_delete":
            work, msg, then = (lambda: self.gh("issue", "delete", str(n), "--yes")), f"#{n} deleted", None
        else:
            raise doc.OpError(f"unknown issue operation {op}")
        if then:  # show it right away; GitHub catches up in the background
            was = iss["state"]
            iss.setdefault("gh_state", was)
            iss["status"], iss["state"] = then, "open" if then in docmodel.ISSUE_OPEN else "closed"
            if iss["state"] == "closed" and was != "closed":
                iss["closed"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if op == "issue_delete":
            self.issues = [i for i in self.issues if i["number"] != n]
        self.rebuild(force=True, issues=False)

        def job():
            try:
                work()
                self.note(msg)
            finally:
                self.issue_jobs -= 1
            if self.issue_jobs == 0:  # read GitHub back only when all issue changes are sent, so nothing flickers
                self.issues_at = 0
                self.rebuild(force=True)
        self.issue_jobs += 1
        self.later(f"issue #{n}", job)
        return {"message": msg, "version": self.version}


    def _inside(self, path):
        return os.path.realpath(path).startswith(os.path.realpath(self.root) + os.sep)

    def _show(self, path):
        return os.path.relpath(path, self.root) if self._inside(path) else path

    def history(self):
        """The page's changes, oldest first, folded into what is applied now and what can be redone."""
        rows = [l.split("\0") for l in reversed(self.git("log", "-400", "--format=%H%x00%s%x00%an%x00%cr").stdout.splitlines()) if l]
        applied, redo = [], []

        def take(stack, pred):
            for k in range(len(stack) - 1, -1, -1):
                if pred(stack[k]):
                    return stack.pop(k)
        for sha, subj, an, cr in rows:
            m = re.match(r"^doc: (undo|redo) ([0-9a-f]{7,40})\b", subj)
            if m:
                src, dst = (applied, redo) if m.group(1) == "undo" else (redo, applied)
                x = take(src, lambda c: c["sha"].startswith(m.group(2)))
                if x:
                    dst.append(x)
            elif subj.startswith('Revert "doc: '):  # undo of doc-kit 0.4-0.6
                x = take(applied, lambda c: 'Revert "doc: ' + c["subj"] + '"' == subj)
                if x:
                    redo.append(x)
            elif subj.startswith("doc: "):
                applied.append({"sha": sha, "subj": subj[5:], "who": an, "when": cr})
                redo = []
        return applied, redo

    def undo(self, dry, redo=False):
        """Undo the newest applied page change, or redo the newest undone one (each step is a new commit)."""
        applied, back = self.history()
        stack = back if redo else applied
        if not stack:
            raise doc.OpError("Nothing to redo." if redo else "Nothing to undo: no change made by the page.")
        c = stack[-1]
        if dry:
            return {"preview": c["subj"], "target": c["sha"][:10], "warnings": []}
        with self.lock:
            files = [x for x in self.git("show", "--name-only", "--format=", c["sha"]).stdout.splitlines() if x.strip()]
            self.guard([os.path.join(self.root, x) for x in files if os.path.exists(os.path.join(self.root, x))])
            r = self.git("cherry-pick" if redo else "revert", "--no-commit", c["sha"])
            if r.returncode:
                self.git("cherry-pick" if redo else "revert", "--abort")
                self.git("reset", "--hard", "HEAD")
                raise doc.OpError(f"could not {'redo' if redo else 'undo'} '{c['subj']}': a later change touched the same lines")
            who = getattr(self, "who", None)
            author = ["--author", f"{who[0]} <{who[1] if '@' in who[1] else who[1] + '@tailscale'}>"] if who and who[1] else []
            msg = f"doc: {'redo' if redo else 'undo'} {c['sha'][:10]} {c['subj']}"
            r = self.git("commit", "--no-verify", "--allow-empty", *author, "-m", msg)
            if r.returncode:
                raise doc.OpError("commit stopped: " + (r.stdout + r.stderr).strip()[-400:])
            self.want_push()
            self.note(f"committed: {msg}")
            self.rebuild(force=True, issues=False)
        return {"message": f"{'Redone' if redo else 'Undone'}: {c['subj']}", "version": self.version}

    def _push(self):
        if not (self.push and self.git("remote").stdout.strip()):
            return None
        pr = self.git("push", "--quiet")
        if pr.returncode:  # someone pushed meanwhile: put ours on top and try once more
            self.git("fetch", "--quiet")
            with self.lock:
                ok = self.git("rebase", "--quiet", "@{u}").returncode == 0
                if not ok:
                    self.git("rebase", "--abort")
            if ok:
                pr = self.git("push", "--quiet")
        if pr.returncode:
            self.note("push failed: " + pr.stderr.strip()[-200:])
        return pr.returncode == 0

    def _model_preview(self, writes, check=True):
        """Diff of each file, plus the model problems this change would add or fix."""
        out = []
        for path, text in writes:
            relp = self._show(path)
            old = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
            if text is None:
                out.append(f"── {relp} (deleted)")
                continue
            diff = list(difflib.unified_diff(old, text.splitlines(), relp, relp, n=1, lineterm=""))[2:]
            out.append(f"── {relp}{' (new file)' if not old else ''}\n" + "\n".join(diff))
        if not check:
            return "\n\n".join(out), []
        norm = lambda xs: {re.sub(r":\d+:", ":", x) for x in xs}
        warn = []
        try:
            after = docmodel.build(self.root, {p: t for p, t in writes if t is not None})["problems"]
            before = (self.model or {}).get("problems", [])
            added, fixed = norm(after) - norm(before), norm(before) - norm(after)
            warn += [f"new model problem: {x}" for x in sorted(added)]
            warn += [f"fixes: {x}" for x in sorted(fixed)]
        except docmodel.ModelError as e:
            warn.append(f"the model would not build: {e}")
        return "\n\n".join(out), warn

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
            self.commit([path], f"doc: add media {fname}")
            self.rebuild(force=True, issues=False)
        return {"file": fname, "message": f"Uploaded {fname}"}


def xlsx(rows):
    """A one-sheet .xlsx from a list of rows (first row = header), standard library only."""
    import io
    import zipfile
    from xml.sax.saxutils import escape

    def col(i):
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s
    sheet = []
    for ri, row in enumerate(rows, 1):
        cells = []
        for ci, v in enumerate(row):
            ref = f"{col(ci)}{ri}"
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                style = ' s="1"' if ri == 1 else ""
                cells.append(f'<c r="{ref}" t="inlineStr"{style}><is><t>{escape(str(v))}</t></is></c>')
        sheet.append(f'<row r="{ri}">{"".join(cells)}</row>')
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="BOM" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        "xl/styles.xml": '<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font/><font><b/></font></fonts><fills count="1"><fill/></fills><borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf/><xf fontId="1" applyFont="1"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet)}</sheetData></worksheet>'}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


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
                # a reload shows the current files: rebuild now if anything changed (no waiting for the next check),
                # and look for new commits on GitHub in the background (the reload banner appears if there are some)
                try:
                    S.rebuild(issues=False)
                except Exception as e:
                    S.note(f"rebuild failed: {e}")
                if time.time() - getattr(S, "pulled_at", 0) > 10:
                    S.pulled_at = time.time()
                    threading.Thread(target=lambda: (S.pull(), S.rebuild()), daemon=True).start()
                if not S.page:
                    return self.send(500, f"<pre>doc model failed:\n{S.error}</pre>", "text/html")
                return self.send(200, S.page, "text/html; charset=utf-8")
            m_ = re.match(r"^/api/issue/(\d+)$", path)
            if m_:
                return self.send(200, docmodel.issue_timeline(S.root, m_.group(1)))
            if path == "/api/version":
                return self.send(200, {"version": S.version, "error": S.error, "log": S.log[-8:], "pending": S.pending,
                                       "sync_error": S.sync_error})
            if path == "/api/model":
                return self.send(200, S.model_json, "application/json")
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
                who = (urllib.parse.unquote(self.headers.get("Tailscale-User-Name") or ""), self.headers.get("Tailscale-User-Login") or "")
                S.who = who if who[1] else None
                if path == "/api/bom.xlsx":
                    data = xlsx(json.loads(raw or b"[]"))
                    self.send_response(200)
                    self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    return self.wfile.write(data)
                if path == "/api/pdf":
                    data = html_pdf(json.loads(raw or b"{}").get("html", ""))
                    if not data:
                        return self.send(501, {"error": "no Chrome, Chromium or Edge found to make the PDF"})
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    return self.wfile.write(data)
                if path == "/api/pick_folder":
                    return self.send(200, {"path": pick_folder()})
                if path == "/api/upload":
                    return self.send(200, S.upload(urllib.parse.unquote(self.headers.get("X-Filename", "upload")), raw))
                m = re.match(r"^/api/(preview|apply)/(\w+)$", path)
                if not m:
                    return self.send(404, {"error": "not found"})
                return self.send(200, S.apply(m.group(2), json.loads(raw or b"{}"), dry=m.group(1) == "preview", who=S.who))
            except (doc.OpError, docedit.EditError, docmodel.ModelError) as e:
                return self.send(400, {"error": str(e)})
            except Exception as e:
                return self.send(500, {"error": f"{type(e).__name__}: {e}"})
    return H


BROWSERS = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]


def pick_folder():
    """The system's own folder dialog (Finder, Explorer, zenity), on the computer running doc serve."""
    if sys.platform == "darwin":
        cmd = ["osascript", "-e", 'POSIX path of (choose folder with prompt "Folder for library parts")']
    elif os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-Command", "Add-Type -AssemblyName System.Windows.Forms; $d = New-Object System.Windows.Forms.FolderBrowserDialog; "
               "$d.Description = 'Folder for library parts'; if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }"]
    elif shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--directory", "--title=Folder for library parts"]
    elif shutil.which("kdialog"):
        cmd = ["kdialog", "--getexistingdirectory", os.path.expanduser("~")]
    else:
        raise doc.OpError("No folder dialog on this computer: type the folder instead")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise doc.OpError(f"folder dialog failed: {e}")
    p = r.stdout.strip().rstrip("/\\") if r.returncode == 0 else ""
    home = os.path.expanduser("~")
    return ("~" + p[len(home):]) if p.startswith(home + os.sep) else p


def pdf_browser():
    for b in [os.environ.get("DOC_PDF_BROWSER")] + BROWSERS:
        if b and (shutil.which(b) or os.path.isfile(b)):
            return shutil.which(b) or b
    return None


def html_pdf(html):
    """Prints an HTML page to PDF with a headless Chrome/Chromium/Edge. None when there is no such browser."""
    b = pdf_browser()
    if not b:
        return None
    with tempfile.TemporaryDirectory() as d:
        src, out = os.path.join(d, "page.html"), os.path.join(d, "page.pdf")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(html)
        subprocess.run([b, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer", "--hide-scrollbars",
                        f"--user-data-dir={os.path.join(d, 'profile')}", f"--print-to-pdf={out}", "file://" + src],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
        return open(out, "rb").read() if os.path.exists(out) else None


def serve(root, port=8765, push=True, interval=60, open_browser=True):
    S = Server(root, push=push, interval=interval)
    print(f"doc serve: building the model for {root}", flush=True)
    S.rebuild(force=True)
    threading.Thread(target=S.loop, daemon=True).start()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(S))
    if open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    print(f"\n  open       http://127.0.0.1:{port}/")
    print(f"  share      tailscale serve --bg {port}   (your devices only)")
    print(f"  pushes     {'on' if push else 'off (--no-push)'} · checks GitHub every {interval} s · Ctrl+C stops\n", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
