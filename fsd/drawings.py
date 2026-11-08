"""Shop drawings, one A3 sheet per panel type, as DXF.

Sheet convention: model space is in *paper* millimetres (A3 = 420 x 297).
Each view is a block drawn at true size (1:1, mm) and inserted at its view
scale; its dimensions carry ``DIMLFAC`` = scale denominator so the printed
value is the true size. Plotting the sheet 1:1 on A3 gives the stated scales.

Profiles are deliberately simple hollow boxes: they show the module geometry
taken from facade-bim (mullion width, transom height, frame depth, joint) and
nothing about a real extrusion. Every sheet says so.
"""
from collections import OrderedDict

import ezdxf
from ezdxf.enums import TextEntityAlignment

from . import members as M
from . import upstream

SHEET_W, SHEET_H = 420, 297
ELEV_SCALE = 20
SECT_SCALE = 5
REV = "P1"
STATUS = "INDICATIVE - NOT FOR CONSTRUCTION"
WALL = 3          # wall thickness of the simplified hollow-box profiles (mm)
LF = chr(10)
IGU = 24         # 6 + 12A + 6 (upstream config IGU_GLASS_MM counts glass only)

LAYERS = {        # name: ACI colour
    "BORDER": 7, "TITLE": 7, "FRAME": 5, "GLAZING": 4, "INFILL": 8,
    "DIMS": 1, "TEXT": 7, "SECTION": 3, "CUTLINE": 6, "SCHEDULE": 7,
}
TITLE_ATTRS = ("DWG_NO", "TITLE", "TYPE", "QTY", "SCALE", "REV", "STATUS", "SOURCE")
BLOCKS_COMMON = ("FSD_TITLE", "FSD_MULLION", "FSD_TRANSOM")


def drawing_no(ptype):
    return "FSD-SD-%d" % (100 + int(ptype[1:]))


def _rect(layout, x0, y0, x1, y1, layer):
    layout.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True,
                          dxfattribs={"layer": layer})


def _text(layout, s, x, y, h=2.5, layer="TEXT", align=TextEntityAlignment.BOTTOM_LEFT, rot=0):
    t = layout.add_text(s, height=h, dxfattribs={"layer": layer, "rotation": rot})
    t.set_placement((x, y), align=align)
    return t


def _new_doc():
    doc = ezdxf.new("R2018", setup=True, units=4)      # 4 = millimetres
    for name, color in LAYERS.items():
        doc.layers.add(name, color=color)
    ds = doc.dimstyles.get("EZDXF")
    ds.dxf.dimtxt = 2.0
    ds.dxf.dimasz = 1.8
    ds.dxf.dimexe = 1.0
    ds.dxf.dimexo = 1.0
    ds.dxf.dimdec = 0
    ds.dxf.dimtad = 1
    ds.dxf.dimgap = 0.6
    return doc


def _title_block(doc):
    b = doc.blocks.new("FSD_TITLE")
    w, h = 180, 48
    _rect(b, 0, 0, w, h, "TITLE")
    rows = [("DWG_NO", "Drawing no."), ("TITLE", "Title"), ("TYPE", "Panel type"),
            ("QTY", "Quantity"), ("SCALE", "Scale"), ("REV", "Revision"),
            ("STATUS", "Status"), ("SOURCE", "Model source")]
    rh = h / len(rows)
    for i, (tag, label) in enumerate(rows):
        y = h - (i + 1) * rh
        b.add_line((0, y), (w, y), dxfattribs={"layer": "TITLE"})
        _text(b, label, 2, y + 1.6, 2.0, "TITLE")
        b.add_attdef(tag, (34, y + 1.6), dxfattribs={"height": 2.2, "layer": "TITLE"})
    b.add_line((32, 0), (32, h), dxfattribs={"layer": "TITLE"})
    return w, h


def _profile_blocks(doc):
    """Simplified hollow boxes at 1:1. Origin = exterior face, left/bottom."""
    c = upstream.config()
    mw, d, t = c["MULLION_W"], c["DEPTH"], c["TRANSOM_H"]
    b = doc.blocks.new("FSD_MULLION")          # plan: x = width, y = depth
    _rect(b, 0, 0, mw, d, "FRAME")
    _rect(b, WALL, WALL, mw - WALL, d - WALL, "FRAME")
    b = doc.blocks.new("FSD_TRANSOM")          # section: x = depth, y = height
    _rect(b, 0, 0, d, t, "FRAME")
    _rect(b, WALL, WALL, d - WALL, t - WALL, "FRAME")


