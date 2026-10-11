#!/usr/bin/env python3
"""
wsm: control panel for ws-mock. Plain python3, no dependencies.

  python3 wsm.py                          what's on right now
  python3 wsm.py up [--demo]              ON THE MAC, the only command a person has to run.
                                          up: proxy, system proxy on, simulator cert.
                                          up --demo: demo server behind mitmproxy, no proxy settings.
                                          Ctrl+C stops it all (and turns the system proxy off).
  python3 wsm.py proxy [--headless]       just mitmweb (or mitmdump) with the addon
  python3 wsm.py down                     stop `up` (works from anywhere that shares this folder)
  python3 wsm.py proxy-off                turn the Mac system proxy off
  python3 wsm.py install-skill            Claude Code skills (ws-mock, ws-mock-demo) -> ~/.claude/skills
  python3 wsm.py pack-skills              dist/*.zip to upload the skills in the Claude apps
  python3 wsm.py screen                   simulator screenshot -> logs/screen.png (needs `up`)
  python3 wsm.py open [url]               open a URL in the simulator, default the demo (needs `up`)
  python3 wsm.py sim | cert               boot the simulator / install the mitmproxy cert in it (needs `up`)

  python3 wsm.py profiles                 list profiles
  python3 wsm.py use <name>               switch profile (turns everything off)
  python3 wsm.py new <name>               new profile from profiles/_template

  python3 wsm.py capture on|off           save every JSON frame from the socket to logs/dumps/<profile>/
  python3 wsm.py inspect [file ...]       explain captured frames, print a ready "frame" block
  python3 wsm.py check                    compare the profile with a real captured frame
  python3 wsm.py log [N]                  last N lines of logs/frames.log (what was patched/dropped/held)
  python3 wsm.py wait [--any] [--timeout 90]
                                          block until the next frame of the profile passes through
  python3 wsm.py wait --up [--timeout 90] block until `up` is running (logs/up.log says why if it isn't)

  python3 wsm.py guide web|sim|phone      what to prepare before testing (certificate, build, phone proxy)
  python3 wsm.py suggest [--json]         what makes sense to do next, from the current state
  python3 wsm.py rules                    built-in + profile rules
  python3 wsm.py on <rule ...>            switch rules on (again = re-arm "once" rules)
  python3 wsm.py off [rule ...]           switch rules off; no names = everything off, presets too

  python3 wsm.py set <id|all|frame> key=value ...
                                          one-off patch, profile untouched: set 1003 status=cancelled,
                                          set all total.amount=0, set 1000 courier=null; set clear
  python3 wsm.py presets                  list presets
  python3 wsm.py preset <name ...|all> [--solo]
                                          show these states as extra items (--solo: only them)
  python3 wsm.py preset off

  python3 wsm.py inject [file.json]       push into the open socket: last frame + "push" rules, or this file
"""
import argparse
import collections
import difflib
import json
import os
import re
import shlex
import shutil
import signal
import sys
import time

sys.dont_write_bytecode = True
import ws_mock as core  # noqa: E402  (stdlib only at import time)

__version__ = "0.1.0"
TEMPLATE = "_template"
DISC_NAMES = ("type", "event", "action", "op", "cid", "kind", "topic", "channel", "method", "msg_type", "messageType")
ID_NAMES = ("id", "uuid", "guid", "key", "_id")
LABEL_NAMES = ("title", "name", "label", "displayName", "display_name", "heading", "caption", "text")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def rel(p):
    return os.path.relpath(p, core.ROOT)


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        die(f"{what} not found: {rel(path)}")
    except json.JSONDecodeError as e:
        die(f"{what} is not valid JSON ({rel(path)} line {e.lineno}, col {e.colno}): {e.msg}")


def load_state():
    try:
        with open(core.STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    tmp = core.STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, core.STATE_PATH)


def current():
    st = load_state()
    name = core.profile_name(st)
    path = core.profile_path(name)
    if not os.path.exists(path):
        die(f"profile '{name}' doesn't exist ({rel(path)}). See: python3 wsm.py profiles")
    return st, name, read_json(path, f"profile '{name}'")


def all_rules(prof):
    named = collections.OrderedDict((n, dict(r, _builtin=True)) for n, r in core.BUILTINS.items())
    for r in prof.get("rules") or []:
        named[r["name"]] = dict(r, _builtin=False)
    return named


def short(v, n=60):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[: n - 1] + "…"


def dumps_for(name):
    d = os.path.join(core.LOG_DIR, "dumps", name)
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".json"))


def host_of(path):
    """Dumps are named <date>-<time>-<ms>-<host>.json; anything else has no host."""
    m = re.fullmatch(r"\d{8}-\d{6}-\d{3}-(.+)\.json", os.path.basename(path))
    return m.group(1) if m else "file"


# ---------------------------------------------------------------------------
# status / profiles
# ---------------------------------------------------------------------------
def cmd_status(_):
    st, name, prof = current()
    fr = prof.get("frame") or {}
    pre = st.get("presets") or []
    print(f"profile   {name}   ({rel(core.profile_path(name))})")
    if os.environ.get("WS_MOCK_PROFILE"):
        print("          (forced by WS_MOCK_PROFILE)")
    print(f"hosts     {', '.join(prof.get('hosts') or []) or 'any'}")
    print(f"frame     list {short(fr.get('list'))}  id {short(fr.get('id'))}  match {short(fr.get('match') or {}, 80)}")
    fmap = mapped_fields(prof)
    print(f"fields    {str(len(fmap)) + ' mapped' if fmap else 'none mapped (wsm.py fields)'}")
    print(f"rules on  {', '.join(st.get('on') or []) or '-'}")
    print(f"presets   {', '.join(pre) or '-'}{'   (solo)' if pre and st.get('solo') else ''}")
    for r in st.get("extra") or []:
        body = r.get("all") or r.get("set") or next(iter((r.get("by_id") or {}).values()), {})
        print(f"set       {r['name'][4:]}: {short(body, 70)}")
    print(f"capture   {'ON -> ' + rel(os.path.join(core.LOG_DIR, 'dumps', name)) if st.get('capture') else 'off'}")
    up = up_info()
    if up:
        print(f"up        running, {up.get('lan_ip')}:{up.get('port')}"
              f"{', demo ' + up['demo_url'] if up.get('demo_url') else ''}"
              f", system proxy {'on' if up.get('system_proxy') else 'off'}")
    else:
        print(f"up        not running (on the Mac: {up_cmd()})")


def cmd_profiles(_):
    st = load_state()
    active = core.profile_name(st)
    for d in sorted(os.listdir(core.PROFILES)):
        p = core.profile_path(d)
        if not os.path.exists(p):
            continue
        try:
            about = json.load(open(p, encoding="utf-8")).get("_about", "")
        except Exception:
            about = "(broken JSON)"
        mark = "*" if d == active else " "
        print(f" {mark} {d:16} {about[:90]}")


def cmd_use(a):
    if a.name == TEMPLATE:
        die("_template is the template. Make your own copy: python3 wsm.py new <name>")
    if not os.path.exists(core.profile_path(a.name)):
        die(f"no profile '{a.name}'. See: python3 wsm.py profiles")
    save_state({"profile": a.name})
    print(f"profile -> {a.name}, everything off")
    print("if its hosts differ from the previous profile, restart the proxy (python3 wsm.py proxy)")


