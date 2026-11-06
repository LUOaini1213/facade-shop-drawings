"""Read the pinned facade-bim inputs.

Nothing here is imported from facade-bim: the three files in ``upstream/`` are
byte copies of facade-bim at a fixed commit (see ``upstream/SOURCE.json``) and
``config.py.txt`` is parsed with ``ast`` -- never executed.
"""
import ast
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UP = ROOT / "upstream"

# Constants this repo needs from facade-bim's config. All are integers in mm.
CONFIG_KEYS = ("MODULE", "JOINT", "DEPTH", "MULLION_W", "TRANSOM_H",
               "SPANDREL_H", "DOOR_LEAF_H")
KG_KEYS = ("MULLION_KG_M", "TRANSOM_KG_M")

TYPE_NAMES = {
    "U1": "Ground-floor standard unit",
    "U2": "Typical-floor unit",
    "U3": "Plant-room louvre unit",
    "U4": "Ground-floor entrance door unit",
    "U5": "Parapet unit",
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_source():
    """Fail loudly if an upstream file differs from the pinned hash."""
    src = json.loads((UP / "SOURCE.json").read_text(encoding="utf-8"))
    for name, digest in src["files"].items():
        got = sha256(UP / name)
        if got != digest:
            raise ValueError("upstream/%s sha256 %s != pinned %s" % (name, got, digest))
    return src


def config():
    """Top-level numeric assignments of facade-bim's config.py, via ast."""
    tree = ast.parse((UP / "config.py.txt").read_text(encoding="utf-8"))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                isinstance(node.targets[0], ast.Name):
            try:
                val = ast.literal_eval(node.value)
            except ValueError:
                continue
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                out[node.targets[0].id] = val
    missing = [k for k in CONFIG_KEYS + KG_KEYS if k not in out]
    if missing:
        raise KeyError("config.py.txt lacks %s" % missing)
    return out


def panels():
    with open(UP / "panels.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["w_mm"] = int(r["w_mm"])
        r["h_mm"] = int(r["h_mm"])
        r["frame_alu_kg"] = float(r["frame_alu_kg"])
    return rows


def takeoff():
    with open(UP / "takeoff.csv", encoding="utf-8", newline="") as f:
        return {r["type"]: r for r in csv.DictReader(f)}
