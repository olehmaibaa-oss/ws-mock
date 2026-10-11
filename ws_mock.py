"""
ws-mock engine: a mitmproxy addon that rewrites WebSocket JSON frames.

Nothing in here is project-specific, you shouldn't need to edit this file.
  - what your app's frames look like and what to do with them:  profiles/<name>/profile.json
  - what is switched on right now:                              .state.json (written by wsm.py)
Both are re-read when they change, so scenarios switch while the app is open.

Start with `python3 wsm.py proxy`, or directly: mitmweb -s ws_mock.py
"""

import asyncio
import copy
import hashlib
import json
import logging
import os
import re
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PROFILES = os.path.join(ROOT, "profiles")
STATE_PATH = os.environ.get("WS_MOCK_STATE") or os.path.join(ROOT, ".state.json")
LOG_DIR = os.environ.get("WS_MOCK_LOGS") or os.path.join(ROOT, "logs")
TRIGGER = os.path.join(LOG_DIR, "inject.trigger")
DEFAULT_PROFILE = "demo"
KEEP_DUMPS = 40
FRAME_KEYS = ("match", "list", "id", "label")

log = logging.getLogger("ws-mock")

# ---------------------------------------------------------------------------
# Fragmentation fix.
#
# When an addon changes a WebSocket message and its length changes, mitmproxy
# re-sends it split into 4000-byte continuation frames. A 3 MB frame becomes
# ~700 frames, and plenty of mobile WS clients can't take that: they drop the
# socket and reconnect in a loop, and it looks like your patch broke the app.
# Raising the threshold makes mitmproxy send the message as one frame.
# ---------------------------------------------------------------------------
FRAGMENT_SIZE = 16 * 1024 * 1024
try:
    if os.environ.get("WS_MOCK_KEEP_FRAGMENTS"):   # to see the bug for yourself
        raise RuntimeError("disabled by WS_MOCK_KEEP_FRAGMENTS")
    from mitmproxy.proxy.layers import websocket as _ws_layer
    _ws_layer.Fragmentizer.FRAGMENT_SIZE = FRAGMENT_SIZE
    _FRAG_ERR = None
except Exception as e:  # pragma: no cover
    _FRAG_ERR = e


# ---------------------------------------------------------------------------
# Built-in scenarios. They work on any profile once its "frame" block is
# filled in. A profile rule with the same name overrides the built-in one.
# ---------------------------------------------------------------------------
BUILTINS = {
    "frozen":     {"_doc": "drop every frame: socket stays open, data stops changing", "drop": True},
    "duplicate":  {"_doc": "every frame arrives twice", "repeat": 2},
    "slow":       {"_doc": "every frame arrives 3 s late", "delay_ms": 3000},
    "late-frame": {"_doc": "one frame is held 5 s and lands after newer ones", "once": True, "delay_ms": 5000},
    "reverse":    {"_doc": "the list comes in reverse order", "reverse": True},
    "empty":      {"_doc": "the list is empty", "empty": True},
}


# ---------------------------------------------------------------------------
# JSON pointer helpers ("/orders", "/data/items/0/title", "" = the whole frame)
# ---------------------------------------------------------------------------
_MISSING = object()


def _parts(ptr):
    if not ptr or ptr == "/":
        return []
    return [p.replace("~1", "/").replace("~0", "~") for p in ptr.lstrip("/").split("/")]


def jget(doc, ptr, default=_MISSING):
    cur = doc
    for p in _parts(ptr):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        elif isinstance(cur, list) and p.isdigit() and int(p) < len(cur):
            cur = cur[int(p)]
        else:
            return default
    return cur


def jset(doc, ptr, value):
    parts = _parts(ptr)
    if not parts:
        raise ValueError("can't replace the whole document with a pointer")
    cur = doc
    for p in parts[:-1]:
        if isinstance(cur, list):
            cur = cur[int(p)]
        else:
            if not isinstance(cur.get(p), (dict, list)):
                cur[p] = {}
            cur = cur[p]
    last = parts[-1]
    if isinstance(cur, list):
        if value == "__DELETE__":
            del cur[int(last)]
        else:
            cur[int(last)] = value
    elif value == "__DELETE__":
        cur.pop(last, None)
    else:
        cur[last] = value


# ---------------------------------------------------------------------------
# Value tokens
#   "__TS__"          now, unix ms
#   "__TS:+2d__"      now + offset, unix ms   (s, m, h, d; + or -)
#   "__TS_S:-45m__"   same, unix seconds
#   "__DELETE__"      remove the key
# ---------------------------------------------------------------------------
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_TS = re.compile(r"__TS(_S)?(?::([+-])(\d+)([smhd]))?__")


