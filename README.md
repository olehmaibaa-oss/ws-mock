# ws-mock

> **Test version, 0.1.** It grew out of testing a real production app, but this version is early: expect rough edges, and commands may still change. I'm developing it further, issues and feedback are welcome.

Rewrite WebSocket frames on the fly to test screens that live on a socket: order tracking, missions, offers, notifications, live prices, chat.

Proxyman and Charles can't edit WebSocket messages, so Map Local and scripting don't help when the whole screen arrives as one WS frame. ws-mock is a mitmproxy addon plus a small CLI that lets you:

- show **every state from the design** on a real build by cloning a real item and patching it, including states the backend can't produce yet
- patch, remove, reorder or empty the list, or patch one field on the fly
- **drop, delay, duplicate** frames, or hold one frame so it lands after newer ones
- **inject** a frame into the open socket to check that the screen updates in place
- point it at a new app in minutes: `inspect` reads a captured frame and tells you where the list is, what the id field is and which fields drive the state

Nothing restarts when you switch scenarios: the proxy re-reads its config on the next frame. It also ships two Claude skills, so you can just ask Claude to set it up and run the scenarios while you watch the screen.

```
ws_mock.py          the engine (mitmproxy addon). You don't edit it.
wsm.py              the CLI. You don't edit it.
profiles/demo/      DEMO profile for the demo app
profiles/_template/ clean profile to copy for your app
profiles/<yours>/   your profiles (gitignored)
examples/demo/      demo backend + page: a food delivery "My orders" screen
.claude/            Claude skills (ws-mock, ws-mock-demo) + Claude Code permissions
CHANGELOG.md, LICENSE
```

---

## What you need

| | |
|---|---|
| **Mac** | `wsm.py up` uses `networksetup` and `xcrun simctl`. The engine and the CLI are plain Python and mitmproxy, so on Linux or Windows you can run `wsm.py proxy` and set the proxy by hand, but that isn't tested yet. |
| **Python 3.9+** | comes with the Xcode Command Line Tools |
| **mitmproxy 10+** | `brew install --cask mitmproxy` or `pip3 install mitmproxy`. Tested with 12.2. |
| **Xcode with the iOS Simulator** | for testing on the simulator |
| **aiohttp** | `pip3 install aiohttp`, only for the demo server |
| **Something to test** | a site in a browser, or a debug build of your app **without certificate pinning** |
| **Claude** (optional) | to let Claude drive it: Claude Code in a terminal, or the Claude desktop app with the chat linked to this Mac and the repo folder connected. Claude doesn't need to see or control your screen: everything goes through files in this folder. |

## Install

```bash
git clone https://github.com/olehmaibaa-oss/ws-mock.git
cd ws-mock
brew install --cask mitmproxy
pip3 install aiohttp        # only for the demo
python3 wsm.py              # prints the status, so you know it runs
```

---

## Try the demo

**With Claude:** ask "show me the ws-mock demo". The `ws-mock-demo` skill runs a five-minute tour on the demo app: every state on one screen, an old frame rolling an order back, a frozen socket, a live update. Then you can ask for any other mock in plain words.

**By hand:**

```bash
python3 wsm.py up --demo
```

It starts the demo backend behind mitmproxy and prints a URL like `http://192.168.1.100:8000`. Open it on anything: the iOS simulator (`python3 wsm.py open` does it for you), a phone on the same Wi-Fi, a browser. No proxy settings and no certificates. In another terminal:

```bash
python3 wsm.py preset all --solo          # every state from the DEMO profile, one card each
python3 wsm.py on late-old-frame          # an old frame lands late and rolls an order back
python3 wsm.py on frozen                  # socket alive, data never changes
python3 wsm.py inject                     # push an update into the open screen
python3 wsm.py set 1003 status=cancelled  # one-off patch of a single field
python3 wsm.py off                        # back to the real frames
```

