from __future__ import annotations

import json
import math
import re
import shutil
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .mapping import (
    note_particle_color_for_note,
    instrument_base_block_for,
    lane_for_note,
    note_block_state_for,
    vanilla_pitch_for,
    vanilla_sound_for,
    volume_for,
)
from .model import CompiledNote, MidiSong, NoteEvent


@dataclass(frozen=True)
class DatapackOptions:
    show_id: str
    out_dir: Path
    # Minecraft Java 1.21.11 uses Data Pack version 94.1. Modern pack.mcmeta
    # writes this as min_format [94, 1] plus max_format 94, matching Mojang's
    # generated 1.21.11 datapacks. Set pack_format for legacy single-integer mcmeta.
    pack_format: int | None = None
    pack_min_format: Any = (94, 1)
    pack_max_format: Any = 94
    tick_rate: int = 20
    mode: str = "command_stage"  # play | command_stage
    gain: float = 1.0
    max_notes_per_tick: int = 24
    zip_output: bool = True
    minecraft_1_21_layout: bool = True


@dataclass(frozen=True)
class DatapackResult:
    pack_dir: Path
    zip_path: Path | None
    namespace: str
    total_ticks: int
    compiled_note_count: int
    parsed_note_count: int


def export_datapack(song: MidiSong, options: DatapackOptions) -> DatapackResult:
    namespace = sanitize_namespace(options.show_id)
    root = options.out_dir / namespace
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    function_dir_name = "function" if options.minecraft_1_21_layout else "functions"
    tag_function_dir_name = "function" if options.minecraft_1_21_layout else "functions"
    ns_function_dir = root / "data" / namespace / function_dir_name
    tags_dir = root / "data" / "minecraft" / "tags" / tag_function_dir_name
    events_dir = ns_function_dir / "events"
    dispatch_dir = ns_function_dir / "dispatch"
    stage_dir = ns_function_dir / "stage"
    for directory in (ns_function_dir, tags_dir, events_dir, dispatch_dir, stage_dir):
        directory.mkdir(parents=True, exist_ok=True)

    compiled = compile_notes(song.notes, options)
    by_tick: Dict[int, List[CompiledNote]] = defaultdict(list)
    for note in compiled:
        by_tick[note.mc_tick].append(note)

    total_ticks = max(1, math.ceil(song.duration_sec * options.tick_rate) + 2)

    _write_pack_mcmeta(root, options, namespace)
    _write_tags(tags_dir, namespace)
    _write_control_functions(ns_function_dir, namespace, options, total_ticks)
    _write_dispatch_functions(dispatch_dir, by_tick, namespace, total_ticks)
    _write_event_functions(events_dir, by_tick, options)
    if options.mode == "command_stage":
        _write_stage_functions(stage_dir, ns_function_dir, namespace)
    _write_readme(root, namespace, options, song, total_ticks)
    _write_manifest(root, namespace, options, song, total_ticks, compiled)

    zip_path = None
    if options.zip_output:
        zip_path = options.out_dir / f"{namespace}.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in root.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(root))

    return DatapackResult(
        pack_dir=root,
        zip_path=zip_path,
        namespace=namespace,
        total_ticks=total_ticks,
        compiled_note_count=len(compiled),
        parsed_note_count=song.note_count,
    )


def compile_notes(notes: Iterable[NoteEvent], options: DatapackOptions) -> List[CompiledNote]:
    compiled: List[CompiledNote] = []
    notes_by_tick: Dict[int, List[NoteEvent]] = defaultdict(list)
    for note in notes:
        mc_tick = max(0, round(note.start_sec * options.tick_rate))
        notes_by_tick[mc_tick].append(note)

    for mc_tick, group in notes_by_tick.items():
        # Prevent one dense tick from spamming hundreds of commands in v0.1.
        group.sort(key=lambda n: (-n.velocity, n.track_index, n.channel, n.note))
        for note in group[: options.max_notes_per_tick]:
            compiled.append(
                CompiledNote(
                    mc_tick=mc_tick,
                    note=note,
                    sound_id=vanilla_sound_for(note),
                    volume=volume_for(note.velocity, options.gain),
                    pitch=vanilla_pitch_for(note.note),
                    lane=lane_for_note(note.note),
                )
            )
    compiled.sort(key=lambda n: (n.mc_tick, n.note.track_index, n.note.channel, n.note.note))
    return compiled


