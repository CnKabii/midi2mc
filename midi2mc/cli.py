from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .export_datapack import DatapackOptions, export_datapack, sanitize_namespace
from .interactive import run_interactive_wizard
from .midi import MidiParseError, parse_midi
from .recommend import TickRateRecommendation, recommend_tick_rate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="midi2mc",
        description="Convert a MIDI file into a Minecraft Java 1.21.11 datapack music show.",
    )
    parser.add_argument("midi", nargs="?", help="Input .mid/.midi file. If omitted, starts the interactive wizard.")
    parser.add_argument("--interactive", "-i", action="store_true", help="Start the interactive wizard.")
    parser.add_argument("--out", default="output", help="Output directory. Default: output")
    parser.add_argument("--show-id", help="Datapack namespace/show id. Default: MIDI file name")
    parser.add_argument(
        "--mode",
        choices=["play", "command_stage"],
        default="command_stage",
        help="Output mode. Default: command_stage",
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
        "--gain",
        type=float,
        default=1.0,
        help="Sound volume multiplier. Default: 1.0",
    )
    parser.add_argument(
        "--max-notes-per-tick",
        type=int,
        default=24,
        help="Safety cap for very dense MIDI chords. Default: 24",
    )
    parser.add_argument("--no-zip", action="store_true", help="Do not create a .zip datapack")
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

    if args.interactive or not args.midi:
        return run_interactive_wizard(args)

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

    show_id = args.show_id or sanitize_namespace(path.stem)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        song = parse_midi(path)
    except MidiParseError as exc:
        print(f"[midi2mc] MIDI parse failed: {exc}", file=sys.stderr)
        return 1

    recommendation = recommend_tick_rate(song)
    try:
        tick_rate = _resolve_tick_rate(args.tick_rate, recommendation)
    except ValueError as exc:
        print(f"[midi2mc] {exc}", file=sys.stderr)
        return 2

    options = DatapackOptions(
        show_id=show_id,
        out_dir=out_dir,
        pack_format=args.pack_format,
        tick_rate=tick_rate,
        mode=args.mode,
        gain=args.gain,
        max_notes_per_tick=args.max_notes_per_tick,
        zip_output=not args.no_zip,
        minecraft_1_21_layout=not args.legacy_1_20,
    )
    result = export_datapack(song, options)

    print_summary(result, song.duration_sec, tick_rate, recommendation)
    return 0


def print_summary(result, duration_sec: float, tick_rate: int, recommendation: TickRateRecommendation | None = None) -> None:
    print("[midi2mc] Done!")
    print(f"  target: Minecraft Java 1.21.11")
    print(f"  show id: {result.namespace}")
    print(f"  notes: {result.parsed_note_count} parsed / {result.compiled_note_count} compiled")
    print(f"  duration: {duration_sec:.2f}s / {result.total_ticks} ticks @ {tick_rate} TPS")
    if recommendation:
        print(f"  BPM hint: {recommendation.primary_bpm:.2f} BPM dominant; recommended /tick rate {recommendation.tick_rate}")
        print(f"  timing: quarter={recommendation.beat_ticks:.2f} ticks, eighth={recommendation.eighth_ticks:.2f}, sixteenth={recommendation.sixteenth_ticks:.2f}")
    print(f"  datapack folder: {result.pack_dir}")
    if result.zip_path:
        print(f"  datapack zip: {result.zip_path}")
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
