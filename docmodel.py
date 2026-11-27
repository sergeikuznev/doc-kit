"""
docmodel.py - the system model for doc-kit.

Builds one model of the robot from the files you already keep:
    .ioc files            boards, peripherals, pins, peripheral settings   (facts)
    ROS2 / micro-ROS code nodes, topics, message types                    (facts)
    docs/requirements.md  requirements                                    (facts)
    docs/fdir.md          faults                                          (facts)
    docs/decisions/       decision records                                (facts)
    docs/model/<name>_arch.sysml   subsystems, modules, wiring, links     (written by you)

and checks that the architecture you wrote still matches the facts.
Nothing is guessed: anything a scanner cannot read for certain is reported as unknown.

Used by doc.py ("doc model"). Python 3.11+ (tomllib), no other dependencies.
"""

import glob
import html
import json
import os
import re

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

REQ_HEADER = "| ID | Requirement | Rationale | Method | Status | Evidence |"
FDIR_HEADER = "| ID | Failure | Effect | Detection | Isolation / response | Recovery | Sev | Req |"

# Port kinds. Every port type specialises one of these; the views filter on them.
KINDS = ["Signal", "Power", "Mechanical"]


class ModelError(Exception):
    pass


# ================================================================ config

def _read(path, overrides=None):
    """File text, or the text a pending page edit would write (for previews)."""
    if overrides and path in overrides:
        return overrides[path]
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_config(root, overrides=None):
    path = os.path.join(root, "docs", "model", "model.toml")
    if not os.path.exists(path) and not (overrides and path in overrides):
        raise ModelError("no docs/model/model.toml (run: doc init)")
    if tomllib is None:
        raise ModelError("doc model needs Python 3.11 or newer")
    try:
        cfg = tomllib.loads(_read(path, overrides))
    except tomllib.TOMLDecodeError as e:
        raise ModelError(f"docs/model/model.toml: {e}")
    if not str(cfg.get("project", {}).get("name", "")).strip():
        raise ModelError("docs/model/model.toml: [project] name is missing")
    cfg.setdefault("board", [])
    cfg.setdefault("subsystem", [])
    cfg.setdefault("ros", {}).setdefault("paths", [])
    return cfg


def subsystem_table(cfg, root=None):
    """[(prefix, name, box, deleted)] from model.toml; older repos: the README table."""
    if cfg.get("subsystem"):
        return [(s["prefix"], s.get("name", s["prefix"]), s.get("box", True), bool(s.get("deleted")))
                for s in cfg["subsystem"] if s.get("prefix")]
    if root:
        rows = _table(os.path.join(root, "docs", "README.md"), "| Prefix | Subsystem |")
        return [(r[0], r[1], r[0] not in ("SYS", "FDIR"), False) for r in rows
                if len(r) > 1 and re.fullmatch(r"[A-Z][A-Z0-9]{1,5}", r[0])]
    return []


def resolve_ioc(root, path):
    """A board's ioc = may name the .ioc file or a folder holding exactly one."""
    full = os.path.join(root, path)
    if os.path.isfile(full):
        return full
    if os.path.isdir(full):
        found = sorted(glob.glob(os.path.join(full, "*.ioc")))
        if len(found) == 1:
            return found[0]
        if not found:
            raise ModelError(f"no .ioc file in {path}")
        names = ", ".join(os.path.basename(f) for f in found)
        raise ModelError(f"{path} holds several .ioc files ({names}); name the file in model.toml")
    raise ModelError(f"{path} does not exist")


# ================================================================ .ioc

def _ioc_lines(path):
    out = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.replace("\\ ", " ").replace("\\:", ":")] = v.replace("\\:", ":")
    return out


SKIP_SETTINGS = {"IPParameters", "VirtualType", "VirtualMode", "VirtualModeFS", "FootprintOK"}
SKIP_IPS = {"NVIC", "RCC", "SYS"}


def _pretty(v):
    """SPI_MODE_MASTER -> master; keep numbers and units as written."""
    m = re.match(r"^[A-Z0-9]+_(?:[A-Z0-9]+_)*?(MODE|POLARITY|PHASE|DIRECTION|ENCODERMODE|BAUDRATEPRESCALER|CHANNEL)_(.+)$", v)
    if m:
        return m.group(2).replace("_", " ").lower()
    return v


def _settings(kv, ip):
    out = []
    for k, v in kv.items():
        if not k.startswith(ip + "."):
            continue
        key = k[len(ip) + 1:]
        if key in SKIP_SETTINGS:
            continue
        m = re.match(r"Channel-(PWM Generation|Input Capture direct mode|Output Compare[\w ]*?)\d* (CH\d)$", key)
        if m:
            out.append([m.group(2), m.group(1).lower()])
            continue
        out.append([NICE.get(key, key), _pretty(v)])
    return out


NICE = {"CalculateBaudRate": "Speed", "BaudRatePrescaler": "Clock prescaler", "CLKPolarity": "Clock polarity (CPOL)",
        "CLKPhase": "Clock phase (CPHA)", "Direction": "Lines", "Mode": "Role", "EncoderMode": "Encoder mode",
        "IC1Filter": "CH1 input filter", "IC2Filter": "CH2 input filter", "Period": "Period (counts)",
        "Prescaler": "Prescaler", "BaudRate": "Baud rate", "WordLength": "Word length", "ClockSpeed": "Clock speed",
        "Timing": "Timing", "CLASS_NAME_FS": "USB class"}


def _port_type(ip, settings):
    s = dict(settings)
    if ip.startswith("SPI"):
        return "SpiBus"
    if ip.startswith("I2C"):
        return "I2cBus"
    if ip.startswith(("USART", "UART", "LPUART")):
        return "UartLink"
    if ip.startswith("USB"):
        return "UsbLink"
    if ip.startswith(("CAN", "FDCAN")):
        return "CanBus"
    if ip.startswith("ADC"):
        return "AnalogIn"
    if ip.startswith("TIM"):
        if "Encoder mode" in s:
            return "EncoderIn"
        if "pwm generation" in s.values():
            return "PwmOut"
        if any(v.startswith("input capture") for v in s.values()):
            return "CaptureIn"
        return "TimerPins"
    return "PeripheralPins"


PORT_DEFS = {  # type -> (kind, plain meaning)
    "SpiBus": ("Signal", "SPI bus"), "I2cBus": ("Signal", "I2C bus"), "UartLink": ("Signal", "UART"),
    "UsbLink": ("Signal", "USB"), "CanBus": ("Signal", "CAN bus"), "AnalogIn": ("Signal", "analog input"),
    "EncoderIn": ("Signal", "encoder input"), "PwmOut": ("Signal", "PWM output"),
    "CaptureIn": ("Signal", "input capture"), "TimerPins": ("Signal", "timer pins"),
    "PeripheralPins": ("Signal", "peripheral pins"), "GpioOut": ("Signal", "GPIO output"),
    "GpioIn": ("Signal", "GPIO input"), "EthernetLink": ("Signal", "Ethernet"), "WifiLink": ("Signal", "WiFi"),
    "RadioLink": ("Signal", "radio link"),
}
KIND_MEANING = {"Signal": "signal", "Power": "power", "Mechanical": "mechanical mount"}


def meaning_of(ptype, port_defs):
    if ptype in PORT_DEFS:
        return PORT_DEFS[ptype][1]
    if port_defs.get(ptype, {}).get("doc"):
        return port_defs[ptype]["doc"]
    return KIND_MEANING.get(ptype, ptype)


def _derived(ip, settings):
    """Facts that follow directly from saved settings; say 'CubeMX default' when not saved."""
    s = dict(settings)
    notes = []
    if ip.startswith("SPI"):
        cp, ch = s.get("Clock polarity (CPOL)"), s.get("Clock phase (CPHA)")
        if cp or ch:
            pol = 1 if "high" in (cp or "low") else 0
            pha = 1 if "2edge" in (ch or "1edge") else 0
            notes.append(["SPI mode", f"{pol * 2 + pha} (CPOL={pol}, CPHA={pha})"])
        else:
            notes.append(["CPOL / CPHA", "not saved (CubeMX default)"])
    return notes