def resolve(v):
    if isinstance(v, str):
        m = _TS.fullmatch(v)
        if m:
            secs = time.time()
            if m.group(2):
                secs += (1 if m.group(2) == "+" else -1) * int(m.group(3)) * _UNITS[m.group(4)]
            return int(secs) if m.group(1) else int(secs * 1000)
        return v
    if isinstance(v, dict):
        return {k: resolve(x) for k, x in v.items()}
    if isinstance(v, list):
        return [resolve(x) for x in v]
    return v


def merge(target, patch):
    """Deep merge: dicts merge, everything else replaces. Keys may be JSON pointers.
    Keys starting with "_" are notes for humans and are skipped."""
    for k, v in patch.items():
        if k.startswith("_"):
            continue
        if k.startswith("/"):
            jset(target, k, resolve(v))
        elif v == "__DELETE__":
            target.pop(k, None)
        elif isinstance(v, dict) and isinstance(target.get(k), dict):
            merge(target[k], v)
        else:
            target[k] = resolve(v)


# ---------------------------------------------------------------------------
# Config: profile + state, compiled into a list of active rules
# ---------------------------------------------------------------------------
_cache = {"st_m": object(), "state": {}, "key": None, "cfg": None}
_fired = set()   # "once" rules that already fired since the last config change


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return None


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def profile_name(state):
    return os.environ.get("WS_MOCK_PROFILE") or state.get("profile") or DEFAULT_PROFILE


def profile_path(name):
    return os.path.join(PROFILES, name, "profile.json")


def _empty_cfg(name, state):
    return {"profile": name, "hosts": [], "frame": {}, "rules": [], "push": [],
            "capture": bool(state.get("capture"))}


def build(name, prof, state):
    """Turn a profile + state into the rules that run on each frame."""
    frame = prof.get("frame") or {}
    base = {k: frame[k] for k in FRAME_KEYS if k in frame}

    def inherit(rule):
        return {**base, **rule}

    named = {n: dict(r) for n, r in BUILTINS.items()}
    for r in prof.get("rules") or []:
        named[r["name"]] = r

    rules = []
    pre = prof.get("presets") or {}
    chosen = state.get("presets") or []
    if chosen:
        items = pre.get("items") or {}
        if chosen == ["all"]:
            chosen = list(items)
        src = pre.get("source")
        first = pre.get("first_id")
        clones = []
        for i, n in enumerate(chosen):
            if n not in items:
                log.warning(f"ws-mock: preset '{n}' is not in profile '{name}'")
                continue
            if first is not None:
                new_id = first + i if isinstance(first, int) else f"{first}{i + 1}"
            else:
                new_id = 990001 + i if isinstance(src, int) else f"mock-{n}"
            clones.append({"from": src, "as": new_id, "tag": n, "patch": items[n]})
        rule = inherit({"name": "presets", "clone": clones})
        if state.get("solo"):
            rule["empty"] = True
        rules.append(rule)

    for n in state.get("on") or []:
        if n not in named:
            log.warning(f"ws-mock: rule '{n}' is not in profile '{name}' or the built-ins")
            continue
        rules.append(inherit({"name": n, **named[n]}))

    for r in state.get("extra") or []:          # one-off patches from `wsm.py set`
        rules.append(inherit(dict(r)))

    return {"profile": name, "hosts": prof.get("hosts") or [], "frame": base,
            "rules": rules, "push": [inherit(r) for r in prof.get("push") or []],
            "capture": bool(state.get("capture"))}


def config():
    st_m = _mtime(STATE_PATH)
    if st_m != _cache["st_m"]:
        try:
            _cache["state"] = _read(STATE_PATH) if st_m else {}
        except Exception as e:
            log.warning(f"ws-mock: .state.json is broken, keeping the previous state: {e}")
        _cache["st_m"] = st_m
    state = _cache["state"]
    name = profile_name(state)
    path = profile_path(name)
    key = (st_m, name, _mtime(path))
    if key == _cache["key"]:
        return _cache["cfg"]

    _cache["key"] = key
    if key[2] is None:
        log.warning(f"ws-mock: profile '{name}' not found: {path}")
        cfg = _empty_cfg(name, state)
    else:
        try:
            cfg = build(name, _read(path), state)
        except Exception as e:
            log.warning(f"ws-mock: profile '{name}' is broken, keeping the previous config: {e}")
            return _cache["cfg"] or _empty_cfg(name, state)
    _cache["cfg"] = cfg
    _fired.clear()
    on = [r["name"] for r in cfg["rules"]]
    log.warning(f"ws-mock: profile '{name}' | on: {', '.join(on) or 'nothing'}"
                f"{' | CAPTURE' if cfg['capture'] else ''}")
    return cfg


# ---------------------------------------------------------------------------
# Matching and applying a rule
# ---------------------------------------------------------------------------
def host_ok(flow, cfg):
    hosts = cfg.get("hosts") or []
    if not hosts:
        return True
    target = f"{flow.request.pretty_host}:{flow.request.port}{flow.request.path}"
    return any(h in target for h in hosts)