def _panel_block(doc, ptype, w, h, c):
    """Elevation of one panel at 1:1 viewed from outside. Returns zone list."""
    b = doc.blocks.new("FSD_PANEL_%s" % ptype)
    mw = c["MULLION_W"]
    for prof, length, z in M.panel_members(ptype, w, h, c):
        if prof == "MUL-L":
            _rect(b, 0, 0, mw, length, "FRAME")
        elif prof == "MUL-R":
            _rect(b, w - mw, 0, w, length, "FRAME")
        else:
            _rect(b, mw, z, mw + length, z + c["TRANSOM_H"], "FRAME")
    z = 0
    stack = M.zones(ptype, h, c)
    for kind, zh in stack:
        if kind != "transom":
            layer = "GLAZING" if kind in ("vision", "door") else "INFILL"
            x0, x1 = mw, w - mw
            if kind == "vision":
                b.add_line((x0, z), (x1, z + zh), dxfattribs={"layer": layer})
            elif kind == "spandrel":
                hatch = b.add_hatch(color=8, dxfattribs={"layer": layer})
                hatch.set_pattern_fill("ANSI31", scale=4)
                hatch.paths.add_polyline_path([(x0, z), (x1, z), (x1, z + zh), (x0, z + zh)])
            elif kind == "louver":
                for y in range(int(z) + 100, int(z + zh), 100):
                    b.add_line((x0, y), (x1, y), dxfattribs={"layer": layer})
            elif kind == "door":
                b.add_line((x0, z), ((x0 + x1) / 2, z + zh), dxfattribs={"layer": layer})
                b.add_line(((x0 + x1) / 2, z + zh), (x1, z), dxfattribs={"layer": layer})
            _text(b, kind.upper(), (x0 + x1) / 2, z + zh / 2, 50, "TEXT",
                  TextEntityAlignment.MIDDLE_CENTER)
        z += zh
    return stack


def _dim(msp, p1, p2, base, scale, angle=0):
    d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle="EZDXF",
                           override={"dimlfac": scale}, dxfattribs={"layer": "DIMS"})
    d.render()


