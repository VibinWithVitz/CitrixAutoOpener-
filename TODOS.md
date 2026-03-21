# TODOS

## Session Monitoring

**What:** Add session health monitoring that detects when a Citrix session disconnects or times out, and optionally re-launches affected apps.

**Why:** Citrix sessions can drop silently (network hiccups, VPN reconnects, idle timeouts). Users don't notice until they try to use an app and it's gone. Automated detection + re-launch would eliminate this pain point.

**Context:** The v2 architecture already has the building blocks — Playwright persistent context keeps the browser alive, the config system supports per-app settings, and the notification system can alert the user. The main work is: (1) a background polling loop that checks session health indicators in the Citrix portal, (2) detection logic for disconnected/timed-out sessions, (3) selective re-launch of only the affected apps. The Citrix portal shows session status at a URL like `/vpn/index.html` — the polling loop would check DOM indicators there.

**Effort:** M (human team) → S (with CC+gstack)

**Priority:** P2

**Depends on:** v2 core implementation (Playwright migration, config system, notification system)