def cmd_new(a):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", a.name):
        die("use letters, digits, dot, dash or underscore for the name")
    dest = os.path.join(core.PROFILES, a.name)
    if os.path.exists(dest):
        die(f"profile '{a.name}' already exists: {rel(dest)}")
    shutil.copytree(os.path.join(core.PROFILES, TEMPLATE), dest)
    save_state({"profile": a.name})
    print(f"created {rel(dest)}/profile.json and switched to it. Next:")
    print("  1. python3 wsm.py proxy, point the device at it (README: Device setup)")
    print("  2. python3 wsm.py capture on, open the screen in the app")
    print("  3. python3 wsm.py inspect   -> paste the suggested blocks into profile.json")
    print("  4. write presets for your states, then python3 wsm.py check")


# ---------------------------------------------------------------------------
# rules / presets
# ---------------------------------------------------------------------------
def cmd_rules(_):
    st, name, prof = current()
    on = set(st.get("on") or [])
    rules = all_rules(prof)
    print("built-in, work on any profile:")
    for n, r in rules.items():
        if r["_builtin"]:
            print(f"  [{'on ' if n in on else 'off'}] {n:18} {r.get('_doc', '')}")
    own = [(n, r) for n, r in rules.items() if not r["_builtin"]]
    print(f"profile '{name}':" if own else f"profile '{name}': no rules of its own")
    for n, r in own:
        tag = "  (overrides built-in)" if n in core.BUILTINS else ""
        print(f"  [{'on ' if n in on else 'off'}] {n:18} {r.get('_doc', '')}{tag}")


def with_deps(names, known):
    """Add the rules listed in each rule's "with" (companions it needs), companions first."""
    out = []
    def add(n, seen=()):
        for dep in known.get(n, {}).get("with") or []:
            if dep in known and dep not in seen:
                add(dep, seen + (n,))
        if n not in out:
            out.append(n)
    for n in names:
        add(n)
    return out


def cmd_on(a):
    st, name, prof = current()
    known = all_rules(prof)
    bad = [n for n in a.names if n not in known]
    if bad:
        die(f"unknown rules: {', '.join(bad)}. See: python3 wsm.py rules")
    names = with_deps(a.names, known)
    on = [n for n in st.get("on") or [] if n not in names] + names
    st["on"] = on
    save_state(st)
    print(f"on: {', '.join(on)}")


def cmd_off(a):
    st = load_state()
    if not a.names:
        st["on"], st["presets"], st["solo"], st["extra"] = [], [], False, []
        save_state(st)
        print("everything off, frames go through untouched")
        return
    st["on"] = [n for n in st.get("on") or [] if n not in a.names]
    save_state(st)
    print(f"on: {', '.join(st['on']) or '-'}")


def _parse_value(v):
    try:
        return json.loads(v)
    except ValueError:
        return v                     # plain text, or a token like __TS_S:-1h__


def _nest(path, value):
    out = value
    for part in reversed(path.split(".")):
        out = {part: out}
    return out


