"""
docedit.py - the page's editor for the system model (doc serve only).

Keeps these files in step, so nobody has to write SysML or TOML by hand:
    docs/model/model.toml            project name, subsystems, boards, ROS2 code folders
    docs/model/<name>_arch.sysml     parts, ports, connections, which computer runs which node,
                                     which part a requirement belongs to (rewritten in one fixed layout)
    docs/README.md                   the subsystem table (between doc-kit markers)
    .github/ISSUE_TEMPLATE/*.yml     the subsystem list of the idea and bug forms

Each operation changes an in-memory copy and returns the new file texts.
docserve shows them as a diff, with the model problems the change adds or fixes,
before anything is written or committed.
"""

import json
import os
import re

import docmodel as dm


class EditError(Exception):
    pass


IDENT = re.compile(r"^[A-Za-z_]\w*$")
PREFIX = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")
KEYWORDS = {"part", "port", "def", "connect", "to", "allocate", "satisfy", "by", "doc", "package", "import", "private",
            "public", "protected", "requirement", "attribute", "item", "action", "state", "alias", "comment", "metadata"}
SKIP_DIRS = {".git", "build", "install", "log", "Drivers", "Middlewares", "node_modules", "Debug", "Release", "__pycache__"}


# ================================================================ model.toml

def cfg_path(root):
    return os.path.join(root, "docs", "model", "model.toml")


def load_cfg(root):
    cfg = dm.load_config(root)
    if not cfg["subsystem"]:  # older repo: take the README table over on the first edit
        cfg["subsystem"] = [{"prefix": t[0], "name": t[1], "box": t[2]} for t in dm.subsystem_table(cfg, root)]
    return cfg


