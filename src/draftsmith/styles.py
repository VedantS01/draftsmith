"""Style catalogs: the names of every depiction style, per slot.

Drawing implementations live in :mod:`draftsmith.compiler`; the names
live here (dependency-free) so the scene model and journal can validate
style references without importing the rendering stack. A door, window
or label can carry its own style override, so one floorplan can mix
styles freely; the scene's ``!S`` header only sets the defaults.
"""

from __future__ import annotations

from typing import Callable

from draftsmith.errors import ToolError

WALL_STYLES: tuple[str, ...] = ("plain",)
DOOR_STYLES: tuple[str, ...] = ("arc", "double", "sliding")
WINDOW_STYLES: tuple[str, ...] = ("triple", "frame")

LABEL_FORMATS: dict[str, Callable[[str], str]] = {
    "plain": lambda s: s,
    "caps": str.upper,
    "title": lambda s: s.title(),
}

SLOTS: dict[str, tuple[str, ...]] = {
    "wall": WALL_STYLES,
    "door": DOOR_STYLES,
    "window": WINDOW_STYLES,
    "label": tuple(LABEL_FORMATS),
}


def validate_style(slot: str, name: str | None) -> str | None:
    """Check a style name against its slot's catalog (None = inherit)."""
    if slot not in SLOTS:
        raise ToolError(f"unknown style slot {slot!r}; valid: {sorted(SLOTS)}")
    if name is not None and name not in SLOTS[slot]:
        raise ToolError(
            f"unknown {slot} style {name!r}; available: {sorted(SLOTS[slot])}"
        )
    return name
