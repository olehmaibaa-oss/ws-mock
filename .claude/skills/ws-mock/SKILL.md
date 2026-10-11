---
name: ws-mock
description: "Test mobile or web screens driven by WebSocket frames with the ws-mock mitmproxy addon: capture a frame, write rules/presets for that API, run state, live-update, order, freeze and duplicate scenarios."
argument-hint: "[what to test, or nothing for a menu]"
allowed-tools: Bash(python3 wsm.py) Bash(python3 wsm.py *)
---

# ws-mock: testing WebSocket-driven screens

Use when a screen gets its data over a WebSocket (one JSON frame = the whole list: orders, missions, offers, notifications, prices) and the user wants to see states the backend can't easily produce, or test update/ordering/staleness behaviour. Proxyman and Charles can't edit WS frames, this can.

**You do the work yourself, the person does the looking.** The person runs at most one command (`wsm.py up`), and only when you can't start it yourself. Everything else (profiles, capture, inspect, check, presets, rules, inject, reloading the page, stopping) you run. Never hand them a list of commands to type, never ask them to change proxy settings by hand. They watch the screen; you don't take screenshots unless they ask for one. Talk to them in their language, short.

## The tool

Repo `ws-mock`, wherever the person cloned it. Never edit `ws_mock.py` or `wsm.py`; all app-specific config is one file.
- `ws_mock.py` engine (mitmproxy addon), re-reads the active profile and `.state.json` on every frame.
- `wsm.py` CLI, plain python3. Every command except `up`/`proxy`/`proxy-off`/`install-skill` only touches files in the repo.
- `up` is the process on the Mac: runs mitmproxy (and the demo), handles the system proxy, and executes simulator actions requested through files (`sim`, `cert`, `open`, `screen`, `down`).
- `profiles/<name>/profile.json`: `hosts`, `frame` (match/list/id/label), `presets` (source + items), `rules`, `push`. `profiles/demo` = DEMO food delivery, `profiles/_template` = clean copy with CHANGE_ME. Own profiles are gitignored.
- `logs/`: `frames.log`, `dumps/<profile>/` (capture, last 40 frames), `up.json` (heartbeat of `up`), `screen.png`.

## 0. Start: one call, no exploring