def _tq(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def cfg_text(cfg):
    out = ["# doc-kit model settings. Edited from the page (Setup). Hand edits are fine,",
           "# but the page rewrites this file in this layout.", "", "[project]", f"name = {_tq(cfg['project']['name'])}"]
    for s in cfg["subsystem"]:
        out += ["", "[[subsystem]]", f"prefix = {_tq(s['prefix'])}", f"name = {_tq(s.get('name', s['prefix']))}"]
        if s.get("about"):
            out.append(f"about = {_tq(s['about'])}")
        if s.get("box", True) is False:
            out.append("box = false      # requirements only: no box in the diagram")
        if s.get("deleted"):
            out.append("deleted = true   # kept so its requirement IDs are never reused")
    for b in cfg["board"]:
        out += ["", "[[board]]", f"name = {_tq(b['name'])}", f"ioc = {_tq(b['ioc'])}"]
        if b.get("def"):
            out.append(f"def = {_tq(b['def'])}")
    out += ["", "[ros]", "paths = [" + ", ".join(_tq(x) for x in cfg["ros"]["paths"]) + "]"]
    if cfg.get("bom", {}).get("columns"):
        out += ["", "[bom]", "columns = [" + ", ".join(_tq(x) for x in cfg["bom"]["columns"]) + "]"]
    for e in cfg.get("bom_item", []):
        out += ["", "[[bom_item]]"] + [f"{k} = {_tq(v)}" for k, v in e.items()]
    return "\n".join(out) + "\n"


def adopt(cfg, A):
    """Top-level parts of a hand-written arch file that model.toml does not list yet become subsystems."""
    known = {s["prefix"] for s in cfg["subsystem"]}
    for c in A["top"]["parts"]:
        if c["name"] not in known and PREFIX.match(c["name"]):
            cfg["subsystem"].append({"prefix": c["name"], "name": c.get("doc") or c["name"]})


def active(cfg):
    return [s for s in cfg["subsystem"] if not s.get("deleted")]


def board_def(b):
    return b.get("def") or re.sub(r"\W", "_", b["name"]).upper()


# ================================================================ arch file

def arch_path(root, cfg):
    return os.path.join(root, "docs", "model", f"{cfg['project']['name']}_arch.sysml")


def _clean(p):
    return {"name": p["name"], "type": p.get("type"), "doc": p.get("doc", ""), "attrs": dict(p.get("attrs", {})),
            "ports": [{"name": q["name"], "type": q["type"], "conj": q["conj"], "attrs": dict(q.get("attrs", {}))} for q in p.get("ports", [])],
            "parts": [_clean(c) for c in p.get("parts", [])]}


def load_arch(root, cfg):
    """The arch file as one tree plus flat lists; every path is relative to the robot part."""
    path = arch_path(root, cfg)
    if os.path.exists(path):
        a = dm.Parser(open(path, encoding="utf-8").read(), os.path.relpath(path, root)).parse()
    else:
        a = {"port_defs": {}, "part_defs": {}, "parts": [], "allocations": [], "satisfies": [], "actions": []}
    if len(a["parts"]) > 1:
        raise EditError(f"{os.path.relpath(path, root)} has {len(a['parts'])} top-level parts; the page needs exactly one (the robot)")
    top = a["parts"][0] if a["parts"] else {"name": cfg["project"]["name"], "type": None, "parts": [], "ports": [],
                                            "connects": [], "doc": ""}
    tn = top["name"]
    rel = lambda segs: segs[1:] if segs and segs[0] == tn else segs
    connects = []  # [a, b, attrs]

    def walk(p, prefix):
        for c in p.get("connects", []):
            ends = [c["a"][1:] if c["a"][0] == tn else prefix + c["a"], c["b"][1:] if c["b"][0] == tn else prefix + c["b"]]
            connects.append(ends + [dict(c.get("attrs", {}))])
        for ch in p["parts"]:
            walk(ch, prefix + [ch["name"]])
    walk(top, [])
    return {"top": _clean(top), "connects": connects,
            "port_defs": {k: {"super": v.get("super"), "doc": v.get("doc", "")} for k, v in a["port_defs"].items()},
            "part_defs": {k: _clean(v) for k, v in a["part_defs"].items()},
            "allocs": [[x["what"], rel(x["to"])] for x in a["allocations"]],
            "sats": [[x["req"], rel(x["by"])] for x in a["satisfies"]],
            "acts": [{"name": x["name"], "doc": x.get("doc", ""), "out": x["out"], "in": x["in"]} for x in a.get("actions", [])]}


def q(s):
    return s if IDENT.match(s) and s not in KEYWORDS else "'" + s.replace("'", "") + "'"


def q_any(s):
    """Topic and message type names always quoted: they hold / and ."""
    return "'" + str(s).replace("'", "") + "'"


def _val(v):
    return " ".join(str(v).replace('"', "'").split())


def _doc(s):
    return " ".join(s.replace("*/", "* /").split())


def arch_text(A, cfg):
    name = cfg["project"]["name"]
    top = A["top"]
    path = lambda segs: ".".join(q(x) for x in segs)
    o = [f"// {name} architecture. Edited from the doc-kit page (System, Electrical and Power views). Hand edits are fine,",
         f"// but the page rewrites this file in this layout. Boards and their ports come from {name}_facts.sysml.",
         f"package {q(name + '_arch')} {{", f"    private import {q(name + '_facts')}::*;"]
    if A["port_defs"]:
        o.append("")
        for n, d in A["port_defs"].items():
            sup = f" :> {q(d['super'])}" if d.get("super") else ""
            o.append(f"    port def {q(n)}{sup}" + (f" {{ doc /* {_doc(d['doc'])} */ }}" if d.get("doc") else ";"))

    def attr_lines(a, ind):
        return [f'{ind}attribute {q(k)} = "{_val(v)}";' for k, v in (a or {}).items()]

    def port_lines(p, ind):
        out = []
        for x in p["ports"]:
            head = f"{ind}port {q(x['name'])} : {'~' if x['conj'] else ''}{q(x['type'])}"
            al = attr_lines(x.get("attrs"), ind + "    ")
            out += [head + " {"] + al + [f"{ind}}}"] if al else [head + ";"]
        return out

    for n, d in A["part_defs"].items():
        o += ["", f"    part def {q(n)} {{"] + ([f"        doc /* {_doc(d['doc'])} */"] if d["doc"] else []) + attr_lines(d.get("attrs"), "        ") + port_lines(d, "        ") + ["    }"]

    def part_lines(p, ind):
        head = f"{ind}part {q(p['name'])}" + (f" : {q(p['type'])}" if p["type"] else "")
        body = ([f"{ind}    doc /* {_doc(p['doc'])} */"] if p["doc"] else []) + attr_lines(p.get("attrs"), ind + "    ") + port_lines(p, ind + "    ")
        for ch in p["parts"]:
            body += part_lines(ch, ind + "    ")
        return [head + " {"] + body + [f"{ind}}}"] if body else [head + ";"]

    order = [s["prefix"] for s in cfg["subsystem"]]
    kids = sorted(top["parts"], key=lambda p: order.index(p["name"]) if p["name"] in order else len(order))
    o += ["", f"    part {q(top['name'])} {{"] + ([f"        doc /* {_doc(top['doc'])} */"] if top["doc"] else [])
    for ch in kids:
        o += part_lines(ch, "        ")
    if A["connects"]:
        o.append("")
        for a, b, at in A["connects"]:
            al = attr_lines(at, "            ")
            o += [f"        connect {path(a)} to {path(b)}" + (" {" if al else ";")] + (al + ["        }"] if al else [])
    o.append("    }")
    if A["allocs"]:
        o.append("")
        o += [f"    allocate {'::'.join(q(x) for x in w)} to {path([top['name']] + t)};" for w, t in A["allocs"]]
    if A["sats"]:
        o.append("")
        o += [f"    satisfy {q(r)} by {path([top['name']] + b)};" for r, b in A["sats"]]
    if A.get("acts"):
        o += ["", "    // ROS2 plan: nodes and the topics they publish (out) and subscribe to (in), drawn on the page.",
              "    // A node with the same name in the code is the same node; the page shows what is planned but not built."]
        for a in A["acts"]:
            body = ([f"        doc /* {_doc(a['doc'])} */"] if a.get("doc") else []) + \
                [f"        {io} item {q_any(x['topic'])}" + (f" : {q_any(x['type'])}" if x.get("type") else "") + ";" for io in ("out", "in") for x in a[io]]
            o += [f"    action {q(a['name'])} {{"] + body + ["    }"] if body else [f"    action {q(a['name'])};"]
    o.append("}")
    return "\n".join(o) + "\n"


# ---------------------------------------------------------------- tree helpers

def node(A, segs):
    """Part at segs (relative to the robot), or None."""
    p = A["top"]
    for s in segs:
        p = next((c for c in p["parts"] if c["name"] == s), None)
        if p is None:
            return None
    return p


def under(end, prefix):
    return end[:len(prefix)] == prefix


def rename_refs(A, old, new):
    for c in A["connects"]:
        for i in (0, 1):
            if under(c[i][:-1], old):
                c[i] = new + c[i][len(old):]
    for lst in (A["allocs"], A["sats"]):
        for x in lst:
            if under(x[1], old):
                x[1] = new + x[1][len(old):]


def drop_refs(A, segs, port=None):
    """Remove connections (and, for a whole part, allocations and requirement links) that use it."""
    gone = []
    keep = []
    for c in A["connects"]:
        a, b = c[0], c[1]
        hit = (a[:-1] == segs and a[-1] == port) or (b[:-1] == segs and b[-1] == port) if port else \
            under(a[:-1], segs) or under(b[:-1], segs)
        (gone.append(f"connection {'.'.join(a)} ↔ {'.'.join(b)}") if hit else keep.append(c))
    A["connects"] = keep
    if port is None:
        for key, label in (("allocs", "ROS node {0} runs here"), ("sats", "requirement {0} belongs here")):
            kept = []
            for x in A[key]:
                if under(x[1], segs):
                    gone.append(label.format(x[0][-1] if key == "allocs" else x[0]))
                else:
                    kept.append(x)
            A[key] = kept
    return gone


def split_path(top, full):
    segs = [x for x in str(full or "").split(".") if x]
    return segs[1:] if segs and segs[0] == top else segs


def check_name(name, what):
    name = str(name or "").strip()
    if not IDENT.match(name) or name in KEYWORDS:
        raise EditError(f"{what}: use letters, digits and _ only, starting with a letter (e.g. imu, left_motor)")
    return name


def port_types(A):
    out = [{"name": k, "kind": v[0], "meaning": v[1], "custom": False} for k, v in dm.PORT_DEFS.items()]
    out += [{"name": k, "kind": k, "meaning": dm.KIND_MEANING[k], "custom": False} for k in dm.KINDS]
    for k, d in A["port_defs"].items():
        out.append({"name": k, "kind": dm._kind_of(k, A["port_defs"]) or "Signal", "meaning": d.get("doc") or k, "custom": True})
    return out


def ensure_boxes(cfg, A):
    """One empty part per subsystem that has a box; drop empty boxes of removed subsystems."""
    names = [c["name"] for c in A["top"]["parts"]]
    boxed = [s["prefix"] for s in active(cfg) if s.get("box", True)]
    for s in boxed:
        if s not in names:
            A["top"]["parts"].append({"name": s, "type": None, "doc": "", "ports": [], "parts": []})
    known = {s["prefix"] for s in cfg["subsystem"]}
    A["top"]["parts"] = [c for c in A["top"]["parts"] if c["name"] in boxed or c["name"] not in known
                         or c["parts"] or c["ports"]]


# ================================================================ generated parts of README and issue forms

MARK_A, MARK_B = "<!-- doc-kit:subsystems (edit on the page: Setup) -->", "<!-- /doc-kit:subsystems -->"


def readme_text(text, cfg):
    rows = ["| Prefix | Subsystem |", "|---|---|"] + [f"| {s['prefix']} | {s.get('name', '')}{'' if s.get('box', True) else ' (requirements only)'} |"
                                                    for s in active(cfg)]
    block = "\n".join([MARK_A] + rows + [MARK_B])
    if MARK_A in text and MARK_B in text:
        return re.sub(re.escape(MARK_A) + r".*?" + re.escape(MARK_B), lambda m: block, text, count=1, flags=re.S)
    lines = text.splitlines()
    head = next((i for i, l in enumerate(lines) if l.strip() == "| Prefix | Subsystem |"), None)
    if head is None:
        return text
    end = head + 1
    while end < len(lines) and lines[end].strip().startswith("|"):
        end += 1
    return "\n".join(lines[:head] + block.splitlines() + lines[end:]) + "\n"


def template_text(text, cfg):
    labels = [s["prefix"].lower() for s in active(cfg)] or ["general"]
    return re.sub(r"(id:\s*subsystem.*?options:\s*)\[[^\]]*\]", lambda m: m.group(1) + "[" + ", ".join(labels) + "]",
                  text, count=1, flags=re.S)


def synced_files(root, cfg):
    out = []
    targets = [(os.path.join(root, "docs", "README.md"), readme_text)] + \
              [(os.path.join(root, ".github", "ISSUE_TEMPLATE", f), template_text) for f in ("idea.yml", "bug.yml")]
    for path, fn in targets:
        if os.path.exists(path):
            out.append((path, fn(open(path, encoding="utf-8").read(), cfg)))
    return out


# ================================================================ what the Setup page offers

def scan_repo(root, cfg):
    used = {os.path.normpath(b["ioc"]) for b in cfg["board"]}
    iocs, ros = [], []
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        relb = os.path.relpath(base, root)
        relb = "" if relb == "." else relb
        low = relb.lower().replace(os.sep, "/")
        note = "library code" if "micro_ros" in low or "utils" in low.split("/") else "legacy" if "legacy" in low.split("/") else ""
        for f in sorted(files):
            if f.endswith(".ioc"):
                rp = os.path.join(relb, f)
                src = os.path.join(os.path.dirname(rp), "Core", "Src")
                iocs.append({"path": rp, "note": "sample project" if f.startswith("sample") else note,
                             "used": os.path.normpath(rp) in used, "src": src if os.path.isdir(os.path.join(root, src)) else ""})
        if "package.xml" in files or "setup.py" in files and relb:
            ros.append({"path": relb, "note": note or "ROS2 package"})
        if relb.endswith(os.path.join("Core", "Src")):
            ros.append({"path": relb, "note": note or "STM32 code (micro-ROS)"})
        if os.path.dirname(relb) in ("software", "src", os.path.join("ros2_ws", "src")) and relb:
            if not any(r["path"] == relb for r in ros):
                ros.append({"path": relb, "note": note or "folder"})
    return iocs, ros


def setup_info(root, model):
    cfg = load_cfg(root)
    A = load_arch(root, cfg)
    adopt(cfg, A)
    iocs, ros = scan_repo(root, cfg)
    reqs = model.get("requirements", []) if model else []
    parts = model.get("parts", {}) if model else {}
    top = model.get("top") if model else None
    subs = []
    for s in cfg["subsystem"]:
        box = parts.get(f"{top}.{s['prefix']}") if top else None
        subs.append({"prefix": s["prefix"], "name": s.get("name", ""), "about": s.get("about", ""), "box": s.get("box", True),
                     "deleted": bool(s.get("deleted")),
                     "reqs": sum(1 for r in reqs if r["prefix"] == s["prefix"] and r["status"] != "Deleted"),
                     "parts": len(box["children"]) if box else 0})
    boards = []
    for b in cfg["board"]:
        where = [k for k, p in parts.items() if p.get("type") == board_def(b)]
        boards.append({"name": b["name"], "ioc": b["ioc"], "def": board_def(b), "placed": where})
    pages = os.path.exists(os.path.join(root, ".github", "workflows", "doc-kit-pages.yml"))
    return {"project": cfg["project"]["name"], "subsystems": subs, "boards": boards, "ros_paths": cfg["ros"]["paths"],
            "ioc_candidates": iocs, "ros_candidates": ros, "port_types": port_types(A), "library": library_info(root),
            "pages": pages, "bom_items": cfg.get("bom_item", [])}


# ================================================================ operations

def _bool(v, default=True):
    if v is None or v == "":
        return default
    return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "yes")


