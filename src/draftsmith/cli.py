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

    compile_p = sub.add_parser(
        "compile", help="Compile an FP1 scene file (.fp) to DXF or an image"
    )
    compile_p.add_argument("scene", type=Path, help="Input .fp file (FP1 format)")
    compile_p.add_argument(
        "-o", "--output", type=Path, required=True, action="append",
        help="Output path (.dxf, .png, .svg or .pdf); repeatable",
    )

    check_p = sub.add_parser(
        "check",
        help="Validate FP1 (file or stdin, fenced chat blocks OK) and print "
             "engine feedback for the agent loop",
    )
    check_p.add_argument(
        "source", type=Path, nargs="?", default=None,
        help="FP1 file (or chat transcript containing a ```fp block); "
             "omit to read stdin",
    )
    check_p.add_argument(
        "--render", type=Path, default=None,
        help="Also render the plan to this image/DXF path",
    )

    sub.add_parser("prompt", help="Print the drafting-agent system prompt")

    ui_p = sub.add_parser("ui", help="Launch draftsmith studio (local web app)")
    ui_p.add_argument("--port", type=int, default=8765)
    ui_p.add_argument(
        "--journal", type=Path, default=None,
        help="JSONL action journal to record to (and resume from, if it exists)",
    )
    ui_p.add_argument(
        "--open", dest="fp_file", type=Path, default=None,
        help="FP1 file to load on start",
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
    elif args.command == "compile":
        from draftsmith.compiler import compile_scene
        from draftsmith.dsl import parse

        sk = compile_scene(parse(args.scene.read_text()))
        for out in args.output:
            if out.suffix.lower() == ".dxf":
                sk.save(out)
            else:
                sk.render(out)
            print(f"Wrote {out}")
    elif args.command == "check":
        import sys

        from draftsmith.agent import check

        text = args.source.read_text() if args.source else sys.stdin.read()
        scene, report = check(text)
        print(report)
        if scene is None:
            raise SystemExit(1)
        if args.render:
            from draftsmith.compiler import compile_scene

            sk = compile_scene(scene)
            if args.render.suffix.lower() == ".dxf":
                sk.save(args.render)
            else:
                sk.render(args.render)
            print(f"rendered -> {args.render}")
    elif args.command == "prompt":
        from draftsmith.agent import system_prompt

        print(system_prompt(), end="")
    elif args.command == "ui":
        from draftsmith.ui.server import serve

        server = serve(args.port, args.journal, args.fp_file)
        print(f"draftsmith studio at http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
