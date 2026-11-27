"""KiCad netlist import: components and nets -> doc-kit parts, ports and wires.

Reads a KiCad netlist (.net, "KiCad" format; KiCad 5 to 9). A .kicad_sch is exported to a netlist
first with kicad-cli when that is installed. Python standard library only.
"""
import os
import re
import shutil
import subprocess
import tempfile

PASSIVE = re.compile(r"^(R|C|L|FB|TP|H|MH|NT|JP|RN|CN|F)\d", re.I)  # resistors, capacitors, test points, holes…
POWER = re.compile(r"^(GND\w*|AGND|DGND|PGND|VSS\w*|VCC\w*|VDD\w*|VBAT\w*|VBUS|VIN|VSYS|\+?\d+V\d*|\+?\d+V|\+?\d+\.\d+V)$", re.I)
KICAD_CLI = ["kicad-cli", "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
             r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe", r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe"]


class KicadError(Exception):
    pass


def _sexp(text):
    """Tiny S-expression reader: lists of strings."""
    tok = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+', text)
    stack, cur = [], []
    for t in tok:
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(t[1:-1].replace('\\"', '"') if t.startswith('"') else t)
    return cur


def _get(node, key):
    return next((x for x in node if isinstance(x, list) and x and x[0] == key), None)


def _val(node, key, default=""):
    n = _get(node, key)
    return n[1] if n and len(n) > 1 and isinstance(n[1], str) else default


def find_files(root):
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "build", "__pycache__")]
        for f in files:
            if f.endswith((".net", ".kicad_sch")) and "-backups" not in base:
                out.append(os.path.relpath(os.path.join(base, f), root))
    # a .net first, and top-level schematics before sheets (shorter paths first)
    return sorted(out, key=lambda p: (not p.endswith(".net"), p.count(os.sep), p))


def _cli():
    for c in KICAD_CLI:
        if shutil.which(c) or os.path.isfile(c):
            return shutil.which(c) or c
    return None


def read(root, rel):
    path = os.path.normpath(os.path.join(root, rel))
    if not path.startswith(os.path.realpath(root)) and not os.path.exists(path):
        raise KicadError("no such file")
    if not os.path.isfile(path):
        raise KicadError(f"{rel} not found")
    if path.endswith(".kicad_sch"):
        cli = _cli()
        if not cli:
            raise KicadError("Reading a .kicad_sch needs kicad-cli (comes with KiCad 7+). "
                             "Or export one in KiCad: Schematic Editor › File › Export › Netlist… (KiCad format) and pick the .net")
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "x.net")
            r = subprocess.run([cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", out, path], capture_output=True, text=True, timeout=120)
            if r.returncode or not os.path.exists(out):
                raise KicadError("kicad-cli failed: " + (r.stderr or r.stdout).strip()[-300:])
            text = open(out, encoding="utf-8").read()
    else:
        text = open(path, encoding="utf-8", errors="replace").read()
    tree = _sexp(text)
    exp = next((x for x in tree if isinstance(x, list) and x and x[0] == "export"), None)
    if not exp:
        raise KicadError(f"{rel} is not a KiCad netlist (KiCad format, S-expressions)")
    comps = []
    for c in (_get(exp, "components") or [])[1:]:
        if not (isinstance(c, list) and c and c[0] == "comp"):
            continue
        lib = _get(c, "libsource") or []
        sheet = _get(c, "sheetpath") or []
        comps.append({"ref": _val(c, "ref"), "value": _val(c, "value"), "footprint": _val(c, "footprint"),
                      "part": _val(lib, "part"), "lib": _val(lib, "lib"), "sheet": _val(sheet, "names").strip("/")})
    nets = []
    for n in (_get(exp, "nets") or [])[1:]:
        if not (isinstance(n, list) and n and n[0] == "net"):
            continue
        nodes = [{"ref": _val(x, "ref"), "pin": _val(x, "pin"), "fn": _val(x, "pinfunction"), "type": _val(x, "pintype")}
                 for x in n if isinstance(x, list) and x and x[0] == "node"]
        nets.append({"name": _val(n, "name"), "nodes": nodes})
    return comps, nets


def short_net(name):
    return name.rsplit("/", 1)[-1] or name


def ident(s, fallback="pin"):
    t = re.sub(r"\W+", "_", s.replace("+", "")).strip("_")
    if not t:
        return fallback
    return ("v" + t) if t[0].isdigit() else t


def voltage(name):
    n = short_net(name).upper().lstrip("+")
    if n.startswith(("GND", "VSS")) or n in ("AGND", "DGND", "PGND"):
        return "0 V"
    m = re.match(r"^(\d+)V(\d+)$", n) or re.match(r"^(\d+(?:\.\d+)?)V$", n)
    if m:
        return f"{m.group(1)}.{m.group(2)} V" if m.lastindex == 2 else f"{m.group(1)} V"
    return ""


def power_port(name):
    n = short_net(name).lstrip("+")
    return n if re.match(r"^[A-Za-z_]", n) else "pwr_" + re.sub(r"\W+", "_", n)


def is_power(name):
    return bool(POWER.match(short_net(name)))


def is_ground(name):
    return voltage(name) == "0 V"


def preview(root, rel, model):
    """Components with suggestions, for the import form."""
    comps, nets = read(root, rel)
    parts = (model or {}).get("parts", {})
    subs = (model or {}).get("subsystems", [])
    boards = [p for p in parts.values() if p.get("board")]
    by_ref = {(p.get("attrs") or {}).get("kicad_ref"): k for k, p in parts.items() if (p.get("attrs") or {}).get("kicad_ref")}
    mcus = {b["board"]: b.get("mcu", "") for b in (model or {}).get("boards", [])}
    used = {}
    for n in nets:
        for x in n["nodes"]:
            used[x["ref"]] = used.get(x["ref"], 0) + 1
    out, taken = [], set()
    for c in comps:
        target = by_ref.get(c["ref"], "")
        if not target and c["value"] and not PASSIVE.match(c["ref"]):  # a part already on the page with this part number
            v = c["value"].upper()
            target = next((k for k, p in parts.items() if p.get("depth", 0) >= 2 and not p.get("board") and not p.get("children")
                           and v in " ".join(str(x) for x in (p.get("type"), p.get("doc"), (p.get("attrs") or {}).get("part_number")) if x).upper()), "")
        if not target:
            for b in boards:
                mcu = mcus.get(b["board"], "")
                if mcu and (mcu[:9].upper() in (c["value"] + c["part"]).upper()):
                    target = b["path"]
        sub = next((s for s in subs if s.lower() in (c["sheet"].lower(), c["ref"].lower())), "")
        if not sub and c["sheet"]:
            sub = next((s for s in subs if s.lower() in c["sheet"].lower()), "")
        name = ident(c["value"].lower())[:28].strip("_") if c["value"] and not PASSIVE.match(c["ref"]) else ident(c["ref"].lower())
        name = name if name not in taken else f"{name}_{c['ref'].lower()}"
        taken.add(name)
        import docmodel as _dm
        kind = _dm.guess_kind({"name": c["value"], "type": c["part"], "doc": c["lib"], "attrs": {"kicad_ref": c["ref"], "footprint": c["footprint"]}})
        out.append({**c, "kind": kind, "include": not PASSIVE.match(c["ref"]) and used.get(c["ref"], 0) > 0, "target": target,
                    "subsystem": sub, "name": name, "pins": used.get(c["ref"], 0)})
    return {"file": rel, "components": out, "nets": len(nets), "power_nets": sum(1 for n in nets if is_power(n["name"]))}