def _req_ids(root, prefix, live_only=False):
    rows = dm._table(os.path.join(root, "docs", "requirements.md"), dm.REQ_HEADER)
    return [r[0] for r in rows if r and r[0].rsplit("-", 1)[0] == prefix and (not live_only or (len(r) > 4 and r[4] != "Deleted"))]


def op_subsystem(cfg, A, f, ctx):
    root = ctx["root"]
    orig = str(f.get("orig") or "").strip()
    prefix = str(f.get("prefix") or "").strip().upper()
    name = str(f.get("name") or "").strip()
    if not PREFIX.match(prefix):
        raise EditError("Prefix: 2 to 6 capital letters or digits, starting with a letter (e.g. CTRL, PWR, COMM)")
    if prefix == "FM":
        raise EditError("FM is used for fault rows (FM-001). Pick another prefix.")
    if not name:
        raise EditError("Name is required (e.g. Control, Power, Communications)")
    box = _bool(f.get("box"))
    other = next((s for s in cfg["subsystem"] if s["prefix"] == prefix and s["prefix"] != orig), None)
    if other:
        raise EditError(f"{prefix} already exists" + (" (deleted: restore it instead, so its old IDs are not reused)" if other.get("deleted") else ""))
    if not orig:
        cfg["subsystem"].append({"prefix": prefix, "name": name, "about": str(f.get("about") or "").strip(), "box": box})
        return f"add subsystem {prefix}", []
    s = next((x for x in cfg["subsystem"] if x["prefix"] == orig), None)
    if s is None:
        raise EditError(f"no subsystem {orig}")
    part = node(A, [orig])
    if prefix != orig:
        used = _req_ids(root, orig)
        if used:
            raise EditError(f"{len(used)} requirement(s) use {orig}- IDs ({', '.join(used[:4])}{'…' if len(used) > 4 else ''}). "
                            f"Requirement IDs never change, so this prefix stays; change the name instead.")
        if part:
            part["name"] = prefix
            rename_refs(A, [orig], [prefix])
    if not box and s.get("box", True) and part and (part["parts"] or part["ports"]):
        raise EditError(f"{orig} still has parts ({', '.join(c['name'] for c in part['parts'])}). Move or delete them first.")
    s.update({"prefix": prefix, "name": name, "about": str(f.get("about") or "").strip(), "box": box})
    return f"edit subsystem {prefix}", []