def _ident(text):
    t = re.sub(r"\W+", "_", text).strip("_").lower()
    return t or "pin"


def parse_ioc(path, board):
    kv = _ioc_lines(path)
    mcu = kv.get("Mcu.CPN") or kv.get("Mcu.UserName") or "MCU"
    ips = sorted({v for k, v in kv.items() if re.match(r"Mcu\.IP\d+$", k)})
    pins = {}  # pin -> {signal, label}
    for k, v in kv.items():
        m = re.match(r"^(P[A-K]\d+)(?: - [^.]+)?\.(Signal|GPIO_Label)$", k)
        if m:
            pins.setdefault(m.group(1), {})[m.group(2)] = v
    ports, used = [], set()

    def add(name, ptype, pin_list, settings, ip=None, label=None):
        base, n = _ident(name), 2
        name = base
        while name in used:
            name, n = f"{base}_{n}", n + 1
        used.add(name)
        kind, meaning = PORT_DEFS.get(ptype, ("Signal", ptype))
        ports.append({"name": name, "type": ptype, "kind": kind, "meaning": meaning, "pins": pin_list,
                      "settings": settings, "ip": ip, "label": label, "conj": False})

    by_ip = {}
    for pin, d in pins.items():
        sig = d.get("Signal", "")
        if sig.startswith("GPIO_") or sig.startswith("GPXTI"):
            label = d.get("GPIO_Label") or pin
            ptype = "GpioOut" if sig == "GPIO_Output" else "GpioIn"
            note = "interrupt (EXTI)" if sig.startswith("GPXTI") else sig.replace("GPIO_", "").lower()
            add(label, ptype, [[pin, note]], [], label=d.get("GPIO_Label"))
            continue
        ip = sig[2:] if sig.startswith("S_") else sig
        ip_name = next((i for i in sorted(ips, key=len, reverse=True) if ip.startswith(i)), None)
        if not ip_name or ip_name in SKIP_IPS:
            continue
        func = ip[len(ip_name):].lstrip("_") or sig
        note = func + (f" ({d['GPIO_Label']})" if d.get("GPIO_Label") else "")
        by_ip.setdefault(ip_name, []).append([pin, note])
    for ip_name in sorted(by_ip):
        st = _settings(kv, ip_name)
        add(ip_name, _port_type(ip_name, st), sorted(by_ip[ip_name], key=lambda x: (x[0][:2], int(x[0][2:]))),
            st + _derived(ip_name, st), ip=ip_name)

    internal = []  # peripherals without pins (timebases, middleware)
    for ip_name in ips:
        if ip_name in by_ip or ip_name in SKIP_IPS:
            continue
        st = _settings(kv, ip_name)
        if ip_name == "FREERTOS":
            tasks = kv.get("FREERTOS.Tasks01", "")
            st = [s for s in st if s[0] != "Tasks01"]
            for t in filter(None, tasks.split(";")):
                f = t.split(",")
                if len(f) >= 4:
                    st.insert(0, [f"task {f[0]}", f"priority {f[1]}, stack {f[2]} words, entry {f[3]}()"])
        if st:
            internal.append({"ip": ip_name, "settings": st})
    clocks = []
    for key, label in (("RCC.SYSCLKFreq_VALUE", "SYSCLK"), ("RCC.HCLKFreq_Value", "HCLK"),
                       ("RCC.APB1Freq_Value", "APB1"), ("RCC.APB2Freq_Value", "APB2")):
        if key in kv and kv[key].isdigit():
            clocks.append([label, f"{int(kv[key]) / 1e6:g} MHz"])
    defname = board.get("def") or re.sub(r"\W", "_", board["name"]).upper()
    return {"def": defname, "mcu": mcu, "package": kv.get("Mcu.Package", ""), "source": os.path.basename(path),
            "ports": ports, "internal": internal, "clocks": clocks, "cubemx": kv.get("MxCube.Version", "")}


# ================================================================ ROS2 static scan

_C_STR = r'"([^"\\]*)"'
ROS_RULES = [
    # (language, regex, role, groups -> (type, topic))
    ("cpp", re.compile(r"create_publisher\s*<\s*([\w:]+)\s*>\s*\(\s*(" + _C_STR + r"|[^,)]+)"), "pub"),
    ("cpp", re.compile(r"create_subscription\s*<\s*([\w:]+)\s*>\s*\(\s*(" + _C_STR + r"|[^,)]+)"), "sub"),
    ("py", re.compile(r"create_publisher\s*\(\s*([\w.]+)\s*,\s*(['\"]([^'\"]*)['\"]|[^,)]+)"), "pub"),
    ("py", re.compile(r"create_subscription\s*\(\s*([\w.]+)\s*,\s*(['\"]([^'\"]*)['\"]|[^,)]+)"), "sub"),
    ("c", re.compile(r"rclc_publisher_init\w*\s*\([^;]*?ROSIDL_GET_MSG_TYPE_SUPPORT\s*\(\s*(\w+)\s*,\s*\w+\s*,\s*(\w+)\s*\)\s*,\s*(" + _C_STR + r"|[^,)]+)", re.S), "pub"),
    ("c", re.compile(r"rclc_subscription_init\w*\s*\([^;]*?ROSIDL_GET_MSG_TYPE_SUPPORT\s*\(\s*(\w+)\s*,\s*\w+\s*,\s*(\w+)\s*\)\s*,\s*(" + _C_STR + r"|[^,)]+)", re.S), "sub"),
]
NODE_RULES = {
    "cpp": re.compile(r"(?:Node|LifecycleNode)\s*\(\s*" + _C_STR),
    "py": re.compile(r"super\(\)\.__init__\s*\(\s*['\"]([^'\"]+)['\"]|Node\s*\(\s*['\"]([^'\"]+)['\"]"),
    "c": re.compile(r"rclc_node_init\w*\s*\(\s*[^,]+,\s*" + _C_STR),
}
EXT = {".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp", ".py": "py", ".c": "c"}


def _line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def scan_ros(root, paths):
    nodes, unknown = {}, []
    files = []
    for p in paths:
        full = os.path.join(root, p)
        if os.path.isfile(full):
            files.append(full)
        for dirpath, dirs, names in os.walk(full):
            dirs[:] = [d for d in dirs if d not in ("build", "install", "log", ".git", "Drivers", "Middlewares")]
            files += [os.path.join(dirpath, n) for n in names if os.path.splitext(n)[1] in EXT]
    for f in sorted(set(files)):
        lang = EXT[os.path.splitext(f)[1]]
        text = open(f, encoding="utf-8", errors="replace").read()
        relf = os.path.relpath(f, root)
        imports = {}
        if lang == "py":
            for im in re.finditer(r"from\s+(\w+)\.msg\s+import\s+([\w, ()\n]+)", text):
                for nm in re.findall(r"\w+", im.group(2)):
                    imports[nm] = f"{im.group(1)}/msg/{nm}"
        found_nodes = [(m.start(), next(g for g in m.groups() if g)) for m in NODE_RULES[lang].finditer(text)]
        endpoints = []
        for rl, rx, role in ROS_RULES:
            if rl != lang:
                continue
            for m in rx.finditer(text):
                g = m.groups()
                if lang == "c":
                    mtype, raw, lit = f"{g[0]}/msg/{g[1]}", g[2], g[3]
                else:
                    mtype, raw, lit = g[0].replace("::", "/").replace(".", "/"), g[1], g[2]
                    mtype = imports.get(mtype, mtype)
                endpoints.append((m.start(), role, mtype, lit, raw.strip(), _line_of(text, m.start())))
        if not endpoints and not found_nodes:
            continue
        if not found_nodes:
            unknown.append(f"{relf}: topics found but no node name written as text")
            found_nodes = [(0, os.path.splitext(os.path.basename(f))[0] + " (node name unknown)")]
        for pos, role, mtype, lit, raw, line in sorted(endpoints):
            owner = [n for n in found_nodes if n[0] <= pos] or found_nodes[:1]
            name = owner[-1][1]
            node = nodes.setdefault(name, {"name": name, "file": relf, "lang": lang, "pub": [], "sub": []})
            if lit is None:
                unknown.append(f"{relf}:{line}: topic name is built at runtime ({raw}), so it cannot be read; write it as a plain string to have it mapped")
                continue
            node[role].append({"topic": lit if lit.startswith("/") else "/" + lit, "type": mtype, "line": line})
        for _, name in found_nodes:
            nodes.setdefault(name, {"name": name, "file": relf, "lang": lang, "pub": [], "sub": []})
    return list(nodes.values()), unknown