def matches(rule, data, from_client=False):
    want = rule.get("direction", "server")
    if want != "both" and (want == "client") != from_client:
        return False
    m = rule.get("match") or {}
    has = m.get("has")
    for ptr in ([has] if isinstance(has, str) else has or []):
        if jget(data, ptr) is _MISSING:
            return False
    for ptr, val in (m.get("equals") or {}).items():
        if jget(data, ptr) != val:
            return False
    return True


def _label(item, field, tag):
    if field.startswith("/"):
        cur = jget(item, field, None)
        if isinstance(cur, str):
            jset(item, field, f"[{tag}] {cur}")
    elif isinstance(item.get(field), str):
        item[field] = f"[{tag}] {item[field]}"


def apply(rule, data):
    """Mutates data. Returns a short description of what changed, or ''."""
    done = []
    ptr = rule.get("list")
    items = jget(data, ptr, None) if ptr is not None else None

    if isinstance(items, list):
        key = rule.get("id", "id")

        def sid(it):
            return str(it.get(key)) if isinstance(it, dict) else None

        before = len(items)
        # clone sources are copied before anything else touches the items
        sources = {}
        for cl in rule.get("clone") or []:
            f = str(cl.get("from"))
            if f not in sources:
                src = next((it for it in items if sid(it) == f), None)
                sources[f] = copy.deepcopy(src) if src is not None else None

        only = {str(x) for x in rule.get("only") or []}
        if only:
            items = [it for it in items if sid(it) in only]
        remove = {str(x) for x in rule.get("remove") or []}
        if remove:
            items = [it for it in items if sid(it) not in remove]
        if rule.get("empty"):
            items = []
            done.append("empty")

        if rule.get("all"):
            for it in items:
                if isinstance(it, dict):
                    merge(it, rule["all"])
            done.append(f"all:{len(items)}")

        by_id = rule.get("by_id") or {}
        hit = 0
        for it in items:
            p = by_id.get(sid(it))
            if p:
                merge(it, p)
                hit += 1
        if hit:
            done.append(f"by_id:{hit}")

        top = 0
        for cl in rule.get("clone") or []:
            src = sources.get(str(cl.get("from")))
            if src is None:
                log.warning(f"ws-mock: clone source {cl.get('from')!r} is not in the frame")
                continue
            new = copy.deepcopy(src)
            if "as" in cl:
                new[key] = cl["as"]
            merge(new, cl.get("patch") or {})
            if rule.get("label") and cl.get("tag"):
                _label(new, rule["label"], cl["tag"])
            if cl.get("position", "top") == "top":
                items.insert(top, new)
                top += 1
            else:
                items.append(new)
        if rule.get("clone"):
            done.append(f"clones:{len(rule['clone'])}")

        if rule.get("reverse"):
            items.reverse()
            done.append("reverse")

        if len(items) != before:
            done.append(f"items {before}->{len(items)}")
        if _parts(ptr):
            jset(data, ptr, items)
        else:
            data[:] = items

    if rule.get("set"):
        merge(data, {k if k.startswith("/") else "/" + k: v for k, v in rule["set"].items()})
        done.append("set")

    return ", ".join(done)


# ---------------------------------------------------------------------------
# Logs and dumps
# ---------------------------------------------------------------------------
def _log_line(name, line):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, name), "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _dump(data, profile, host):
    """Raw server frame -> logs/dumps/<profile>/<time>-<host>.json, keeps the last KEEP_DUMPS."""
    try:
        d = os.path.join(LOG_DIR, "dumps", profile)
        os.makedirs(d, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9.\-]", "_", host)
        name = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}-{safe}.json"
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        old = sorted(x for x in os.listdir(d) if x.endswith(".json"))[:-KEEP_DUMPS]
        for x in old:
            os.remove(os.path.join(d, x))
    except Exception as e:
        log.warning(f"ws-mock: dump failed: {e}")


# ---------------------------------------------------------------------------
# The hook
# ---------------------------------------------------------------------------
_last = {"flow": None, "raw": None}
_ours = {}      # hash -> count of frames we injected ourselves, so they aren't patched again


def _h(b):
    return hashlib.sha1(b).hexdigest()


def _inject(flow, body, to_client=True):
    from mitmproxy import ctx
    _ours[_h(body)] = _ours.get(_h(body), 0) + 1
    ctx.master.commands.call("inject.websocket", flow, to_client, body, True)


async def _later(flow, body, delay_ms, times, to_client):
    if delay_ms:
        await asyncio.sleep(delay_ms / 1000)
    for _ in range(times):
        if flow.websocket is None or flow.websocket.timestamp_end:
            log.warning("ws-mock: socket closed before a held frame went out")
            return
        _inject(flow, body, to_client)


