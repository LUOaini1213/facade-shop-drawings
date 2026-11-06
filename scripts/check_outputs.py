"""Run the independent output checks; exit 1 on any failure."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fsd import checks  # noqa: E402


def main(out=ROOT / "out"):
    res = checks.run_all(out)
    bad = 0
    for group, fails in res.items():
        print("%-9s %s" % (group, "PASS" if not fails else "FAIL (%d)" % len(fails)))
        for f in fails[:20]:
            print("   -", f)
        bad += len(fails)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out"))