# ================================================================ docs

def _cells(line):
    parts = re.split(r"(?<!\\)\|", line.strip())[1:-1]
    return [c.strip() for c in parts]


def _table(path, header):
    if not os.path.exists(path):
        return []
    rows, inside = [], False
    for line in open(path, encoding="utf-8"):
        s = line.strip()
        if s == header:
            inside = True
            continue
        if inside:
            if not s.startswith("|"):
                inside = False
                continue
            if re.match(r"^\|[\s:|-]+\|$", s):
                continue
            rows.append(_cells(s))
    return rows


def load_docs(root):
    reqs = []
    for r in _table(os.path.join(root, "docs", "requirements.md"), REQ_HEADER):
        r += [""] * (6 - len(r))
        reqs.append({"id": r[0], "text": r[1], "rationale": r[2], "method": r[3], "status": r[4] or "Draft",
                     "evidence": [e.strip() for e in r[5].split("<br>") if e.strip()],
                     "prefix": r[0].rsplit("-", 1)[0]})
    faults = []
    for f in _table(os.path.join(root, "docs", "fdir.md"), FDIR_HEADER):
        f += [""] * (8 - len(f))
        faults.append({"id": f[0], "failure": f[1], "effect": f[2], "detection": f[3], "response": f[4],
                       "recovery": f[5], "sev": f[6], "req": f[7]})
    decisions = []
    folder = os.path.join(root, "docs", "decisions")
    if os.path.isdir(folder):
        for fn in sorted(os.listdir(folder)):
            m = re.match(r"(\d{3})-", fn)
            if not m or int(m.group(1)) == 0:
                continue
            text = open(os.path.join(folder, fn), encoding="utf-8").read()

            def field(name):
                x = re.search(rf"\*\*{name}:\*\*\s*(.*)$", text, re.M)
                return x.group(1).strip() if x else ""

            def sect(name):
                x = re.search(rf"^## {name}\s*\n(.*?)(?=\n## |\Z)", text, re.S | re.M)
                return x.group(1).strip() if x else ""
            title = re.search(r"^#\s*\d+\.\s*(.*)$", text, re.M)
            decisions.append({"num": m.group(1), "file": fn, "title": title.group(1) if title else fn,
                              "status": field("Status"), "date": field("Date"), "related": field("Related"),
                              "decision": sect("Decision"), "why": sect("Why") or sect("Rationale")})
    return reqs, faults, decisions


# ================================================================ SysML subset parser

TOKEN = re.compile(r"""
    (?P<doc>/\*.*?\*/) | (?P<comment>//[^\n]*) | (?P<ws>\s+) |
    (?P<str>"[^"]*") | (?P<qname>'[^']*') |
    (?P<sym>:>|::|[{};:~.,=]) | (?P<id>[A-Za-z_]\w*) | (?P<num>\d[\w.]*) | (?P<bad>.)
""", re.S | re.X)


def tokenize(text):
    out = []
    for m in TOKEN.finditer(text):
        k = m.lastgroup
        if k in ("ws", "comment"):
            continue
        v = m.group()
        if k == "qname":
            k, v = "id", v[1:-1]
        out.append((k, v, text.count("\n", 0, m.start()) + 1))
    return out


class Parser:
    def __init__(self, text, fname):
        self.t, self.i, self.f = tokenize(text), 0, fname

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else ("eof", "", self.t[-1][2] if self.t else 1)

    def err(self, msg):
        raise ModelError(f"{self.f}:{self.peek()[2]}: {msg}")

    def take(self, value=None, kind=None):
        tok = self.peek()
        if (value and tok[1] != value) or (kind and tok[0] != kind):
            self.err(f"expected {value or kind}, found {tok[1] or 'end of file'!r}")
        self.i += 1
        return tok

    def accept(self, value):
        if self.peek()[1] == value:
            self.i += 1
            return True
        return False

    def path(self):
        parts = [self.take(kind="id")[1]]
        while self.peek()[1] in (".", "::"):
            self.i += 1
            parts.append(self.take(kind="id")[1])
        return parts

    def skip_block(self):
        depth = 0
        while True:
            k, v, _ = self.take()
            depth += {"{": 1, "}": -1}.get(v, 0)
            if depth == 0 and v in ("}", ";"):
                return

    def attrs_block(self, target):
        """{ attribute key = "value"; doc /* */ ... }  ->  target["attrs"]; other elements are skipped."""
        while not self.accept("}"):
            k, v, _ = self.peek()
            if v == "attribute":
                self.attribute(target)
            elif k == "doc":
                self.take()
            elif v == "doc":
                self.take()
                if self.peek()[0] == "doc":
                    self.take()
            else:
                self.skip_block()

    def attribute(self, owner):
        self.take("attribute")
        key = self.take(kind="id")[1]
        if self.accept(":"):
            self.path()
        val = ""
        if self.accept("="):
            parts = []
            while self.peek()[1] not in (";", "}", "") and self.peek()[0] != "eof":
                t = self.take()
                parts.append(t[1][1:-1] if t[0] == "str" else t[1])
            val = " ".join(parts)
        if self.peek()[1] == "{":
            self.skip_block()
        else:
            self.take(";")
        if owner is not None:
            owner.setdefault("attrs", {})[key] = val

    def doc_of(self):
        if self.peek()[0] == "doc":
            return re.sub(r"^/\*|\*/$", "", self.take()[1]).strip()
        return ""

    # ---- grammar
    def parse(self):
        model = {"port_defs": {}, "part_defs": {}, "parts": [], "allocations": [], "satisfies": [], "doc": ""}
        while self.peek()[0] != "eof":
            if self.peek()[1] == "package":
                self.take()
                self.path()
                self.take("{")
                self.body(model, top=True)
                self.take("}")
            else:
                self.element(model, None, top=True)
        return model

    def body(self, model, top):
        while self.peek()[1] not in ("}", "") and self.peek()[0] != "eof":
            self.element(model, None, top)

    def element(self, model, owner, top):
        k, v, line = self.peek()
        if k == "doc" and v.startswith("/*"):
            self.take()
            if owner is not None:
                owner["doc"] = re.sub(r"^/\*|\*/$", "", v).strip()
            return
        if v == "doc":
            self.take()
            d = self.take(kind="doc")[1] if self.peek()[0] == "doc" else ""
            if owner is not None:
                owner["doc"] = re.sub(r"^/\*|\*/$", "", d).strip()
            return
        if v in ("private", "public", "protected"):
            self.take()
            return
        if v == "import":
            while self.take()[1] != ";":
                pass
            return
        if v == "port" and self.peek(1)[1] == "def":
            self.take(); self.take()
            name = self.take(kind="id")[1]
            sup = None
            if self.accept(":>"):
                sup = self.path()[-1]
            pdoc = ""
            if self.accept("{"):
                depth = 1
                while depth:
                    k2, v2, _ = self.take()
                    if k2 == "doc":
                        pdoc = re.sub(r"^/\*|\*/$", "", v2).strip()
                    depth += {"{": 1, "}": -1}.get(v2, 0)
            else:
                self.take(";")
            model["port_defs"][name] = {"super": sup, "line": line, "doc": pdoc}
            return
        if v == "part" and self.peek(1)[1] == "def":
            self.take(); self.take()
            name = self.take(kind="id")[1]
            d = {"name": name, "ports": [], "doc": "", "line": line, "attrs": {}}
            if self.accept(":>"):
                self.path()
            if self.accept("{"):
                while not self.accept("}"):
                    self.element(model, d, False)
            else:
                self.take(";")
            model["part_defs"][name] = d
            return
        if v == "part":
            self.take()
            name = self.take(kind="id")[1]
            p = {"name": name, "type": None, "parts": [], "ports": [], "connects": [], "doc": "", "line": line, "attrs": {}}
            if self.accept(":"):
                p["type"] = self.path()[-1]
            if self.accept("{"):
                while not self.accept("}"):
                    self.element(model, p, False)
            else:
                self.take(";")
            (owner["parts"] if owner is not None and "parts" in owner else model["parts"]).append(p)
            return
        if v == "port":
            self.take()
            name = self.take(kind="id")[1]
            self.take(":")
            conj = self.accept("~")
            ptype = self.path()[-1]
            port = {"name": name, "type": ptype, "conj": conj, "line": line, "attrs": {}}
            if self.accept("{"):
                self.attrs_block(port)
            else:
                self.take(";")
            if owner is None:
                self.err("a port must be inside a part or part def")
            owner["ports"].append(port)
            return
        if v == "connect":
            self.take()
            a = self.path()
            self.take("to")
            b = self.path()
            c = {"a": a, "b": b, "line": line, "attrs": {}}
            if self.accept("{"):
                self.attrs_block(c)
            else:
                self.take(";")
            if owner is None or "connects" not in owner:
                self.err("connect must be inside a part")
            owner["connects"].append(c)
            return
        if v == "allocate":
            self.take()
            a = self.path()
            self.take("to")
            b = self.path()
            self.take(";")
            model["allocations"].append({"what": a, "to": b, "line": line})
            return
        if v == "satisfy":
            self.take()
            self.accept("requirement")
            rid = self.take(kind="id")[1]
            self.take("by")
            b = self.path()
            self.take(";")
            model["satisfies"].append({"req": rid, "by": b, "line": line})
            return
        if v == "attribute":
            self.attribute(owner)
            return
        if v in ("item", "requirement", "action", "state", "alias", "comment", "metadata"):
            self.skip_block()
            return
        self.err(f"unexpected {v!r} (doc model reads: part, part def, port, port def, connect, allocate, satisfy)")