def _merge_dicts(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge_dicts(a[k], v)
        else:
            a[k] = v
    return a


def cmd_set(a):
    st = load_state()
    if a.target == "clear":
        st["extra"] = []
        save_state(st)
        print("one-off patches cleared")
        return
    patch = {}
    for kv in a.pairs:
        if "=" not in kv:
            die(f"expected key=value, got {kv!r} (nested keys with dots: total.amount=0)")
        k, v = kv.split("=", 1)
        _merge_dicts(patch, _nest(k, _parse_value(v)) if not k.startswith("/") else {k: _parse_value(v)})
    if not patch:
        die("nothing to set: give key=value pairs")
    name = f"set:{a.target}"
    extra = [r for r in st.get("extra") or []]
    rule = next((r for r in extra if r.get("name") == name), None)
    if rule is None:
        rule = {"name": name}
        extra.append(rule)
    if a.target == "all":
        rule["all"] = _merge_dicts(rule.get("all") or {}, patch)
    elif a.target == "frame":
        flat = {}
        def walk(d, prefix):
            for k, v in d.items():
                key = k if k.startswith("/") else f"{prefix}/{k}"
                if isinstance(v, dict) and not k.startswith("/"):
                    walk(v, key)
                else:
                    flat[key] = v
        walk(patch, "")
        rule["set"] = {**(rule.get("set") or {}), **flat}
    else:
        rule["by_id"] = {a.target: _merge_dicts(((rule.get("by_id") or {}).get(a.target)) or {}, patch)}
    st["extra"] = extra
    save_state(st)
    shown = rule.get("all") or rule.get("set") or rule["by_id"][a.target]
    print(f"{name}: {json.dumps(shown, ensure_ascii=False)}   (wsm.py set clear / wsm.py off to drop)")


def cmd_presets(_):
    st, name, prof = current()
    pre = prof.get("presets") or {}
    chosen = st.get("presets") or []
    items = pre.get("items") or {}
    if not items:
        print(f"profile '{name}' has no presets")
        return
    print(f"source item: {short(pre.get('source'))}")
    for n, patch in items.items():
        mark = "on " if (n in chosen or chosen == ["all"]) else "off"
        print(f"  [{mark}] {n:20} {short(patch, 70)}")


def cmd_preset(a):
    st, name, prof = current()
    items = (prof.get("presets") or {}).get("items") or {}
    if a.names == ["off"]:
        st["presets"], st["solo"] = [], False
        save_state(st)
        print("presets off")
        return
    if a.names != ["all"]:
        bad = [n for n in a.names if n not in items]
        if bad:
            die(f"unknown presets: {', '.join(bad)}. See: python3 wsm.py presets")
    st["presets"], st["solo"] = a.names, a.solo
    save_state(st)
    shown = list(items) if a.names == ["all"] else a.names
    print(f"presets: {', '.join(shown)}{'   (solo: real items hidden)' if a.solo else ''}")
    print("reopen or refresh the screen to see them")


# ---------------------------------------------------------------------------
# capture / inspect
# ---------------------------------------------------------------------------
def cmd_capture(a):
    st, name, _ = current()
    st["capture"] = a.mode == "on"
    save_state(st)
    where = rel(os.path.join(core.LOG_DIR, "dumps", name))
    if st["capture"]:
        print(f"capture on: every JSON frame from the socket goes to {where}/ (last {core.KEEP_DUMPS} kept)")
        print("open the screen in the app, then: python3 wsm.py inspect")
    else:
        print("capture off")


def find_lists(node, ptr="", depth=0, out=None):
    """Arrays of objects inside a frame. Doesn't go inside the items themselves."""
    out = [] if out is None else out
    if depth > 6:
        return out
    if isinstance(node, list):
        if node and all(isinstance(x, dict) for x in node):
            out.append((ptr, node))
    elif isinstance(node, dict):
        for k, v in node.items():
            find_lists(v, ptr + "/" + k.replace("~", "~0").replace("/", "~1"), depth + 1, out)
    return out


def ordered_keys(items, limit=500):
    keys = []
    for it in items[:limit]:
        for k in it:
            if k not in keys:
                keys.append(k)
    return keys


def guess_id(items):
    sample = items[:500]
    best = None
    for k in ordered_keys(sample):
        vals = [it.get(k) for it in sample]
        if not all(isinstance(v, (str, int)) and not isinstance(v, bool) for v in vals):
            continue
        if len(set(vals)) != len(vals):
            continue
        kl = k.lower()
        if kl in ID_NAMES:
            score = 3
        elif kl.endswith("_id") or k.endswith("Id") or kl.endswith("id"):
            score = 2
        elif all(isinstance(v, int) for v in vals):
            score = 1
        else:
            continue
        if best is None or score > best[0]:
            best = (score, k)
    return best[1] if best else None


def guess_label(items, idk):
    first = items[0]
    for n in LABEL_NAMES:
        if isinstance(first.get(n), str):
            return n
    for k, v in first.items():
        if isinstance(v, dict):
            for n in LABEL_NAMES:
                if isinstance(v.get(n), str):
                    return f"/{k}/{n}"
    best = None
    sample = items[:200]
    for k in ordered_keys(sample):
        if k == idk:
            continue
        vals = [x.get(k) for x in sample if isinstance(x.get(k), str)]
        if len(vals) < len(sample) * 0.9:
            continue
        d = len(set(vals))
        if d > 1 and (best is None or d > best[0]):
            best = (d, k)
    return best[1] if best else None


_OBJ = object()


def flat(it):
    out = {}
    for k, v in it.items():
        if isinstance(v, dict):
            out[k] = _OBJ
            for k2, v2 in v.items():
                if not isinstance(v2, (dict, list)):
                    out[f"{k}/{k2}"] = v2
        elif not isinstance(v, list):
            out[k] = v
    return out


def state_fields(items, skip, limit=8):
    """Fields with a handful of distinct values: those usually drive the UI state."""
    flats = [flat(it) for it in items[:1000]]
    keys = []
    for f in flats:
        for k in f:
            if k not in keys:
                keys.append(k)
    rows = []
    for k in keys:
        if k == skip:
            continue
        c = collections.Counter("(missing)" if k not in f else "{…}" if f[k] is _OBJ
                                else json.dumps(f[k], ensure_ascii=False) for f in flats)
        if 2 <= len(c) <= limit and len(c) < len(flats):
            rows.append((k, c.most_common()))
    return rows


def discriminator(frames):
    dicts = [d for d in frames if isinstance(d, dict)]
    if not dicts:
        return None
    for k in DISC_NAMES:
        vals = {json.dumps(d.get(k)) for d in dicts if k in d}
        if len(vals) == 1 and all(k in d for d in dicts):
            v = dicts[0][k]
            if isinstance(v, (str, int)) and not isinstance(v, bool):
                return k, v
    return None


def item_keys_line(items):
    out = []
    for k in ordered_keys(items, 50):
        v = items[0].get(k)
        if isinstance(v, dict):
            out.append(f"{k}{{{','.join(list(v)[:6])}{',…' if len(v) > 6 else ''}}}")
        elif isinstance(v, list):
            out.append(f"{k}[{len(v)}]")
        else:
            out.append(k)
    return ", ".join(out)


def cmd_inspect(a):
    if a.files:
        paths = a.files
    else:
        _, name, _ = current()
        paths = dumps_for(name)[-a.last:]
        if not paths:
            die("nothing captured yet. python3 wsm.py capture on, open the screen, then run inspect again")

    groups = collections.OrderedDict()
    for p in paths:
        try:
            data = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            print(f"skip {p}: {e}")
            continue
        sig = tuple(sorted(data)) if isinstance(data, dict) else ("(list)",)
        groups.setdefault((host_of(p), sig), []).append((p, data, os.path.getsize(p)))

    best = None
    for (host, sig), frames in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        p, data, size = frames[-1]
        keys = ", ".join(sig[:12]) + (", …" if len(sig) > 12 else "")
        print(f"\n== {host} · {len(frames)} frame(s) · ~{size / 1024:.1f} KB · keys: {keys}")
        disc = discriminator([d for _, d, _ in frames])
        if disc:
            print(f"   {disc[0]} = {short(disc[1])}")
        lists = sorted(find_lists(data), key=lambda x: -len(x[1]))
        if not lists:
            print("   no list of objects in this frame")
            continue
        for i, (ptr, items) in enumerate(lists[:3]):
            idk = guess_id(items)
            lbl = guess_label(items, idk)
            print(f"   list {ptr or '(the whole frame)'}: {len(items)} items · id {short(idk)} · label {short(lbl)}")
            if i == 0:
                print(f"     item keys: {item_keys_line(items)}")
                rows = state_fields(items, idk)
                if rows:
                    print("     fields that look like state:")
                    for k, c in rows[:14]:
                        vals = " · ".join(f"{v[:28]} {n}" for v, n in c)
                        print(f"       /{k:26} {vals}")
                print(f"     first item: {short(items[0], 300)}")
            score = len(items)
            if best is None or score > best[0]:
                best = (score, host, ptr, idk, lbl, disc, items)

    if not best:
        return
    _, host, ptr, idk, lbl, disc, items = best
    match = {"has": ptr} if ptr else {}
    if disc:
        match["equals"] = {f"/{disc[0]}": disc[1]}
    frame = {"match": match, "list": ptr, "id": idk or "CHANGE_ME", "label": lbl or "CHANGE_ME"}
    src = items[0].get(idk) if idk else "CHANGE_ME"
    print("\nsuggested for profile.json (biggest list):")
    if host != "file":
        print(f'  "hosts": [{json.dumps(host)}],')
    print(f'  "frame": {json.dumps(frame, ensure_ascii=False)},')
    print(f'  "presets": {{"source": {json.dumps(src, ensure_ascii=False)}, "items": {{ ... }}}}')


def field_ptr(k):
    """Field map key (dotted or /pointer) -> pointer inside one item."""
    return k if k.startswith("/") else "/" + k.replace(".", "/")


def mapped_fields(prof):
    """The profile's field map without notes and CHANGE_ME placeholders."""
    return {k: v for k, v in (prof.get("fields") or {}).items()
            if not k.startswith("_") and "CHANGE_ME" not in k and "CHANGE_ME" not in str(v)}


def last_frame(name, fr):
    """Newest captured frame of this profile that matches frame.match: (path, frame, items) or None."""
    for p in reversed(dumps_for(name)):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if core.matches({"match": fr.get("match")}, d):
            items = core.jget(d, fr.get("list", ""), None)
            return p, d, [it for it in items if isinstance(it, dict)] if isinstance(items, list) else []
    return None


def cmd_fields(_):
    _, name, prof = current()
    fr = prof.get("frame") or {}
    fmap = mapped_fields(prof)
    found = last_frame(name, fr) if fr.get("list") else None
    items = found[2] if found else []
    print(f"profile {name}: {len(fmap)} field(s) mapped"
          + (f", real values from {rel(found[0])} ({len(items)} items)" if found else ", no captured frame yet"))
    for k, meaning in fmap.items():
        print(f"\n  {k}\n    {meaning}")
        if items:
            c = collections.Counter()
            for it in items:
                v = core.jget(it, field_ptr(k), core._MISSING)
                c["(missing)" if v is core._MISSING else short(v, 28)] += 1
            if c.get("(missing)") == len(items):
                print("    real: not in any item (typo, or the server never sends it?)")
            else:
                print("    real: " + " · ".join(f"{v} {n}" for v, n in c.most_common(6))
                      + (" · …" if len(c) > 6 else ""))
    if items:
        done = {field_ptr(k).strip("/") for k in fmap}
        rest = [(k, c) for k, c in state_fields(items, fr.get("id")) if k not in done]
        if rest:
            print("\nnot mapped yet, look like state:")
            for k, c in rest[:14]:
                print(f"  /{k:26} " + " · ".join(f"{v[:28]} {n}" for v, n in c[:6]))
    if not fmap:
        print("\nNo field map yet. Before writing presets: which field drives what on the screen?"
              " Spec / dev / try it with `wsm.py set <id> field=value`, then write it into \"fields\".")


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------
def placeholders(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("_"):
                continue    # notes for humans
            p = f"{path}.{k}" if path else k
            if "CHANGE_ME" in k:
                yield p
            yield from placeholders(v, p)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from placeholders(v, f"{path}[{i}]")
    elif isinstance(node, str) and "CHANGE_ME" in node:
        yield path


def _norm(k):
    return re.sub(r"[_\-\s]", "", k).lower()


def suggest(k, keys):
    for c in keys:
        if _norm(c) == _norm(k):
            return c
    m = difflib.get_close_matches(k, keys, n=1, cutoff=0.75)
    return m[0] if m else None


def _kind(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    return type(v).__name__


def unknown_keys(patch, target, path=""):
    out = []
    if not isinstance(target, dict) or not isinstance(patch, dict):
        return out
    for k, v in patch.items():
        if k.startswith("_"):
            continue
        if k.startswith("/"):
            if core.jget(target, k) is core._MISSING:
                out.append(f"{k} doesn't exist in the real item (it will be created)")
            continue
        if k not in target:
            s = suggest(k, list(target))
            hint = f", did you mean '{path}{s}'?" if s else " (typo, or a field the server never sends?)"
            out.append(f"'{path}{k}' isn't in the real item{hint}")
            continue
        t = target[k]
        if isinstance(v, dict) and isinstance(t, dict):
            out += unknown_keys(v, t, f"{path}{k}.")
        elif (v is not None and t is not None and not (isinstance(v, str) and v.startswith("__") and v.endswith("__"))
              and _kind(v) != _kind(t)):
            out.append(f"'{path}{k}' is a {_kind(t)} in the real item, the patch has a {_kind(v)} ({short(v, 30)})")
    return out


def cmd_check(_):
    st, name, prof = current()
    fr = prof.get("frame") or {}
    errors, warns, oks = [], [], []

    ph = list(dict.fromkeys(placeholders(prof)))
    if ph:
        warns.append(f"still has CHANGE_ME: {', '.join(ph[:8])}{' …' if len(ph) > 8 else ''}")
    if "list" not in fr:
        errors.append('frame.list is missing (run inspect to get it)')

    found = None
    for p in reversed(dumps_for(name)):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if core.matches({"match": fr.get("match")}, d):
            found = (p, d)
            break

    if not found:
        errors.append(f"no captured frame matches frame.match {short(fr.get('match') or {}, 80)}. "
                      "python3 wsm.py capture on, open the screen, check again")
    else:
        p, d = found
        oks.append(f"frame.match matches {rel(p)}")
        items = core.jget(d, fr.get("list", ""), None)
        if not isinstance(items, list):
            errors.append(f"frame.list {fr.get('list')!r} is not a list in that frame")
            items = []
        else:
            oks.append(f"frame.list {fr.get('list')!r}: {len(items)} items")
        key = fr.get("id", "id")
        by_id = {str(it.get(key)): it for it in items if isinstance(it, dict) and key in it}
        missing = sum(1 for it in items if not (isinstance(it, dict) and key in it))
        if items and missing:
            errors.append(f"id field {key!r} is missing in {missing} of {len(items)} items")
        elif items:
            oks.append(f"id {key!r} present in every item")
        lbl = fr.get("label")
        if lbl and items:
            val = core.jget(items[0], lbl, None) if lbl.startswith("/") else items[0].get(lbl)
            if isinstance(val, str):
                oks.append(f"label {lbl!r} -> {short(val, 40)}")
            else:
                warns.append(f"label {lbl!r} is not a text field in the items, presets won't get a [name] prefix")
        sample_ids = ", ".join(list(by_id)[:4])

        fmap = mapped_fields(prof)
        if not fmap:
            warns.append("no field map: \"fields\" says nothing about which field drives what on the screen "
                         "(python3 wsm.py fields)")
        else:
            oks.append(f"field map: {len(fmap)} field(s)")
            for k in fmap:
                if items and all(core.jget(it, field_ptr(k), core._MISSING) is core._MISSING
                                 for it in items if isinstance(it, dict)):
                    warns.append(f"fields: {k!r} is not in any real item (typo, or the server never sends it?)")

        pre = prof.get("presets") or {}
        if pre.get("items"):
            src = by_id.get(str(pre.get("source")))
            if src is None:
                errors.append(f"presets.source {pre.get('source')!r} is not in the list (ids look like: {sample_ids})")
            else:
                oks.append(f"presets.source {pre.get('source')!r} found, {len(pre['items'])} presets")
                for n, patch in pre["items"].items():
                    warns += [f"preset {n}: {m}" for m in unknown_keys(patch, src)]

        for section in ("rules", "push"):
            for r in prof.get(section) or []:
                rn = f"{section[:-1] if section == 'rules' else 'push'} {r.get('name')}"
                if r.get("list", fr.get("list")) != fr.get("list"):
                    continue    # works on another list, can't check against this frame
                for i, patch in (r.get("by_id") or {}).items():
                    it = by_id.get(str(i))
                    if it is None:
                        errors.append(f"{rn}: id {i} is not in the list (ids look like: {sample_ids})")
                    else:
                        warns += [f"{rn} by_id {i}: {m}" for m in unknown_keys(patch, it)]
                if r.get("all") and items:
                    warns += [f"{rn} all: {m}" for m in unknown_keys(r["all"], items[0])]
                for cl in r.get("clone") or []:
                    it = by_id.get(str(cl.get("from")))
                    if it is None:
                        errors.append(f"{rn}: clone source {cl.get('from')!r} is not in the list")
                    else:
                        warns += [f"{rn} clone: {m}" for m in unknown_keys(cl.get("patch") or {}, it)]

    for o in oks:
        print(f"  ok    {o}")
    for w in warns:
        print(f"  warn  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    print("\n" + ("errors above" if errors else "looks good" if not warns else "works, check the warnings"))
    sys.exit(1 if errors else 0)


# ---------------------------------------------------------------------------
# inject / proxy
# ---------------------------------------------------------------------------
def cmd_inject(a):
    os.makedirs(core.LOG_DIR, exist_ok=True)
    req = {"t": time.time()}
    if a.file:
        path = os.path.abspath(a.file)
        read_json(path, "frame file")
        inside = os.path.commonpath([path, core.ROOT]) == core.ROOT
        req["file"] = os.path.relpath(path, core.ROOT) if inside else path
    with open(core.TRIGGER, "w", encoding="utf-8") as f:
        json.dump(req, f)
    print("sent to the proxy, watch its log (the screen must be open)")


def host_regex(h):
    return re.escape(h.split("/")[0])


def cmd_proxy(a):
    _, name, prof = current()
    exe = "mitmdump" if a.headless else "mitmweb"
    cmd = [exe, "-s", os.path.join(core.ROOT, "ws_mock.py"), "--listen-port", str(a.port)]
    if not a.headless:
        cmd += ["--web-port", str(a.web_port)]
    hosts = [] if a.all_hosts else prof.get("hosts") or []
    if hosts:
        cmd += ["--allow-hosts", "|".join(host_regex(h) for h in hosts)]
    cmd += a.extra[1:] if a.extra[:1] == ["--"] else a.extra
    print(f"profile '{name}'")
    if not hosts:
        print("no hosts in the profile: every connection goes through mitmproxy")
    print("$ " + " ".join(shlex.quote(c) for c in cmd), flush=True)
    try:
        os.execvp(exe, cmd)
    except FileNotFoundError:
        die(f"{exe} not found. Install mitmproxy: brew install --cask mitmproxy  (or: pip install mitmproxy)")


# ---------------------------------------------------------------------------
# up: one command on the Mac. Everything else can be driven through files.
# ---------------------------------------------------------------------------
UP_INFO = os.path.join(core.LOG_DIR, "up.json")
DEV_TRIGGER = os.path.join(core.LOG_DIR, "device.trigger")
DEV_RESULT = os.path.join(core.LOG_DIR, "device.result.json")
CERT = os.path.expanduser("~/.mitmproxy/mitmproxy-ca-cert.pem")


UP_LOG = os.path.join(core.LOG_DIR, "up.log")


def _read_up():
    try:
        with open(UP_INFO, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def up_info():
    """Contents of logs/up.json if `up` is alive, else None.
    Fresh heartbeat = alive. Otherwise watch the beat counter for a moment: if it moves, `up` is alive
    and only the clocks differ (a VM reading the Mac's folder can have its own clock)."""
    info = _read_up()
    if not info:
        return None
    if abs(time.time() - info.get("heartbeat", 0)) < 10:
        return info
    beat = info.get("beat")
    time.sleep(1.5)
    again = _read_up()
    return again if again and beat is not None and again.get("beat") != beat else None


def up_cmd(args="up"):
    """The command to start `up` on the Mac, with the repo path `up` last ran from (if known)."""
    repo = (_read_up() or {}).get("repo")
    return f"cd {shlex.quote(repo)} && python3 wsm.py {args}" if repo else f"python3 wsm.py {args} (in the ws-mock folder)"


def up_log(msg):
    """Print and keep a copy in logs/up.log, so whoever drives ws-mock can see what `up` did."""
    print(msg, flush=True)
    try:
        os.makedirs(core.LOG_DIR, exist_ok=True)
        with open(UP_LOG, "a", encoding="utf-8") as f:
            for line in str(msg).strip("\n").splitlines():
                f.write(time.strftime("%H:%M:%S ") + line + "\n")
    except Exception:
        pass


def port_busy(port):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def lan_ip():
    """The Mac's Wi-Fi/Ethernet address (what a phone on the same network can reach), not a VPN one."""
    if shutil.which("ipconfig"):
        for iface in ("en0", "en1"):
            ok, out = run(["ipconfig", "getifaddr", iface], timeout=3)
            if ok and out:
                return out.splitlines()[0].strip()
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # no packet is sent, this only picks the outgoing interface
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def run(cmd, timeout=20):
    import subprocess
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return False, f"{cmd[0]} not found"
    except Exception as e:
        return False, str(e)


def system_proxy(service, on, port=8080):
    if not shutil.which("networksetup"):
        return False, "networksetup not found (not a Mac)"
    if on:
        cmds = [["networksetup", "-setwebproxy", service, "127.0.0.1", str(port)],
                ["networksetup", "-setsecurewebproxy", service, "127.0.0.1", str(port)]]
    else:
        cmds = [["networksetup", "-setwebproxystate", service, "off"],
                ["networksetup", "-setsecurewebproxystate", service, "off"]]
    out = [run(c) for c in cmds]
    return all(ok for ok, _ in out), "; ".join(m for _, m in out if m)


def device_action(req):
    act = req.get("action")
    if not shutil.which("xcrun"):
        return {"ok": False, "error": "xcrun not found (needs a Mac with Xcode)"}
    if act == "screen":
        out = os.path.join(core.LOG_DIR, "screen.png")
        ok, msg = run(["xcrun", "simctl", "io", "booted", "screenshot", out])
        return {"ok": ok, "file": os.path.relpath(out, core.ROOT), "error": None if ok else msg}
    if act == "open":
        ok, msg = run(["xcrun", "simctl", "openurl", "booted", req["url"]])
        return {"ok": ok, "error": None if ok else msg}
    if act == "sim":
        ok, msg = run(["open", "-a", "Simulator"])
        for _ in range(60):                     # wait until a device is booted
            ok2, out = run(["xcrun", "simctl", "list", "devices", "booted"])
            if ok2 and "Booted" in out:
                return {"ok": True, "error": None}
            time.sleep(1)
        return {"ok": False, "error": msg or "no booted simulator after 60 s"}
    if act == "cert":
        ok, msg = run(["xcrun", "simctl", "keychain", "booted", "add-root-cert", CERT])
        return {"ok": ok, "error": None if ok else msg}
    return {"ok": False, "error": f"unknown action {act!r}"}


def cmd_up(a):
    import subprocess
    import threading
    _, name, prof = current()
    os.makedirs(core.LOG_DIR, exist_ok=True)

    running = up_info()
    if running:
        up_log(f"up is already running (pid {running.get('pid')}, {running.get('demo_url') or 'proxy :' + str(running.get('port'))}). "
               "Use that one, or stop it first: python3 wsm.py down")
        sys.exit(1)
    ports = [a.demo_port, a.demo_port + 1] if a.demo else [a.port]
    if not a.headless:
        ports.append(a.web_port)
    busy = [p for p in ports if port_busy(p)]
    if busy:
        up_log(f"can't start: port {', '.join(map(str, busy))} is busy. Another ws-mock or mitmproxy is probably "
               "still running: close that terminal or run python3 wsm.py down, then start again.")
        sys.exit(1)

    up_log(f"--- up starting: profile '{name}', {'demo' if a.demo else 'proxy'}, pid {os.getpid()}")
    children = []           # (name, Popen)
    ip = lan_ip()
    demo_url = None

    exe = "mitmdump" if a.headless else "mitmweb"
    cmd = [exe, "-s", os.path.join(core.ROOT, "ws_mock.py")]
    if not a.headless:
        cmd += ["--web-port", str(a.web_port)]
        if a.no_browser:
            cmd += ["--set", "web_open_browser=false"]

    if a.demo:
        # Demo: mitmproxy sits in front of the demo server as a reverse proxy.
        # The page is opened through mitmproxy's port, so no system proxy is needed
        # (the simulator can bypass the system proxy for LAN IPs anyway).
        inner = a.demo_port + 1
        srv = [sys.executable, os.path.join(core.ROOT, "examples", "demo", "server.py"),
               "--host", "127.0.0.1", "--port", str(inner),
               "--orders", str(a.orders), "--interval", str(a.interval)]
        children.append(("demo server", subprocess.Popen(srv)))
        cmd += ["--mode", f"reverse:http://127.0.0.1:{inner}@{a.demo_port}"]
        demo_url = f"http://{ip}:{a.demo_port}"
        a.no_system_proxy = True
    else:
        cmd += ["--listen-port", str(a.port)]
        hosts = [] if a.all_hosts else prof.get("hosts") or []
        if hosts:
            cmd += ["--allow-hosts", "|".join(host_regex(h) for h in hosts)]
    try:
        children.append((exe, subprocess.Popen(cmd)))
    except FileNotFoundError:
        for _, c in children:
            c.terminate()
        up_log(f"{exe} not found. Install mitmproxy: brew install --cask mitmproxy  (or: pip install mitmproxy)")
        sys.exit(1)

    sys_proxy = False
    if not a.no_system_proxy:
        sys_proxy, msg = system_proxy(a.service, True, a.port)
        up_log(f"system proxy ({a.service}): {'ON' if sys_proxy else 'not changed: ' + msg}")

    for _ in range(20):                         # mitmproxy creates the CA on first start
        if os.path.exists(CERT):
            break
        time.sleep(0.25)
    if shutil.which("xcrun"):
        r = device_action({"action": "cert"})
        up_log("simulator cert: " + ("installed" if r["ok"] else f"skipped ({r['error']})"))

    print("\n" + "=" * 60)
    if demo_url:
        up_log(f"ws-mock is up. profile '{name}'. Demo through mitmproxy: {demo_url}")
        print("Open that URL on any device (simulator, phone, desktop browser). No proxy settings needed.")
        print("Ctrl+C stops everything.")
    else:
        up_log(f"ws-mock is up. profile '{name}', proxy {ip}:{a.port}")
        print("Ctrl+C stops everything and turns the system proxy back off.")
    print("=" * 60 + "\n", flush=True)

    import signal as _sig
    def _stop(*_):
        raise KeyboardInterrupt
    for s_ in ("SIGTERM", "SIGHUP"):
        if hasattr(_sig, s_):
            _sig.signal(getattr(_sig, s_), _stop)

    last_req = os.path.getmtime(DEV_TRIGGER) if os.path.exists(DEV_TRIGGER) else None
    info = {"pid": os.getpid(), "started": time.time(), "lan_ip": ip,
            "port": a.demo_port if demo_url else a.port,
            "demo_url": demo_url, "system_proxy": sys_proxy, "profile": name, "beat": 0,
            "repo": core.ROOT}
    alive = threading.Event()
    alive.set()

    def heartbeat():
        # its own thread, so a slow action (booting the simulator) doesn't make `up` look dead
        while alive.is_set():
            info["heartbeat"] = time.time()
            info["beat"] += 1
            try:
                tmp = UP_INFO + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(info, f)
                os.replace(tmp, UP_INFO)
            except Exception:
                pass
            time.sleep(0.5)

    hb = threading.Thread(target=heartbeat, daemon=True)
    hb.start()
    try:
        while True:
            dead = [(n, c.returncode) for n, c in children if c.poll() is not None]
            if dead:
                up_log("; ".join(f"{n} exited with code {rc}" for n, rc in dead)
                       + ". Shutting down (scroll up in this terminal for its error).")
                break
            m = os.path.getmtime(DEV_TRIGGER) if os.path.exists(DEV_TRIGGER) else None
            if m and m != last_req:
                last_req = m
                try:
                    req = json.load(open(DEV_TRIGGER, encoding="utf-8"))
                    res = {"ok": True} if req.get("action") == "down" else device_action(req)
                except Exception as e:
                    req, res = {}, {"ok": False, "error": str(e)}
                res["id"] = req.get("id")
                json.dump(res, open(DEV_RESULT, "w", encoding="utf-8"))
                if req.get("action") != "down":
                    up_log(f"action {req.get('action')}: {'ok' if res.get('ok') else res.get('error')}")
                if req.get("action") == "down":
                    up_log("stop requested (wsm.py down)")
                    break
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        alive.clear()
        hb.join(timeout=2)
        if sys_proxy:
            ok, msg = system_proxy(a.service, False)
            up_log(f"system proxy: {'off' if ok else 'COULD NOT TURN OFF: ' + msg}")
        for _, c in children:
            if c.poll() is None:
                c.terminate()
        for _, c in children:
            try:
                c.wait(timeout=5)
            except Exception:
                c.kill()
        mine = _read_up()
        if mine and mine.get("pid") == os.getpid():
            try:
                os.remove(UP_INFO)
            except OSError:
                pass
        up_log("--- up stopped")


def ask_up(req, wait=15):
    """Hand an action to the running `up` (it runs on the Mac) and wait for the answer."""
    if not up_info():
        die(f"`up` is not running. On the Mac: {up_cmd()}")
    req["id"] = f"{time.time():.6f}"
    with open(DEV_TRIGGER, "w", encoding="utf-8") as f:
        json.dump(req, f)
    end = time.time() + wait
    while time.time() < end:
        try:
            res = json.load(open(DEV_RESULT, encoding="utf-8"))
            if res.get("id") == req["id"]:
                return res
        except Exception:
            pass
        time.sleep(0.3)
    die("no answer from `up` in time")


def cmd_screen(_):
    res = ask_up({"action": "screen"})
    if not res["ok"]:
        die(f"screenshot failed: {res['error']}")
    print(res["file"])


def cmd_open(a):
    url = a.url or (up_info() or {}).get("demo_url")
    if not url:
        die("give a URL (no demo running)")
    res = ask_up({"action": "open", "url": url})
    print(f"opened {url}" if res["ok"] else f"failed: {res['error']}")


def cmd_sim(_):
    res = ask_up({"action": "sim"}, wait=75)
    print("simulator is booted" if res["ok"] else f"failed: {res['error']}")


def cmd_cert(_):
    res = ask_up({"action": "cert"})
    print("mitmproxy cert installed in the booted simulator" if res["ok"] else f"failed: {res['error']}")


def cmd_down(_):
    if not up_info():
        print("`up` is not running")
        return
    ask_up({"action": "down"})
    for _ in range(40):                 # wait until it cleaned up (system proxy off, children stopped)
        if not os.path.exists(UP_INFO):
            print("up stopped")
            return
        time.sleep(0.25)
    print("asked `up` to stop; it is still cleaning up")


def cmd_install_skill(_):
    base = os.path.join(core.ROOT, ".claude", "skills")
    names = sorted(d for d in os.listdir(base) if os.path.exists(os.path.join(base, d, "SKILL.md"))) \
        if os.path.isdir(base) else []
    if not names:
        die(f"no skills in the repo: {rel(base)}")
    for name in names:
        dest = os.path.expanduser(os.path.join("~", ".claude", "skills", name))
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        shutil.copytree(os.path.join(base, name), dest)
        with open(os.path.join(dest, "repo.txt"), "w", encoding="utf-8") as f:
            f.write(core.ROOT + "\n")
        print(f"skill installed: {dest}")
    print(f"they point at this repo: {core.ROOT}")
    print("Claude Code picks them up in any folder now. Run this again after pulling a new version.")


def suggestions():
    """What makes sense to do next, by priority, from the current state."""
    st = load_state()
    name = core.profile_name(st)
    path = core.profile_path(name)
    up = up_info()
    out = []

    def add(key, title, why, cmds):
        out.append({"id": key, "title": title, "why": why, "commands": cmds})

    if not os.path.exists(path):
        add("use-demo", "Switch to the demo profile", f"profile '{name}' doesn't exist", ["use demo"])
        return out
    try:
        prof = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        add("fix-profile", f"Fix profile '{name}'", f"profile.json is broken: {e}", [])
        return out

    if name == "demo":
        # the main skill is about the person's own app: their profiles first, the demo is one entry
        own = [d for d in sorted(os.listdir(core.PROFILES))
               if d not in ("demo", TEMPLATE) and os.path.exists(core.profile_path(d))]
        if st.get("on") or st.get("presets") or st.get("extra"):
            add("reset", "Back to real data", "something is still switched on in the demo", ["off"])
        add("new", "Set up ws-mock for your app or site",
            "new profile from a captured frame: capture, inspect, check", ["new <name>"])
        for d in own[:2]:
            add(f"use:{d}", f"Continue with profile '{d}'", "your existing profile", [f"use {d}"])
        add("demo-tour", "Show the demo tour first", "5 minutes on the built-in demo app (ws-mock-demo skill)", [])
        if up:
            add("stop", "Stop ws-mock", "stops the proxy (and the demo), system proxy off", ["down"])
        return out

    unset = bool(list(placeholders(prof)))
    dumps = dumps_for(name)
    on = st.get("on") or []
    pre = st.get("presets") or []
    items = (prof.get("presets") or {}).get("items") or {}
    known = all_rules(prof)
    demo = name == "demo"

    if not up:
        add("start", "Start ws-mock" + (" with the demo" if demo else ""),
            "nothing goes through the proxy yet", ["up --demo" if demo else "up"])
    if unset:
        add("setup", f"Set up profile '{name}' from a real frame",
            "it still has CHANGE_ME: capture a frame, inspect, fill the profile, check",
            ["capture on", "wait --any", "capture off", "inspect", "check"])
    elif not mapped_fields(prof):
        add("fields", f"Map the fields of '{name}'",
            "which field drives what on the screen; mocks are only as right as this map", ["fields"])
    extra = [r["name"] for r in st.get("extra") or []]
    if on or pre or extra:
        now = on + ([f"presets: {', '.join(pre)}"] if pre else []) + extra
        add("reset", "Back to real data", "on now: " + "; ".join(now), ["off"])
    if not unset:
        if items:
            add("states", f"Show all {len(items)} states at once",
                "one card per preset, real items hidden, each labelled [preset-name]", ["preset all --solo"])
        companions = {d for r in known.values() for d in (r.get("with") or [])}
        for n, r in known.items():
            if not r["_builtin"] and n not in companions:
                add(f"rule:{n}", r.get("_doc") or n, f"profile rule '{n}'", [f"on {n}"])
        add("frozen", "Socket hangs: data stops coming",
            "socket stays open, every frame is dropped; is there any staleness indicator?", ["on frozen"])
        if not any(not r["_builtin"] and r.get("once") for r in known.values()):
            add("late-frame", "An old frame lands after a newer one",
                "one frame held 5 s; does the screen roll back?", ["on late-frame"])
        if prof.get("push"):
            add("inject", "Live update into the open screen",
                "pushes the profile's push rules into the socket, no reload", ["inject"])
        add("duplicate", "Every frame arrives twice", "double toasts, double items, double analytics", ["on duplicate"])
        add("empty", "Empty list", "empty state", ["on empty"])
        add("slow", "Every frame 3 s late", "loading states, acting on old data", ["on slow"])
        add("reverse", "List in reverse order", "does the client sort by itself?", ["on reverse"])
    add("new", "Profile for another app", "new profile from the template", ["new <name>"])
    if up:
        add("stop", "Stop ws-mock", "stops the proxy (and the demo), system proxy off", ["down"])
    return out


def cmd_suggest(a):
    sug = suggestions()
    if a.json:
        print(json.dumps(sug, ensure_ascii=False, indent=2))
        return
    for i, s_ in enumerate(sug, 1):
        cmds = " && ".join(f"wsm.py {c}" for c in s_["commands"]) or "-"
        print(f"{i:2}. {s_['title']}\n      {s_['why']}\n      {cmds}")


GUIDES = {
    "web": [
        "Web",
        "- Browser on the Mac (Chrome, Safari): trust the mitmproxy certificate once:",
        "  sudo security add-trusted-cert -d -p ssl -p basic -k /Library/Keychains/System.keychain ~/.mitmproxy/mitmproxy-ca-cert.pem",
        "  Firefox keeps its own store: Settings > Certificates > Import",
        "- Safari in the iOS simulator: nothing to do",
    ],
    "sim": [
        "App on the iOS simulator",
        "- A debug build without certificate pinning, installed in the simulator",
        "- Nothing else: the proxy and the certificate are set up for you",
    ],
    "phone": [
        "App on a phone",
        "- A debug build without certificate pinning (Android: with a network_security_config that trusts user certificates)",
        "- Same Wi-Fi as the Mac; in that Wi-Fi's settings: Proxy > Manual > {ip}, port {port}",
        "- On the phone open mitm.it and install the certificate",
        "- iPhone: Settings > General > About > Certificate Trust Settings > turn it on",
    ],
}
GUIDE_DURING = [
    "During the test",
    "- open the screen or pull the list down when asked",
    "- say what you see",
    "- share the design or the list of states if we compare against it",
]


def cmd_guide(a):
    up = up_info()
    ip = up.get("lan_ip") if up and not up.get("demo_url") else None
    port = up.get("port") if up and not up.get("demo_url") else 8080
    ip = ip or "your Mac's IP (System Settings > Wi-Fi > Details)"
    print("\n".join(line.format(ip=ip, port=port) for line in GUIDES[a.target]))
    print()
    print("\n".join(GUIDE_DURING))


def wait_up(timeout):
    end = time.time() + timeout
    while time.time() < end:
        info = up_info()
        if info:
            print(f"up is running: {info.get('demo_url') or 'proxy ' + str(info.get('lan_ip')) + ':' + str(info.get('port'))}")
            return
        time.sleep(1)
    tail = ""
    if os.path.exists(UP_LOG):
        with open(UP_LOG, encoding="utf-8", errors="replace") as f:
            tail = "".join(collections.deque(f, maxlen=6))
    die("timeout: `up` isn't running." + (f" Last lines of logs/up.log:\n{tail}" if tail else
        " Nothing in logs/up.log either: it hasn't been started in this folder."))


def cmd_wait(a):
    """Block until a new frame passes through the proxy: the profile's frame, or any JSON
    server frame with --any. For flows where a person has to do something in the app."""
    if a.up:
        return wait_up(a.timeout)
    path = os.path.join(core.LOG_DIR, "frames.log")
    start = os.path.getsize(path) if os.path.exists(path) else 0
    end = time.time() + a.timeout
    seen_other = 0
    while time.time() < end:
        size = os.path.getsize(path) if os.path.exists(path) else 0
        if size < start:            # log was removed or rotated
            start = 0
        if size > start:
            with open(path, encoding="utf-8", errors="replace") as f:
                f.seek(start)
                chunk = f.read()
            start = size
            for line in chunk.splitlines():
                if " server " not in f" {line}":
                    continue
                if a.any or line.rstrip().endswith(" FRAME"):
                    print(f"got it: {line.strip()}")
                    return
                seen_other += 1
        time.sleep(0.5)
    if seen_other:
        die(f"timeout: {seen_other} server frame(s) came through, but none matched the profile's frame.match "
            "(wrong screen, or frame.match needs fixing: wsm.py inspect)")
    die("timeout: nothing came through the proxy. The screen isn't open yet, or the device isn't using the proxy "
        "(phone: Wi-Fi proxy = Mac IP:8080; check `wsm.py`)")


def cmd_log(a):
    path = os.path.join(core.LOG_DIR, "frames.log")
    if not os.path.exists(path):
        die("no frames.log yet: nothing has gone through the proxy")
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = collections.deque(f, maxlen=a.n)
    print("".join(lines), end="")


def cmd_pack_skills(_):
    """ZIP each skill folder for uploading in the Claude apps (Settings > Capabilities > Skills)."""
    import zipfile
    base = os.path.join(core.ROOT, ".claude", "skills")
    out = os.path.join(core.ROOT, "dist")
    os.makedirs(out, exist_ok=True)
    for name in sorted(os.listdir(base)):
        src = os.path.join(base, name)
        if not os.path.exists(os.path.join(src, "SKILL.md")):
            continue
        dest = os.path.join(out, f"{name}.zip")
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _, files in os.walk(src):
                for f in files:
                    full = os.path.join(root, f)
                    z.write(full, os.path.join(name, os.path.relpath(full, src)))
        print(rel(dest))
    print("Upload them in Claude: Settings > Capabilities > Skills > Upload skill, then turn them on.")


def cmd_proxy_off(a):
    ok, msg = system_proxy(a.service, False)
    print("system proxy off" if ok else f"failed: {msg}")


# ---------------------------------------------------------------------------
def main():
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # `wsm.py presets | head` shouldn't print a traceback
    ap = argparse.ArgumentParser(prog="wsm.py", description="ws-mock control panel",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--version", action="version", version=f"ws-mock {__version__} (test version)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("profiles").set_defaults(fn=cmd_profiles)
    s = sub.add_parser("use"); s.add_argument("name"); s.set_defaults(fn=cmd_use)
    s = sub.add_parser("new"); s.add_argument("name"); s.set_defaults(fn=cmd_new)
    s = sub.add_parser("capture"); s.add_argument("mode", choices=["on", "off"]); s.set_defaults(fn=cmd_capture)
    s = sub.add_parser("inspect"); s.add_argument("files", nargs="*")
    s.add_argument("--last", type=int, default=20, help="how many recent dumps to read"); s.set_defaults(fn=cmd_inspect)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    sub.add_parser("fields").set_defaults(fn=cmd_fields)
    s = sub.add_parser("guide", help="what the person prepares before testing: web, sim or phone")
    s.add_argument("target", choices=["web", "sim", "phone"]); s.set_defaults(fn=cmd_guide)
    s = sub.add_parser("suggest", help="what makes sense to do next, from the current state")
    s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_suggest)
    s = sub.add_parser("wait", help="block until the profile's frame passes through the proxy (after asking the person to open the screen)")
    s.add_argument("--timeout", type=float, default=90)
    s.add_argument("--any", action="store_true", help="any JSON server frame (profile not set up yet)")
    s.add_argument("--up", action="store_true", help="wait until `up` is running instead (after asking the person to start it)")
    s.set_defaults(fn=cmd_wait)
    s = sub.add_parser("log", help="last lines of logs/frames.log: frames and what ws-mock did to them")
    s.add_argument("n", nargs="?", type=int, default=20); s.set_defaults(fn=cmd_log)
    sub.add_parser("rules").set_defaults(fn=cmd_rules)
    s = sub.add_parser("on"); s.add_argument("names", nargs="+"); s.set_defaults(fn=cmd_on)
    s = sub.add_parser("off"); s.add_argument("names", nargs="*"); s.set_defaults(fn=cmd_off)
    s = sub.add_parser("set", help="one-off patch without touching the profile: set <id|all|frame> key=value ... | set clear")
    s.add_argument("target"); s.add_argument("pairs", nargs="*"); s.set_defaults(fn=cmd_set)
    sub.add_parser("presets").set_defaults(fn=cmd_presets)
    s = sub.add_parser("preset"); s.add_argument("names", nargs="+")
    s.add_argument("--solo", action="store_true", help="hide the real items"); s.set_defaults(fn=cmd_preset)
    s = sub.add_parser("inject"); s.add_argument("file", nargs="?"); s.set_defaults(fn=cmd_inject)
    s = sub.add_parser("proxy")
    s.add_argument("--port", type=int, default=8080)
    s.add_argument("--web-port", type=int, default=8082)
    s.add_argument("--headless", action="store_true", help="mitmdump instead of mitmweb")
    s.add_argument("--all-hosts", action="store_true", help="ignore the profile hosts, intercept everything")
    s.add_argument("extra", nargs=argparse.REMAINDER, help="passed to mitmproxy as is")
    s.set_defaults(fn=cmd_proxy)

    s = sub.add_parser("up", help="on the Mac: proxy, system proxy on, simulator cert; Ctrl+C undoes it")
    s.add_argument("--demo", action="store_true", help="demo server behind mitmproxy (reverse proxy), no system proxy")
    s.add_argument("--demo-port", type=int, default=8000)
    s.add_argument("--orders", type=int, default=60)
    s.add_argument("--interval", type=float, default=2.0)
    s.add_argument("--port", type=int, default=8080)
    s.add_argument("--web-port", type=int, default=8082)
    s.add_argument("--headless", action="store_true", help="mitmdump instead of mitmweb")
    s.add_argument("--all-hosts", action="store_true")
    s.add_argument("--service", default="Wi-Fi", help="network service for the system proxy (networksetup -listallnetworkservices)")
    s.add_argument("--no-system-proxy", action="store_true", help="don't touch the Mac proxy settings (real phone)")
    s.add_argument("--no-browser", action="store_true", help="don't open the mitmweb page (background runs)")
    s.set_defaults(fn=cmd_up)
    sub.add_parser("down", help="stop a running `up` (also from another machine/VM sharing the folder)").set_defaults(fn=cmd_down)
    sub.add_parser("install-skill", help="install the Claude Code skills into ~/.claude/skills").set_defaults(fn=cmd_install_skill)
    sub.add_parser("pack-skills", help="dist/<skill>.zip for uploading in the Claude apps").set_defaults(fn=cmd_pack_skills)
    sub.add_parser("screen", help="screenshot of the booted simulator -> logs/screen.png").set_defaults(fn=cmd_screen)
    s = sub.add_parser("open", help="open a URL in the booted simulator (default: the demo)")
    s.add_argument("url", nargs="?"); s.set_defaults(fn=cmd_open)
    sub.add_parser("sim", help="start the iOS Simulator and wait until it's booted (needs `up`)").set_defaults(fn=cmd_sim)
    sub.add_parser("cert", help="install the mitmproxy cert in the booted simulator (needs `up`)").set_defaults(fn=cmd_cert)
    s = sub.add_parser("proxy-off", help="turn the Mac system proxy off")
    s.add_argument("--service", default="Wi-Fi"); s.set_defaults(fn=cmd_proxy_off)

    a = ap.parse_args()
    (getattr(a, "fn", None) or cmd_status)(a)


if __name__ == "__main__":
    main()