def sheet(ptype, w, h, qty, src):
    """Build one shop-drawing sheet. Returns the ezdxf document."""
    c = upstream.config()
    mw, jt, dep, th = c["MULLION_W"], c["JOINT"], c["DEPTH"], c["TRANSOM_H"]
    doc = _new_doc()
    msp = doc.modelspace()
    tw, thh = _title_block(doc)
    _profile_blocks(doc)
    stack = _panel_block(doc, ptype, w, h, c)

    # border + title block
    _rect(msp, 10, 10, SHEET_W - 10, SHEET_H - 10, "BORDER")
    title = msp.add_blockref("FSD_TITLE", (SHEET_W - 10 - tw, 10), dxfattribs={"layer": "TITLE"})
    title.add_auto_attribs({
        "DWG_NO": drawing_no(ptype), "TITLE": "Unit %s - %s" % (ptype, upstream.TYPE_NAMES[ptype]),
        "TYPE": ptype, "QTY": "%d No." % qty,
        "SCALE": "1:%d (elevation), 1:%d (sections) @ A3" % (ELEV_SCALE, SECT_SCALE),
        "REV": REV, "STATUS": STATUS, "SOURCE": "facade-bim @ %s" % src[:7],
    })

    # ---- elevation (1:20) -------------------------------------------------
    s = 1.0 / ELEV_SCALE
    ex, ey = 40, 297 - 30 - h * s
    msp.add_blockref("FSD_PANEL_%s" % ptype, (ex, ey), dxfattribs={
        "layer": "FRAME", "xscale": s, "yscale": s})
    _text(msp, "ELEVATION (VIEWED FROM OUTSIDE)  1:%d" % ELEV_SCALE, ex - 20, 297 - 17, 3.0)
    top = ey + h * s
    _dim(msp, (ex, ey), (ex + w * s, ey), (ex, ey - 8), ELEV_SCALE)                        # width
    _dim(msp, (ex + mw * s, top), (ex + (w - mw) * s, top), (ex, top + 6), ELEV_SCALE)     # daylight
    _dim(msp, (ex, top), (ex + mw * s, top), (ex, top + 6), ELEV_SCALE)                    # mullion
    _dim(msp, (ex, ey), (ex, top), (ex - 10, ey), ELEV_SCALE, angle=90)                    # height
    z = 0
    for kind, zh in stack:                                                                 # zone chain
        _dim(msp, (ex + w * s, ey + z * s), (ex + w * s, ey + (z + zh) * s),
             (ex + w * s + 10, ey), ELEV_SCALE, angle=90)
        z += zh
    # section cut lines on the elevation
    vis = [i for i, (k, _) in enumerate(stack) if k in ("vision", "louver", "spandrel")][0]
    zc = sum(zh for _, zh in stack[:vis]) + stack[vis][1] / 2
    msp.add_line((ex - 4, ey + zc * s), (ex + w * s + 4, ey + zc * s), dxfattribs={"layer": "CUTLINE"})
    _text(msp, "A", ex - 7, ey + zc * s, 3.0, "CUTLINE", TextEntityAlignment.MIDDLE_CENTER)
    xc = ex + w * s * 0.75
    msp.add_line((xc, ey - 3), (xc, top + 3), dxfattribs={"layer": "CUTLINE"})
    _text(msp, "B", xc, top + 4, 3.0, "CUTLINE", TextEntityAlignment.BOTTOM_CENTER)
    _text(msp, "PANEL MARK %s  (%d No.)" % (ptype, qty), ex, ey - 22, 3.0)
    _text(msp, "%d x %d mm" % (w, h), ex, ey - 27, 2.5)

    # ---- section A: horizontal, vertical joint between two panels (1:5) ---
    s5 = 1.0 / SECT_SCALE
    ax, ay = 185, 205
    _text(msp, "SECTION A - HORIZONTAL AT VERTICAL JOINT  1:%d" % SECT_SCALE, ax - 25, ay + dep * s5 + 22, 3.0)
    msp.add_blockref("FSD_MULLION", (ax, ay), dxfattribs={"layer": "SECTION", "xscale": s5, "yscale": s5})
    msp.add_blockref("FSD_MULLION", (ax + (mw + jt) * s5, ay),
                     dxfattribs={"layer": "SECTION", "xscale": s5, "yscale": s5})
    gy0, gy1 = ay + 20 * s5, ay + (20 + IGU) * s5
    _rect(msp, ax - 120 * s5, gy0, ax, gy1, "GLAZING")
    _rect(msp, ax + (2 * mw + jt) * s5, gy0, ax + (2 * mw + jt + 120) * s5, gy1, "GLAZING")
    _dim(msp, (ax, ay), (ax + mw * s5, ay), (ax, ay - 8), SECT_SCALE)
    _dim(msp, (ax + mw * s5, ay), (ax + (mw + jt) * s5, ay), (ax, ay - 8), SECT_SCALE)
    _dim(msp, (ax + (mw + jt) * s5, ay), (ax + (2 * mw + jt) * s5, ay), (ax, ay - 8), SECT_SCALE)
    _dim(msp, (ax + (2 * mw + jt) * s5, ay), (ax + (2 * mw + jt) * s5, ay + dep * s5),
         (ax + (2 * mw + jt) * s5 + 34, ay), SECT_SCALE, angle=90)
    _text(msp, "EXTERNAL", ax - 24, ay - 3, 2.0)
    _text(msp, "INTERNAL", ax - 24, ay + dep * s5 - 2, 2.0)
    _text(msp, "MUL-R (left panel)", ax - 30, ay + dep * s5 + 4, 2.0)
    _text(msp, "MUL-L (right panel)", ax + (mw + jt) * s5, ay + dep * s5 + 4, 2.0)
    infill = {"vision": "IGU 6+12A+6", "louver": "LOUVRE (outline only)",
              "spandrel": "SPANDREL (outline only)"}[stack[vis][0]]
    _text(msp, infill, ax - 24, gy1 + 1, 2.0, "GLAZING")

    # ---- section B: vertical, stack joint (head below, sill above) (1:5) --
    bx, by = 290, 140
    _text(msp, "SECTION B - VERTICAL AT STACK JOINT  1:%d" % SECT_SCALE, bx - 30, by + (2 * th + jt) * s5 + 50, 3.0)
    msp.add_blockref("FSD_TRANSOM", (bx, by), dxfattribs={"layer": "SECTION", "xscale": s5, "yscale": s5})
    msp.add_blockref("FSD_TRANSOM", (bx, by + (th + jt) * s5),
                     dxfattribs={"layer": "SECTION", "xscale": s5, "yscale": s5})
    _rect(msp, bx + 20 * s5, by - 160 * s5, bx + 26 * s5, by, "INFILL")              # spandrel glass
    _rect(msp, bx + 100 * s5, by - 160 * s5, bx + 150 * s5, by, "INFILL")            # insulation
    _rect(msp, bx + 150 * s5, by - 160 * s5, bx + 153 * s5, by, "INFILL")            # back pan
    up = by + (2 * th + jt) * s5
    _rect(msp, bx + 20 * s5, up, bx + (20 + IGU) * s5, up + 160 * s5, "GLAZING")
    _dim(msp, (bx, by), (bx, by + th * s5), (bx - 10, by), SECT_SCALE, angle=90)
    _dim(msp, (bx, by + th * s5), (bx, by + (th + jt) * s5), (bx - 10, by), SECT_SCALE, angle=90)
    _dim(msp, (bx, by + (th + jt) * s5), (bx, up), (bx - 10, by), SECT_SCALE, angle=90)
    _dim(msp, (bx, by - 160 * s5), (bx + dep * s5, by - 160 * s5), (bx, by - 160 * s5 - 8), SECT_SCALE)
    _text(msp, "SILL (upper panel)", bx + dep * s5 + 3, by + (th + jt) * s5 + 2, 2.0)
    _text(msp, "HEAD (lower panel)", bx + dep * s5 + 3, by + 4, 2.0)
    _text(msp, "spandrel: glass / insulation / back pan", bx + dep * s5 + 3, by - 20, 2.0)
    _text(msp, "EXT.", bx - 4, up + 160 * s5 + 2, 2.0)
    _text(msp, "INT.", bx + dep * s5 - 6, up + 160 * s5 + 2, 2.0)

    # ---- member schedule (text, parsed back by checks) ---------------------
    sx, sy = 160, 150
    _text(msp, "MEMBER SCHEDULE (PER PANEL / TOTAL)", sx, sy, 3.0, "SCHEDULE")
    per = {}
    for prof, length, _ in M.panel_members(ptype, w, h, c):
        per[(prof, length)] = per.get((prof, length), 0) + 1
    for i, prof in enumerate(M.PROFILES):
        for (p, length), n in per.items():
            if p == prof:
                y = sy - 6 - 5 * len([k for k in per if M.PROFILES.index(k[0]) < i])
                _text(msp, "%-8s L=%d  %d/panel  %d total" % (prof, length, n, n * qty),
                      sx, y, 2.5, "SCHEDULE")

    # ---- notes ---------------------------------------------------------------
    notes = [
        "NOTES",
        "1. Independent personal project. Fictional building from facade-bim.",
        "2. Profiles are simplified hollow boxes - indicative only, not a supplier system.",
        "3. NOT FOR CONSTRUCTION. All dimensions in mm.",
        "4. Cut length = member length in model; square cuts; no machining allowance.",
        "5. Glass, gaskets, brackets, coping, sealant and anchors are not detailed.",
    ]
    for i, n in enumerate(notes):
        _text(msp, n, 160, 100 - 5 * i, 2.5 if i else 3.0)
    return doc