def op_subsystem_delete(cfg, A, f, ctx):
    prefix = str(f.get("prefix") or "")
    s = next((x for x in cfg["subsystem"] if x["prefix"] == prefix), None)
    if s is None:
        raise EditError(f"no subsystem {prefix}")
    live = _req_ids(ctx["root"], prefix, live_only=True)
    if live:
        raise EditError(f"{prefix} has requirements that are not deleted ({', '.join(live[:5])}{'…' if len(live) > 5 else ''}). "
                        f"Mark them deleted first, or keep the subsystem.")
    part = node(A, [prefix])
    if part and (part["parts"] or part["ports"]):
        raise EditError(f"{prefix} still has parts ({', '.join(c['name'] for c in part['parts'])}). Move or delete them first.")
    if _req_ids(ctx["root"], prefix):
        s["deleted"] = True
        return f"mark subsystem {prefix} deleted", [f"{prefix} is kept as deleted because old requirement IDs use it; it is hidden everywhere else."]
    cfg["subsystem"].remove(s)
    A["top"]["parts"] = [c for c in A["top"]["parts"] if c["name"] != prefix]
    return f"remove subsystem {prefix}", []


def op_subsystem_restore(cfg, A, f, ctx):
    s = next((x for x in cfg["subsystem"] if x["prefix"] == f.get("prefix")), None)
    if s is None:
        raise EditError("no such subsystem")
    s.pop("deleted", None)
    return f"restore subsystem {s['prefix']}", []


def op_subsystem_move(cfg, A, f, ctx):
    lst = cfg["subsystem"]
    i = next((k for k, x in enumerate(lst) if x["prefix"] == f.get("prefix")), None)
    if i is None:
        raise EditError("no such subsystem")
    j = i + (1 if str(f.get("dir")) in ("1", "down") else -1)
    if not 0 <= j < len(lst):
        raise EditError("already at the end")
    lst[i], lst[j] = lst[j], lst[i]
    return f"move subsystem {lst[j]['prefix']}", []


def op_board(cfg, A, f, ctx):
    root = ctx["root"]
    orig = str(f.get("orig") or "").strip()
    ioc = os.path.normpath(str(f.get("ioc") or "").strip().strip("/"))
    full = os.path.join(root, ioc)
    if not ioc.endswith(".ioc") or not os.path.isfile(full):
        raise EditError(f"{ioc or 'the .ioc file'} does not exist. Pick the board's .ioc file (each board needs its own).")
    if any(os.path.normpath(b["ioc"]) == ioc and b["name"] != orig for b in cfg["board"]):
        raise EditError(f"{ioc} is already used by another board")
    if orig:
        b = next((x for x in cfg["board"] if x["name"] == orig), None)
        if b is None:
            raise EditError(f"no board {orig}")
        b["ioc"] = ioc
        try:
            dm.parse_ioc(full, b)
        except Exception as e:
            raise EditError(f"could not read {ioc}: {e}")
        return f"board {orig} uses {os.path.basename(ioc)}", []
    name = check_name(f.get("name"), "Board name")
    sub = str(f.get("subsystem") or "")
    if sub not in [s["prefix"] for s in active(cfg) if s.get("box", True)]:
        raise EditError("Pick the subsystem the board sits in (add subsystems first)")
    if any(b["name"] == name for b in cfg["board"]):
        raise EditError(f"a board called {name} already exists")
    dfn = re.sub(r"\W", "_", name).upper()
    if dfn in A["part_defs"] or any(board_def(b) == dfn for b in cfg["board"]) or dfn in dm.PORT_DEFS:
        raise EditError(f"the name {name} clashes with an existing type ({dfn}); pick another")
    b = {"name": name, "ioc": ioc}
    try:
        dm.parse_ioc(full, b)
    except Exception as e:
        raise EditError(f"could not read {ioc}: {e}")
    cfg["board"].append(b)
    ensure_boxes(cfg, A)
    box = node(A, [sub])
    if any(c["name"] == name for c in box["parts"]):
        raise EditError(f"{sub} already has a part called {name}")
    box["parts"].append({"name": name, "type": dfn, "doc": "", "ports": [], "parts": []})
    notes = []
    src = os.path.join(os.path.dirname(ioc), "Core", "Src")
    if _bool(f.get("scan"), False) and os.path.isdir(os.path.join(root, src)) and src not in cfg["ros"]["paths"]:
        cfg["ros"]["paths"].append(src)
        notes.append(f"{src} added to the ROS2 code folders")
    return f"add board {name} ({os.path.basename(ioc)}) to {sub}", notes


def _remove_part(A, segs):
    parent = node(A, segs[:-1])
    parent["parts"] = [c for c in parent["parts"] if c["name"] != segs[-1]]


def _paths_of_type(A, typ, p=None, prefix=()):
    p = p or A["top"]
    out = []
    for c in p["parts"]:
        if c["type"] == typ:
            out.append(list(prefix) + [c["name"]])
        out += _paths_of_type(A, typ, c, tuple(prefix) + (c["name"],))
    return out


def op_board_remove(cfg, A, f, ctx):
    b = next((x for x in cfg["board"] if x["name"] == f.get("name")), None)
    if b is None:
        raise EditError("no such board")
    cfg["board"].remove(b)
    gone = []
    for segs in _paths_of_type(A, board_def(b)):
        gone += [f"part {'.'.join(segs)}"] + drop_refs(A, segs)
        _remove_part(A, segs)
    return f"remove board {b['name']}", [f"also removes {g}" for g in gone]


def op_ros_paths(cfg, A, f, ctx):
    paths = []
    for x in f.get("paths") or []:
        x = os.path.normpath(str(x).strip().strip("/"))
        if not x or x == ".":
            continue
        if not os.path.exists(os.path.join(ctx["root"], x)):
            raise EditError(f"{x} does not exist in the project")
        if x not in paths:
            paths.append(x)
    cfg["ros"]["paths"] = paths
    return "ROS2 code folders", []


def op_port_type(cfg, A, f, ctx):
    name = check_name(f.get("name"), "Type name")
    if name in dm.PORT_DEFS or name in dm.KINDS or name in A["port_defs"]:
        raise EditError(f"{name} already exists")
    kind = f.get("kind")
    if kind not in dm.KINDS:
        raise EditError("Kind must be Signal, Power or Mechanical")
    A["port_defs"][name] = {"super": kind, "doc": str(f.get("meaning") or "").strip()}
    return f"add port type {name}", []