Ctrl+C in the `up` terminal stops everything. The demo page has five real bugs in it; the scenarios find them (see [Demo walkthrough](#demo-walkthrough)).

Tip: `alias wsm="python3 /path/to/ws-mock/wsm.py"`.

---

## Use it on your own app or site

### Before you start: know your frame

ws-mock changes **data**, not the screen. On a real project you first need to know which fields of the WebSocket frame drive what you see: the status badge, the timer, the button, the progress, the labels. Without that map a mock hits at random, and a "bug" may just be a field you misread.

Where the map comes from:
- `wsm.py inspect` and `wsm.py fields` list the fields that look like state, with the values the server actually sends
- the spec, the design annotations or a developer say what they mean (watch for naming: the spec may say `is_opted_in` while the wire says `isOptedIn`)
- when in doubt, an experiment: change one field on one real item with `wsm.py set <id> field=value` and see what changes on the screen

The map lives in the profile, under `fields`: what each field drives on the screen, its values, and how you know it (spec, dev, or tried). Write it down before the presets, so whoever opens the profile next (you in a month, a teammate, Claude in a new chat) starts from it instead of guessing again. With Claude, the `ws-mock` skill stops at this point and asks you for the spec, the design or what you know, then checks the rest by experiment and shows you the map to confirm.

A bug you find with a mock is a bug in how the client handles that data. Before filing it, make sure the backend can really send it, or that the client is expected to handle it anyway.

You change one file: `profiles/<name>/profile.json`. The engine and the CLI stay as they are.

### 0. Prepare the device

`python3 wsm.py guide web`, `guide sim` or `guide phone` prints what to do on the browser, simulator or phone side: trust the certificate, a debug build without pinning, the phone's Wi-Fi proxy (with your Mac's IP once `up` runs). The Claude skill shows the same list before the first test.

### 1. Make a profile

```bash
python3 wsm.py new myapp
```

Copies `profiles/_template` to `profiles/myapp` and switches to it. Your profiles are gitignored, so company hosts and payloads stay on your machine.

### 2. Start the proxy and capture a real frame

```bash
python3 wsm.py up                  # web or simulator; phone: up --no-system-proxy
python3 wsm.py capture on
# open the screen in your app
python3 wsm.py wait --any          # returns as soon as a frame comes through
python3 wsm.py capture off
```

`up` points the Mac system proxy at mitmproxy, installs the certificate in the booted simulator, and **turns the system proxy back off on Ctrl+C** (or `python3 wsm.py down`). The template has no hosts yet, so at this point everything goes through mitmproxy. Raw server frames go to `logs/dumps/myapp/`.

### 3. Let `inspect` read them

```bash
python3 wsm.py inspect
```

```
== 192.168.1.100 · 3 frame(s) · ~22.2 KB · keys: orders, seq, ts, type
   type = "orders.snapshot"
   list /orders: 60 items · id "id" · label "restaurant"
     item keys: id, restaurant, items, total{amount,currency}, status, step{current,of}, courier, eta, note
     fields that look like state:
       /status            "preparing" 18 · "placed" 18 · "on_the_way" 16 · "delivered" 8
       /step/current      2 18 · 1 18 · 3 16 · 4 8
       /courier           null 42 · {…} 18
     first item: {"id": 1000, "restaurant": "Bao Bar", "items": 1, ...}

suggested for profile.json (biggest list):
  "hosts": ["192.168.1.100"],
  "frame": {"match": {"has": "/orders", "equals": {"/type": "orders.snapshot"}}, "list": "/orders", "id": "id", "label": "restaurant"},
  "presets": {"source": 1000, "items": { ... }}
```

It shows which hosts sent JSON frames, the kinds of frames, the list inside each, the id field, a label field (nested ones too, like `/meta/name`), and the fields with a handful of values. Works on any saved frame too: `python3 wsm.py inspect frame.json`.

### 4. Fill the profile

| section | what goes in | where you get it |
|---|---|---|
| `hosts` | the socket host | `inspect` |
| `frame` | how to recognise the frame, where the list is, id field, label field | `inspect`, paste as is |
| `fields` | the field map: `"path.in.item": "what it drives: values (source)"` | your spec, a developer, `set` experiments; `wsm.py fields` shows it next to the real values |
| `presets.source` | id of a normal-looking real item to clone from | `inspect` |
| `presets.items` | one entry per state from your design or spec; the patch holds only the fields that make that state | your spec + the field map above |
| `rules` | app-specific scenarios: patch one item, a stale-state pair, error responses. Optional | you |
| `push` | what `inject` changes before pushing into the open socket. Optional | you |

For example:

```json
"fields": {
  "status": "status badge and colour: placed | preparing | on_the_way | delivered | cancelled (spec)",
  "courier.name": "courier line, only while on_the_way; null = no courier (tried)"
}
```

A preset is just the fields that differ, e.g. `"locked": {"isLocked": true, "unlockAt": "__TS:+2d__"}`.

### 5. Check it against the real frame

```bash
python3 wsm.py check
```

```
  ok    frame.match matches logs/dumps/myapp/20261010-105640-464-192.168.1.100.json
  ok    frame.list '/orders': 60 items
  ok    id 'id' present in every item
  ok    presets.source 1000 found, 4 presets
  warn  preset typo: 'staus' isn't in the real item, did you mean 'status'?
  warn  preset wrong-type: 'items' is a number in the real item, the patch has a str ("3")
  ERROR rule bad-id: id 424242 is not in the list (ids look like: 1000, 1001, 1002, 1003)
```

It compares every patch with the real item: unknown keys, wrong types, ids that aren't in the frame, leftover `CHANGE_ME`.

### 6. Restart the proxy

Ctrl+C and `python3 wsm.py up` again: it now passes `--allow-hosts` from your profile, so only the socket host is intercepted and everything else tunnels untouched (no fights with pinned analytics SDKs).

---

## With Claude

The repo ships two skills in `.claude/skills/`:

- **`ws-mock`** runs the whole flow on your app or site: asks what you test (web, simulator, phone) and shows what to prepare, sets up the profile from a captured frame, checks it, then switches presets and scenarios and tells you what to look at. A short report at the end.
- **`ws-mock-demo`** is the guided tour on the demo app. Good for a first look or for recording a demo.

How you run them:

- **Claude Code in a terminal:** `cd ws-mock && claude`. The skills and the permissions in `.claude/settings.json` load with the folder. Claude starts and stops `up` itself, nothing for you to run. To use the skills from any folder: `python3 wsm.py install-skill`.
- **Claude desktop app:** add the skills to your account once:
  1. `python3 wsm.py pack-skills` makes `dist/ws-mock.zip` and `dist/ws-mock-demo.zip`
  2. in Claude: Settings > Capabilities, make sure code execution and file creation are on
  3. in the Skills section: Upload skill, pick a ZIP, then turn the skill on; repeat for the second one

  Skills need a Pro, Max, Team or Enterprise plan; on Enterprise an owner has to enable them first ([Using Skills in Claude](https://support.claude.com/en/articles/12512180-using-skills-in-claude)). After pulling a new version, pack and upload again.

  Then open the chat linked to your Mac and connect the repo folder. From there Claude can't start processes on the Mac, so it asks you to run one command (`python3 wsm.py up ...`); everything else it does through the folder, and it stops `up` itself at the end.

What Claude does and doesn't do:
- It switches scenarios, writes the profile, checks it, and confirms every change in `wsm.py log`. You watch the screen and say what you see.
- It can't tap inside your app. When a scenario needs a fresh frame, it asks you in one line to open the screen or pull to refresh, and continues the moment the frame comes through (`wsm.py wait`).
- It doesn't take screenshots unless you ask, and it doesn't edit the engine or the CLI.
- Invoked with no task (`/ws-mock`), it looks at the current state and offers the next few actions to pick from.

The same works for any agent or script that can write to this folder: everything except `up` is files (`.state.json`, `profiles/`, `logs/`), and `wsm.py screen`, `open`, `sim`, `cert`, `down` are executed by the running `up`.

---

## Built-in scenarios

Work on any profile once `frame` is filled in. Nothing to write.

| rule | what the app gets | what to look for |
|---|---|---|
| `frozen` | nothing, socket stays open | stale data with no "last updated", spinners forever, no retry |
| `duplicate` | every frame twice | double toasts, double analytics events, items rendered twice |
| `slow` | every frame 3 s late | loading states, the user acting on old data |
| `late-frame` | one frame held 5 s, lands after newer ones | screen rolls back to old data, `seq`/timestamps ignored |
| `reverse` | list in reverse order | sorting the client relies on the server for |
| `empty` | empty list | empty state |

`once` rules (like `late-frame`) fire on one frame and re-arm every time you run `wsm.py on`, `off` or `preset`.

---

## Demo walkthrough

The DEMO profile has 14 presets and two rules of its own. The demo page has real bugs in it, these are what the scenarios find:

- `preset all --solo`: "1 items", a raw `refunded` on a red badge, "On the way" with no courier, step 7 of 4 drawn as a full bar, a price line ending in "·".
- `on late-old-frame` (brings `delivered` along): order #1000 is delivered in every frame; one older frame with #1000 still on the way is held 5 s. Newer frames arrive first, the old one lands and the order goes back from Delivered to On the way, because the page doesn't check `seq`. With `python3 wsm.py up --demo --interval 4` it stays visible longer:
  ```
  +4s  seq=2  #1000 delivered
  +5s  seq=1  #1000 on_the_way    <- old frame overwrote the newer one
  +8s  seq=3  #1000 delivered
  ```
- `on frozen`: the page says "connected", ETAs keep counting down, statuses never move.
- `inject`: #1000 goes on the way without reopening the screen.

---

## wsm.py

| command | does |
|---|---|
| `wsm.py` | status: profile, hosts, rules, presets, patches, capture, whether `up` runs |
| `wsm.py up [--no-system-proxy] [--service Wi-Fi] [--headless] [--no-browser]` | on the Mac: proxy, system proxy on, simulator cert; Ctrl+C undoes all of it |
| `wsm.py up --demo [--interval 4]` | on the Mac: demo backend behind mitmproxy (reverse proxy), no proxy settings |
| `wsm.py down` | stop `up`: children stopped, system proxy off. Works from anything that shares the folder. `up` refuses to start twice or on a busy port, and keeps its own log in `logs/up.log` |
| `wsm.py screen` / `open [url]` / `sim` / `cert` | through a running `up`: simulator screenshot, open a URL, boot the simulator, install the cert |
| `wsm.py proxy [--headless] [--all-hosts] [-- mitmproxy args]` | just mitmweb with the addon and `--allow-hosts` from the profile, no system proxy |
| `wsm.py proxy-off` | turn the Mac system proxy off (if `up` was killed hard) |
| `wsm.py guide web\|sim\|phone` | what to prepare before testing |
| `wsm.py profiles` / `use <name>` / `new <name>` | list / switch / create from the template |
| `wsm.py capture on\|off` | save every JSON server frame to `logs/dumps/<profile>/` (last 40) |
| `wsm.py wait [--any] [--timeout 90]` | block until the profile's frame (or any JSON frame) passes through |
| `wsm.py wait --up [--timeout 90]` | block until `up` is running; on timeout shows why from `logs/up.log` |
| `wsm.py inspect [file ...]` | explain captured (or given) frames, suggest the `frame` block |
| `wsm.py fields` | the field map next to the real values, plus state-like fields not mapped yet |
| `wsm.py check` | validate the profile against the latest captured frame |
| `wsm.py log [N]` | last N lines of `logs/frames.log`: each frame and what ws-mock did to it |
| `wsm.py suggest [--json]` | what makes sense to do next from the current state |
| `wsm.py rules` | built-in and profile rules, on/off |
| `wsm.py on <rule ...>` / `off [rule ...]` | switch rules; `off` alone = everything off, presets and `set` patches too |
| `wsm.py presets` / `preset <name ...\|all> [--solo]` / `preset off` | show states as extra items; `--solo` hides the real ones |
| `wsm.py set <id\|all\|frame> key=value ...` / `set clear` | one-off patch without editing the profile: `set 1003 status=cancelled`, `set all total.amount=0`, `set 1000 courier=null` (dotted keys nest, values parse as JSON) |
| `wsm.py inject [file.json]` | push into the open socket: the last real frame + `push` rules, or a file as is |
| `wsm.py install-skill` | install the Claude Code skills to `~/.claude/skills/` |
| `wsm.py pack-skills` | `dist/*.zip` to upload the skills in the Claude apps |
| `wsm.py --version` | the version |

From an automated test it's the same: call `wsm.py` before opening the screen. `WS_MOCK_PROFILE` forces a profile, `WS_MOCK_STATE` and `WS_MOCK_LOGS` move the state file and the logs.

---

## profile.json reference

```json
{
  "hosts": ["api.example.com"],
  "frame": {
    "match": {"has": "/orders", "equals": {"/type": "orders.snapshot"}},
    "list": "/orders",
    "id": "id",
    "label": "title"
  },
  "presets": {
    "source": 1000,
    "first_id": 9001,
    "items": {"cancelled": {"status": "cancelled"}}
  },
  "rules": [
    {"name": "delivered", "_doc": "shown by wsm.py rules", "by_id": {"1000": {"status": "delivered"}}}
  ],
  "push": [
    {"name": "live-update", "by_id": {"1000": {"status": "on_the_way"}}}
  ]
}
```

Rules and push rules inherit `match`, `list`, `id` and `label` from `frame`. Give a rule its own `match` to work on other frames (`"direction": "client"` for messages the app sends).

| rule key | what it does |
|---|---|
| `match.has` | JSON pointer(s) that must exist in the frame |
| `match.equals` | pointer -> value that must match |
| `direction` | `server` (default), `client`, `both` |
| `list` / `id` | the array of objects and its id field (`""` = the frame itself is the list) |
| `only` / `remove` | keep / remove items by id |
| `empty` | clear the list |
| `all` | patch every item |
| `by_id` | patch specific items |
| `clone` | `[{"from": id, "as": new_id, "tag": "name", "patch": {...}}]`, goes on top |
| `label` | field (or pointer like `/meta/name`) that gets a `[tag]` prefix on clones |
| `reverse` | reverse the list |
| `set` | patch the frame itself: `{"/seq": 0}` |
| `drop` | the app never gets the frame |
| `delay_ms` / `repeat` | send it later / several times |
| `once` | fire on one frame only |
| `with` | rules turned on together with this one, e.g. a stale frame needs a "new state" rule |
| `_doc`, any `_key` | notes; `_doc` is shown by `rules` and `suggest` |

Patches deep-merge into objects; keys starting with `/` are JSON pointers inside the item. Values can be tokens:

| token | value |
|---|---|
| `__TS__` | now, unix ms |
| `__TS:+2d__`, `__TS:-45m__` | now ± offset, unix ms (`s`, `m`, `h`, `d`) |
| `__TS_S:+2d__` | same in seconds |
| `__DELETE__` | remove the key |

---

## Device setup by hand

`wsm.py up` and `wsm.py guide` cover this. For reference:

**iOS simulator** uses the Mac's system proxy:
```bash
networksetup -setwebproxy Wi-Fi 127.0.0.1 8080
networksetup -setsecurewebproxy Wi-Fi 127.0.0.1 8080
xcrun simctl keychain booted add-root-cert ~/.mitmproxy/mitmproxy-ca-cert.pem
```
`simctl` not found: `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer`. "No devices are booted": `open -a Simulator` first. The simulator can skip the system proxy for LAN addresses like `192.168.x.x`; that's why the demo runs behind a reverse proxy instead.

**Turn the system proxy off before you stop mitmproxy**, otherwise the whole Mac loses internet:
```bash
networksetup -setwebproxystate Wi-Fi off; networksetup -setsecurewebproxystate Wi-Fi off
```

**Browser on the Mac** (Chrome, Safari): trust the certificate once:
```bash
sudo security add-trusted-cert -d -p ssl -p basic -k /Library/Keychains/System.keychain ~/.mitmproxy/mitmproxy-ca-cert.pem
```
Firefox keeps its own store: Settings > Certificates > Import.

**iPhone.** Wi-Fi > proxy manual > Mac IP, port 8080. Open `mitm.it`, install the profile, then Settings > General > About > Certificate Trust Settings > enable it.

**Android.** Same proxy, cert from `mitm.it`. Apps ignore user certificates unless the debug build trusts them:
```xml
<network-security-config>
  <debug-overrides><trust-anchors><certificates src="user"/></trust-anchors></debug-overrides>
</network-security-config>
```

---

## The fragmentation trap

If patched frames make the app drop the socket and reconnect in a loop, this is why.

When an addon changes a WebSocket message and its **length changes**, mitmproxy re-sends it split into 4000-byte continuation frames. A 3 MB frame turns into ~700 of them. RFC allows it, a lot of mobile WS clients don't handle it. If the length stays the same, the original framing is kept, which is why it looks random: `"preparing"` → `"delivered"` (same length) works, `"preparing"` → `"on_the_way"` kills the socket.

`ws_mock.py` raises `Fragmentizer.FRAGMENT_SIZE` to 16 MB. To see the bug yourself: `WS_MOCK_KEEP_FRAGMENTS=1 python3 wsm.py up --demo`.

---

## Limitations

- **Test version.** Commands and the profile format may still change between versions; see [CHANGELOG.md](CHANGELOG.md).
- **JSON text frames only.** Binary frames (protobuf, msgpack) pass through untouched. Socket.IO, SignalR and STOMP wrap JSON in their own framing (`42["event",{...}]`); that isn't parsed yet.
- **Mac first.** `up` (system proxy, simulator) is macOS only; the rest isn't tested on Linux or Windows yet.
- **Local sites.** Browsers and the simulator skip the proxy for `localhost` and LAN addresses. The demo works around it with a reverse proxy; a site you run on localhost isn't covered yet.
- **Certificate pinning** blocks interception. You need a debug build without it.
- **The fragmentation fix** changes a mitmproxy internal. Tested with mitmproxy 12.2; a future mitmproxy may need an update here.

## Be careful with

- **What you test.** Only apps, sites and accounts you're allowed to test: your own builds, dev and staging environments.
- **The system proxy.** `up` changes it and puts it back on Ctrl+C or `wsm.py down`. If `up` was killed hard and the Mac has no internet: `python3 wsm.py proxy-off`.
- **The mitmproxy certificate.** Anything that trusts it lets mitmproxy decrypt its traffic. Install it only on test devices and simulators, and remove or untrust it when you're done (Keychain Access on the Mac; Settings > General > VPN & Device Management on iPhone; the user credentials in the security settings on Android). The private key lives in `~/.mitmproxy`; never share that folder.
- **Captured data.** `logs/dumps/` can hold real user or company data. `logs/` and your own profiles are gitignored; keep it that way and don't share dumps.
- **Claude's permissions.** `.claude/settings.json` lets Claude Code run `python3 wsm.py ...` without asking every time. Delete it if you want a prompt for each command.
- **Claude's work.** Claude can make mistakes. Review the profiles it writes; `wsm.py check` catches most of them.

---

## What's next

Android over `adb` (deep links and screenshots on a phone), a reverse proxy for sites on localhost, Socket.IO framing, testing on Linux and Windows. Ideas and bug reports are welcome in the issues.

## License

MIT, see [LICENSE](LICENSE).
