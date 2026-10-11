---
name: ws-mock-demo
description: "Guided tour of ws-mock on its built-in demo app (food delivery orders over a WebSocket): every state on one screen, an old frame rolling an order back, a frozen socket, a live update. Use to show or try what ws-mock does without setting anything up."
argument-hint: "[full tour, or one part: states, rollback, frozen, live update]"
allowed-tools: Bash(python3 wsm.py) Bash(python3 wsm.py *)
---

# ws-mock demo tour

Use when the person wants to see what ws-mock does: "show me the ws-mock demo", "how does it work", before trying it on their own app, or to record a demo. Everything runs on the demo app that ships with the repo (`examples/demo`, a "My orders" screen fed by one JSON frame over a WebSocket) and the ready `demo` profile. Nothing to set up, no profile to create. For their own app, the `ws-mock` skill is the one.

You drive, the person watches. They only run one command if you can't start it yourself (desktop chat). No screenshots unless they ask. Talk in their language, short: before each step one line on what ws-mock does now and what to watch on the screen, then wait for their "next" or reaction.

## 0. Start: one call

Don't search the disk, don't read the repo's code or README, don't look through other projects or memory.
- **Mode B, chat linked to the Mac** (`mcp__remote-devices__device_bash` exists, a Linux VM with the connected folders). One call:
  `for d in $HOME/mnt/*/ $HOME/mnt/*/*/ $HOME/mnt/*/*/*/; do [ -f "$d/wsm.py" ] && [ -f "$d/ws_mock.py" ] && cd "$d" && pwd && python3 wsm.py && break; done`
  Nothing printed: the repo folder isn't connected. Ask the person where they cloned ws-mock (one short question), then `device_request_folder_access` for that folder and run the call again. Don't assume `~/Downloads`. For the one command the person runs on the Mac you need the repo's path on the Mac, not the VM one: `device_list_dir` on the folder you found (the `$HOME/mnt/...` spelling) returns it as `resolvedPath` (or match it in `get_device_info.connectedFolders`). Once `up` has run, `W` prints the ready command itself (`up not running (on the Mac: cd ... && python3 wsm.py up)`).
- **Mode A, shell on the Mac** (Claude Code): the repo is `${CLAUDE_SKILL_DIR}/../../..` (installed copy: the path in `${CLAUDE_SKILL_DIR}/repo.txt`), else the current folder; otherwise ask where they cloned it. One call: `python3 wsm.py`.

`W` below = `python3 wsm.py` in the repo (Mode B: `cd <repo> && python3 wsm.py`).

Then `W use demo` (switches to the demo profile and turns everything off).

## 1. Pick the tour

Unless the request already says, ask with AskUserQuestion: **Full tour** (recommended, ~5 minutes) / **Every state on one screen** / **An old frame rolls an order back** / **Socket hangs**. The free-text answer covers "live update" and "under the hood".

## 2. Demo up and on the screen

Status says whether `up` runs and in which mode (`demo http://...` means demo mode).
- Not running: Mode A: start it yourself in the background, `python3 wsm.py up --demo --interval 4 --no-browser` (Bash background option, or `nohup ... > /dev/null 2>&1 &`). Mode B: ask them to run once in Terminal, nothing else, and don't ask them to tell you when it's up: `cd <repo path on the Mac> && python3 wsm.py up --demo --interval 4` (path as in section 0).
- Running, but not in demo mode: `W down`, then start it as above.
- Then `W wait --up --timeout 100` (repeat once if needed): it returns the moment `up` is alive; their "done" is not proof, this is. On timeout it prints the last lines of `logs/up.log` with the reason (another `up` running, a busy port, mitmproxy or aiohttp missing: `brew install --cask mitmproxy`, `pip3 install aiohttp`). Fix that with them, then ask to start `up` again.

`--interval 4` makes the server push every 4 s, so the rollback stays on screen long enough to see. If `up --demo` already runs with the default 2 s, keep it; the rollback is just shorter.