Don't search the disk, don't open the repo's code or README, don't look through other projects, chats, docs or memory. `wsm.py` tells you everything you need: status (profile, what's on, whether `up` runs) and `suggest` (what to do next).

- **Mode B, chat linked to the Mac** (the `mcp__remote-devices__device_bash` tool exists; it's a Linux VM that sees only connected folders). One call:
  `for d in $HOME/mnt/*/ $HOME/mnt/*/*/ $HOME/mnt/*/*/*/; do [ -f "$d/wsm.py" ] && [ -f "$d/ws_mock.py" ] && cd "$d" && pwd && python3 wsm.py && python3 wsm.py suggest --json && break; done`
  Nothing printed: the repo folder isn't connected. Ask the person where they cloned ws-mock (one short question), then `device_request_folder_access` for that folder and run the call again. Don't assume `~/Downloads`. For the one command the person runs on the Mac you need the repo's path on the Mac, not the VM one: `device_list_dir` on the folder you found (the `$HOME/mnt/...` spelling) returns it as `resolvedPath` (or match it in `get_device_info.connectedFolders`). Once `up` has run, `W` prints the ready command itself (`up not running (on the Mac: cd ... && python3 wsm.py up)`). In this mode you run every `wsm.py` command in the VM; `up` is the one thing the person starts on the Mac.
- **Mode A, shell on the Mac** (Claude Code in a terminal on the Mac). The repo is `${CLAUDE_SKILL_DIR}/../../..` when this skill comes from the repo, the path in `${CLAUDE_SKILL_DIR}/repo.txt` for an installed copy, else the current folder if it has `wsm.py`; otherwise ask where they cloned it. One call there: `python3 wsm.py && python3 wsm.py suggest --json`. You run everything, `up` included.
- **Neither** (no device tool, no local Mac shell): you can't reach the Mac. Say so: open the chat from the Claude desktop app on that Mac, or run Claude Code in the repo folder.

Below, `W` = `python3 wsm.py` in the repo folder (Mode B: `cd <repo> && python3 wsm.py`).

## Menu: invoked without a concrete task

If the person just invokes the skill (`/ws-mock`, "ws-mock", "what can we do") or a scenario is done and they haven't said what's next: the start call (section 0) already gave you `suggest`; offer its first 4 entries (already ordered by what makes sense now) with AskUserQuestion: a short label in their language from `title`, `why` as the description. The free-text answer covers the rest; mention one or two of them in the question text. Then carry the chosen action out fully, the same way as if they had asked for it in words: "Set up ws-mock for your app" starts at section 1 (what is tested), "Continue with profile X" is `W use X` and then the scenarios (if `suggest` offers "Map the fields", the profile has no field map: do step 4 of section 3 first), "Show the demo tour" hands over to the `ws-mock-demo` skill. Without an AskUserQuestion tool, show the 4 as a short numbered list and stop.

This skill is about the person's own app or site. While the active profile is `demo`, `suggest` offers their profiles, a new one, and the demo tour as a single entry; don't offer demo scenarios here.

## 1. What is tested, what the person prepares

Skip this for the demo. Otherwise settle the target: **web** (a site in a browser on the Mac, or in Safari on the iOS simulator), **app on the simulator**, or **app on a phone**. If the request doesn't make it clear, ask with AskUserQuestion (Web / App on the simulator / App on a phone).

Then show `W guide web|sim|phone` once, in their language, before anything else. That is the only setup list they get: don't add steps of your own. Installing mitmproxy and getting the repo are in the README, and Claude's permission prompts appear by themselves. The phone IP in the guide comes from the running `up`; before `up` runs it says where to find it. In Mode B add the one `up` line from the next section; in Mode A don't, you start `up` yourself.

## 2. Start `up`

Variants:
- **demo**: `up --demo` (add `--interval 4` for the out-of-order story). The demo server runs behind mitmproxy as a reverse proxy, the page is at the printed URL (`http://<LAN-IP>:8000`). No system proxy, no certificates. The simulator can bypass the system proxy for LAN IPs, so a local server always goes behind a reverse proxy, never through the system proxy.
- **web, or app on the simulator**: `up` (regular proxy on 8080, Mac system proxy on, cert into the booted simulator; stopping it turns the system proxy off).
- **app on a phone**: `up --no-system-proxy`; the phone side is in `W guide phone`.

How:
- Mode A: start it yourself as a background process, e.g. `python3 wsm.py up --demo --no-browser` with the Bash tool's background option (or `nohup python3 wsm.py up --demo --no-browser > /dev/null 2>&1 &`).
- Mode B: if `W` says `up not running`, ask the person to run once in Terminal, and nothing else: `cd <repo path on the Mac> && python3 wsm.py up --demo` (or the variant that fits; the path as in section 0, never a guessed one). Don't ask them to tell you when it's running.

Right after, run `W wait --up --timeout 100` (repeat once if needed): it returns the moment `up` is alive. Never take "done" from the person as proof; `wait --up` is. If it times out, it prints the last lines of `logs/up.log`, where `up` writes why it didn't start or why it stopped (another `up` already running, a busy port, mitmweb not found, a child process that exited). Fix that, then ask them to start `up` again. If `up` fails: `mitmweb not found` → `brew install --cask mitmproxy`; `No module named 'aiohttp'` → `pip3 install aiohttp`; no `xcrun simctl` → `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer`. Mode A: run the installs yourself if allowed; anything with sudo goes to the person.

Then, through `up`, yourself. `W sim`, `W open`, `W screen`, `W cert` and `W down` work from the VM too: `up` executes them on the Mac. Never ask the person to run them. If one of them says "`up` is not running", it's `up` that is down, not your access: `W wait --up` and `logs/up.log` tell you why, and the only thing to ask the person is to start `up` again.
- `W sim` boots the simulator if none is booted; own app: then `W cert`
- `W open [url]` opens or reloads a page in the simulator (default: the demo URL)
- `W log [N]` shows the last lines of `logs/frames.log`: every frame with its size and keys, and under it what ws-mock did (`-> presets[clones:5, ...]`, `-> dropped`, `-> held 5000ms x1`). This is how you confirm a switch took effect. Before testing, check that the socket's `server ... keys=[...]` lines keep coming; if they don't, the device bypasses the proxy.
- `W screen` writes `logs/screen.png` (Mode A: Read it; Mode B: `device_stage_files`, then Read). Only when the person asks for a screenshot, or for a bug report they want with images. Never one per preset or per scenario.

### When the person has to do something in the app

You can't tap inside a real app (phone, or an app on the simulator), so some steps need the person: open a screen, pull to refresh, reopen it. Every time:
1. Tell them exactly one action, in one line, naming the screen ("Open the Orders screen", "Pull the list down"). They must see it right away: if the session has a SendUserMessage tool, send it with that and keep working; Claude Code shows your text as you go.
2. Right after, run `W wait` (`W wait --any` while the profile's `frame` isn't set up yet). It returns the moment that frame passes through the proxy, so they don't have to confirm anything.
3. On timeout, read what it says. "Nothing came through": the screen isn't open or the device isn't on the proxy; tell them which setting to check (phone: Wi-Fi proxy = Mac IP:8080). "Came through, but none matched": wrong screen, or `frame.match` needs fixing.

Simulator or demo: try `W open <url or deep link>` first; ask the person only when that can't reach the screen. Device shell calls time out after ~2-3 minutes: keep `--timeout` at 100 or less and repeat if they need longer.

## 3. New app: profile from the template

If the app has no profile yet (`W profiles`), or the person asks for one from scratch, don't reuse `demo`:
1. `W new <name>` (copies `_template`, switches to it).
2. `W capture on`; demo: `W open`, then `W wait --any`; real app: ask them to open the screen (protocol above) and `W wait --any`; then `W capture off`.
3. `W inspect` (or `W inspect file.json` for any saved frame): hosts, frame kinds, discriminator (type/cid/event...), lists with id and label guesses (label may be a pointer like `/meta/name`), fields that look like state with value counts, first item, and a ready `hosts`/`frame`/`presets.source` block. Write those into the profile yourself (edit the JSON, keep `_` notes). Behind a reverse proxy (demo) the host is the upstream `127.0.0.1`; leave `hosts` empty there.
4. **The field map. Stop here, before any preset.** A mock is only as right as the person's knowledge of which field does what; without it you'd be mocking at random and nobody would notice. Tell them that in one or two plain sentences, show the candidates (`W fields`: the state-like fields with the values the server really sends), and ask for what they have: the spec (PRD, Jira), the design with annotations, a developer's answer, or just what they know. Then:
   - **spec or design given**: match it to the wire fields yourself (names differ: `is_opted_in` vs `isOptedIn`, nested vs flat);
   - **they know part of it**: take that, and check the rest by experiment;
   - **nothing**: experiments only; say it's slower and less sure.
   Experiment = `W set <id> field=value` on one real item, ask them what changed on the screen (a fresh frame first if needed), `W set clear`. One field at a time.
   Show the result as a short table, field / what it drives on the screen / values / source (spec, dev, tried), and ask them to confirm or correct it. Only then write it into `fields` in the profile (key = path inside one item, value = "what it drives: values (source)") and go on. A field nobody could confirm stays marked as a guess, or stays out.
5. Presets: one per state from their design/spec (ask for it if you don't have it), plus edge values, built from the confirmed field map only. Patch only the fields that make the state. Use field names from the wire, not the spec (snake_case vs camelCase).
6. `W check`: compares every preset/rule/push patch with the real item. Fix every ERROR yourself (unknown ids, source missing, no matching frame). Warnings: unknown keys with a did-you-mean, type mismatches, leftover CHANGE_ME; explain the intentional ones (a field the server never sends).
7. Own app: if `hosts` changed, restart `up` (Mode A: `W down`, start again; Mode B: `W down`, ask them to start it again) so only the socket host is intercepted.

Binary/protobuf frames pass through untouched; say so if the socket isn't JSON. Certificate pinning: ask for a build without it.

## 4. Profile format

Rules and push rules inherit `match`, `list`, `id`, `label` from `frame`; a rule's own `match` targets other frames (`"direction": "client"` for app messages).
`fields`: the field map, `{"path.in.item": "what it drives: values (source)"}`; `W fields` shows it next to the real values and lists state-like fields not mapped yet, `W check` warns when it's empty or names a field the server never sends.
Rule keys: `name`, `_doc` (shown in `rules` and as the menu title), `with` (companion rules turned on together), `direction`, `match.has`, `match.equals`, `list`, `id`, `only`, `remove`, `empty`, `all`, `by_id`, `clone` [{from, as, tag, patch, position}], `label`, `reverse`, `set` (JSON pointer keys), `drop`, `delay_ms`, `repeat`, `once`.
Patches deep-merge; `/` keys are pointers; `_` keys are notes. Tokens: `__TS__`, `__TS:+2d__` (ms), `__TS_S:-45m__` (s), `__DELETE__`.
Presets: `{"source": <real id>, "first_id": <optional>, "items": {name: patch}}`.

## 5. Scenarios: you switch them, the person looks

Commands: `W` status, `W guide web|sim|phone`, `W fields`, `W suggest [--json]`, `W log [N]`, `W wait [--any] [--timeout N]`, `W wait --up`, `W profiles`, `W use <name>`, `W presets`, `W preset <names|all> [--solo]` (clones on top with a `[name]` prefix on the label; `--solo` hides real items), `W preset off`, `W set <id|all|frame> key=value ...` (one-off patch without touching the profile: `set 1003 status=cancelled`, `set all total.amount=0`, `set 1000 courier=null`; dotted keys nest; values parse as JSON, else text; `set clear` drops them), `W rules`, `W on <rules...>` (additive, also turns on the rule's `with` companions; again = re-arm `once`), `W off [rules...]` (no names = everything off incl. presets and `set` patches), `W inject [file-inside-repo.json]` (last real frame + `push` rules, or a file as is).
Built-ins on any profile with a filled `frame`: `frozen` (drop all), `duplicate` (x2), `slow` (3 s), `late-frame` (once, one frame held 5 s), `reverse`, `empty`. A profile rule with the same name overrides a built-in.

For each scenario: switch it; if it needs a fresh frame, get one (demo: `W open`; real app: ask for a refresh or reopen per the protocol above, then `W wait`); confirm with `W log` that the frame was changed the way you meant; then tell the person in one line what is on the screen now and what to look at, and wait for their reaction before the next one. Show many states at once rather than one at a time.
1. **State matrix**: `W preset all --solo` puts every state on one screen, each card labelled `[preset-name]`; the person compares them with the design. Long lists: a few `--solo` groups.
2. **Edge values** as presets: unknown enum, null/missing object, overflow (current > target), zero, empty string vs missing field, long text, timestamps past / now / far future, s vs ms.
3. **Live update**: `W inject` with the screen open, no reload; tell them which card should change. Expect in-place update, scroll kept, no duplicates.
4. **Out of order**: `W on late-frame`, or for a guaranteed rollback a rule that sets the new state every frame plus a `once` rule with `delay_ms` longer than the push interval that sets the old state (DEMO: `W on late-old-frame`, it brings `delivered` along via `with`; best with `up --demo --interval 4`). Tell them when the old frame lands (the delay after the next frame) and what should not happen. Check the client ignores stale seq/timestamps.
5. **Frozen**: load the screen, then `W on frozen`; tell them to watch for a staleness indicator or retry.
6. **Duplicate**, **slow**, **reverse**, **empty**.
7. **Error frames** if the protocol has them: a rule with its own `match` that patches the response into an error.

Frame-level evidence: `logs/frames.log` shows what was patched, dropped or held per frame.

## 6. Gotchas

- mitmproxy re-splits a modified frame into 4000-byte continuation frames only when its LENGTH changes; same-length patches keep the original framing, which is why the bug looks random. The engine raises `Fragmentizer.FRAGMENT_SIZE` (`FRAGMENT_SIZE -> 16777216` in the mitm log). `WS_MOCK_KEEP_FRAGMENTS=1` reproduces the bug.
- Never use localhost for anything the device should reach; use the LAN IP. Plain `ws://` needs no cert.
- A broken profile or state keeps the previous config; the mitm log shows `ws-mock: profile ... | on: ...` on every change.
- Clones copy every field of the source, including ones the server keeps changing; patch everything the state depends on.
- Inject needs a live socket: the screen must be open. Inject files must be inside the repo.
- If `up` died hard and the Mac has no internet: `python3 wsm.py proxy-off` on the Mac.
- `logs/up.log` is `up`'s own log: start, system proxy, simulator actions, why it stopped.
- Never commit work profiles or dumps to a public repo; `profiles/*` except demo and _template is gitignored.

## 7. Finish

`W off`, `W capture off`. Report: short table (scenario, what was done, expected, what the person saw, bug yes/no); bugs with steps (profile, preset/rule names), build, device, frame excerpt from `W log` or the dump. Then `W down`: it stops `up` and turns the system proxy back off.