def websocket_message(flow):
    cfg = config()
    if not host_ok(flow, cfg):
        return
    msg = flow.websocket.messages[-1]
    if not msg.is_text:
        return      # binary frames (protobuf, msgpack) pass through untouched
    h = _h(msg.content)
    if _ours.get(h):
        _ours[h] -= 1
        if not _ours[h]:
            del _ours[h]
        return

    who = "client" if msg.from_client else "server"
    host = flow.request.pretty_host
    try:
        data = json.loads(msg.content)
    except Exception:
        _log_line("frames.log", f"{who} {host} non-JSON {len(msg.content)}b")
        return
    if isinstance(data, dict):
        keys = list(data)[:8]
    elif isinstance(data, list):
        keys = f"list[{len(data)}]"
    else:
        keys = type(data).__name__
    # " FRAME" marks the frame the profile is about; `wsm.py wait` looks for it
    is_frame = not msg.from_client and matches({"match": cfg["frame"].get("match")}, data)
    _log_line("frames.log", f"{who} {host} {len(msg.content)}b keys={keys}{' FRAME' if is_frame else ''}")

    if not msg.from_client:
        if cfg["capture"]:
            _dump(data, cfg["profile"], host)
        if is_frame:
            _last["flow"], _last["raw"] = flow, bytes(msg.content)

    active = [r for r in cfg["rules"]
              if not (r.get("once") and r["name"] in _fired) and matches(r, data, msg.from_client)]
    if not active:
        return
    for r in active:
        if r.get("once"):
            _fired.add(r["name"])
            log.warning(f"ws-mock: '{r['name']}' fired once, re-arms when you switch rules again")

    changes, drop, delay, times = [], False, 0, 1
    for r in active:
        what = apply(r, data)
        if what:
            changes.append(f"{r['name']}[{what}]")
        drop = drop or bool(r.get("drop"))
        delay = max(delay, int(r.get("delay_ms") or 0))
        times = max(times, int(r.get("repeat") or 1))

    if drop:
        msg.drop()
        log.info(f"ws-mock: dropped {who} frame ({len(msg.content)}b)")
        _log_line("frames.log", "  -> dropped")
        return

    if changes:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        json.loads(body)  # never send something that doesn't parse back
        msg.content = body
        log.warning(f"ws-mock: {who} frame: {'; '.join(changes)} -> {len(body)}b")
        _log_line("frames.log", f"  -> {'; '.join(changes)}")

    if delay or times > 1:
        msg.drop()
        asyncio.get_running_loop().create_task(
            _later(flow, bytes(msg.content), delay, times, not msg.from_client))
        _log_line("frames.log", f"  -> held {delay}ms x{times}")


# ---------------------------------------------------------------------------
# Inject into the live socket (triggered by `wsm.py inject`)
# ---------------------------------------------------------------------------
def _do_inject(req):
    flow = _last["flow"]
    if flow is None or flow.websocket is None:
        log.warning("ws-mock: nothing to inject into yet, open the screen so a frame passes through")
        return
    if flow.websocket.timestamp_end:
        log.warning("ws-mock: the last socket is closed, reopen the screen and try again")
        return
    if req.get("file"):
        path = req["file"] if os.path.isabs(req["file"]) else os.path.join(ROOT, req["file"])
        with open(path, "rb") as f:
            body = f.read()
        json.loads(body)
    else:
        data = json.loads(_last["raw"])
        for r in config()["push"]:
            apply(r, data)
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    _inject(flow, body, to_client=True)
    log.warning(f"ws-mock: injected {len(body)}b into the live socket")
    _log_line("frames.log", f"inject {len(body)}b")


async def _watch():
    os.makedirs(LOG_DIR, exist_ok=True)
    last = _mtime(TRIGGER)
    while True:
        await asyncio.sleep(0.3)
        m = _mtime(TRIGGER)
        if m is None or m == last:
            continue
        last = m
        try:
            with open(TRIGGER, encoding="utf-8") as f:
                _do_inject(json.loads(f.read() or "{}"))
        except Exception as e:
            log.warning(f"ws-mock: inject failed: {type(e).__name__}: {e}")


def running():
    asyncio.get_running_loop().create_task(_watch())


def load(loader):
    log.warning("=" * 60)
    if _FRAG_ERR:
        log.warning(f"ws-mock: FRAGMENT_SIZE not raised ({_FRAG_ERR}), big patched frames will be split")
    else:
        log.warning(f"ws-mock: FRAGMENT_SIZE -> {FRAGMENT_SIZE} (the default 4000 splits big patched frames)")
    try:
        config()
    except Exception as e:
        log.warning(f"ws-mock: config: {e}")
    log.warning("=" * 60)