def _ports_using(A, typ, p=None):
    p = p or A["top"]
    n = sum(1 for x in p["ports"] if x["type"] == typ)
    return n + sum(_ports_using(A, typ, c) for c in p["parts"])


def op_port_type_delete(cfg, A, f, ctx):
    name = f.get("name")
    if name not in A["port_defs"]:
        raise EditError("only port types you added can be deleted")
    n = _ports_using(A, name) + sum(1 for d in A["part_defs"].values() for x in d["ports"] if x["type"] == name)
    if n:
        raise EditError(f"{n} port(s) use {name}. Change them first.")
    del A["port_defs"][name]
    return f"delete port type {name}", []


def _attrs(rows):
    """[{key, value}] or {key: value} from the page -> {key: value}; keys become identifiers."""
    if isinstance(rows, dict):
        rows = [{"key": k, "value": v} for k, v in rows.items()]
    out = {}
    for r in rows or []:
        k = re.sub(r"\W+", "_", str(r.get("key") or "").strip().lower()).strip("_")
        v = " ".join(str(r.get("value") or "").split())
        if k and v:
            if not IDENT.match(k):
                k = "f_" + k
            out[k] = v
    return out


def _ports_from_form(rows, known_types, old, inherited=()):
    """inherited: names of ports that come from the part's type or .ioc; a row with such a name
    only stores details (attributes) for that port, and is dropped when it has none."""
    out, seen, renames = [], set(), []
    for r in rows or []:
        nm = str(r.get("name") or "").strip()
        if not nm:
            continue
        if nm in inherited:
            if _attrs(r.get("attrs")):
                out.append({"name": nm, "type": str(r.get("type") or ""), "conj": False, "attrs": _attrs(r.get("attrs"))})
            seen.add(nm)
            continue
        nm = check_name(nm, f"Port {nm}")
        if nm in seen:
            raise EditError(f"two ports are called {nm}")
        seen.add(nm)
        typ = str(r.get("type") or "")
        if typ not in known_types:
            raise EditError(f"port {nm}: pick a type")
        was = str(r.get("was") or "")
        prev = next((x for x in old if x["name"] == was), None)
        out.append({"name": nm, "type": typ, "conj": prev["conj"] if prev and prev["type"] == typ else False,
                    "attrs": _attrs(r.get("attrs"))})
        if prev and was != nm:
            renames.append((was, nm))
    kept = {r for r in (str(x.get("was") or "") for x in rows or []) if r} | set(inherited)
    removed = [x["name"] for x in old if x["name"] not in kept]
    return out, renames, removed


def _is_board(cfg, p):
    return bool(p and p["type"] and any(board_def(b) == p["type"] for b in cfg["board"]))


def op_part(cfg, A, f, ctx):
    tn = A["top"]["name"]
    orig = split_path(tn, f.get("orig"))
    parent = split_path(tn, f.get("parent"))
    name = check_name(f.get("name"), "Part name")
    pnode = node(A, parent) if parent else None
    if pnode is None:
        raise EditError("Pick where the part goes: a subsystem, or a part to put it inside")
    if _is_board(cfg, pnode):
        raise EditError("A board cannot hold other parts. Put the part in the board's subsystem instead.")
    if orig and under(parent, orig):
        raise EditError("A part cannot go inside itself")
    known = {t["name"] for t in port_types(A)}
    new_path = parent + [name]
    where = ".".join(parent)
    notes = []
    if not orig:
        if any(c["name"] == name for c in pnode["parts"]):
            raise EditError(f"{where} already has a part called {name}")
        ports, _, _ = _ports_from_form(f.get("ports"), known, [])
        pnode["parts"].append({"name": name, "type": None, "doc": str(f.get("doc") or "").strip(), "ports": ports, "parts": [],
                               "attrs": _attrs(f.get("attrs"))})
        return f"add part {'.'.join(new_path)}", notes
    if len(orig) < 2:
        raise EditError("Subsystems are edited in Setup")
    p = node(A, orig)
    if p is None:
        raise EditError(f"no part {'.'.join(orig)}")
    if new_path != orig:
        if any(c["name"] == name for c in pnode["parts"]):
            raise EditError(f"{where} already has a part called {name}")
        _remove_part(A, orig)
        p["name"] = name
        pnode["parts"].append(p)
        rename_refs(A, orig, new_path)
        notes.append(f"connections and links now point to {'.'.join(new_path)}")
    p["doc"] = str(f.get("doc") or "").strip()
    if "attrs" in f:
        p["attrs"] = _attrs(f.get("attrs"))
    if "ports" in f:  # a part's own ports (a board or typed part keeps the ports of its type as well)
        mp = ((ctx["model"] or {}).get("parts") or {}).get(f"{tn}.{'.'.join(orig)}") or {}
        inherited = {q["name"] for q in mp.get("ports", []) if not q.get("own") and not q.get("missing")}
        ports, renames, removed = _ports_from_form(f.get("ports"), known, p["ports"], inherited)
        for old_n, new_n in renames:
            for c in A["connects"]:
                for i in (0, 1):
                    if c[i][:-1] == new_path and c[i][-1] == old_n:
                        c[i] = new_path + [new_n]
        for r in removed:
            notes += [f"also removes {g}" for g in drop_refs(A, new_path, r)]
        p["ports"] = ports
    return f"edit part {'.'.join(new_path)}", notes


def op_wire(cfg, A, f, ctx):
    tn = A["top"]["name"]
    a, b = split_path(tn, f.get("a")), split_path(tn, f.get("b"))
    c = next((c for c in A["connects"] if sorted([c[0], c[1]]) == sorted([a, b])), None)
    if c is None:
        raise EditError("no such connection")
    c[2] = _attrs(f.get("attrs"))
    return f"wire {'.'.join(a)} ↔ {'.'.join(b)}", []


def op_part_delete(cfg, A, f, ctx):
    segs = split_path(A["top"]["name"], f.get("path"))
    if len(segs) < 2:
        raise EditError("Subsystems are removed in Setup")
    p = node(A, segs)
    if p is None:
        raise EditError("no such part")
    gone = drop_refs(A, segs)
    _remove_part(A, segs)
    notes = [f"also removes {g}" for g in gone]
    b = next((x for x in cfg["board"] if board_def(x) == p["type"]), None)
    if b and not _paths_of_type(A, p["type"]):
        cfg["board"].remove(b)
        notes.append(f"also removes board {b['name']} from Setup")
    return f"delete part {'.'.join(segs)}", notes


