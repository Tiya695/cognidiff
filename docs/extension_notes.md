# Chrome Extension Notes

Written for the viva questions about extension architecture, in plain terms.

---

## The four pieces

**`manifest.json`** — the extension's declaration of intent. It tells Chrome what
the extension is called, which permissions it wants, which sites its content
scripts may run on, and which files are the background worker and popup. Chrome
reads it before running anything, and everything the extension is allowed to do
is bounded by what this file asks for.

**`content_script.js`** — runs *inside the page*, in the same DOM as the website
the user is looking at. It can see and listen to page events, which is why the
keystroke listeners live here. It is deliberately sandboxed from the page's own
JavaScript variables, and it cannot make arbitrary cross-origin requests.

**`background.js`** — a service worker running *outside* any page, with no DOM at
all. It survives page navigation, receives messages from content scripts,
persists data and talks to the backend. In Manifest V3 it is event-driven and
Chrome may terminate it when idle, so it must keep no important state in memory.

**`popup.html` / `popup.js`** — the panel that appears when the toolbar icon is
clicked. Its own tiny page with its own lifecycle: it exists only while open, so
it reads state rather than holding it.

---

## Content script vs background script — the viva question

**When does each run?**

A **content script** is injected into a matching page each time that page loads,
and dies with it. Ten open tabs means ten independent copies, each seeing only
its own page. It has DOM access but restricted extension APIs.

A **background service worker** starts when an event needs it — a message
arrives, an alarm fires, the extension installs — and Chrome shuts it down when
idle. There is exactly one, shared across every tab. It has no DOM and full
extension API access.

**Why the split matters for CogniDiff.**

The content script is where the sensitive work happens, so it holds as little as
possible: it categorises each key, keeps a minute of timings, and discards the
buffer entirely the moment a sensitive context appears. It never talks to the
network.

The background worker never sees a keystroke. It receives finished, anonymised
feature batches and is responsible for storage and upload. That separation means
the component with page access has no network access, and the component with
network access has no page access.

Because the worker can be terminated at any time, the offline queue lives in
`chrome.storage.local` rather than in memory. A batch that fails to upload
survives the worker being shut down.

---

## Manifest V3 choices

| Decision | Why |
|---|---|
| **No static `content_scripts` at all** | The extension ships with access to zero sites. Every monitored site is requested at runtime with `chrome.permissions.request()`, so Chrome shows its own prompt and the user can audit and revoke from `chrome://extensions`. A fixed `matches` list is consent the user never actually gave. |
| **Dynamic registration** via `chrome.scripting.registerContentScripts()` | The content script is registered per host only once the permission is genuinely held, and `permissions.onRemoved` unregisters it again. The permission set is the source of truth; our stored list is only a cache. |
| **`storage`** | The local ring buffer and the user's settings. |
| **`alarms`** | Retrying the upload queue every five minutes. A `setInterval` would not survive the worker being terminated. |
| **`activeTab` + `scripting`** | Runtime injection on user-chosen sites. |
| **`tabs`** | Reading the current tab's host, so the popup can offer "monitor this site" for the page you are actually on. |
| **`host_permissions: localhost:8000`** | The backend. The only host the extension may contact. |
| **No `tabs` permission** | Not needed, so not requested. |
| **CSP `script-src 'self'`** | No remote code in extension pages. |

---

## Data flow

```
keydown  →  categorise()  →  'l' | 'd' | 's' | 'b' | 'p'   (character discarded)
              │
              ├─ sensitive context?  →  discard the whole buffer, stop
              │
         60-second buffer: categories[], offsets[], holds[]
              │
         buildBatch()  →  wpm, avg IKI, avg hold, counts, device fingerprint
              │
         chrome.runtime.sendMessage → background.js
              │
              ├─ chrome.storage.local  (always — local copy first)
              └─ POST /api/session     (if signed in and reachable)
                    └─ on failure → pending_queue, retried by alarm
```

The local write happens **before** the upload attempt. Typing data is never lost
because a server was down, and it is never sent anywhere else.

---

## Why capture is disabled where it is

The checks run *before* anything is recorded, not as a filter afterwards:

- `input[type=password]`
- `autocomplete` containing `cc-`, `one-time-code`, `current-password`, `new-password`
- any element inside a form that contains a password field — the username box
  next to a password box is still part of an authentication flow
- `data-sensitive`, or a label matching `password|cvv|otp|pin|aadhaar|…`
- URLs matching the banking, payment, health-portal and authentication blocklist
- incognito windows

And the part that is easy to miss: if a sensitive context appears **mid-session**,
the partial buffer is deleted rather than flushed. A minute that began on a
normal page and continued into a checkout form never leaves the browser.

---

## The consent bug this replaced

Worth writing down, because it looked fine and was not.

The first version hardcoded three Google domains into the manifest's
`content_scripts` and kept a "site allowlist" in the popup. Adding a site to
that list wrote to `chrome.storage.local` and re-rendered the UI, so it looked
like it worked. It did nothing: Chrome injects content scripts from the manifest
`matches`, so the script never ran on the site the user added, while it ran on
all three Google domains whether they wanted it or not.

The answer to "which sites am I monitored on" was therefore the manifest, not
the user's choice, and the interface actively implied otherwise. For a consent
mechanism that is the worst available failure: not an absent control, but a
control that reports success while doing nothing.

The fix moves the decision into Chrome's own permission system, where the user
can verify it without having to trust our UI.

## Testing it

1. `chrome://extensions` → Developer mode → **Load unpacked** → select `extension/`
2. The consent page opens by itself on first install. Read it.
3. Open the popup, sign in, then press **Monitor this site** on somewhere you
   actually write. Chrome shows its own permission prompt; accept it.
4. Reload that tab, then turn monitoring **on** (off by default, consent
   precedes capture)
5. Type there for two minutes
6. `chrome://extensions` → **service worker** → Console: batches appear every
   60 seconds, containing only numbers
7. Confirm the negative cases produce **zero** batches:
   - typing in a password field
   - typing on a URL containing `/checkout`
   - typing in an incognito window
8. **View My Data** shows stored features; **Delete All My Data** clears them
9. Confirm the consent is real, not just ours: `chrome://extensions` →
   CogniDiff → **Details** → **Site access**. Only the sites you approved are
   listed. Remove one there and it disappears from the popup too, because
   `permissions.onRemoved` unregisters the script.

Step 7 is the one that matters. Documented in `docs/data_flow_audit.md`.
