"""Re-download the pinned facade-bim files from GitHub and compare SHA-256.

Read-only: fetches raw files at the pinned commit; never writes to facade-bim.
"""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    src = json.loads((ROOT / "upstream" / "SOURCE.json").read_text(encoding="utf-8"))
    base = src["repo"].replace("https://github.com/", "https://raw.githubusercontent.com/")
    bad = 0
    for name, digest in src["files"].items():
        url = "%s/%s/%s" % (base, src["commit"], src["paths"][name])
        with urllib.request.urlopen(url, timeout=30) as r:
            got = hashlib.sha256(r.read()).hexdigest()
        ok = got == digest
        bad += not ok
        print("%-14s %s" % (name, "OK" if ok else "MISMATCH %s" % got))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