def build_all(out_dir, panels=None):
    """Write one DXF per panel type. Returns the register rows."""
    ezdxf.options.write_fixed_meta_data_for_testing = True   # reproducible bytes
    src = upstream.verify_source()["commit"]
    panels = panels if panels is not None else upstream.panels()
    out_dir.mkdir(parents=True, exist_ok=True)
    reg = []
    for ptype, (w, h, qty) in M.panel_types(panels).items():
        doc = sheet(ptype, w, h, qty, src)
        name = "%s.dxf" % drawing_no(ptype)
        # ezdxf takes its required CLASS names from a set, so their order follows
        # the per-process hash seed; register them now and sort for stable bytes
        doc.classes.add_required_classes(doc.dxfversion)
        doc.classes.classes = OrderedDict(sorted(doc.classes.classes.items()))
        with open(out_dir / name, "w", encoding="utf-8", newline=LF) as f:   # LF on every OS
            doc.write(f)
        reg.append({"drawing_no": drawing_no(ptype), "revision": REV,
                    "title": "Unit %s - %s - elevation, sections A and B, member schedule"
                             % (ptype, upstream.TYPE_NAMES[ptype]),
                    "panel_type": ptype, "panels": qty, "sheet": "A3",
                    "scale": "1:%d / 1:%d" % (ELEV_SCALE, SECT_SCALE),
                    "status": STATUS, "file": "drawings/" + name})
    return reg
