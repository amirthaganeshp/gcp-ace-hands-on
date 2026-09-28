"""Shared figure style, so every example in the repository looks like one repository.

    from plotting import use_house_style, save_figure, PALETTE

    use_house_style()
    fig, ax = plt.subplots()
    ...
    save_figure(fig, "outputs/my_figure.png")

The palette is Okabe-Ito, which stays distinguishable under all common forms of
colour vision deficiency. Figures are saved, never shown - these scripts are meant
to run unattended.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed; scripts save rather than show
import matplotlib.pyplot as plt  # noqa: E402

# Okabe-Ito - colour-vision-deficiency safe
PALETTE = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "green": "#009E73",
    "vermillion": "#D55E00",
    "sky": "#56B4E9",
    "pink": "#CC79A7",
    "yellow": "#F0E442",
    "black": "#000000",
    "grey": "#8C8C8C",
}

CYCLE = [PALETTE[k] for k in ("blue", "vermillion", "green", "orange", "pink", "sky")]


def use_house_style() -> None:
    """Apply the repository's figure style. Call once, near the top of a script."""
    plt.rcParams.update(
        {
            "figure.figsize": (9, 5.5),
            "figure.dpi": 110,
            "savefig.dpi": 140,
            "savefig.bbox": "tight",
            "font.size": 10.5,
            "axes.titlesize": 12.5,
            "axes.titleweight": "bold",
            "axes.labelsize": 10.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": "#DDDDDD",
            "grid.linewidth": 0.8,
            "legend.frameon": False,
            "lines.linewidth": 2.0,
            "lines.markersize": 5,
            "axes.prop_cycle": plt.cycler(color=CYCLE),
        }
    )


def save_figure(fig, path: str | Path, close: bool = True) -> Path:
    """Save a figure, creating the directory if needed. Returns the path."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    if close:
        plt.close(fig)
    return out
