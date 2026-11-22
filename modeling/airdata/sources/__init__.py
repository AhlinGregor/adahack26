"""Registry of all input sources."""

from __future__ import annotations

from . import arso_live, arso_pm, calibrated, cams, camx, eea, gral, purpleair, sensor_community
from .base import SourceSpec, Task

#: Deterministic processing / output order.
ALL_SPECS: tuple[SourceSpec, ...] = (
    arso_pm.SPEC,
    arso_live.SPEC,
    eea.SPEC,
    purpleair.SPEC,
    sensor_community.SPEC,
    calibrated.SPEC,
    cams.SPEC,
    cams.FORECAST_SPEC,
    camx.SPEC,
    gral.SPEC,
)

SOURCE_NAMES: tuple[str, ...] = tuple(spec.name for spec in ALL_SPECS)

BY_NAME: dict[str, SourceSpec] = {spec.name: spec for spec in ALL_SPECS}

GROUPS: dict[str, tuple[str, ...]] = {
    "all": SOURCE_NAMES,
    "measurements": tuple(spec.name for spec in ALL_SPECS if spec.value_type == "measurement"),
    "models": tuple(spec.name for spec in ALL_SPECS if spec.value_type == "model"),
    "estimates": tuple(spec.name for spec in ALL_SPECS if spec.value_type == "estimate"),
}


def resolve_sources(sources: str | None = None, exclude: str | None = None) -> list[SourceSpec]:
    """Resolve a comma-separated source list (or group name) into specs."""
    if not sources or sources.strip().lower() in ("all", "default"):
        names = list(GROUPS["all"])
    else:
        names = []
        for token in sources.split(","):
            token = token.strip().lower()
            if not token:
                continue
            if token in GROUPS:
                names.extend(GROUPS[token])
            elif token in BY_NAME:
                names.append(token)
            else:
                raise ValueError(
                    f"Unknown source {token!r}. Available: {', '.join(SOURCE_NAMES)} "
                    f"(groups: {', '.join(GROUPS)})"
                )
    if exclude:
        blocked = {t.strip().lower() for t in exclude.split(",") if t.strip()}
        names = [n for n in names if n not in blocked]
    # de-duplicate while keeping order
    seen: set[str] = set()
    ordered = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return [BY_NAME[n] for n in ordered]


__all__ = [
    "ALL_SPECS",
    "BY_NAME",
    "GROUPS",
    "SOURCE_NAMES",
    "SourceSpec",
    "Task",
    "resolve_sources",
]
