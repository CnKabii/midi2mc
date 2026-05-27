from __future__ import annotations

from collections import Counter

from ..mapping import note_particle_color_for_note
from ..model import CompiledNote

# Compact Soma concert stage modules, relative to the stage marker.
# v0.5.0 expands the original five-zone stage into a still-compact layered
# layout. It is intentionally decoration-light so users can build around it.
MODULES = {
    # Wider v0.9 spacing: FX now has room to breathe and can follow each module.
    "drums": {"x": -21, "z": 2, "block": "minecraft:iron_block", "label": "DRUMS"},
    "bass": {"x": -15, "z": 2, "block": "minecraft:oak_planks", "label": "BASS"},
    "piano": {"x": -9, "z": 2, "block": "minecraft:smooth_quartz", "label": "PIANO"},
    "guitar": {"x": -3, "z": 2, "block": "minecraft:white_wool", "label": "GUITAR"},
    "strings": {"x": 3, "z": 2, "block": "minecraft:birch_planks", "label": "STRINGS"},
    "wind": {"x": 9, "z": 2, "block": "minecraft:clay", "label": "WIND"},
    "synth": {"x": 15, "z": 2, "block": "minecraft:emerald_block", "label": "SYNTH"},
    "other": {"x": 21, "z": 2, "block": "minecraft:amethyst_block", "label": "OTHER"},
}

def _score_name(module_name: str) -> str:
    # Fake players are global. Keep names short and stable; midi2mc is intended
    # for one active show at a time in these early datapack builds.
    return f"$soma_{module_name}"


def soma_module_for(compiled: CompiledNote) -> str:
    note = compiled.note
    program = note.program
    key = (compiled.instrument_key or "").lower()
    label = (compiled.sound_label or "").lower()
    if note.is_drum or key in {"basedrum", "snare", "hat"} or "drum" in label:
        return "drums"
    if key == "bass" or "bass" in label or 32 <= program <= 39:
        return "bass"
    if key in {"guitar", "banjo"} or "guitar" in label or 24 <= program <= 31 or 104 <= program <= 111:
        return "guitar"
    if "string" in label or "violin" in label or "cello" in label or 40 <= program <= 55:
        return "strings"
    if key == "flute" or "flute" in label or "wind" in label or "sax" in label or "brass" in label or 56 <= program <= 79:
        return "wind"
    if key in {"bit", "chime"} or "synth" in label or "square" in label or 80 <= program <= 103:
        return "synth"
    if key in {"harp", "pling", "bell", "xylophone", "iron_xylophone", "cow_bell"} or program <= 23:
        return "piano"
    return "other"


def soma_concert_setup_lines(namespace: str) -> list[str]:
    lines = [
        f"kill @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage]",
        f"summon minecraft:marker ~ ~ ~ {{Tags:[\"midi2mc_stage\",\"midi2mc_{namespace}_stage\"]}}",
        f"say [midi2mc] Soma spacious layered concert stage created here for {namespace}",
    ]
    lines.extend(soma_concert_reset_lines(namespace))
    for name, module in MODULES.items():
        x = module["x"]
        z = module["z"]
        base = module["block"]
        lines.extend(
            [
                f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run fill ~{x - 1} ~0 ~{z - 1} ~{x + 1} ~0 ~{z + 1} {base}",
                f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~1 ~{z} minecraft:redstone_lamp[lit=false]",
                f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~2 ~{z} minecraft:air",
            ]
        )
    return lines


def soma_concert_reset_lines(namespace: str) -> list[str]:
    lines: list[str] = []
    for name, module in MODULES.items():
        x = module["x"]
        z = module["z"]
        lines.extend(
            [
                f"scoreboard players set {_score_name(name)} midi2mc 0",
                f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~1 ~{z} minecraft:redstone_lamp[lit=false]",
            ]
        )
    return lines or ["# no stage modules"]


def soma_concert_clear_lines(namespace: str) -> list[str]:
    """Refresh short flashes and sustained lights once per tick.

    v0.9.0 intentionally does *not* turn a continuous note on in the same
    tick it starts. The note start only increments the module counter; the
    next tick's clear/refresh pass lights it. If one long note ends exactly
    as another starts, the lamp briefly turns off for that handoff tick instead
    of looking like one overlong unbroken sustain.
    """
    lines: list[str] = []
    for name, module in MODULES.items():
        x = module["x"]
        z = module["z"]
        lines.extend(
            [
                f"execute if score {_score_name(name)} midi2mc matches 1.. at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~1 ~{z} minecraft:redstone_lamp[lit=true]",
                f"execute unless score {_score_name(name)} midi2mc matches 1.. at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~1 ~{z} minecraft:redstone_lamp[lit=false]",
            ]
        )
    return lines or ["# no stage modules"]


def soma_concert_note_lines(compiled: CompiledNote, namespace: str, min_note: int, max_note: int, stage_particles: bool = True) -> list[str]:
    module_name = soma_module_for(compiled)
    module = MODULES[module_name]
    x = module["x"]
    z = module["z"]
    color = note_particle_color_for_note(compiled.note.note, min_note=min_note, max_note=max_note)
    # Velocity gives a tiny vertical boost so strong notes feel more energetic.
    y = 2.1 + min(0.6, max(0, compiled.note.velocity - 64) / 127)
    lines: list[str] = []
    if compiled.used_continuous:
        # Continuous lights are intentionally delayed until the next tick's
        # clear/refresh pass. This creates a visible articulation gap when
        # back-to-back long notes share a module.
        lines.append(f"scoreboard players add {_score_name(module_name)} midi2mc 1")
    else:
        lines.append(
            f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~1 ~{z} minecraft:redstone_lamp[lit=true]"
        )
    if stage_particles:
        lines.append(
            f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run particle minecraft:note ~{x} ~{y:.2f} ~{z} {color:g} 0 0 1 0 force"
        )
    return lines


def soma_concert_stop_lines(compiled: CompiledNote, namespace: str) -> list[str]:
    if not compiled.used_continuous:
        return []
    module_name = soma_module_for(compiled)
    module = MODULES[module_name]
    x = module["x"]
    z = module["z"]
    return [
        f"execute if score {_score_name(module_name)} midi2mc matches 1.. run scoreboard players remove {_score_name(module_name)} midi2mc 1",
        f"execute unless score {_score_name(module_name)} midi2mc matches 1.. at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~1 ~{z} minecraft:redstone_lamp[lit=false]",
    ]


def soma_stage_usage_report(compiled: list[CompiledNote]) -> dict[str, object]:
    counter = Counter(soma_module_for(note) for note in compiled if note.sound_engine == "soma")
    sustained = Counter(soma_module_for(note) for note in compiled if note.sound_engine == "soma" and note.used_continuous)
    return {
        "profile": "soma_concert",
        "layout": "spacious_v0.9",
        "modules": {name: counter.get(name, 0) for name in MODULES},
        "sustained_modules": {name: sustained.get(name, 0) for name in MODULES},
        "module_count": len(MODULES),
        "module_positions": {name: {"x": module["x"], "z": module["z"]} for name, module in MODULES.items()},
        "sustained_light_policy": "continuous_notes_light_from_next_tick_until_note_off_with_handoff_gap",
    }
