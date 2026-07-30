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
    check_p.add_argument(
        "--save", type=Path, default=None,
        help="Also write the canonical FP1 document to this path",
    )

    prompt_p = sub.add_parser(
        "prompt", help="Print the drafting-agent system prompt"
    )
    prompt_p.add_argument(
        "--design", action="store_true",
        help="Append the design-quality guidelines (what a good plan "
             "looks like) to the prompt",
    )

    eval_p = sub.add_parser(
        "evaluate",
        help="Score a plan: (correctness, compliance, soundness) — the M4 "
             "deterministic metric layers (docs/evaluation.md)",
    )
    eval_p.add_argument(
        "source", type=Path, nargs="?", default=None,
        help="FP1 file (or chat transcript with a ```fp block); "
             "omit to read stdin",
    )
    eval_p.add_argument(
        "--brief", type=Path, default=None,
        help="Brief spec JSON (rooms/areas/adjacent/total_area) to score "
             "compliance against",
    )
    eval_p.add_argument(
        "--json", action="store_true", help="Emit the full report as JSON"
    )

    loop_p = sub.add_parser(
        "loop",
        help="Drive a brief through the phased drafting loop (plan -> "
             "perimeter -> rooms -> refine) with an API model "
             "(DRAFTSMITH_API_* env vars)",
    )
    loop_p.add_argument(
        "request", help="The natural-language brief (or @file to read one)"
    )
    loop_p.add_argument(
        "--brief", type=Path, default=None,
        help="Brief spec JSON to validate the program and score against",
    )
    loop_p.add_argument(
        "--save", type=Path, default=None, help="Write the final FP1 here"
    )
    loop_p.add_argument(
        "--render", type=Path, default=None,
        help="Render the final plan to this image/DXF path",
    )
    loop_p.add_argument(
        "--transcript", type=Path, default=None,
        help="Write the full loop transcript (JSON) here",
    )
    loop_p.add_argument("--rounds", type=int, default=4,
                        help="Rework rounds per phase (default 4)")
    loop_p.add_argument(
        "--no-design", action="store_true",
        help="System prompt without the design guidelines block",
    )

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
    ui_p.add_argument(
        "--chat-model", default="sonnet",
        help="Model for the chat panel's local claude fallback (default: "
        "sonnet). Ignored when DRAFTSMITH_API_BASE/_MODEL select a cloud "
        "OpenAI-compatible API backend (see docs/llm_providers.md)",
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
        if args.save:
            from draftsmith.dsl import serialize

            args.save.write_text(serialize(scene))
            print(f"saved -> {args.save}")
        if args.render:
            from draftsmith.compiler import compile_scene

            sk = compile_scene(scene)
            if args.render.suffix.lower() == ".dxf":
                sk.save(args.render)
            else:
                sk.render(args.render)
            print(f"rendered -> {args.render}")
    elif args.command == "evaluate":
        import json
        import sys

        from draftsmith.agent import extract_fp
        from draftsmith.dsl import parse
        from draftsmith.evaluate import Brief, evaluate

        text = args.source.read_text() if args.source else sys.stdin.read()
        scene = parse(extract_fp(text))
        brief = (
            Brief.from_dict(json.loads(args.brief.read_text()))
            if args.brief else None
        )
        report = evaluate(scene, brief)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(report.render_text())
    elif args.command == "prompt":
        from draftsmith.agent import system_prompt

        print(system_prompt(design=args.design), end="")
    elif args.command == "loop":
        import dataclasses
        import json

        from draftsmith.agent import system_prompt
        from draftsmith.evaluate import Brief
        from draftsmith.loop import DraftingLoop
        from draftsmith.ui.chat import api_runner_from_env

        runner = api_runner_from_env()
        if runner is None:
            raise SystemExit(
                "no API configured - set DRAFTSMITH_API_BASE / "
                "DRAFTSMITH_API_MODEL / DRAFTSMITH_API_KEY")
        runner.system = system_prompt(design=not args.no_design)
        request = args.request
        if request.startswith("@"):
            request = Path(request[1:]).read_text().strip()
        brief = (Brief.from_dict(json.loads(args.brief.read_text()))
                 if args.brief else None)
        loop = DraftingLoop(runner, request, brief,
                            rounds_per_phase=args.rounds, progress=print)
        result = loop.run()
        print(result.summary())
        if result.report is not None:
            print(result.report.render_text())
        if result.scene is not None:
            from draftsmith.dsl import serialize

            if args.save:
                args.save.write_text(serialize(result.scene))
                print(f"saved -> {args.save}")
            if args.render:
                from draftsmith.compiler import compile_scene

                sk = compile_scene(result.scene)
                if args.render.suffix.lower() == ".dxf":
                    sk.save(args.render)
                else:
                    sk.render(args.render)
                print(f"rendered -> {args.render}")
        if args.transcript:
            args.transcript.write_text(json.dumps(
                [dataclasses.asdict(t) for t in result.transcript], indent=1))
            print(f"transcript -> {args.transcript}")
    elif args.command == "ui":
        from draftsmith.ui.server import serve

        server = serve(args.port, args.journal, args.fp_file, chat_model=args.chat_model)
        print(f"draftsmith studio at http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