def sanitize_namespace(raw: str) -> str:
    value = raw.strip().lower()
    value = re.sub(r"[^a-z0-9_.-]+", "_", value)
    value = value.strip("._-") or "midi2mc_show"
    return value[:64]


def _write_pack_mcmeta(root: Path, options: DatapackOptions, namespace: str) -> None:
    pack: dict[str, object] = {
        "description": f"midi2mc v0.1.4 datapack for Minecraft Java 1.21.11: {namespace}",
    }
    if options.pack_format is not None:
        pack["pack_format"] = options.pack_format
    else:
        pack["min_format"] = _json_pack_format(options.pack_min_format)
        pack["max_format"] = _json_pack_format(options.pack_max_format)
    data = {"pack": pack}
    (root / "pack.mcmeta").write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _write_tags(tags_dir: Path, namespace: str) -> None:
    (tags_dir / "load.json").write_text(
        json.dumps({"values": [f"{namespace}:load"]}, indent=2), "utf-8"
    )
    (tags_dir / "tick.json").write_text(
        json.dumps({"values": [f"{namespace}:tick"]}, indent=2), "utf-8"
    )


def _write_control_functions(
    fn_dir: Path, namespace: str, options: DatapackOptions, total_ticks: int
) -> None:
    objective = "midi2mc"
    tick_tip = _tick_rate_tip(namespace, options.tick_rate)
    _write_function(
        fn_dir / "load.mcfunction",
        [
            "scoreboard objectives add midi2mc dummy",
            "scoreboard players set $time midi2mc -1",
            "scoreboard players set $playing midi2mc 0",
            "scoreboard players set $loop midi2mc 0",
            f"say [midi2mc] Loaded {namespace}. Run /function {namespace}:setup then /function {namespace}:play",
            tick_tip,
        ],
    )
    tick_lines = [
        "execute if score $playing midi2mc matches 1 run scoreboard players add $time midi2mc 1",
    ]
    if options.mode == "command_stage":
        tick_lines.append(
            "execute if score $playing midi2mc matches 1 run function "
            f"{namespace}:stage/clear"
        )
    tick_lines.extend(
        [
            f"execute if score $playing midi2mc matches 1 run function {namespace}:dispatch/root",
            f"execute if score $time midi2mc matches {total_ticks}.. if score $loop midi2mc matches 1 run function {namespace}:play",
            f"execute if score $time midi2mc matches {total_ticks}.. unless score $loop midi2mc matches 1 run function {namespace}:stop",
        ]
    )
    _write_function(fn_dir / "tick.mcfunction", tick_lines)
    _write_function(
        fn_dir / "play.mcfunction",
        [
            "scoreboard players set $time midi2mc -1",
            "scoreboard players set $playing midi2mc 1",
            f"say [midi2mc] Playing {namespace}",
            tick_tip,
        ],
    )
    _write_function(
        fn_dir / "pause.mcfunction",
        [
            "scoreboard players set $playing midi2mc 0",
            f"say [midi2mc] Paused {namespace}",
        ],
    )
    _write_function(
        fn_dir / "resume.mcfunction",
        [
            "scoreboard players set $playing midi2mc 1",
            f"say [midi2mc] Resumed {namespace}",
        ],
    )
    _write_function(
        fn_dir / "stop.mcfunction",
        [
            "scoreboard players set $playing midi2mc 0",
            "scoreboard players set $time midi2mc -1",
            f"function {namespace}:stage/clear" if options.mode == "command_stage" else "",
            f"say [midi2mc] Stopped {namespace}",
        ],
    )
    _write_function(
        fn_dir / "loop_on.mcfunction",
        ["scoreboard players set $loop midi2mc 1", f"say [midi2mc] Loop on: {namespace}"],
    )
    _write_function(
        fn_dir / "loop_off.mcfunction",
        ["scoreboard players set $loop midi2mc 0", f"say [midi2mc] Loop off: {namespace}"],
    )

    setup_lines = []
    if options.mode == "command_stage":
        setup_lines.extend(
            [
                f"kill @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage]",
                f"summon minecraft:marker ~ ~ ~ {{Tags:[\"midi2mc_stage\",\"midi2mc_{namespace}_stage\"]}}",
                "fill ~-8 ~0 ~0 ~8 ~0 ~0 minecraft:black_concrete",
                "fill ~-8 ~1 ~0 ~8 ~1 ~0 minecraft:note_block",
                "fill ~-8 ~1 ~-1 ~8 ~1 ~-1 minecraft:black_concrete",
                "fill ~-8 ~2 ~0 ~8 ~2 ~0 minecraft:air",
                f"say [midi2mc] Pseudo-redstone note block stage created here for {namespace}",
                tick_tip,
            ]
        )
    else:
        setup_lines.append(f"say [midi2mc] No stage needed for {namespace}; run /function {namespace}:play")
    _write_function(fn_dir / "setup.mcfunction", setup_lines)


