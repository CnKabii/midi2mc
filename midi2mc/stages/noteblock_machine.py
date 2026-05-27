from __future__ import annotations

from collections import Counter

from ..mapping import instrument_base_block_for, instrument_key_for, note_block_state_for, note_particle_color_for_note
from ..model import CompiledNote

# v0.9 widens the pseudo-redstone machine and spreads instruments into rough
# groups. It is still decoration-light: users can build their own shell around
# this core playable area.
WIDE_LEFT = -18
WIDE_RIGHT = 18

INSTRUMENT_GROUP_LANES = {
    "basedrum": -17,
    "snare": -15,
    "hat": -13,
    "bass": -10,
    "harp": -3,
    "pling": -1,
    "bell": 3,
    "xylophone": 5,
    "iron_xylophone": 7,
    "guitar": 10,
    "banjo": 12,
    "flute": 14,
    "chime": 16,
    "bit": 18,
    "cow_bell": 6,
    "didgeridoo": -11,
}


def noteblock_lane_for(compiled: CompiledNote) -> int:
    """Return a spacious v0.9 lane for the visual note-block machine.

    Drums and bass stay left, keyboard-like instruments occupy the center, and
    guitars/synths/winds move right. Piano/harp notes get a little pitch-based
    spread so dense melodies do not stack on one block.
    """
    key = instrument_key_for(compiled.note)
    if key == "harp":
        # Center keyboard strip: -7..7 by pitch.
        return -7 + (compiled.note.note % 15)
    base = INSTRUMENT_GROUP_LANES.get(key, compiled.lane)
    # Tiny per-channel nudge helps type-1 MIDI files with duplicated programs.
    if key not in {"basedrum", "snare", "hat"}:
        base += (compiled.note.channel % 3) - 1
    return max(WIDE_LEFT, min(WIDE_RIGHT, base))


def noteblock_setup_lines(namespace: str) -> list[str]:
    return [
        f"kill @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage]",
        f"summon minecraft:marker ~ ~ ~ {{Tags:[\"midi2mc_stage\",\"midi2mc_{namespace}_stage\"]}}",
        f"fill ~{WIDE_LEFT} ~0 ~0 ~{WIDE_RIGHT} ~0 ~0 minecraft:black_concrete",
        f"fill ~{WIDE_LEFT} ~1 ~0 ~{WIDE_RIGHT} ~1 ~0 minecraft:note_block",
        f"fill ~{WIDE_LEFT} ~1 ~-1 ~{WIDE_RIGHT} ~1 ~-1 minecraft:black_concrete",
        f"fill ~{WIDE_LEFT} ~2 ~0 ~{WIDE_RIGHT} ~2 ~0 minecraft:air",
        f"say [midi2mc] Spacious pseudo-redstone note block stage created here for {namespace}",
    ]


def noteblock_clear_lines(namespace: str) -> list[str]:
    return [
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run fill ~{WIDE_LEFT} ~0 ~0 ~{WIDE_RIGHT} ~0 ~0 minecraft:black_concrete",
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run fill ~{WIDE_LEFT} ~1 ~0 ~{WIDE_RIGHT} ~1 ~0 minecraft:note_block",
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run fill ~{WIDE_LEFT} ~1 ~-1 ~{WIDE_RIGHT} ~1 ~-1 minecraft:black_concrete",
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run fill ~{WIDE_LEFT} ~2 ~0 ~{WIDE_RIGHT} ~2 ~0 minecraft:air",
    ]


def stage_note_lines(compiled: CompiledNote, namespace: str, min_note: int, max_note: int, stage_particles: bool = True) -> list[str]:
    """Return pseudo-redstone note-block stage commands for one note."""
    base_block = instrument_base_block_for(compiled.note)
    note_block = note_block_state_for(compiled.note)
    note_color = note_particle_color_for_note(compiled.note.note, min_note=min_note, max_note=max_note)
    lane = noteblock_lane_for(compiled)
    lines = [
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{lane} ~0 ~0 {base_block}",
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{lane} ~1 ~0 {note_block}",
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{lane} ~1 ~-1 minecraft:redstone_lamp[lit=true]",
    ]
    if stage_particles:
        lines.append(
            f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run particle minecraft:note ~{lane} ~2.2 ~0 {note_color:g} 0 0 1 0 force"
        )
    return lines


def noteblock_stage_usage_report(compiled: list[CompiledNote]) -> dict[str, object]:
    instruments = Counter(instrument_key_for(note.note) for note in compiled if note.sound_engine == "vanilla")
    channels = Counter(str(note.note.channel + 1) for note in compiled if note.sound_engine == "vanilla")
    return {
        "profile": "noteblock_machine",
        "layout": "spacious_v0.9",
        "lane_range": [WIDE_LEFT, WIDE_RIGHT],
        "instrument_groups": dict(instruments),
        "channel_groups": dict(channels),
        "policy": "drums/bass left, keyboard center, guitar/wind/synth right; harp notes spread by pitch",
    }