# ================================================================ build + check

def _kind_of(ptype, port_defs, seen=None):
    if ptype in KINDS:
        return ptype
    if ptype in PORT_DEFS:
        return PORT_DEFS[ptype][0]
    d = port_defs.get(ptype)
    seen = seen or set()
    if d and d["super"] and ptype not in seen:
        seen.add(ptype)
        return _kind_of(d["super"], port_defs, seen)
    return None


def build(root, overrides=None):
    cfg = load_config(root, overrides)
    name = cfg["project"]["name"]
    problems, notes = [], []

    boards = []
    for b in cfg["board"]:
        if "name" not in b or "ioc" not in b:
            raise ModelError("each [[board]] in model.toml needs name and ioc")
        boards.append(parse_ioc(resolve_ioc(root, b["ioc"]), b) | {"board": b["name"]})
    nodes, ros_unknown = scan_ros(root, cfg["ros"]["paths"])
    launches = scan_launch(root, cfg["ros"]["paths"])
    for n in nodes:
        n["launch"] = [dict(e, file=l["file"]) for l in launches for e in l["nodes"]
                       if n["name"] in (e.get("name"), e.get("executable"))]
    reqs, faults, decisions = load_docs(root)

    arch_path = os.path.join(root, "docs", "model", f"{name}_arch.sysml")
    afile = os.path.relpath(arch_path, root)
    if os.path.exists(arch_path) or (overrides and arch_path in overrides):
        arch = Parser(_read(arch_path, overrides), afile).parse()
    else:
        arch = {"port_defs": {}, "part_defs": {}, "parts": [], "allocations": [], "satisfies": [], "doc": ""}
    if not arch["parts"]:
        arch["parts"] = [{"name": name, "type": None, "parts": [], "ports": [], "connects": [], "doc": "", "line": 1}]
    table = subsystem_table(cfg, root)
    box_subs = [t[0] for t in table if t[2] and not t[3]]
    group_only = [t[0] for t in table if not t[2] and not t[3]]

    defs = {}  # part def name -> {ports, source, doc, board?}
    for b in boards:
        defs[b["def"]] = {"ports": b["ports"], "source": "facts", "doc": f"{b['mcu']} - from {b['source']}", "board": b}
    for dn, d in arch["part_defs"].items():
        if dn in defs:
            problems.append(f"{afile}:{d['line']}: part def {dn} is already defined by the facts")
            continue
        ports = []
        for q in d["ports"]:
            kind = _kind_of(q["type"], arch["port_defs"])
            if kind is None:
                problems.append(f"{afile}:{q['line']}: port {dn}.{q['name']}: unknown type {q['type']}")
            ports.append({"name": q["name"], "type": q["type"], "conj": q["conj"], "kind": kind or "Signal",
                          "meaning": meaning_of(q["type"], arch["port_defs"]), "pins": [], "settings": [], "attrs": q.get("attrs", {})})
        defs[dn] = {"ports": ports, "source": "arch", "doc": d["doc"], "attrs": d.get("attrs", {})}

    if len(arch["parts"]) != 1:
        raise ModelError(f"{afile}: write exactly one top-level part (the robot), found {len(arch['parts'])}")
    top = arch["parts"][0]

    parts = {}  # path -> part

    def walk(p, prefix, subsystem):
        path = prefix + [p["name"]]
        key = ".".join(path)
        sub = subsystem or (path[1] if len(path) > 1 else None)
        ports = []
        if p["type"]:
            if p["type"] not in defs:
                problems.append(f"{afile}:{p['line']}: part {key}: type {p['type']} is not defined")
            else:
                ports = [dict(q) for q in defs[p["type"]]["ports"]]
        for q in p["ports"]:
            base = next((x for x in ports if x["name"] == q["name"] and not x.get("own")), None)
            if base is not None:  # same name as a port of its type: adds details (voltage, address, ...) to that port
                if q["type"] != base["type"]:
                    problems.append(f"{afile}:{q['line']}: port {key}.{q['name']}: its type says {base['type']}, not {q['type']}")
                base["attrs"] = {**base.get("attrs", {}), **q.get("attrs", {})}
                continue
            kind = _kind_of(q["type"], arch["port_defs"])
            if kind is None:
                problems.append(f"{afile}:{q['line']}: port {key}.{q['name']}: unknown type {q['type']}")
            ports.append({"name": q["name"], "type": q["type"], "conj": q["conj"], "kind": kind or "Signal",
                          "meaning": meaning_of(q["type"], arch["port_defs"]), "pins": [], "settings": [], "own": True,
                          "attrs": q.get("attrs", {})})
        d = defs.get(p["type"], {})
        parts[key] = {"path": key, "name": p["name"], "type": p["type"], "ports": ports, "doc": p["doc"] or d.get("doc", ""),
                      "attrs": {**d.get("attrs", {}), **p.get("attrs", {})},
                      "source": d.get("source", "arch"), "subsystem": sub, "children": [], "depth": len(path) - 1,
                      "board": d.get("board", {}).get("board") if d.get("board") else None}
        if prefix:
            parts[".".join(prefix)]["children"].append(key)
        for c in p["parts"]:
            walk(c, path, sub)
    walk(top, [], None)
    for s in box_subs:  # a subsystem from model.toml with nothing in it yet
        key = f"{top['name']}.{s}"
        if key not in parts:
            parts[key] = {"path": key, "name": s, "type": None, "ports": [], "doc": "", "source": "arch", "subsystem": s,
                          "children": [], "depth": 1, "board": None, "attrs": {}}
            parts[top["name"]]["children"].append(key)

    def resolve(owner_path, segs, line, what):
        """owner.sub.part.port -> (part path, port) ; segments are relative to owner."""
        if segs[0] == top["name"]:
            segs = segs[1:]
            owner_path = top["name"]
        part_path = owner_path
        for s in segs[:-1]:
            nxt = f"{part_path}.{s}"
            if nxt not in parts:
                problems.append(f"{afile}:{line}: {what}: no part {s!r} in {part_path}")
                return None
            part_path = nxt
        port = next((q for q in parts[part_path]["ports"] if q["name"] == segs[-1]), None)
        if port is None:
            src = parts[part_path]["source"]
            hint = " (it is not in the .ioc any more - pin renamed or removed?)" if src == "facts" else ""
            problems.append(f"{afile}:{line}: {what}: {part_path} has no port {segs[-1]!r}{hint}")
            ghost = {"name": segs[-1], "type": "?", "conj": False, "kind": "Signal", "meaning": "missing",
                     "pins": [], "settings": [], "missing": True}
            parts[part_path]["ports"].append(ghost)
            return part_path, ghost
        return part_path, port

    connections = []

    def collect(p, prefix):
        path = ".".join(prefix + [p["name"]])
        for c in p["connects"]:
            what = f"connect {'.'.join(c['a'])} to {'.'.join(c['b'])}"
            ea, eb = resolve(path, c["a"], c["line"], what), resolve(path, c["b"], c["line"], what)
            ok = ea is not None and eb is not None and not ea[1].get("missing") and not eb[1].get("missing")
            if ok:
                qa, qb = ea[1], eb[1]
                if qa["type"] != qb["type"]:
                    problems.append(f"{afile}:{c['line']}: {what}: types do not match "
                                    f"({qa['type']} vs {qb['type']})")
                    ok = False
                elif qa["conj"] == qb["conj"]:
                    notes.append(f"{afile}:{c['line']}: {what}: both ends are {'~' if qa['conj'] else ''}{qa['type']}; "
                                 f"one end is normally ~{qa['type']}")
            if ea and eb and (ea[1].get("missing") or eb[1].get("missing")):
                real = eb if ea[1].get("missing") else ea
                for g in (ea, eb):
                    if g[1].get("missing"):
                        g[1]["kind"], g[1]["conj"] = real[1]["kind"], not real[1]["conj"]
            connections.append({"drawn": bool(ea and eb), "a": ea and [ea[0], ea[1]["name"]], "b": eb and [eb[0], eb[1]["name"]],
                                "a_txt": ".".join(c["a"]), "b_txt": ".".join(c["b"]),
                                "kind": (ea or eb)[1]["kind"] if (ea or eb) else "Signal",
                                "type": (ea or eb)[1]["type"] if (ea or eb) else "?", "ok": ok, "line": c["line"],
                                "attrs": c.get("attrs", {})})
        for ch in p["parts"]:
            collect(ch, prefix + [p["name"]])
    collect(top, [])

    # ---- ROS allocations
    node_names = {n["name"] for n in nodes}
    host, via_launch = {}, {}
    launch_files = {l["file"]: l for l in launches}
    for a in arch["allocations"]:
        w = a["what"][-1]
        tgt = ".".join(a["to"] if a["to"][0] == top["name"] else [top["name"]] + a["to"])
        if a["what"][0] in ("ROS", "ros") and (w in node_names or w in launch_files):
            if tgt not in parts:
                problems.append(f"{afile}:{a['line']}: allocate {w}: no part {tgt}")
            elif w in node_names:
                host[w] = tgt
            else:
                launch_files[w]["host"] = tgt
                for n in nodes:
                    if any(e["file"] == w for e in n["launch"]):
                        via_launch.setdefault(n["name"], tgt)
        else:
            problems.append(f"{afile}:{a['line']}: allocate {'::'.join(a['what'])}: no ROS node of that name "
                            f"(found: {', '.join(sorted(node_names)) or 'none'})")
    for n in nodes:
        n["host"] = host.get(n["name"]) or via_launch.get(n["name"])
        n["host_from"] = "node" if n["name"] in host else "launch" if n["host"] else None

    # ---- requirement placement
    found = [c.split(".")[-1] for c in parts[top["name"]]["children"]]
    subsystems = [s for s in box_subs if s in found] + [s for s in found if s not in box_subs]
    parts[top["name"]]["children"] = [f"{top['name']}.{s}" for s in subsystems]
    req_ids = {r["id"] for r in reqs}
    whole = group_only if table else ["SYS"]
    for r in reqs:
        r["subsystem"] = r["prefix"] if r["prefix"] in subsystems else (top["name"] if r["prefix"] in whole else None)
        r["parts"] = []
    for s in arch["satisfies"]:
        r = next((x for x in reqs if x["id"] == s["req"]), None)
        tgt = ".".join(s["by"] if s["by"][0] == top["name"] else [top["name"]] + s["by"])
        if r is None:
            problems.append(f"{afile}:{s['line']}: satisfy {s['req']}: no such requirement in requirements.md")
        elif tgt not in parts:
            problems.append(f"{afile}:{s['line']}: satisfy {s['req']}: no part {tgt}")
        else:
            r["parts"].append(tgt)
    for f in faults:
        f["reqs"] = [x for x in re.findall(r"[A-Z]+-\d+", f["req"])]
        for x in f["reqs"]:
            if x not in req_ids:
                problems.append(f"docs/fdir.md: {f['id']} names requirement {x}, which does not exist")
    for d in decisions:
        d["reqs"] = [x for x in re.findall(r"[A-Z]+-\d+", d["related"]) if x in req_ids]
        d["parts"] = [k for k, p in parts.items() if p["depth"] >= 1 and re.search(rf"(?<![\w-]){re.escape(p['name'])}(?![\w-])", d["related"])]

    # ---- gaps a design review would ask about
    gaps = []

    def gap(kind, text, refs=()):
        gaps.append({"kind": kind, "text": text, "refs": list(refs)})
    for s in subsystems:
        if not any(r["subsystem"] == s for r in reqs):
            gap("requirements", f"Subsystem {s} has no requirements (no {s}-### rows)", [f"{top['name']}.{s}"])
    orphan = sorted({r["prefix"] for r in reqs if r["subsystem"] is None})
    for pfx in orphan:
        n = sum(r["prefix"] == pfx for r in reqs)
        gap("requirements", f"{n} {pfx}-### requirement(s) match no subsystem: add subsystem {pfx} in Setup")
    for f in faults:
        if not f["reqs"]:
            gap("faults", f"{f['id']} ({f['failure']}) has no requirement covering it")
    covered = {r["subsystem"] for f in faults for x in f["reqs"] for r in reqs if r["id"] == x}
    for s in subsystems:
        if s not in covered:
            gap("faults", f"Subsystem {s} has no fault analysed (no fault row covered by a {s} requirement)",
                [f"{top['name']}.{s}"])
    topics = {}
    for n in nodes:
        for role in ("pub", "sub"):
            for e in n[role]:
                t = topics.setdefault(e["topic"], {"topic": e["topic"], "types": set(), "pub": [], "sub": []})
                t["types"].add(e["type"])
                t[role].append(n["name"])
    for t in topics.values():
        if len(t["types"]) > 1:
            problems.append(f"ROS topic {t['topic']} is used with different types: {', '.join(sorted(t['types']))}")
        if not t["sub"]:
            gap("software", f"{t['topic']} is published by {', '.join(t['pub'])} but nothing subscribes to it")
        if not t["pub"]:
            gap("software", f"{t['topic']} is subscribed by {', '.join(t['sub'])} but nothing publishes it")
        t["types"] = sorted(t["types"])
    for n in nodes:
        if not n["host"]:
            gap("software", f"ROS node {n['name']} runs on no computer yet (Software view: click it, Runs on)")
    for u in ros_unknown:
        gap("software", u)
    for b in boards:
        if not any(p["type"] == b["def"] for p in parts.values()):
            gap("wiring", f"Board {b['board']} ({b['source']}) is not placed in any subsystem (remove it in Setup and add it again)")
    for k, p in parts.items():
        if p["depth"] >= 2 and p["ports"] and not any(c["ok"] and (c["a"][0] == k or c["b"][0] == k) for c in connections):
            gap("wiring", f"{k} has ports but nothing is connected to it", [k])

    # ---- interfaces between subsystems (generated ICD)
    def sub_of(path):
        return parts[path]["subsystem"]
    icd = []
    for c in connections:
        if not c["ok"]:
            continue
        sa, sb = sub_of(c["a"][0]), sub_of(c["b"][0])
        if sa and sb and sa != sb:
            pa = next(q for q in parts[c["a"][0]]["ports"] if q["name"] == c["a"][1])
            pb = next(q for q in parts[c["b"][0]]["ports"] if q["name"] == c["b"][1])
            fact = pa if pa.get("pins") else pb
            icd.append({"pair": sorted([sa, sb]), "from": ".".join(c["a"]), "to": ".".join(c["b"]),
                        "kind": c["kind"], "type": c["type"], "meaning": fact.get("meaning", c["type"]),
                        "pins": fact.get("pins", []), "settings": [s for s in fact.get("settings", [])
                                                                    if s[0] in ("Speed", "SPI mode", "Role", "Baud rate", "Clock speed", "Timing")]})

    power, i2c = electrical(parts, connections, gap)
    bom = build_bom(cfg, parts, connections)
    return {"name": name, "top": top["name"], "subsystems": subsystems, "parts": parts, "connections": connections,
            "power": power, "i2c": i2c, "bom": bom, "launches": launches,
            "boards": boards, "nodes": nodes, "topics": sorted(topics.values(), key=lambda t: t["topic"]),
            "requirements": reqs, "faults": faults, "decisions": decisions, "icd": icd, "gaps": gaps,
            "problems": problems, "notes": notes, "arch_file": afile,
            "prefix_names": {t[0]: t[1] for t in table}, "group_only": group_only}