def _model_port(ctx, full):
    m = ctx["model"]
    part, _, port = str(full or "").rpartition(".")
    p = (m or {}).get("parts", {}).get(part)
    q_ = next((x for x in (p or {}).get("ports", []) if x["name"] == port and not x.get("missing")), None)
    if q_ is None:
        raise EditError(f"no port {full}")
    return part, p, q_


def _own_port(A, segs, name):
    p = node(A, segs)
    return next((x for x in p["ports"] if x["name"] == name), None) if p and not p["type"] else None


def op_connect(cfg, A, f, ctx):
    tn = A["top"]["name"]
    a_part, _, qa = _model_port(ctx, f.get("a"))
    a = split_path(tn, a_part) + [qa["name"]]
    b_part = str(f.get("b_part") or "")
    bsegs = split_path(tn, b_part)
    if len(bsegs) < 2 or node(A, bsegs) is None:
        raise EditError("Pick the part at the other end")
    notes = []
    if str(f.get("b_port") or "") == "+new":
        bn = node(A, bsegs)
        if bn["type"]:
            src = "its .ioc file" if any(board_def(x) == bn["type"] for x in cfg["board"]) else f"its type {bn['type']} in the arch file"
            raise EditError(f"{'.'.join(bsegs)} gets its ports from {src}. Pick one of them.")
        nm = check_name(f.get("b_new"), "New port name")
        if any(x["name"] == nm for x in bn["ports"]):
            raise EditError(f"{'.'.join(bsegs)} already has a port {nm}")
        bn["ports"].append({"name": nm, "type": qa["type"], "conj": not qa["conj"]})
        b = bsegs + [nm]
        notes.append(f"adds port {nm} ({qa['type']}) to {'.'.join(bsegs)}")
    else:
        _, _, qb = _model_port(ctx, f"{b_part}.{f.get('b_port')}")
        if qb["type"] != qa["type"]:
            raise EditError(f"the ends do not match: {qa['name']} is {qa['type']}, {qb['name']} is {qb['type']}")
        b = bsegs + [qb["name"]]
        if qa["conj"] == qb["conj"]:  # one end must be the mirror (~) of the other: flip a port you wrote
            for segs, nm in ((b[:-1], b[-1]), (a[:-1], a[-1])):
                own = _own_port(A, segs, nm)
                if own:
                    own["conj"] = not own["conj"]
                    break
    if a == b:
        raise EditError("a port cannot connect to itself")
    if any(sorted([c[0], c[1]]) == sorted([a, b]) for c in A["connects"]):
        raise EditError("these two ports are already connected")
    A["connects"].append([a, b, {k: v for k, v in _attrs(f.get("attrs")).items()}])
    return f"connect {'.'.join(a)} to {'.'.join(b)}", notes


def op_disconnect(cfg, A, f, ctx):
    tn = A["top"]["name"]
    a, b = split_path(tn, f.get("a")), split_path(tn, f.get("b"))
    before = len(A["connects"])
    A["connects"] = [c for c in A["connects"] if sorted([c[0], c[1]]) != sorted([a, b])]
    if len(A["connects"]) == before:
        raise EditError("no such connection")
    return f"disconnect {'.'.join(a)} from {'.'.join(b)}", []


def op_allocate(cfg, A, f, ctx):
    nodes = {n["name"] for n in (ctx["model"] or {}).get("nodes", [])}
    nm = str(f.get("node") or "")
    if nm not in nodes:
        raise EditError(f"no ROS node {nm}")
    launch = str(f.get("launch") or "")
    if launch:  # every node this launch file starts
        if launch not in {l["file"] for l in (ctx["model"] or {}).get("launches", [])}:
            raise EditError(f"no launch file {launch}")
        nm = launch
    to = split_path(A["top"]["name"], f.get("to"))
    A["allocs"] = [x for x in A["allocs"] if x[0][-1] != nm]
    if to:
        if len(to) < 2 or node(A, to) is None:
            raise EditError("Pick the computer or board the node runs on")
        A["allocs"].append([["ROS", nm], to])
        return f"{'launch file' if launch else 'ROS node'} {nm} runs on {'.'.join(to)}", []
    return f"{'launch file' if launch else 'ROS node'} {nm} not allocated", []


def op_satisfy(cfg, A, f, ctx):
    rid = str(f.get("rid") or "").upper()
    if rid not in {r["id"] for r in (ctx["model"] or {}).get("requirements", [])}:
        raise EditError(f"no requirement {rid}")
    tn = A["top"]["name"]
    A["sats"] = [x for x in A["sats"] if x[0] != rid]
    for full in f.get("parts") or []:
        segs = split_path(tn, full)
        if len(segs) < 2 or node(A, segs) is None:
            raise EditError(f"no part {full}")
        A["sats"].append([rid, segs])
    return f"{rid} belongs to {', '.join(f.get('parts') or []) or 'its subsystem'}", []


def op_bom_columns(cfg, A, f, ctx):
    cols = []
    for c in f.get("columns") or []:
        k = re.sub(r"\W+", "_", str(c).strip().lower()).strip("_")
        if k and k not in cols:
            cols.append(k)
    cfg.setdefault("bom", {})["columns"] = cols
    return "BOM columns", []


def op_bom_item(cfg, A, f, ctx):
    items = cfg.setdefault("bom_item", [])
    idx = f.get("index")
    if f.get("delete"):
        del items[int(idx)]
        return "remove BOM item", []
    item = str(f.get("item") or "").strip()
    if not item:
        raise EditError("Item is required (e.g. M3x8 screw, heat-shrink, zip ties)")
    row = {"item": item, "qty": str(f.get("qty") or "1").strip(), **_attrs(f.get("attrs"))}
    if idx not in (None, ""):
        items[int(idx)] = row
        return f"edit BOM item {item}", []
    items.append(row)
    return f"add BOM item {item}", []


PAGES_WORKFLOW = """# Publishes the doc-kit page (read-only) to GitHub Pages on every push.
# Written by doc-kit (Setup > Publish). Enable once: repo Settings > Pages > Source: GitHub Actions.
name: doc-kit page
on:
  push:
    branches: [main, master]
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
  issues: read
concurrency:
  group: pages
  cancel-in-progress: true
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Build the page (it is published even when the model has problems; they show on it)
        run: python3 tools/doc-kit/doc.py model --no-open || true
        env:
          GH_TOKEN: ${{ github.token }}
      - run: |
          mkdir -p _site
          cp docs/system.html _site/index.html
          if [ -d docs/media ]; then cp -r docs/media _site/media; fi
      - uses: actions/upload-pages-artifact@v3
        with:
          path: _site
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
"""


