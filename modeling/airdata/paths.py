"""Path helpers.

The code lives in ``modeling/`` (this package's parent) but the data package
lives one level up.  Everything the pipeline writes stays inside ``modeling/``.
"""

from __future__ import annotations

from pathlib import Path

#: Folders that identify the root of the ADA Hack data package.
DATA_MARKERS = ("01_meritve", "02_modeli", "03_vreme_inverzija")

#: The ``modeling/`` folder (parent of the ``airdata`` package).
MODELING_DIR = Path(__file__).resolve().parents[1]


def find_data_root(start: str | Path | None = None) -> Path:
    """Find the data-package root by walking up from *start* (default: cwd)."""
    if start is not None:
        candidate = Path(start).resolve()
        if all((candidate / marker).is_dir() for marker in DATA_MARKERS):
            return candidate
        # A relative --root such as ".." is resolved against the cwd already.
        raise FileNotFoundError(
            f"{candidate} does not look like the data package root "
            f"(missing {', '.join(DATA_MARKERS)})"
        )
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if all((candidate / marker).is_dir() for marker in DATA_MARKERS):
            return candidate
    # Fall back to the folder above modeling/ (the usual layout).
    fallback = MODELING_DIR.parent
    if all((fallback / marker).is_dir() for marker in DATA_MARKERS):
        return fallback
    raise FileNotFoundError(
        "Could not locate the data package (01_meritve/, 02_modeli/, ...). "
        "Pass --root explicitly."
    )


def default_output_dir() -> Path:
    """Default dataset destination, always inside ``modeling/``."""
    return MODELING_DIR / "data" / "processed" / "lj_air_dataset"