# ================================================================ budgets, checks, BOM

def num(v):
    """'5', '5 V', '3V3', '300 mA', '0.3A' -> float in base units, or None."""
    t = str(v or "").strip().replace(",", ".")
    m = re.match(r"^(\d+)[Vv](\d+)$", t)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.match(r"^([-+]?\d*\.?\d+)\s*([mµuk]?)", t)
    if not m:
        return None
    return float(m.group(1)) * {"m": 1e-3, "µ": 1e-6, "u": 1e-6, "k": 1e3}.get(m.group(2), 1)


def length_m(v):
    """'0.2 m', '150 mm', '30cm', '12 in' -> metres, or None."""
    m = re.match(r"^\s*(\d*\.?\d+)\s*(mm|cm|m|in|ft)?\b", str(v or "").replace(",", "."))
    if not m:
        return None
    return float(m.group(1)) * {"mm": 1e-3, "cm": 1e-2, "in": 0.0254, "ft": 0.3048}.get(m.group(2), 1)


def _nets(connections, keep):
    """Groups of 'part.port' joined by wires (union-find), for the wires keep() accepts."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for c in connections:
        if c["ok"] and keep(c):
            a, b = ".".join(c["a"]), ".".join(c["b"])
            parent[find(a)] = find(b)
    groups = {}
    for x in list(parent):
        groups.setdefault(find(x), []).append(x)
    return list(groups.values())


def electrical(parts, connections, gap):
    def port(full):
        p, _, n = full.rpartition(".")
        return p, next((q for q in parts[p]["ports"] if q["name"] == n), {})
    power = []
    for net in _nets(connections, lambda c: c["kind"] == "Power"):
        rows = []
        for full in sorted(net):
            p, q = port(full)
            a = q.get("attrs") or {}
            rows.append({"port": full, "part": p, "voltage": num(a.get("voltage")), "max_current": num(a.get("max_current")),
                         "current": num(a.get("current"))})
        src = [r for r in rows if r["max_current"] is not None]
        loads = [r for r in rows if r["current"] is not None and r["max_current"] is None]
        volts = sorted({r["voltage"] for r in rows if r["voltage"] is not None})
        cap = sum(r["max_current"] for r in src) if src else None
        load = sum(r["current"] for r in loads)
        name = (src[0] if src else rows[0])["port"]
        rail = {"name": name, "ports": rows, "voltage": volts[0] if len(volts) == 1 else None, "voltages": volts,
                "capacity": cap, "load": load, "unknown": [r["port"] for r in rows if r not in src and r not in loads]}
        power.append(rail)
        short = name.split(".", 1)[-1]
        if len(volts) > 1:
            gap("power", f"Rail {short} joins ports of different voltages ({', '.join(f'{v:g} V' for v in volts)})",
                sorted({r["part"] for r in rows}))
        if cap is not None and load > cap:
            gap("power", f"Rail {short} is overloaded: {load:g} A drawn, {cap:g} A available", [src[0]["part"]])
    power.sort(key=lambda r: (r["capacity"] is None and not r["load"] and not r["voltages"], r["name"]))
    i2c = []
    for net in _nets(connections, lambda c: c["type"] == "I2cBus"):
        devs = []
        for full in sorted(net):
            p, q = port(full)
            addr = (q.get("attrs") or {}).get("address") or parts[p]["attrs"].get("i2c_address")
            devs.append({"port": full, "part": p, "address": addr})
        i2c.append({"name": devs[0]["port"], "devices": devs})
        seen = {}
        for d in devs:
            if d["address"]:
                key = d["address"].lower().replace("0x", "").lstrip("0") or "0"
                if key in seen:
                    gap("electrical", f"I2C address {d['address']} used twice on one bus: {seen[key].split('.', 1)[-1]} and "
                        f"{d['port'].split('.', 1)[-1]}", [d["part"]])
                seen[key] = d["port"]
    return power, i2c


BOM_CORE = ["part_number", "manufacturer", "supplier", "link", "unit_cost"]


def build_bom(cfg, parts, connections):
    groups = {}
    for k, p in parts.items():
        if p["depth"] < 2 or (p["children"] and not p["attrs"].get("part_number")):
            continue
        a = p["attrs"]
        key = a.get("part_number") or p["doc"] or p["type"] or p["name"]
        g = groups.setdefault(key, {"kind": "part", "item": p["doc"] or p["type"] or p["name"], "qty": 0, "parts": [],
                                    "subsystems": [], "values": {}})
        g["qty"] += num(a.get("quantity")) or 1
        g["parts"].append(k)
        if p["subsystem"] not in g["subsystems"]:
            g["subsystems"].append(p["subsystem"])
        for kk, vv in a.items():
            g["values"].setdefault(kk, vv)
    rows = sorted(groups.values(), key=lambda g: (g["subsystems"][0] or "", g["item"]))
    wires, conns = {}, {}
    for c in connections:
        a = c.get("attrs") or {}
        if a.get("gauge") or a.get("cable"):
            label = " ".join(x for x in (a.get("cable"), a.get("gauge")) if x)
            w = wires.setdefault(label, {"kind": "wire", "item": f"Wire {label}", "qty": 0, "length": 0.0, "unmeasured": 0,
                                         "parts": [], "subsystems": [], "values": {}})
            w["qty"] += 1
            ln = length_m(a.get("length"))
            w["length"] += ln or 0
            w["unmeasured"] += ln is None
        if a.get("connector"):
            cc = conns.setdefault(a["connector"], {"kind": "connector", "item": f"Connector {a['connector']} (mated pair)",
                                                   "qty": 0, "parts": [], "subsystems": [], "values": {}})
            cc["qty"] += 1
    extra = [{"kind": "extra", "item": e.get("item", ""), "qty": num(e.get("qty")) or 1, "parts": [], "subsystems": [],
              "values": {k: v for k, v in e.items() if k not in ("item", "qty")}, "index": i}
             for i, e in enumerate(cfg.get("bom_item", []))]
    return {"columns": list(cfg.get("bom", {}).get("columns", [])), "rows": rows + list(wires.values()) + list(conns.values()) + extra}


# ================================================================ ROS2 launch files

def scan_launch(root, paths):
    """Nodes started by launch files (.launch.py / .launch.xml / .launch), with remappings and parameters."""
    files = []
    for p in paths:
        for dirpath, dirs, names in os.walk(os.path.join(root, p)):
            dirs[:] = [d for d in dirs if d not in ("build", "install", "log", ".git")]
            files += [os.path.join(dirpath, n) for n in names
                      if n.endswith((".launch.py", ".launch.xml", ".launch")) or (os.path.basename(dirpath) == "launch" and n.endswith((".py", ".xml")))]
    out = []
    for f in sorted(set(files)):
        text = open(f, encoding="utf-8", errors="replace").read()
        nodes = []
        if f.endswith(".py"):
            for m in re.finditer(r"\bNode\s*\(", text):
                i, depth = m.end(), 1
                while i < len(text) and depth:
                    depth += {"(": 1, ")": -1}.get(text[i], 0)
                    i += 1
                body = text[m.end():i - 1]
                kw = lambda k: (re.search(rf"\b{k}\s*=\s*['\"]([^'\"]+)['\"]", body) or [None, None])[1]
                remaps = re.findall(r"\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)",
                                    (re.search(r"remappings\s*=\s*\[(.*?)\]", body, re.S) or [None, ""])[1])
                params = re.search(r"parameters\s*=\s*\[(.*?)\]\s*[,)]?", body, re.S)
                nodes.append({"package": kw("package"), "executable": kw("executable") or kw("node_executable"),
                              "name": kw("name") or kw("node_name"), "namespace": kw("namespace"), "remappings": remaps,
                              "parameters": " ".join(params.group(1).split())[:300] if params else ""})
        else:
            for m in re.finditer(r"<node\b([^>]*?)(/>|>(.*?)</node>)", text, re.S):
                at = dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', m.group(1)))
                inner = m.group(3) or ""
                nodes.append({"package": at.get("pkg"), "executable": at.get("exec") or at.get("type"), "name": at.get("name"),
                              "namespace": at.get("namespace") or at.get("ns"),
                              "remappings": re.findall(r'<remap\s+from="([^"]+)"\s+to="([^"]+)"', inner),
                              "parameters": ", ".join(f"{a}={b}" for a, b in re.findall(r'<param\s+name="([^"]+)"\s+value="([^"]*)"', inner))})
        if nodes:
            out.append({"file": os.path.relpath(f, root), "nodes": nodes, "host": None})
    return out


# ================================================================ facts export (SysML v2 text)

def facts_sysml(m):
    q = lambda s: s if re.match(r"^[A-Za-z_]\w*$", s) else "'" + s.replace("'", "") + "'"
    esc = lambda s: s.replace('"', "'")
    out = [f"// GENERATED by doc model from the .ioc files, ROS2 code and docs/. Do not edit:",
           f"// your changes would be overwritten. Write architecture in {os.path.basename(m['arch_file'])}.",
           f"package {m['name']}_facts {{", "    private import ScalarValues::*;", "",
           "    // port kinds used by the views", *[f"    port def {k};" for k in KINDS], ""]
    for t, (kind, meaning) in PORT_DEFS.items():
        out.append(f"    port def {t} :> {kind} {{ doc /* {meaning} */ }}")
    for b in m["boards"]:
        out += ["", f"    part def {b['def']} {{", f"        doc /* {b['mcu']} {b['package']}, from {b['source']} */"]
        for c in b["clocks"]:
            out.append(f'        attribute {q("clock_" + c[0].lower())} : String = "{c[1]}";')
        for i in b["internal"]:
            for s in i["settings"]:
                out.append(f'        attribute {q(i["ip"].lower() + "_" + _ident(s[0]))} : String = "{esc(s[1])}";')
        for p in b["ports"]:
            out.append(f"        port {q(p['name'])} : {p['type']} {{")
            out.append(f'            attribute pins : String = "{esc(", ".join(f"{a} {b_}" for a, b_ in p["pins"]))}";')
            for s in p["settings"]:
                out.append(f'            attribute {q(_ident(s[0]))} : String = "{esc(s[1])}";')
            out.append("        }")
        out.append("    }")
    if m["nodes"]:
        out += ["", "    package ROS {", "        part def RosNode;"]
        for n in m["nodes"]:
            out.append(f"        part {q(n['name'])} : RosNode {{ doc /* {n['file']} */")
            for role in ("pub", "sub"):
                for e in n[role]:
                    out.append(f'            attribute {"publishes" if role == "pub" else "subscribes"}_{_ident(e["topic"])} : String = "{e["topic"]} [{e["type"]}]";')
            out.append("        }")
        out.append("    }")
    if m["requirements"]:
        out += ["", "    package Requirements {"]
        for r in m["requirements"]:
            out.append(f"        requirement {q(r['id'])} {{ doc /* {r['text'].replace('*/', '')} */ }}")
        out.append("    }")
    out.append("}")
    return "\n".join(out) + "\n"


# ================================================================ page

def page(m, report_link=True):
    tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docmodel_page.html"), encoding="utf-8").read()
    elk = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "elk.bundled.js")
    if not os.path.exists(elk):
        raise ModelError("vendor/elk.bundled.js is missing next to doc.py")
    data = json.dumps(m, default=list).replace("</", "<\\/")
    return (tpl.replace("/*__ELK__*/", open(elk, encoding="utf-8").read())
               .replace("__DATA__", data)
               .replace("__TITLE__", html.escape(m["name"])))


# ================================================================ extras: issues, docs, media

ISSUE_OPEN = ["backlog", "todo", "in progress", "in review"]
ISSUE_CLOSED = {"COMPLETED": "done", "NOT_PLANNED": "not planned", "DUPLICATE": "duplicate"}


def issue_status(i):
    """Open issues: a 'status: …' label (Backlog if none). Closed: GitHub's close reason."""
    if i["state"].upper() == "CLOSED":
        if any(l["name"] == "duplicate" for l in i.get("labels", [])) and (i.get("stateReason") or "").upper() != "COMPLETED":
            return "duplicate"
        return ISSUE_CLOSED.get((i.get("stateReason") or "COMPLETED").upper(), "done")
    for l in i.get("labels", []):
        if l["name"].startswith("status: ") and l["name"][8:] in ISSUE_OPEN:
            return l["name"][8:]
    return "backlog"


