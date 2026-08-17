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
| **Explicit site allowlist**, not `<all_urls>` | Monitoring three named domains by default is a far narrower permission surface than every page the user visits. `optional_host_permissions` lets the user add sites at runtime. |
| **`storage`** | The local ring buffer and the user's settings. |
| **`alarms`** | Retrying the upload queue every five minutes. A `setInterval` would not survive the worker being terminated. |
| **`activeTab` + `scripting`** | Runtime injection on user-chosen sites. |
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

## Testing it

1. `chrome://extensions` → Developer mode → **Load unpacked** → select `extension/`
2. Open the popup, read the privacy notice, turn monitoring **on** (it is off by
   default — consent precedes capture)
3. Type on an allowlisted site for two minutes
4. `chrome://extensions` → **service worker** → Console: batches appear every
   60 seconds, containing only numbers
5. Confirm the negative cases produce **zero** batches:
   - typing in a password field
   - typing on a URL containing `/checkout`
   - typing in an incognito window
6. **View My Data** shows stored features; **Delete All My Data** clears them

Step 5 is the one that matters. Documented in `docs/data_flow_audit.md`.