def op_pages(cfg, A, f, ctx):
    path = os.path.join(ctx["root"], ".github", "workflows", "doc-kit-pages.yml")
    if f.get("disable"):
        if not os.path.exists(path):
            raise EditError("publishing is not set up")
        ctx["extra"].append((path, None))
        return "stop publishing the page to GitHub Pages", []
    ctx["extra"].append((path, PAGES_WORKFLOW))
    return "publish the page to GitHub Pages", ["Then, once: repo Settings > Pages > Source: GitHub Actions."]


# ---------------------------------------------------------------- ROS plan (Software view)

def _act(A, name, create=True):
    a = next((x for x in A.setdefault("acts", []) if x["name"] == name), None)
    if a is None and create:
        a = {"name": name, "doc": "", "out": [], "in": []}
        A["acts"].append(a)
    return a


def _topic(t):
    t = str(t or "").strip()
    if not t:
        raise EditError("Topic is required, e.g. /cmd_vel")
    if not re.match(r"^~?/?[A-Za-z_][\w/{}~]*$", t):
        raise EditError(f"{t} is not a ROS topic name (letters, digits, _ and /)")
    return t if t.startswith(("/", "~")) else "/" + t


def op_ros_node(cfg, A, f, ctx):
    """Plan a node: name, what it does, topics out and in, and where it runs."""
    name = check_name(f.get("name"), "Node")
    orig = str(f.get("orig") or "")
    code = {n["name"] for n in (ctx["model"] or {}).get("nodes", []) if n.get("lang") != "plan"}
    if orig and orig != name:
        if orig in code:
            raise EditError(f"{orig} is in the code; rename it there")
        a = _act(A, orig, False)
        if a:
            a["name"] = name
        for x in A["allocs"]:
            if x[0][-1] == orig:
                x[0][-1] = name
    elif not orig and (_act(A, name, False) or name in code):
        raise EditError(f"there is already a node {name}; click it to edit its plan")
    a = _act(A, name)
    a["doc"] = str(f.get("doc") or "").strip()
    for io in ("out", "in"):
        rows = []
        for r in f.get(io) or []:
            if str(r.get("topic") or "").strip():
                rows.append({"topic": _topic(r["topic"]), "type": str(r.get("type") or "").strip()})
        a[io] = rows
    if "to" in f and [x[1] for x in A["allocs"] if x[0][-1] == name] != ([split_path(A["top"]["name"], f.get("to"))] if f.get("to") else []):
        to = split_path(A["top"]["name"], f.get("to"))
        A["allocs"] = [x for x in A["allocs"] if x[0][-1] != name]
        if to:
            if node(A, to) is None:
                raise EditError(f"no part {'.'.join(to)}")
            A["allocs"].append([["ROS", name], to])
    return f"ROS plan: node {name}", []


def op_ros_node_delete(cfg, A, f, ctx):
    name = str(f.get("name") or "")
    if not _act(A, name, False):
        raise EditError(f"{name} has no plan")
    A["acts"] = [x for x in A["acts"] if x["name"] != name]
    code = {n["name"] for n in (ctx["model"] or {}).get("nodes", []) if n.get("lang") != "plan"}
    if name not in code:
        A["allocs"] = [x for x in A["allocs"] if x[0][-1] != name]
    return f"ROS plan: remove node {name}", []


def op_ros_topic(cfg, A, f, ctx):
    """A topic between nodes: from publishes it, to subscribes to it (either may be empty)."""
    t = _topic(f.get("topic"))
    typ = str(f.get("type") or "").strip()
    nodes = {n["name"]: n for n in (ctx["model"] or {}).get("nodes", [])}
    have = [x for x in next((tp["types"] for tp in (ctx["model"] or {}).get("topics", []) if tp["topic"] == t), []) if x != "?"]
    if have and typ and typ not in have:
        raise EditError(f"{t} carries {have[0]}, not {typ}: both ends of a topic must use the same message type "
                        f"(use another topic name for {typ.split('/')[-1]})")
    typ = typ or (have[0] if have else "")
    if f.get("from") and f.get("from") == f.get("to"):
        raise EditError("A node cannot be both ends of the same new topic; pick two different nodes")
    done = []
    for who, io in ((f.get("from"), "out"), (f.get("to"), "in")):
        if not who:
            continue
        if who not in nodes and not _act(A, who, False):
            raise EditError(f"no ROS node {who}")
        a = _act(A, who)
        n = nodes.get(who)
        if n and n.get("lang") != "plan" and not a["out"] and not a["in"]:  # first plan for a node in code: start from what the code does
            a["out"] = [{"topic": e["topic"], "type": e["type"]} for e in n["pub"] if not e.get("planned")]
            a["in"] = [{"topic": e["topic"], "type": e["type"]} for e in n["sub"] if not e.get("planned")]
        if not any(x["topic"] == t for x in a[io]):
            a[io].append({"topic": t, "type": typ})
        done.append(f"{who} {'publishes' if io == 'out' else 'subscribes to'} {t}")
    if not done:
        raise EditError("Pick a publisher or a subscriber")
    return "ROS plan: " + ", ".join(done), []


def op_ros_unplan(cfg, A, f, ctx):
    """Drop one planned topic from a node."""
    a = _act(A, str(f.get("node") or ""), False)
    if not a:
        raise EditError("that node has no plan")
    t = str(f.get("topic") or "")
    for io in ("out", "in"):
        a[io] = [x for x in a[io] if x["topic"] != t]
    return f"ROS plan: {a['name']} without {t}", []


def op_ros_link(cfg, A, f, ctx):
    """Mark the wire that carries ROS (micro-ROS agent link, Ethernet...) between two computers."""
    tn = A["top"]["name"]
    ends = [split_path(tn, f.get("a")), split_path(tn, f.get("b"))]
    via = str(f.get("via") or "").strip()
    for c in A["connects"]:
        if sorted([c[0], c[1]]) == sorted(ends):
            if via:
                c[2]["ros"] = via
            else:
                c[2].pop("ros", None)
            return (f"ROS link {'.'.join(ends[0])} ↔ {'.'.join(ends[1])}: {via}" if via
                    else f"ROS link removed from {'.'.join(ends[0])} ↔ {'.'.join(ends[1])}"), []
    raise EditError("no such wire; connect the two in the Electrical view first")


OPS = {"ros_node": op_ros_node, "ros_node_delete": op_ros_node_delete, "ros_topic": op_ros_topic, "ros_unplan": op_ros_unplan, "ros_link": op_ros_link,
       "subsystem": op_subsystem, "subsystem_delete": op_subsystem_delete, "subsystem_restore": op_subsystem_restore,
       "subsystem_move": op_subsystem_move, "board": op_board, "board_remove": op_board_remove, "ros_paths": op_ros_paths,
       "port_type": op_port_type, "port_type_delete": op_port_type_delete, "part": op_part, "part_delete": op_part_delete,
       "connect": op_connect, "disconnect": op_disconnect, "allocate": op_allocate, "satisfy": op_satisfy,
       "wire": op_wire, "bom_columns": op_bom_columns, "bom_item": op_bom_item, "pages": op_pages}


