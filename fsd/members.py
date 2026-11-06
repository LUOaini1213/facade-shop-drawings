"""Frame members of every panel, derived from facade-bim's panel list + config.

The upstream model has, per panel: two full-height mullions (``MULLION_W`` wide)
and horizontal members (``TRANSOM_H`` high) spanning between the mullions.
Zone stacks below copy the rules in facade-bim ``facade/model.py::zones_for``.

Profile split used for the cutting list (an assumption of this repo, typical of
unitized systems but not taken from any supplier):

* MUL-L / MUL-R  -- left / right half of the split mullion, length = panel height
* SILL           -- lowest horizontal member
* HEAD           -- highest horizontal member
* TRANSOM        -- any intermediate horizontal member

Cut length = member length in the model (square cuts, no machining allowance).
"""
from collections import Counter, OrderedDict

from . import upstream

PROFILES = ("MUL-L", "MUL-R", "SILL", "HEAD", "TRANSOM")


def zones(ptype, h, c):
    """Bottom-to-top zone stack [(kind, height_mm)] -- same rules as facade-bim."""
    t = c["TRANSOM_H"]
    if ptype == "U5":
        return [("transom", t), ("spandrel", h - 2 * t), ("transom", t)]
    if ptype == "U4":
        vision = h - 4 * t - c["DOOR_LEAF_H"] - c["SPANDREL_H"]
        return [("transom", t), ("door", c["DOOR_LEAF_H"]), ("transom", t),
                ("vision", vision), ("transom", t), ("spandrel", c["SPANDREL_H"]),
                ("transom", t)]
    infill = "louver" if ptype == "U3" else "vision"
    return [("transom", t), (infill, h - 3 * t - c["SPANDREL_H"]), ("transom", t),
            ("spandrel", c["SPANDREL_H"]), ("transom", t)]


def panel_members(ptype, w, h, c):
    """[(profile, length_mm, z_bottom_mm)] for one panel."""
    mw = c["MULLION_W"]
    out = [("MUL-L", h, 0), ("MUL-R", h, 0)]
    stack = zones(ptype, h, c)
    idx = [i for i, (k, _) in enumerate(stack) if k == "transom"]
    z = 0
    for i, (kind, zh) in enumerate(stack):
        if kind == "transom":
            prof = "SILL" if i == idx[0] else "HEAD" if i == idx[-1] else "TRANSOM"
            out.append((prof, w - 2 * mw, z))
        z += zh
    return out


def panel_types(panels):
    """{type: (w, h, count)} -- each type must have a single size."""
    sizes, counts = {}, Counter()
    for p in panels:
        key = (p["w_mm"], p["h_mm"])
        if sizes.setdefault(p["type"], key) != key:
            raise ValueError("type %s has more than one size" % p["type"])
        counts[p["type"]] += 1
    return OrderedDict((t, sizes[t] + (counts[t],)) for t in sorted(sizes))


def member_rows(panels=None, c=None):
    """One row per member per panel (the full cutting list)."""
    panels = panels if panels is not None else upstream.panels()
    c = c if c is not None else upstream.config()
    rows = []
    for p in panels:
        for n, (prof, length, z) in enumerate(panel_members(p["type"], p["w_mm"], p["h_mm"], c), 1):
            rows.append({"pid": p["pid"], "type": p["type"], "mark": "%s-%02d" % (p["pid"], n),
                         "profile": prof, "length_mm": length, "z_mm": z})
    return rows


def demand(rows, profile, ptype=None):
    """Counter {length: qty} for one profile, optionally one panel type."""
    return Counter(r["length_mm"] for r in rows
                   if r["profile"] == profile and (ptype is None or r["type"] == ptype))


def frame_kg(rows, c):
    """Aluminium frame mass by panel type from member lengths x linear mass."""
    kg = Counter()
    for r in rows:
        lm = c["MULLION_KG_M"] if r["profile"].startswith("MUL") else c["TRANSOM_KG_M"]
        kg[r["type"]] += r["length_mm"] / 1000.0 * lm
    return kg