def _write_dispatch_functions(
    dispatch_dir: Path, by_tick: Dict[int, List[CompiledNote]], namespace: str, total_ticks: int
) -> None:
    active_ticks = sorted(by_tick)
    chunk_size = 100
    chunks: Dict[int, List[int]] = defaultdict(list)
    for tick in active_ticks:
        chunks[tick // chunk_size].append(tick)

    root_lines = []
    max_chunk = max(chunks.keys(), default=0)
    for chunk in range(max_chunk + 1):
        start = chunk * chunk_size
        end = start + chunk_size - 1
        if chunk in chunks:
            root_lines.append(
                f"execute if score $time midi2mc matches {start}..{end} run function {namespace}:dispatch/{chunk:04d}"
            )
    if not root_lines:
        root_lines.append("# No note events were generated.")
    _write_function(dispatch_dir / "root.mcfunction", root_lines)

    for chunk, ticks in chunks.items():
        lines = [
            f"execute if score $time midi2mc matches {tick} run function {namespace}:events/{tick:06d}"
            for tick in ticks
        ]
        _write_function(dispatch_dir / f"{chunk:04d}.mcfunction", lines)


def _write_event_functions(events_dir: Path, by_tick: Dict[int, List[CompiledNote]], options: DatapackOptions) -> None:
    namespace = sanitize_namespace(options.show_id)
    note_values = [compiled.note.note for notes in by_tick.values() for compiled in notes]
    min_note = min(note_values) if note_values else 21
    max_note = max(note_values) if note_values else 108
    for tick, notes in sorted(by_tick.items()):
        lines: List[str] = []
        for compiled in notes:
            lines.append(
                "execute as @a at @s run playsound "
                f"{compiled.sound_id} master @s ~ ~ ~ {compiled.volume:g} {compiled.pitch:g}"
            )
            if options.mode == "command_stage":
                base_block = instrument_base_block_for(compiled.note)
                note_block = note_block_state_for(compiled.note)
                lines.append(
                    f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] "
                    f"run setblock ~{compiled.lane} ~0 ~0 {base_block}"
                )
                lines.append(
                    f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] "
                    f"run setblock ~{compiled.lane} ~1 ~0 {note_block}"
                )
                lines.append(
                    f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] "
                    f"run setblock ~{compiled.lane} ~1 ~-1 minecraft:redstone_lamp[lit=true]"
                )
                # Vanilla note particles use delta X as a color selector when count=0.
                # Syntax: particle <name> <pos> <delta> <speed> <count> [force|normal]
                note_color = note_particle_color_for_note(compiled.note.note, min_note=min_note, max_note=max_note)
                lines.append(
                    f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] "
                    f"run particle minecraft:note ~{compiled.lane} ~2.2 ~0 {note_color:g} 0 0 1 0 force"
                )
        _write_function(events_dir / f"{tick:06d}.mcfunction", lines)


def _write_stage_functions(stage_dir: Path, fn_dir: Path, namespace: str) -> None:
    _write_function(
        stage_dir / "clear.mcfunction",
        [
            f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run fill ~-8 ~0 ~0 ~8 ~0 ~0 minecraft:black_concrete",
            f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run fill ~-8 ~1 ~0 ~8 ~1 ~0 minecraft:note_block",
            f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run fill ~-8 ~1 ~-1 ~8 ~1 ~-1 minecraft:black_concrete",
            f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run fill ~-8 ~2 ~0 ~8 ~2 ~0 minecraft:air",
        ],
    )