def issue_timeline(root, number):
    """Comments and events of one issue, oldest first (GitHub timeline API via gh)."""
    import subprocess
    r = subprocess.run(["gh", "api", "--paginate", f"repos/{{owner}}/{{repo}}/issues/{int(number)}/timeline?per_page=100"],
                       cwd=root, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return {"error": (r.stderr.strip().splitlines() or ["gh failed"])[-1], "events": []}
    items, dec, pos, txt = [], json.JSONDecoder(), 0, r.stdout.strip()
    while pos < len(txt):  # --paginate prints one JSON array per page, back to back
        page, pos = dec.raw_decode(txt, pos)
        items += page
        while pos < len(txt) and txt[pos].isspace():
            pos += 1
    out = []
    for e in items:
        kind = e.get("event")
        who = (e.get("actor") or e.get("user") or {}).get("login", "")
        at = e.get("created_at") or e.get("submitted_at") or ""
        if kind == "commented":
            out.append({"type": "comment", "who": who, "at": at, "body": e.get("body", "")})
        elif kind in ("labeled", "unlabeled"):
            name = (e.get("label") or {}).get("name", "")
            if out and out[-1]["type"] == kind and out[-1]["who"] == who:
                out[-1]["labels"].append(name)
            else:
                out.append({"type": kind, "who": who, "at": at, "labels": [name]})
        elif kind == "closed":
            out.append({"type": "closed", "who": who, "at": at, "reason": (e.get("state_reason") or "completed").replace("_", " ")})
        elif kind == "reopened":
            out.append({"type": "reopened", "who": who, "at": at})
        elif kind == "renamed":
            out.append({"type": "renamed", "who": who, "at": at, "to": (e.get("rename") or {}).get("to", "")})
        elif kind in ("cross-referenced", "referenced"):
            out.append({"type": "referenced", "who": who, "at": at, "commit": (e.get("commit_id") or "")[:7]})
    return {"events": out}


def fetch_issues(root):
    """Open issues plus recently closed ones, via the GitHub CLI. Returns (issues, error)."""
    import shutil, subprocess, datetime
    if not shutil.which("gh"):
        return [], "GitHub CLI (gh) not installed"
    out = []
    for state, limit in (("open", 200), ("closed", 30)):
        r = subprocess.run(["gh", "issue", "list", "--state", state, "--limit", str(limit), "--json",
                            "number,title,labels,url,updatedAt,createdAt,author,body,state,stateReason"],
                           cwd=root, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return [], (r.stderr.strip().splitlines() or ["gh failed"])[-1]
        for i in json.loads(r.stdout or "[]"):
            out.append({"number": i["number"], "title": i["title"], "url": i["url"], "state": i["state"].lower(),
                        "labels": [l["name"] for l in i.get("labels", [])], "updated": i.get("updatedAt", ""),
                        "created": i.get("createdAt", ""), "author": (i.get("author") or {}).get("login", ""),
                        "body": i.get("body", ""), "status": issue_status(i)})
    return out, None


def _inline(t):
    t = html.escape(t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", r'<img alt="\1" src="\2">', t)
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?!\w)", r"<em>\1</em>", t)
    for tag in ("br", "sub", "/sub", "sup", "/sup"):
        t = t.replace(f"&lt;{tag}&gt;", f"<{tag}>")
    return t


def md_html(text):
    """Small Markdown renderer for the docs pages: headings, lists, tables, code, quotes, links, images."""
    text = re.sub(r"<!--.*?-->[ \t]*\n?", "", text, flags=re.S)  # HTML comments (e.g. doc-kit markers) are not shown
    lines, out, i = text.splitlines(), [], 0
    heads = []
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            lang = ln[3:].strip()
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append(f'<pre class="code {html.escape(lang)}"><code>{html.escape(chr(10).join(lines[i + 1:j]))}</code></pre>')
            i = j + 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            lvl, title = len(m.group(1)), m.group(2).strip()
            slug = re.sub(r"[^\w\- ]", "", title.lower()).strip().replace(" ", "-")
            heads.append((lvl, title, slug))
            out.append(f'<h{lvl} id="{slug}">{_inline(title)}</h{lvl}>')
            i += 1
            continue
        if ln.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            hdr = _cells(ln)
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            out.append("<table><tr>" + "".join(f"<th>{_inline(h)}</th>" for h in hdr) + "</tr>" +
                       "".join("<tr>" + "".join(f"<td>{_inline(c.replace(chr(92) + '|', '|'))}</td>" for c in r) + "</tr>" for r in rows) + "</table>")
            continue
        if re.match(r"^\s*([-*]|\d+\.)\s+", ln):
            ordered = bool(re.match(r"^\s*\d+\.", ln))
            items = []
            while i < len(lines) and (re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]) or (lines[i].startswith("   ") and items)):
                s = lines[i]
                mm = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", s)
                if mm:
                    body = mm.group(3)
                    box = re.match(r"^\[( |x|X)\]\s+(.*)$", body)
                    if box:
                        body = ("☑ " if box.group(1).strip() else "☐ ") + box.group(2)
                    items.append([len(mm.group(1)), body])
                else:
                    items[-1][1] += " " + s.strip()
                i += 1
            tag = "ol" if ordered else "ul"
            html_items, depth0 = [], items[0][0]
            for d, b in items:
                cls = ' class="sub"' if d > depth0 else ""
                html_items.append(f"<li{cls}>{_inline(b)}</li>")
            out.append(f"<{tag}>" + "".join(html_items) + f"</{tag}>")
            continue
        if ln.startswith(">"):
            q = []
            while i < len(lines) and lines[i].startswith(">"):
                q.append(lines[i].lstrip("> "))
                i += 1
            out.append(f"<blockquote>{_inline(' '.join(q))}</blockquote>")
            continue
        if re.match(r"^\s*(---|\*\*\*)\s*$", ln):
            out.append("<hr>")
            i += 1
            continue
        if not ln.strip():
            i += 1
            continue
        para = [ln]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,4}\s|```|\s*([-*]|\d+\.)\s|\||>)", lines[i]):
            para.append(lines[i])
            i += 1
        out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out), heads


GUIDE_IMAGES = "https://raw.githubusercontent.com/sergeikuznev/doc-kit/HEAD/docs/images/"

MEDIA_KIND = {".jpg": "image", ".jpeg": "image", ".png": "image", ".gif": "image", ".webp": "image", ".svg": "image",
              ".heic": "image", ".mp4": "video", ".mov": "video", ".webm": "video", ".m4v": "video",
              ".csv": "data", ".json": "data", ".txt": "data", ".log": "data", ".pdf": "pdf"}


def collect_extras(root, m, with_issues=True):
    """Docs pages, media files and GitHub issues, linked to the model where the text names them."""
    import datetime
    docs = []
    here = os.path.dirname(os.path.abspath(__file__))
    groups = [("Project", os.path.join(root, "docs"), ["README.md", "requirements.md", "fdir.md", "devlog.md"]),
              ("Procedures", os.path.join(root, "docs", "procedures"), None),
              ("Interfaces", os.path.join(root, "docs", "icd"), None),
              ("How to use doc-kit", os.path.join(here, "guides"), ["README.md", "PAGE.md", "TERMINAL.md", "HANDBOOK.md"])]
    for group, folder, names in groups:
        if not os.path.isdir(folder):
            continue
        files = names if names else sorted(f for f in os.listdir(folder) if f.endswith(".md"))
        for f in files:
            path = os.path.join(folder, f)
            if not os.path.isfile(path):
                continue
            body, heads = md_html(open(path, encoding="utf-8").read())
            if group == "How to use doc-kit":
                # screenshots live in the doc-kit repo, not in every project
                body = re.sub(r'src="(?:\./)?(?:docs/)?images/', f'src="{GUIDE_IMAGES}', body)
            title = next((h[1] for h in heads if h[0] == 1), f[:-3].replace("_", " "))
            docs.append({"group": group, "file": os.path.relpath(path, root) if group != "How to use doc-kit" else f"doc-kit/{f}",
                         "title": title, "html": body, "toc": [h for h in heads if h[0] in (2, 3)]})
    media = []
    mdir = os.path.join(root, "docs", "media")
    if os.path.isdir(mdir):
        for base, _, files in os.walk(mdir):
            for f in sorted(files):
                if f.startswith("."):
                    continue
                full = os.path.join(base, f)
                relp = os.path.relpath(full, mdir).replace(os.sep, "/")
                ext = os.path.splitext(f)[1].lower()
                st = os.stat(full)
                media.append({"file": relp, "name": f, "kind": MEDIA_KIND.get(ext, "file"), "size": st.st_size,
                              "date": datetime.date.fromtimestamp(st.st_mtime).isoformat(), "reqs": [], "parts": []})
    for med in media:
        stem = os.path.splitext(med["name"])[0]
        for r in m["requirements"]:
            if any(med["name"] in e or re.search(rf"(?<![\w-]){re.escape(stem)}(?![\w-])", e) for e in r["evidence"]):
                med["reqs"].append(r["id"])
                r.setdefault("media", []).append(med["file"])
    issues, issue_error = ([], "skipped") if not with_issues else fetch_issues(root)
    m.update({"docs": docs, "media": media, "issues": issues, "issue_error": issue_error,
              "built": datetime.datetime.now().isoformat(timespec="seconds")})
    collect_extras_link_issues(m)
    return m


def collect_extras_link_issues(m):
    """Place each issue in the subsystems its labels name, and link the requirement IDs it mentions."""
    names = {s.lower(): s for s in m["subsystems"]}
    for pfx, full in m.get("prefix_names", {}).items():
        if pfx in m["subsystems"]:
            names[full.lower()] = pfx
            names[full.lower()[:4]] = pfx
    ids = {r["id"] for r in m["requirements"]}
    for iss in m["issues"]:
        iss["subsystems"] = []
        for lab in iss["labels"]:
            l = lab.lower()
            hit = names.get(l) or names.get(l[:4]) or next((s for s in m["subsystems"] if l.startswith(s.lower())), None)
            if hit and hit not in iss["subsystems"]:
                iss["subsystems"].append(hit)
        iss["reqs"] = sorted(set(re.findall(r"\b[A-Z]{2,6}-\d{3}\b", iss["title"] + " " + iss["body"])) & ids)
        iss["kind"] = "bug" if "bug" in iss["labels"] else "idea" if "idea" in iss["labels"] else "other"
