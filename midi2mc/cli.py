from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .export_datapack import DatapackOptions, export_datapack, sanitize_namespace
from .interactive import run_interactive_wizard
from .midi import MidiParseError, parse_midi
from .recommend import TickRateRecommendation, recommend_tick_rate
from .quality import quality_choices, quality_profile
from .project import load_project_namespace, write_project_template
from .preset_profiles import apply_preset, preset_choices, PRESETS
from .summary import format_midi_summary_lines, warning_lines
from .safety import analyze_safety, format_safety_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="midi2mc",
        description="Convert a MIDI file into a Minecraft Java 1.21.11 datapack music show.",
    )
    parser.add_argument("midi", nargs="?", help="Input .mid/.midi file. If omitted, starts the interactive wizard unless --project is used.")
    parser.add_argument("--project", help="Load a .m2mc.json project config. Paths inside the JSON are resolved relative to the project file.")
    parser.add_argument("--write-project-template", metavar="PATH", help="Write an example .m2mc.json project config and exit.")
    parser.add_argument("--preset", choices=preset_choices(), default=None, help="Apply a built-in style preset, e.g. vanilla_machine, vanilla_fx, vanilla_safe, soma_concert.")
    parser.add_argument("--list-presets", action="store_true", help="List built-in presets and exit.")
    parser.add_argument("--interactive", "-i", action="store_true", help="Start the interactive wizard.")
    parser.add_argument("--gui", action="store_true", help="Start the simple local tkinter GUI.")
    parser.add_argument("--out", default="output", help="Output directory. Default: output")
    parser.add_argument("--show-id", help="Datapack namespace/show id. Default: MIDI file name")
    parser.add_argument(
        "--mode",
        choices=["play", "command_stage"],
        default="command_stage",
        help="Output mode. Default: command_stage",
    )
    parser.add_argument(
        "--sound-engine",
        choices=["vanilla", "soma"],
        default="vanilla",
        help="Sound engine. vanilla uses Minecraft note block sounds; soma uses a Soma resource-pack preset. Default: vanilla",
    )
    parser.add_argument(
        "--stage-profile",
        default="auto",
        help="Stage profile. Use auto, noteblock_machine, or soma_concert. Default: auto",
    )
    parser.add_argument(
        "--stage-layout",
        choices=["auto", "compact", "wide", "huge"],
        default="auto",
        help="Vanilla noteblock_machine layout. auto chooses compact/wide/huge from MIDI content. Default: auto",
    )
    parser.add_argument(
        "--stage-template",
        choices=["pulse", "classic_line", "minimal"],
        default="pulse",
        help="Vanilla noteblock_machine stage template. pulse=default transient modules; classic_line=one-row machine; minimal=marker/particle-only. Default: pulse",
    )

    parser.add_argument(
        "--module-hold-ticks",
        type=int,
        default=0,
        help="Vanilla Pulse Stage module hold ticks. 0=auto; try 2-12 for custom pulse length. Default: 0",
    )
    parser.add_argument(
        "--soma-namespace",
        default="",
        help="Deprecated compatibility option. Soma v20 sound events are emitted without a namespace, e.g. 2.66.",
    )
    parser.add_argument(
        "--soma-map",
        default=None,
        help="Optional JSON file overriding the built-in Soma v20 program map.",
    )
    parser.add_argument(
        "--soma-reference-note",
        type=int,
        default=60,
        help="Compatibility option for old/simple Soma maps. Ignored by the built-in v20 map. Default: 60 (C4)",
    )
    parser.add_argument(
        "--soma-long-note-beats",
        type=float,
        default=1.0,
        help="For Soma v20, notes at least this many MIDI beats long use the c/continuous sound and get stopsound at note-off. Default: 1.0",
    )
    parser.add_argument(
        "--soma-drum-kit",
        choices=["auto", "normal", "electronic", "percussion"],
        default="auto",
        help="Soma v20 drum mapping. auto uses 0/0e/0p variants by drum type; normal forces v0.11-style 0.* drums. Default: auto",
    )
    parser.add_argument(
        "--tick-rate",
        default="auto",
        help="Compiler timebase TPS. Use an integer or 'auto'. Default: auto",
    )
    parser.add_argument(
        "--pack-format",
        type=int,
        default=None,
        help=(
            "Legacy pack.mcmeta pack_format override. For Minecraft 1.21.11, leave this unset; "
            "midi2mc will write min_format [94, 1] and max_format 94."
        ),
    )
    parser.add_argument(
        "--safe-mode",
        action="store_true",
        help="Apply conservative defaults for large/dense MIDI: low quality, 8 notes/tick, no stage particles, no Piano Roll, no Show FX.",
    )
    parser.add_argument(
        "--quality",
        choices=quality_choices(),
        default="medium",
        help="Quality/performance preset. low=8 notes/tick and no stage particles; medium=24; high=48; insane=96. Default: medium",
    )
    parser.add_argument(
        "--no-stage-particles",
        action="store_true",
        help="Disable visual note particles on command_stage outputs. Lamps/sound still work.",
    )
    roll_group = parser.add_mutually_exclusive_group()
    roll_group.add_argument(
        "--piano-roll",
        dest="piano_roll",
        action="store_true",
        help="Enable the lightweight particle piano-roll visualizer on command_stage outputs.",
    )
    roll_group.add_argument(
        "--no-piano-roll",
        dest="piano_roll",
        action="store_false",
        help="Disable the particle piano-roll visualizer.",
    )
    parser.set_defaults(piano_roll=None)
    parser.add_argument(
        "--show-fx",
        choices=["auto", "none", "lightshow", "fireworks", "both"],
        default="auto",
        help="FX layers. auto=lightshow for command-stage outputs except low quality; fireworks uses particle bursts, not real firework entities. Default: auto",
    )
    parser.add_argument(
        "--fx-profile",
        choices=["clean", "redstone", "concert", "magic"],
        default="concert",
        help="Visual style for Show FX. clean=subtle dust; redstone=electric sparks/warm dust; concert=colorful dust/end_rod accents; magic=purple dust/enchant/portal accents. Default: concert",
    )
    parser.add_argument(
        "--gain",
        type=float,
        default=1.0,
        help="Sound volume multiplier. Default: 1.0",
    )

    parser.add_argument(
        "--fx-intensity",
        type=float,
        default=1.0,
        help="Global Show FX intensity multiplier. 0.25=subtle, 1.0=default, 2.0=strong. Default: 1.0",
    )
    parser.add_argument(
        "--fx-layers",
        default="all",
        help="Comma-separated FX layers: all, note,drum,bass,chord,beat,lead,fireworks,finale. Default: all",
    )
    parser.add_argument(
        "--max-notes-per-tick",
        type=int,
        default=None,
        help="Safety cap for very dense MIDI chords. Default comes from --quality.",
    )
    parser.add_argument("--no-zip", action="store_true", help="Do not create a .zip datapack")
    parser.add_argument("--no-report", action="store_true", help="Do not generate report.html")
    parser.add_argument(
        "--legacy-1-20",
        action="store_true",
        help="Use pre-1.21 plural folders: data/<namespace>/functions and tags/functions.",
    )
    parser.add_argument("--version", action="version", version=f"midi2mc {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.gui:
        from .gui import run_gui
        return run_gui()

    if args.list_presets:
        print("Built-in midi2mc presets:")
        for name, profile in PRESETS.items():
            print(f"  {name:18s} {profile.label} - {profile.description}")
        return 0

    if args.write_project_template:
        path = write_project_template(Path(args.write_project_template))
        print(f"[midi2mc] Project template written: {path}")
        return 0

    if args.project:
        try:
            project_args = load_project_namespace(Path(args.project), args)
        except (FileNotFoundError, ValueError) as exc:
            print(f"[midi2mc] {exc}", file=sys.stderr)
            return 2
        project_args = apply_preset(project_args)
        print(f"[midi2mc] Loaded project config: {Path(args.project)}")
        if getattr(project_args, "preset", None):
            print(f"[midi2mc] Preset: {project_args.preset}")
        return run_export_from_args(project_args)

    if args.interactive or not args.midi:
        return run_interactive_wizard(args)

    args = apply_preset(args)
    return run_export_from_args(args)


def _resolve_tick_rate(raw: str | int, recommendation: TickRateRecommendation) -> int:
    text = str(raw).strip().lower()
    if text in {"", "auto", "a"}:
        return recommendation.tick_rate
    try:
        value = int(text)
    except ValueError as exc:
        raise ValueError("--tick-rate must be an integer or 'auto'") from exc
    if not (1 <= value <= 240):
        raise ValueError("--tick-rate must be between 1 and 240")
    return value


def run_export_from_args(args: argparse.Namespace) -> int:
    path = Path(args.midi)
    if not path.exists():
        print(f"[midi2mc] MIDI file not found: {path}", file=sys.stderr)
        return 2

    requested_show_id = args.show_id or path.stem
    show_id = sanitize_namespace(requested_show_id)
    if show_id != str(requested_show_id).strip().lower():
        print(f"[midi2mc] Show ID sanitized to: {show_id}")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        song = parse_midi(path)
    except MidiParseError as exc:
        _print_parse_error(path, exc)
        return 1

    recommendation = recommend_tick_rate(song)
    try:
        tick_rate = _resolve_tick_rate(args.tick_rate, recommendation)
    except ValueError as exc:
        print(f"[midi2mc] {exc}", file=sys.stderr)
        return 2

    effective_quality = "low" if getattr(args, "safe_mode", False) else args.quality
    profile = quality_profile(effective_quality)
    max_notes_per_tick = args.max_notes_per_tick if args.max_notes_per_tick is not None else profile.max_notes_per_tick
    stage_particles = (not args.no_stage_particles) and profile.stage_particles
    piano_roll = profile.piano_roll if args.piano_roll is None else bool(args.piano_roll)
    show_fx = args.show_fx
    if getattr(args, "safe_mode", False):
        max_notes_per_tick = min(max_notes_per_tick, profile.max_notes_per_tick)
        stage_particles = False
        piano_roll = False
        show_fx = "none"
    if args.mode != "command_stage":
        piano_roll = False
        show_fx = "none"

    options = DatapackOptions(
        show_id=show_id,
        out_dir=out_dir,
        pack_format=args.pack_format,
        tick_rate=tick_rate,
        mode=args.mode,
        gain=args.gain,
        sound_engine=args.sound_engine,
        stage_profile=args.stage_profile,
        stage_layout=args.stage_layout,
        stage_template=getattr(args, "stage_template", "pulse"),
        module_hold_ticks=max(0, int(getattr(args, "module_hold_ticks", 0) or 0)),
        soma_namespace=args.soma_namespace,
        soma_map=Path(args.soma_map) if args.soma_map else None,
        soma_reference_note=args.soma_reference_note,
        soma_long_note_beats=args.soma_long_note_beats,
        soma_drum_kit=args.soma_drum_kit,
        quality=profile.name,
        safe_mode=bool(getattr(args, "safe_mode", False)),
        max_notes_per_tick=max_notes_per_tick,
        stage_particles=stage_particles,
        piano_roll=piano_roll,
        show_fx=show_fx,
        fx_profile=getattr(args, "fx_profile", "concert"),
        fx_intensity=max(0.0, min(3.0, float(getattr(args, "fx_intensity", 1.0) or 1.0))),
        fx_layers=str(getattr(args, "fx_layers", "all") or "all"),
        preset=getattr(args, "preset", None),
        html_report=not getattr(args, "no_report", False),
        zip_output=not args.no_zip,
        minecraft_1_21_layout=not args.legacy_1_20,
    )
    safety = analyze_safety(song, tick_rate=tick_rate, max_notes_per_tick=max_notes_per_tick, quality=profile.name, mode=args.mode, sound_engine=args.sound_engine, stage_profile=args.stage_profile, show_fx=show_fx, piano_roll=piano_roll)
    if getattr(args, "safe_mode", False) or safety.level in {"medium", "high", "critical"}:
        print("\n[midi2mc] 安全评估:")
        print(format_safety_report(safety))

    result = export_datapack(song, options)

    print_summary(result, song.duration_sec, tick_rate, recommendation, song=song, max_notes_per_tick=max_notes_per_tick)
    return 0


def _print_parse_error(path: Path, exc: MidiParseError) -> None:
    print(f"[midi2mc] MIDI parse failed: {path}", file=sys.stderr)
    print(f"  reason: {exc}", file=sys.stderr)
    print("  tips:", file=sys.stderr)
    print("    - 确认输入的是 .mid/.midi 标准 MIDI 文件，不是 mp3/wav/ogg。", file=sys.stderr)
    print("    - 当前 v3.0.0 支持 PPQ/ticks-per-quarter MIDI，不支持 SMPTE division。", file=sys.stderr)
    print("    - 可以先用 examples/demo_scale.mid 测试环境是否正常。", file=sys.stderr)


def print_summary(result, duration_sec: float, tick_rate: int, recommendation: TickRateRecommendation | None = None, song=None, max_notes_per_tick: int = 24) -> None:
    print("[midi2mc] Done!")
    print(f"  target: Minecraft Java 1.21.11")
    print(f"  show id: {result.namespace}")
    print(f"  notes: {result.parsed_note_count} parsed / {result.compiled_note_count} compiled")
    print(f"  duration: {duration_sec:.2f}s / {result.total_ticks} ticks @ {tick_rate} TPS")
    if song is not None:
        print("")
        for line in format_midi_summary_lines(song, recommendation, tick_rate, max_notes_per_tick):
            print(line)
        warnings = warning_lines(song, tick_rate, max_notes_per_tick)
        if warnings:
            print("\n风险提示:")
            for line in warnings:
                print(f"  - {line}")
    elif recommendation:
        print(f"  BPM hint: {recommendation.primary_bpm:.2f} BPM dominant; recommended /tick rate {recommendation.tick_rate}")
        print(f"  timing: quarter={recommendation.beat_ticks:.2f} ticks, eighth={recommendation.eighth_ticks:.2f}, sixteenth={recommendation.sixteenth_ticks:.2f}")
    print(f"\n  datapack folder: {result.pack_dir}")
    if result.zip_path:
        print(f"  datapack zip: {result.zip_path}")
    print(f"  how-to file: {result.pack_dir.parent / (result.namespace + '_HOW_TO_PLAY.txt')}")
    report_path = result.pack_dir / "report.html"
    if report_path.exists():
        print(f"  html report: {report_path}")
    print("\nIn Minecraft 1.21.11:")
    print("  /reload")
    print(f"  /function {result.namespace}:setup")
    if tick_rate != 20:
        print(f"  /tick rate {tick_rate}")
    print(f"  /function {result.namespace}:play")
    if tick_rate != 20:
        print("  # after the show: /tick rate 20")


if __name__ == "__main__":
    raise SystemExit(main())
