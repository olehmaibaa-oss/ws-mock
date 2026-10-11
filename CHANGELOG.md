# Changelog

## 0.1.0, test version (2026-10-10)

First public version.

- Engine (`ws_mock.py`): mitmproxy addon that rewrites WebSocket JSON frames from a profile, with live reload. Patch, clone, remove, reorder or empty list items; drop, delay, repeat, hold one frame; inject into a live socket. Raises mitmproxy's fragment size so big patched frames aren't split.
- CLI (`wsm.py`): `up`/`down` (proxy, system proxy, simulator cert), profiles from a template with a field map, `capture`, `inspect`, `fields`, `check`, `guide`, `wait`, `log`, `suggest`, presets, rules, one-off `set` patches, `inject`.
- Built-in scenarios: `frozen`, `duplicate`, `slow`, `late-frame`, `reverse`, `empty`.
- Demo app (food delivery orders) and the DEMO profile.
- Claude skills: `ws-mock` (your app or site) and `ws-mock-demo` (guided tour).

Known gaps: Socket.IO/SignalR framing, sites on localhost, Android navigation over adb, Linux and Windows.