Then `W sim` (boots the simulator if needed) and `W open` (loads the demo page in Safari there). Both work from the VM too: `up` runs them on the Mac. Never ask the person to run them; if they say "`up` is not running", `up` is down, see `W wait --up` and `logs/up.log`. `W log 3` should show `server ... keys=['type', 'seq', 'ts', 'orders'] FRAME` lines. The demo needs no proxy settings and no certificate: mitmproxy sits in front of the demo server.

## 3. The tour

Before each step: one line on what you switch and what to look at. After it: `W log 4` to confirm the frame changed the way you meant (don't show raw logs unless asked, just say it worked), then wait for them.

1. **Live screen.** Nothing switched. "My orders, a real list over a WebSocket; the whole screen is one JSON frame every few seconds, `seq` in the top right counts them. Some orders move forward on their own."
2. **Every state at once.** `W preset all --solo`. 14 cards, one per state, each labelled `[state-name]`, all cloned from one real order. Ask them to look for what's broken before you tell; then name the five real bugs in the demo page: "1 items"; a raw `refunded` on a red badge (unknown status); "On the way" with no courier name; step 7 of 4 drawn as a full bar; the price line ending in "·" when there's no total. Point out this is how you check a whole state matrix from the design without the backend producing a single one of them.
3. **Rollback.** `W preset off`, then `W on late-old-frame` (it brings `delivered` along). "Bao Bar, the first order, becomes Delivered. One older frame where it's still On the way is held back for 5 s; when it lands, the order jumps back to On the way until the next frame, and `seq` in the corner goes backwards." The page doesn't check `seq`, that's the bug. This one can't be reproduced by tapping; it's the reason ws-mock exists. To show it again: `W on late-old-frame` once more (re-arms it).
4. **Socket hangs.** `W off`, then `W on frozen`. "The socket stays open and the page says connected, but no frame gets through: ETAs keep counting down, statuses never move, and nothing tells the user the data is stale."
5. **Live update.** `W off`, then `W inject`. "Pushed into the open socket, no reload: Bao Bar goes On the way with courier Sam, the card flashes orange. The next frame from the server puts the real state back."
6. **Under the hood** (if they're curious). `W log 8`: every frame and what happened to it (`-> presets[empty, clones:14, items 60->14]`, `-> dropped`, `-> held 5000ms x1`). All of this is one file, `profiles/demo/profile.json`: the frame description, the field map (`W fields`: what each field does on the screen, next to the real values), 14 presets, two rules, one push. Built-in scenarios (`frozen`, `duplicate`, `slow`, `late-frame`, `reverse`, `empty`) work on any app once its profile knows where the list is. For their own app: the `ws-mock` skill sets up a profile from a captured frame (`wsm.py new`, `capture`, `inspect`, `check`).

A single-part tour is that step plus the start, section 4 and the finish.

## 4. After the last step

Don't wrap up yet. Write two short things:

1. **Any other mock, in plain words.** They can ask for whatever they want to see on the demo and you'll do it, e.g. "make order #1003 cancelled", "everyone is an hour late", "no courier name", "a £0 order", "empty list", "every frame twice", "only the on-the-way states". You build them from `W set <id|all|frame> key=value ...` (one-off patches, the profile stays untouched; `W set clear` drops them), the built-ins (`W on frozen|duplicate|slow|late-frame|reverse|empty`) and the presets (`W preset <names> --solo`). Handle each request like a tour step: switch, `W log` to confirm, one line on what to look at.
2. **Before using it on a real project.** ws-mock changes data, not the screen. On a real app you first need to know which fields of the WebSocket frame drive what is on the screen: the status badge, the timer, the button, the progress. Without that map a mock hits at random. `W fields` shows the fields that look like state, the spec or a developer says what they mean, and a quick experiment confirms it: change one field with `set`, see what changed on the screen. The `ws-mock` skill stops and asks for exactly that before it writes a single mock, and keeps the answer in the profile, so the next session doesn't guess again.

## 5. Finish

When they say they're done: `W off`, then `W down` (stops the demo and mitmproxy).