def run(op, root, f, model):
    """Returns (writes, message, notes). Nothing is written here."""
    cfg = load_cfg(root)
    A = load_arch(root, cfg)
    adopt(cfg, A)
    ctx = {"root": root, "model": model, "extra": []}
    msg, notes = OPS[op](cfg, A, f, ctx)
    ensure_boxes(cfg, A)
    writes = []
    for path, text in [(cfg_path(root), cfg_text(cfg)), (arch_path(root, cfg), arch_text(A, cfg))] + synced_files(root, cfg) + ctx["extra"]:
        old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if text != old:
            writes.append((path, text))
    if not writes:
        raise EditError("No change.")
    return writes, msg, notes


# ================================================================ part library (templates shared between projects)
# Folders are listed per computer in ~/.config/doc-kit/settings.json, so one library can serve
# every project. A folder inside the project is committed with it (shared with the team);
# a folder outside is only written.

def settings_path():
    return os.path.join(os.path.expanduser("~"), ".config", "doc-kit", "settings.json")


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as fh:
            s = json.load(fh)
    except (OSError, ValueError):
        s = {}
    s.setdefault("libraries", [])
    s.setdefault("default", None)
    return s


def lib_abs(root, p):
    p = os.path.expanduser(str(p or "").strip())
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(root, p))


def _in_repo(root, path):
    return os.path.realpath(path).startswith(os.path.realpath(root) + os.sep)


def library_info(root):
    s = load_settings()
    folders = []
    for p in s["libraries"]:
        full = lib_abs(root, p)
        temps = []
        if os.path.isdir(full):
            for fn in sorted(os.listdir(full)):
                if fn.endswith(".json"):
                    try:
                        t = json.load(open(os.path.join(full, fn), encoding="utf-8"))
                        temps.append({"file": fn, "name": t.get("name", fn[:-5]), "doc": t.get("doc", ""),
                                      "attrs": t.get("attrs", {}), "ports": t.get("ports", [])})
                    except (OSError, ValueError):
                        pass
        folders.append({"path": p, "full": full, "exists": os.path.isdir(full), "in_repo": _in_repo(root, full),
                        "default": p == s["default"], "templates": temps})
    return {"folders": folders, "default": s["default"], "settings": settings_path(), "suggest": _folder_suggestions(root)}


def _folder_suggestions(root):
    """Folders you might keep parts in: this project's folders (two levels) and the top of your home folder."""
    out = ["docs/model/parts"]
    skip = {".git", "node_modules", "__pycache__", "build", "install", "log", "tools"}
    for base, depth in ((root, 2), (os.path.expanduser("~"), 1)):
        stack = [(base, 0)]
        while stack:
            cur, lv = stack.pop()
            try:
                names = sorted(os.listdir(cur))
            except OSError:
                continue
            for n in names:
                full = os.path.join(cur, n)
                if n.startswith(".") or n in skip or not os.path.isdir(full):
                    continue
                out.append(os.path.relpath(full, root) if base == root else "~/" + os.path.relpath(full, base))
                if lv + 1 < depth:
                    stack.append((full, lv + 1))
    return list(dict.fromkeys(out))[:200]


def run_library(op, root, f):
    """Returns (writes, message, notes); writes may lie outside the project (then they are not committed)."""
    s = load_settings()
    writes, notes = [], []

    def save_settings():
        writes.append((settings_path(), json.dumps(s, indent=2) + "\n"))
    if op == "lib_folder":
        p = str(f.get("path") or "").strip()
        if not p:
            raise EditError("Folder is required, e.g. ~/robotics/parts or docs/model/parts")
        full = lib_abs(root, p)
        if not os.path.isdir(full):
            writes.append((os.path.join(full, ".keep"), ""))
        if p not in s["libraries"]:
            s["libraries"].append(p)
        if f.get("default") or not s["default"]:
            s["default"] = p
        save_settings()
        notes.append("inside the project: templates there are committed and shared with the team" if _in_repo(root, full)
                     else "outside the project: templates there stay on this computer (share the folder yourself, e.g. a git repo)")
        return writes, f"part library {p}", notes
    if op == "lib_folder_remove":
        p = f.get("path")
        if p not in s["libraries"]:
            raise EditError("no such library folder")
        s["libraries"].remove(p)
        if s["default"] == p:
            s["default"] = s["libraries"][0] if s["libraries"] else None
        save_settings()
        return writes, f"forget part library {p} (its files are kept)", notes
    if op == "lib_default":
        if f.get("path") not in s["libraries"]:
            raise EditError("no such library folder")
        s["default"] = f["path"]
        save_settings()
        return writes, f"default part library {f['path']}", notes
    if op == "template_save":
        folder = str(f.get("folder") or s["default"] or "").strip()
        if not folder:
            raise EditError("Folder is required, e.g. docs/model/parts or ~/robotics/parts")
        if folder not in s["libraries"]:
            s["libraries"].append(folder)
            if not s["default"]:
                s["default"] = folder
            save_settings()
            notes.append(f"new parts folder {folder}")
        name = str(f.get("name") or "").strip()
        if not name:
            raise EditError("Template name is required, e.g. ICM-42688-P")
        fn = re.sub(r"[^\w.-]+", "_", name).strip("_") + ".json"
        full = os.path.join(lib_abs(root, folder), fn)
        ports = []
        for r in f.get("ports") or []:
            if str(r.get("name") or "").strip():
                ports.append({"name": check_name(r["name"], "Port"), "type": str(r.get("type") or ""), "attrs": _attrs(r.get("attrs"))})
        t = {"name": name, "doc": str(f.get("doc") or "").strip(), "attrs": _attrs(f.get("attrs")), "ports": ports}
        orig = f.get("orig_file")
        if orig and orig != fn:
            writes.append((os.path.join(lib_abs(root, f.get("orig_folder") or folder), orig), None))
        elif os.path.exists(full) and not orig:
            raise EditError(f"{fn} already exists in {folder}; edit that template instead")
        writes.append((full, json.dumps(t, indent=2, ensure_ascii=False) + "\n"))
        return writes, f"parts library: {name}", notes
    if op == "template_delete":
        full = os.path.join(lib_abs(root, f.get("folder")), os.path.basename(str(f.get("file") or "")))
        if not os.path.exists(full):
            raise EditError("no such template")
        writes.append((full, None))
        return writes, f"parts library: delete {f.get('file')}", notes
    raise EditError(f"unknown library operation {op}")


LIB_OPS = {"lib_folder", "lib_folder_remove", "lib_default", "template_save", "template_delete"}
