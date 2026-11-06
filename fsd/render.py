"""PDF output: shop-drawing sheets rendered from the DXF files, and cutting sheets."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

import ezdxf  # noqa: E402
from ezdxf.addons.drawing import Frontend, RenderContext  # noqa: E402
from ezdxf.addons.drawing.config import (BackgroundPolicy, ColorPolicy,  # noqa: E402
                                         Configuration)
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend  # noqa: E402

from .drawings import SHEET_H, SHEET_W  # noqa: E402

A3 = (SHEET_W / 25.4, SHEET_H / 25.4)
A4L = (297 / 25.4, 210 / 25.4)
PDF_META = {"CreationDate": None, "Creator": "facade-shop-drawings", "Producer": None}


def dxf_page(pdf, path, png=None):
    doc = ezdxf.readfile(path)
    fig = plt.figure(figsize=A3)
    ax = fig.add_axes([0, 0, 1, 1])
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.BLACK,
                        lineweight_scaling=0.5)
    Frontend(RenderContext(doc), MatplotlibBackend(ax), config=cfg).draw_layout(
        doc.modelspace(), finalize=False)
    ax.set_xlim(0, SHEET_W)
    ax.set_ylim(0, SHEET_H)
    ax.set_aspect("equal")
    ax.axis("off")
    pdf.savefig(fig)
    if png:
        fig.savefig(png, dpi=90)
    plt.close(fig)


def shop_pdf(dxf_paths, out, preview=None):
    """preview: (index, png_path) of one sheet to also save as an image."""
    with PdfPages(out, metadata=PDF_META) as pdf:
        for i, p in enumerate(dxf_paths):
            dxf_page(pdf, p, preview[1] if preview and preview[0] == i else None)


def _bar_page(pdf, title, subtitle, groups, kerf, trim, max_rows=18, png=None):
    """One page per <= max_rows pattern groups. groups: [(profile, L, pieces, qty)]."""
    for start in range(0, max(len(groups), 1), max_rows):
        chunk = groups[start:start + max_rows]
        fig = plt.figure(figsize=A4L)
        fig.text(0.04, 0.95, title, fontsize=12, weight="bold")
        fig.text(0.04, 0.915, subtitle, fontsize=7.5)
        ax = fig.add_axes([0.04, 0.06, 0.92, 0.82])
        ax.set_xlim(-2600, 7000)
        ax.set_ylim(len(chunk) + 0.5, -0.8)
        ax.axis("off")
        ax.text(-2600, -0.5, "profile  stock  qty", fontsize=7, family="monospace", weight="bold")
        ax.text(0, -0.5, "pattern (piece lengths mm; grey = trim/kerf/offcut)", fontsize=7, weight="bold")
        for i, (prof, L, pieces, qty) in enumerate(chunk):
            ax.text(-2600, i + 0.15, "%-8s %5d  x%-4d" % (prof, L, qty), fontsize=7, family="monospace")
            ax.add_patch(plt.Rectangle((0, i - 0.3), L, 0.6, fc="#dddddd", ec="black", lw=0.4))
            x = trim / 2.0
            for p in pieces:
                ax.add_patch(plt.Rectangle((x, i - 0.3), p, 0.6, fc="#9ecae1", ec="black", lw=0.4))
                ax.text(x + p / 2, i + 0.1, str(p), fontsize=6, ha="center")
                x += p + kerf
            off = L - trim - sum(pieces) - kerf * len(pieces)
            ax.text(L + 60, i + 0.1, "offcut %d" % off, fontsize=6)
        pdf.savefig(fig)
        if png and start == 0:
            fig.savefig(png, dpi=90)
        plt.close(fig)


def cutting_pdf(sheets, out, kerf, trim, preview=None):
    """sheets: [(title, subtitle, groups)]; preview: (index, png_path)."""
    with PdfPages(out, metadata=PDF_META) as pdf:
        for i, (title, subtitle, groups) in enumerate(sheets):
            _bar_page(pdf, title, subtitle, groups, kerf, trim,
                      png=preview[1] if preview and preview[0] == i else None)
