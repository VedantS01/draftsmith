"""Command line interface for draftsmith."""

from __future__ import annotations

import argparse
from pathlib import Path

from draftsmith.renderer import render_doc, render_dxf
from draftsmith.samples import build_sample_floorplan


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="draftsmith",
        description="Natural language to DXF drawings (step 1: DXF renderer).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    render_p = sub.add_parser("render", help="Render a DXF file to PNG/SVG/PDF")
    render_p.add_argument("dxf", type=Path, help="Input DXF file")
    render_p.add_argument(
        "-o", "--output", type=Path, required=True,
        help="Output image path (.png, .svg or .pdf)",
    )
    render_p.add_argument("--dpi", type=int, default=300)
    render_p.add_argument(
        "--dark", action="store_true", help="Render on a black background"
    )

    demo_p = sub.add_parser(
        "demo", help="Generate the sample floorplan DXF and render it"
    )
    demo_p.add_argument(
        "-d", "--dir", type=Path, default=Path("demo"),
        help="Output directory (default: ./demo)",
    )

    args = parser.parse_args(argv)

    if args.command == "render":
        out = render_dxf(args.dxf, args.output, dpi=args.dpi, dark=args.dark)
        print(f"Rendered {args.dxf} -> {out}")
    elif args.command == "demo":
        args.dir.mkdir(parents=True, exist_ok=True)
        doc = build_sample_floorplan()
        dxf_path = args.dir / "floorplan.dxf"
        doc.saveas(dxf_path)
        png = render_doc(doc, args.dir / "floorplan.png")
        svg = render_doc(doc, args.dir / "floorplan.svg")
        print(f"Wrote {dxf_path}, {png}, {svg}")


if __name__ == "__main__":
    main()
