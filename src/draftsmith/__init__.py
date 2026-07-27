"""draftsmith: a floorplan scene-graph engine for LLM-agent drafting,
synthetic dataset generation, and DXF tooling."""

from draftsmith.compiler import compile_scene
from draftsmith.dsl import parse, serialize
from draftsmith.errors import ToolError
from draftsmith.renderer import render_dxf
from draftsmith.scene import Scene
from draftsmith.toolkit import Sketch

__version__ = "0.3.0"
__all__ = [
    "Scene",
    "Sketch",
    "ToolError",
    "compile_scene",
    "parse",
    "serialize",
    "render_dxf",
]
