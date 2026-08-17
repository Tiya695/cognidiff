# How to run CogniDiff

Plain-language instructions. No prior setup needed, everything is already
installed on this machine.

---

## What the three pieces are

Think of it like a shop.

| Piece | What it is | Where it runs |
|---|---|---|
| **The backend** | The stockroom and the accountant. Stores your typing data and works out your score. Has no screen. | A black terminal window |
| **The website** | The shop floor. The dashboard, charts and reports you actually look at. | Your browser, `localhost:3000` |
| **The extension** | The doorbell. Sits inside Chrome and notices how you type. | Chrome itself |

The website and the extension both talk to the backend. **So the backend has to
be running first**, or the other two have nothing to talk to.

---

## Part 1: start the backend

Open a terminal in the project folder. (In VS Code: **Terminal** menu →
**New Terminal**.)

**Step 1.** Turn on the project's Python. Type this and press Enter:

```bash
.\venv\Scripts\Activate.ps1
```

You'll know it worked because `(venv)` appears at the start of the line:

```
(venv) PS C:\cognidiff>
```

> **If you get a red error about "running scripts is disabled"**, type this once,
> then try again:
> ```bash
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
> ```

**Step 2.** Start the backend:

```bash
uvicorn backend.main:app --reload --port 8000
```

You should see `Application startup complete.`

**Leave this window open.** It has to keep running. Closing it switches the
backend off. It will look like it's frozen, that's normal, it's waiting for
work.

---

## Part 2: start the website

The backend is using your first terminal, so you need a **second one**.
(In VS Code, click the **+** icon in the terminal panel.)

In the new terminal, type:

```bash
python -m http.server 3000 --directory frontend
```

Leave this one open too.

Now open Chrome and go to:

```
http://localhost:3000
```

You should see the landing page with the brain. Click **Open dashboard** and
sign in:

| | |
|---|---|
| Username | `tiya` |
| Password | `cognidiff2026` |

This account already has 186 sessions and 157 daily scores in it, so the charts
have something to show straight away.

To see the doctor's side: sign out, then sign in as `dr.mehta` with the same
password.

---

## Part 3: install the extension in Chrome

You don't need the zip file for your own computer. Chrome can load the folder
directly.

**Step 1.** In Chrome, go to:

```
chrome://extensions
```

**Step 2.** Top right, switch on **Developer mode**.

**Step 3.** A row of buttons appears. Click **Load unpacked**.

**Step 4.** Navigate to and select this folder:

```
C:\cognidiff\extension
```

CogniDiff now appears in your list, and a welcome page opens explaining what it
does and does not record.

**Step 5.** Click the CogniDiff icon in your toolbar, top right of Chrome. If
you can't see it, click the **puzzle-piece icon** and pin CogniDiff.

---

## Part 4: connect the extension to your account

In the popup:

1. Under **ACCOUNT**, sign in with `tiya` / `cognidiff2026`
2. Go to a site where you type a lot, for example `docs.google.com`
3. Open the popup again and press **MONITOR THIS SITE**
4. **Chrome will ask your permission.** Click **Allow**
5. **Reload that tab** (press F5). This step is easy to miss and nothing works
   without it
6. Open the popup and switch **Monitoring** to **ON**

Now type on that page for a couple of minutes. Every 60 seconds the extension
sends a batch of numbers, never your words.

Press **VIEW MY DATA** in the popup to see exactly what was stored. It's all
numbers.

---

## When you're finished

In each terminal window, press **Ctrl + C** to stop the server. Or just close
the windows.

---

## If something goes wrong

**"ModuleNotFoundError: No module named 'numpy'"**
You forgot Step 1 of Part 1. Run `.\venv\Scripts\Activate.ps1` first and look
for `(venv)`.

**"An attempt was made to access a socket in a way forbidden by its access
permissions"**
Something is already using that port, usually an old terminal you left open.
Close the other terminals and try again. To find and stop it:
```bash
netstat -ano | findstr :8000
```
Then `taskkill /PID <the number at the end> /F`.

**The website says "Cannot reach the CogniDiff API"**
The backend isn't running. Go back to Part 1.

**`127.0.0.1:8000` shows text instead of the website**
That's correct, that's the backend and it has no pages. The website is on
port **3000**.

**The extension isn't capturing anything**
Check all four: signed in, site approved, tab reloaded after approving,
monitoring switched on. The reload is the usual culprit.

**The page looks stale after I changed something**
Press **Ctrl + Shift + R** for a hard refresh.

---

## Giving the extension to someone else

They can't use your folder, so build a zip:

```bash
python scripts/package_extension.py
```

That writes `dist/cognidiff-extension-1.0.0.zip`. They unzip it somewhere
permanent and follow Part 3 from Step 1, choosing their unzipped folder.

Note that the backend currently runs on your machine only, so on their computer
the extension will store data locally but have nothing to sync to. Putting the
backend on a real server is a separate job.