def _write_readme(root: Path, namespace: str, options: DatapackOptions, song: MidiSong, total_ticks: int) -> None:
    tick_command = f"/tick rate {options.tick_rate}"
    reset_command = "/tick rate 20"
    tick_note = (
        "No tick-rate command is needed for vanilla 20 TPS."
        if options.tick_rate == 20
        else f"For best sync, run {tick_command} before playing. After the show, run {reset_command} to restore vanilla speed."
    )
    text = f"""midi2mc v0.1.4 datapack: {namespace}

Install:
1. Put this folder or zip into your world/datapacks folder.
2. Run /reload in the world.
3. Run /function {namespace}:setup where you want the small stage.
4. {tick_note}
5. Run /function {namespace}:play

Controls:
/function {namespace}:play
/function {namespace}:pause
/function {namespace}:resume
/function {namespace}:stop
/function {namespace}:loop_on
/function {namespace}:loop_off

Generated settings:
- target Minecraft: Java 1.21.11
- pack.mcmeta: {"legacy pack_format " + str(options.pack_format) if options.pack_format is not None else "min_format [94, 1] / max_format 94"}
- tick_rate used by compiler: {options.tick_rate}
- suggested command: {tick_command}
- mode: {options.mode}
- MIDI notes parsed: {song.note_count}
- Minecraft duration ticks: {total_ticks}

Pseudo-redstone stage:
- v0.1.4 uses note blocks as the visible player row.
- The block below each note block changes by instrument: guitar uses wool, bit/square wave uses emerald block, bell uses gold block, etc.
- Decorative gold/deepslate framing is removed; setup now keeps only the compact playable core.
- Note pulse particles now use vanilla note-particle color parameters instead of the fixed green default.
- Actual playback still uses playsound so MIDI pitch can exceed the vanilla 25-note note-block range.

Notes:
- v0.1.4 uses vanilla note block sounds, not Soma yet.
- v0.1.4 targets Minecraft Java 1.21.11 by default.
- v0.1.4 uses the Minecraft 1.21+ singular folder layout by default: data/<namespace>/function.
- For older Minecraft versions, re-export with --legacy-1-20 and a matching --pack-format.
"""
    (root / "README.txt").write_text(text, "utf-8")

def _write_manifest(
    root: Path,
    namespace: str,
    options: DatapackOptions,
    song: MidiSong,
    total_ticks: int,
    compiled: List[CompiledNote],
) -> None:
    data = {
        "format": "midi2mc.show.v0.1.4",
        "namespace": namespace,
        "target_minecraft": "Java 1.21.11",
        "pack_format": options.pack_format,
        "pack_min_format": _json_pack_format(options.pack_min_format),
        "pack_max_format": _json_pack_format(options.pack_max_format),
        "tick_rate": options.tick_rate,
        "suggested_tick_command": f"/tick rate {options.tick_rate}",
        "mode": options.mode,
        "duration_seconds": round(song.duration_sec, 3),
        "duration_ticks": total_ticks,
        "midi_notes": song.note_count,
        "compiled_notes": len(compiled),
        "track_names": song.track_names,
    }
    (root / "midi2mc_manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")



def _tick_rate_tip(namespace: str, tick_rate: int) -> str:
    if tick_rate == 20:
        return f"say [midi2mc] Compiled for vanilla 20 TPS. No /tick rate change needed for {namespace}."
    return (
        f"say [midi2mc] Best sync for {namespace}: run /tick rate {tick_rate} before play; "
        "run /tick rate 20 after the show if you want vanilla speed."
    )

def _json_pack_format(value: Any) -> object:
    if isinstance(value, tuple):
        return list(value)
    return value


def _write_function(path: Path, lines: Iterable[str]) -> None:
    cleaned = [line for line in lines if line is not None and str(line).strip()]
    if not cleaned:
        cleaned = ["# empty"]
    path.write_text("\n".join(cleaned) + "\n", "utf-8")
