"""Package the CogniDiff extension into an installable .zip.

    python scripts/package_extension.py

Writes dist/cognidiff-extension-<version>.zip, which is what you hand to
someone else, upload to the Chrome Web Store, or keep as a release artefact.

The zip is checked before it is written: a missing icon or a file referenced by
the manifest that is not on disk fails here rather than as a broken install on
somebody else's machine.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
DIST = ROOT / "dist"

#: Everything that belongs in a shipped extension. An explicit list rather than
#: a directory sweep, so a stray note or a scratch file cannot ride along.
INCLUDE = [
    "manifest.json",
    "background.js",
    "content_script.js",
    "popup.html",
    "popup.css",
    "popup.js",
    "welcome.html",
    "welcome.css",
    "welcome.js",
    "icons/icon16.png",
    "icons/icon48.png",
    "icons/icon128.png",
]


def check() -> tuple[dict, list[str]]:
    problems: list[str] = []

    manifest_path = EXT / "manifest.json"
    if not manifest_path.exists():
        return {}, ["manifest.json is missing"]

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, [f"manifest.json is not valid JSON: {exc}"]

    for rel in INCLUDE:
        if not (EXT / rel).exists():
            problems.append(f"missing file: {rel}")

    # Every file the manifest points at must actually exist.
    referenced = set()
    sw = manifest.get("background", {}).get("service_worker")
    if sw:
        referenced.add(sw)
    popup = manifest.get("action", {}).get("default_popup")
    if popup:
        referenced.add(popup)
    for size_map in (manifest.get("icons", {}),
                     manifest.get("action", {}).get("default_icon", {})):
        referenced.update(size_map.values())

    for rel in sorted(referenced):
        if not (EXT / rel).exists():
            problems.append(f"manifest references a file that is not on disk: {rel}")

    # welcome.html is opened by background.js, so it has to ship even though the
    # manifest never names it.
    if "welcome.html" not in INCLUDE:
        problems.append("welcome.html is opened on install but is not packaged")

    if manifest.get("manifest_version") != 3:
        problems.append("manifest_version must be 3")

    return manifest, problems


def main() -> int:
    manifest, problems = check()
    if problems:
        print("Cannot package:")
        for p in problems:
            print(f"  - {p}")
        return 1

    version = manifest.get("version", "0.0.0")
    DIST.mkdir(exist_ok=True)
    out = DIST / f"cognidiff-extension-{version}.zip"

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in INCLUDE:
            z.write(EXT / rel, rel)

    size_kb = out.stat().st_size / 1024
    print(f"packaged {len(INCLUDE)} files -> {out}  ({size_kb:.1f} KB)")
    print()
    print("To install:")
    print("  1. unzip it somewhere permanent (Chrome loads it from that folder,")
    print("     so deleting the folder uninstalls the extension)")
    print("  2. open chrome://extensions")
    print("  3. turn on Developer mode, top right")
    print("  4. Load unpacked, and select the unzipped folder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
