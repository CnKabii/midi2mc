from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math

from ..mapping import instrument_base_block_for, instrument_key_for, note_block_state_for, note_particle_color_for_note
from ..model import CompiledNote
from ..recommend import primary_bpm
from ..model import MidiSong

# v2.8 keeps the vanilla pseudo-redstone machine as the flagship stage.
# Pulse Stage: setup stays sparse; triggered note modules remain visible
# briefly for a few ticks before event-level cleanup. The old moving playhead
# and actionbar Bar/Beat text stay removed; beat lamps carry timing. v2.8
# improves vanilla instrument placement and gives drums readable sub-zones.

GROUP_ORDER = ["drums", "bass", "keyboard", "bells", "guitar", "wind_synth"]
GROUP_LABELS = {
    "drums": "drums",
    "bass": "bass",
    "keyboard": "keyboard",
    "bells": "bells/mallets",
    "guitar": "guitar/banjo",
    "wind_synth": "wind/synth",
}

# Keep visual modules visible long enough to read, without accumulating into a
# full note-block carpet. Long notes can hold a little longer, but are capped.
PULSE_HOLD_TICKS = 4
PULSE_LONG_HOLD_TICKS = 8
STAGE_TEMPLATE_CHOICES = ["pulse", "classic_line", "minimal"]


def normalize_stage_template(template: str | None) -> str:
    value = (template or "pulse").strip().lower().replace("-", "_")
    return value if value in STAGE_TEMPLATE_CHOICES else "pulse"

# Canonical mapping from vanilla note-block instruments to visual rows.
INSTRUMENT_GROUPS: dict[str, str] = {
    "basedrum": "drums",
    "snare": "drums",
    "hat": "drums",
    "bass": "bass",
    "didgeridoo": "bass",
    "harp": "keyboard",
    "pling": "keyboard",
    "bell": "bells",
    "xylophone": "bells",
    "iron_xylophone": "bells",
    "cow_bell": "bells",
    "guitar": "guitar",
    "banjo": "guitar",
    "flute": "wind_synth",
    "chime": "wind_synth",
    "bit": "wind_synth",
}


@dataclass(frozen=True)
class BeatInfo:
    primary_bpm: float
    beat_ticks: int
    bar_ticks: int
    beats_per_bar: int = 4

    @property
    def policy(self) -> str:
        return f"4/4 meter estimated from primary BPM {self.primary_bpm:.2f}; quarter note = {self.beat_ticks} MC ticks"


def resolve_beat_info(song: MidiSong | None = None, tick_rate: int = 20) -> BeatInfo:
    bpm = primary_bpm(song) if song is not None else 120.0
    beat_ticks = max(1, int(round(float(tick_rate) * 60.0 / max(1.0, bpm))))
    return BeatInfo(primary_bpm=bpm, beat_ticks=beat_ticks, bar_ticks=beat_ticks * 4)


@dataclass(frozen=True)
class NoteblockLayout:
    name: str
    requested: str
    template: str
    left: int
    right: int
    rows: dict[str, int]
    beat_z: int
    control_z: int
    reason: str

    @property
    def width(self) -> int:
        return self.right - self.left + 1

    @property
    def stage_rows(self) -> list[int]:
        return [self.rows[group] for group in GROUP_ORDER if group in self.rows]


def _group_for_key(key: str) -> str:
    return INSTRUMENT_GROUPS.get(key, "keyboard")


def _group_for(compiled: CompiledNote) -> str:
    return _group_for_key(instrument_key_for(compiled.note))

DRUM_FAMILY_LABELS = {
    "kick": "Kick / low tom",
    "snare": "Snare / clap",
    "hat": "Hi-hat",
    "cymbal": "Cymbal",
    "tom": "Tom",
    "percussion": "Percussion",
}


def drum_family_for_midi(drum_note: int) -> str:
    """Return a readable GM drum family for vanilla stage placement/FX.

    The sound engine still maps drums to vanilla note-block instruments, but v2.8
    uses the original GM drum note to place kick/snare/hat/cymbal/tom hits in
    different parts of the stage and to drive dedicated FX.
    """
    if drum_note in {35, 36}:
        return "kick"
    if drum_note in {38, 39, 40}:
        return "snare"
    if drum_note in {42, 44, 46}:
        return "hat"
    if drum_note in {49, 51, 52, 55, 57, 59}:
        return "cymbal"
    if drum_note in {41, 43, 45, 47, 48, 50}:
        return "tom"
    return "percussion"


def drum_family_for(compiled: CompiledNote) -> str | None:
    if not compiled.note.is_drum:
        return None
    return drum_family_for_midi(compiled.note.note)


def _layout_size(requested: str, *, note_count: int, active_group_count: int, note_span: int) -> tuple[str, int, int, str]:
    requested = (requested or "auto").strip().lower()
    if requested in {"compact", "wide", "huge"}:
        size = requested
        reason = f"manual {requested}"
    else:
        # Deliberately simple and explainable: small/solo MIDI stays compact;
        # multi-instrument or broad-range MIDI gets more room; very dense MIDI
        # gets the large machine so particles/lamps do not collapse into one blob.
        if note_count >= 5000 or active_group_count >= 6 or note_span >= 60:
            size = "huge"
            reason = "auto: dense/wide-range/many-instrument MIDI"
        elif note_count >= 1200 or active_group_count >= 4 or note_span >= 42:
            size = "wide"
            reason = "auto: medium arrangement"
        else:
            size = "compact"
            reason = "auto: small/solo arrangement"
    if size == "compact":
        return size, -16, 16, reason
    if size == "huge":
        return size, -34, 34, reason
    return size, -24, 24, reason


def _active_groups(compiled: list[CompiledNote]) -> list[str]:
    groups = {_group_for(note) for note in compiled if note.sound_engine == "vanilla"}
    if not groups:
        groups = {"keyboard"}
    return [group for group in GROUP_ORDER if group in groups]


def resolve_noteblock_layout(compiled: list[CompiledNote] | None = None, requested: str = "auto", template: str = "pulse") -> NoteblockLayout:
    template = normalize_stage_template(template)
    notes = [note for note in (compiled or []) if note.sound_engine == "vanilla"]
    groups = _active_groups(notes)
    note_values = [note.note.note for note in notes]
    note_span = (max(note_values) - min(note_values)) if note_values else 0
    name, left, right, reason = _layout_size(
        requested,
        note_count=len(notes),
        active_group_count=len(groups),
        note_span=note_span,
    )

    if template == "classic_line":
        rows = {group: 0 for group in groups}
        beat_z = -3
        control_z = 3
        reason = f"{reason}; template classic_line keeps every instrument on one readable row"
    elif template == "minimal":
        # Minimal keeps the same musical coordinate system, but setup and notes
        # avoid persistent blocks. This gives builders a clean marker-only stage.
        spacing = 1 if name == "compact" else 2
        start_z = -((len(groups) - 1) * spacing) // 2
        rows = {group: start_z + idx * spacing for idx, group in enumerate(groups)}
        min_z = min(rows.values()) if rows else 0
        max_z = max(rows.values()) if rows else 0
        beat_z = min_z - 2
        control_z = max_z + 2
        reason = f"{reason}; template minimal uses marker/particle-only note feedback"
    else:
        # Pulse Stage remains the default: sparse skeleton at setup, transient
        # note modules held for a few ticks at play time.
        spacing = 1 if name == "compact" else 2
        start_z = -((len(groups) - 1) * spacing) // 2
        rows = {group: start_z + idx * spacing for idx, group in enumerate(groups)}
        min_z = min(rows.values()) if rows else 0
        max_z = max(rows.values()) if rows else 0
        beat_z = min_z - 3
        control_z = max_z + 3

    return NoteblockLayout(
        name=name,
        requested=(requested or "auto"),
        template=template,
        left=left,
        right=right,
        rows=rows,
        beat_z=beat_z,
        control_z=control_z,
        reason=reason,
    )


def _clamp_x(layout: NoteblockLayout, x: int) -> int:
    return max(layout.left, min(layout.right, x))


def _within(layout: NoteblockLayout, ratio: float) -> int:
    ratio = max(-1.0, min(1.0, ratio))
    half = (layout.width - 1) / 2.0
    return int(round(ratio * half))


def _pitch_x(layout: NoteblockLayout, midi_note: int, *, left_ratio: float = -0.75, right_ratio: float = 0.75) -> int:
    # Use a practical piano range. Values outside the range clamp to the edge.
    low, high = 36, 96
    t = (max(low, min(high, midi_note)) - low) / (high - low)
    ratio = left_ratio + t * (right_ratio - left_ratio)
    return _within(layout, ratio)


def noteblock_position_for(compiled: CompiledNote, layout: NoteblockLayout | None = None) -> tuple[int, int]:
    """Return a v2.8 vanilla stage position for the visual note-block machine.

    v2.8 deliberately makes positions more musical and more stable:
    - drums are split into kick/snare/hat/cymbal/tom zones;
    - bass stays in the left/low machine area;
    - keyboard follows pitch across the center;
    - guitar/banjo and wind/synth sit farther right so FX do not pile up.
    """
    layout = layout or resolve_noteblock_layout([compiled], "auto")
    key = instrument_key_for(compiled.note)
    group = _group_for_key(key)
    z = layout.rows.get(group, 0)

    if group == "drums":
        family = drum_family_for(compiled) or "percussion"
        # Separate common GM drum families. This makes both the note-block pulse
        # and the dedicated v2.8 drum FX read as rhythm parts instead of one blob.
        ratio_by_family = {
            "kick": -0.64,
            "snare": -0.28,
            "hat": 0.10,
            "cymbal": 0.48,
            "tom": 0.72,
            "percussion": 0.28,
        }
        x = _within(layout, ratio_by_family.get(family, 0.0))
        x += (compiled.note.note % 3) - 1
    elif group == "bass":
        # Keep bass visually grounded and stable; small pitch/channel offsets add
        # life without drifting into the keyboard area.
        x = _within(layout, -0.62) + ((compiled.note.note + compiled.note.channel) % 5) - 2
    elif group == "keyboard":
        # Piano/keyboard is the main harmonic center, so map pitch across a broad
        # but central range.
        x = _pitch_x(layout, compiled.note.note, left_ratio=-0.68, right_ratio=0.68)
        x += (compiled.note.channel % 3) - 1
    elif group == "bells":
        # Bells/mallets live slightly to the right and higher in the visual mix.
        x = _pitch_x(layout, compiled.note.note, left_ratio=-0.28, right_ratio=0.72)
        if key in {"xylophone", "iron_xylophone"}:
            x += 2
        elif key == "cow_bell":
            x += 5
    elif group == "guitar":
        # Guitar/banjo get their own right-side band lane.
        x = _within(layout, 0.22 if key == "guitar" else 0.52)
        x += ((compiled.note.note + compiled.note.channel) % 5) - 2
    else:  # wind_synth
        if key == "flute":
            x = _within(layout, 0.18)
        elif key == "chime":
            x = _within(layout, 0.44)
        else:  # bit / synth
            x = _within(layout, 0.68)
        x += (compiled.note.note % 3) - 1
    return _clamp_x(layout, x), z

def noteblock_lane_for(compiled: CompiledNote, layout: NoteblockLayout | None = None) -> int:
    """Return only the X lane for systems that still need a one-dimensional coordinate."""
    return noteblock_position_for(compiled, layout)[0]


def _row_marker_block(group: str) -> str:
    return {
        "drums": "minecraft:red_concrete",
        "bass": "minecraft:brown_concrete",
        "keyboard": "minecraft:white_concrete",
        "bells": "minecraft:yellow_concrete",
        "guitar": "minecraft:orange_concrete",
        "wind_synth": "minecraft:purple_concrete",
    }.get(group, "minecraft:gray_concrete")


def _template_label(template: str) -> str:
    return {"pulse": "Pulse", "classic_line": "Classic Line", "minimal": "Minimal"}.get(template, template)


def noteblock_setup_lines(namespace: str, layout: NoteblockLayout | None = None) -> list[str]:
    layout = layout or resolve_noteblock_layout(None, "auto", "pulse")
    template_label = _template_label(layout.template)
    lines = [
        f"kill @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage]",
        f"summon minecraft:marker ~ ~ ~ {{Tags:[\"midi2mc_stage\",\"midi2mc_{namespace}_stage\"]}}",
        f"scoreboard players set $stage_width midi2mc {layout.width}",
        f"say [midi2mc] Vanilla v2.8 {template_label} Stage created for {namespace} ({layout.name}, {layout.reason})",
    ]
    if layout.template == "classic_line":
        # A deliberately readable one-row machine. The rail is sparse, so it
        # keeps the old one-line flavor without rebuilding the old block carpet.
        for x in range(layout.left, layout.right + 1, 4):
            lines.append(f"setblock ~{x} ~0 ~0 minecraft:polished_blackstone")
        lines.extend([
            f"setblock ~{layout.left - 2} ~0 ~0 minecraft:white_concrete",
            f"setblock ~{layout.left - 1} ~0 ~0 minecraft:black_concrete",
            f"say [midi2mc] Classic Line template: one-row pseudo-redstone machine with transient note modules.",
        ])
    elif layout.template == "minimal":
        lines.append(f"say [midi2mc] Minimal template: no note-block modules in setup; notes use particles only so builders can decorate freely.")
    else:
        # Sparse row guides only. The playable note blocks/base blocks are
        # created at the exact lane when the note sounds.
        for group in GROUP_ORDER:
            if group not in layout.rows:
                continue
            z = layout.rows[group]
            marker = _row_marker_block(group)
            lines.extend([
                f"setblock ~{layout.left - 2} ~0 ~{z} {marker}",
                f"setblock ~{layout.left - 1} ~0 ~{z} minecraft:black_concrete",
            ])

    # Beat meter is useful across all vanilla templates. It stays tiny in
    # Minimal and sits away from the note field in Classic Line/Pulse.
    for idx, x in enumerate([-3, -1, 1, 3], start=1):
        base = "minecraft:gold_block" if idx == 1 else "minecraft:polished_blackstone"
        lines.extend([
            f"setblock ~{x} ~0 ~{layout.beat_z} {base}",
            f"setblock ~{x} ~1 ~{layout.beat_z} minecraft:redstone_lamp[lit=false]",
        ])
    lines.append(f"say [midi2mc] Beat meter enabled. Stage template={layout.template}; actionbar/playhead are disabled.")

    if layout.template != "minimal":
        lines.extend([
            f"setblock ~-6 ~0 ~{layout.control_z} minecraft:deepslate_tiles",
            f"setblock ~-5 ~1 ~{layout.control_z} minecraft:lime_concrete",
            f"setblock ~-3 ~1 ~{layout.control_z} minecraft:yellow_concrete",
            f"setblock ~-1 ~1 ~{layout.control_z} minecraft:red_concrete",
            f"setblock ~1 ~1 ~{layout.control_z} minecraft:blue_concrete",
            f"setblock ~3 ~1 ~{layout.control_z} minecraft:redstone_lamp[lit=false]",
            f"say [midi2mc] Control pads: lime=play, yellow=pause, red=stop, blue=loop. Use /function commands listed in README.txt.",
        ])
    return lines


def noteblock_clear_lines(namespace: str, layout: NoteblockLayout | None = None) -> list[str]:
    layout = layout or resolve_noteblock_layout(None, "auto")
    lines: list[str] = []
    # Clear the transient playable area. v1.9 normally clears individual pulses
    # via event-level cleanup, but reset/stop still need a full stage wipe.
    for z in layout.stage_rows:
        lines.extend(
            [
                f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run fill ~{layout.left} ~0 ~{z} ~{layout.right} ~0 ~{z} minecraft:air",
                f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run fill ~{layout.left} ~1 ~{z} ~{layout.right} ~1 ~{z} minecraft:air",
                f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run fill ~{layout.left} ~2 ~{z} ~{layout.right} ~2 ~{z} minecraft:air",
            ]
        )
    for x in [-3, -1, 1, 3, 5]:
        lines.append(
            f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~1 ~{layout.beat_z} minecraft:redstone_lamp[lit=false]"
        )
    return lines


def noteblock_meter_lines(namespace: str, layout: NoteblockLayout | None = None, beat_info: BeatInfo | None = None) -> list[str]:
    layout = layout or resolve_noteblock_layout(None, "auto")
    beat_info = beat_info or resolve_beat_info(None, 20)
    beat_lanes = [-3, -1, 1, 3]
    lines = [
        f"scoreboard players set $beat_ticks midi2mc {beat_info.beat_ticks}",
        f"scoreboard players set $bar_ticks midi2mc {beat_info.bar_ticks}",
        f"scoreboard players set $beats_per_bar midi2mc {beat_info.beats_per_bar}",
        "scoreboard players operation $beat_pos midi2mc = $time midi2mc",
        "scoreboard players operation $beat_pos midi2mc %= $beat_ticks midi2mc",
        "scoreboard players operation $beat_index midi2mc = $time midi2mc",
        "scoreboard players operation $beat_index midi2mc /= $beat_ticks midi2mc",
        "scoreboard players operation $beat_index midi2mc %= $beats_per_bar midi2mc",
        "scoreboard players operation $bar_pos midi2mc = $time midi2mc",
        "scoreboard players operation $bar_pos midi2mc %= $bar_ticks midi2mc",
        "scoreboard players operation $bar_index midi2mc = $time midi2mc",
        "scoreboard players operation $bar_index midi2mc /= $bar_ticks midi2mc",
        "scoreboard players operation $beat_display midi2mc = $beat_index midi2mc",
        "scoreboard players add $beat_display midi2mc 1",
        "scoreboard players operation $bar_display midi2mc = $bar_index midi2mc",
        "scoreboard players add $bar_display midi2mc 1",
    ]
    for x in beat_lanes:
        lines.append(
            f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~1 ~{layout.beat_z} minecraft:redstone_lamp[lit=false]"
        )
    for idx, x in enumerate(beat_lanes):
        lines.append(
            f"execute if score $beat_index midi2mc matches {idx} at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~1 ~{layout.beat_z} minecraft:redstone_lamp[lit=true]"
        )
    # Downbeat accent: a tiny extra lamp next to the meter lights on the first tick of every bar.
    lines.append(
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~5 ~1 ~{layout.beat_z} minecraft:redstone_lamp[lit=false]"
    )
    lines.append(
        f"execute if score $bar_pos midi2mc matches 0 at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~5 ~1 ~{layout.beat_z} minecraft:redstone_lamp[lit=true]"
    )
    # No actionbar text in v1.9; the beat lamps are enough and avoid UI noise.
    return lines


def noteblock_playhead_lines(namespace: str, layout: NoteblockLayout | None = None) -> list[str]:
    return ["# playhead removed in midi2mc v1.9+; beat meter is the timing UI"]


def stage_note_lines(compiled: CompiledNote, namespace: str, min_note: int, max_note: int, stage_particles: bool = True, layout: NoteblockLayout | None = None) -> list[str]:
    """Return pseudo-redstone note-block stage commands for one note."""
    layout = layout or resolve_noteblock_layout([compiled], "auto")
    base_block = instrument_base_block_for(compiled.note)
    note_block = note_block_state_for(compiled.note)
    note_color = note_particle_color_for_note(compiled.note.note, min_note=min_note, max_note=max_note)
    x, z = noteblock_position_for(compiled, layout)
    if layout.template == "minimal":
        lines: list[str] = []
        if stage_particles:
            lines.append(
                f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run particle minecraft:note ~{x} ~2.45 ~{z} {note_color:g} 0 0 1 0 force"
            )
        return lines

    lines = [
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~0 ~{z} {base_block}",
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~1 ~{z} {note_block}",
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~2 ~{z} minecraft:redstone_lamp[lit=true]",
    ]
    if stage_particles:
        lines.append(
            f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run particle minecraft:note ~{x} ~3.85 ~{z} {note_color:g} 0 0 1 0 force"
        )
    return lines


def pulse_hold_ticks_for(compiled: CompiledNote, tick_rate: int = 20, custom_hold_ticks: int = 0) -> int:
    """Return how long a vanilla note-block visual pulse should stay visible.

    custom_hold_ticks is the v3.0 editor override. 0 keeps the old auto policy.
    """
    if custom_hold_ticks and custom_hold_ticks > 0:
        return max(1, min(40, int(custom_hold_ticks)))
    duration_ticks = int(round(max(0.0, compiled.note.duration_sec) * tick_rate))
    if duration_ticks >= PULSE_HOLD_TICKS:
        return max(PULSE_HOLD_TICKS, min(PULSE_LONG_HOLD_TICKS, duration_ticks))
    return PULSE_HOLD_TICKS


def noteblock_pulse_clear_lines(compiled: CompiledNote, namespace: str, layout: NoteblockLayout | None = None) -> list[str]:
    """Clear the temporary note-block module created for a note pulse."""
    layout = layout or resolve_noteblock_layout([compiled], "auto")
    if layout.template == "minimal":
        return []
    x, z = noteblock_position_for(compiled, layout)
    return [
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~2 ~{z} minecraft:air",
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~1 ~{z} minecraft:air",
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run setblock ~{x} ~0 ~{z} minecraft:air",
    ]


def noteblock_stage_usage_report(compiled: list[CompiledNote], requested_layout: str = "auto", stage_template: str = "pulse") -> dict[str, object]:
    vanilla = [note for note in compiled if note.sound_engine == "vanilla"]
    layout = resolve_noteblock_layout(vanilla, requested_layout, stage_template)
    instruments = Counter(instrument_key_for(note.note) for note in vanilla)
    channels = Counter(str(note.note.channel + 1) for note in vanilla)
    row_counts: Counter[str] = Counter()
    group_counts: Counter[str] = Counter()
    drum_family_counts: Counter[str] = Counter()
    for note in vanilla:
        group = _group_for(note)
        group_counts[group] += 1
        row_counts[GROUP_LABELS.get(group, group)] += 1
        family = drum_family_for(note)
        if family:
            drum_family_counts[DRUM_FAMILY_LABELS.get(family, family)] += 1
    return {
        "profile": "noteblock_machine",
        "layout": (
            f"vanilla_machine_v2.8_smart_fx_pulse_stage_{layout.name}"
            if layout.template == "pulse"
            else f"vanilla_machine_v2.8_{layout.template}_{layout.name}"
        ),
        "layout_requested": layout.requested,
        "layout_resolved": layout.name,
        "layout_reason": layout.reason,
        "lane_range": [layout.left, layout.right],
        "width": layout.width,
        "stage_template": layout.template,
        "active_rows": {GROUP_LABELS.get(group, group): z for group, z in layout.rows.items()},
        "instrument_groups": dict(instruments),
        "channel_groups": dict(channels),
        "row_groups": dict(row_counts),
        "group_counts": dict(group_counts),
        "drum_family_groups": dict(drum_family_counts),
        "playhead": {"enabled": False, "reason": "removed_in_v1.9_use_beat_meter"},
        "beat_meter": {"enabled": True, "z": layout.beat_z, "beats_per_bar": 4, "display": "redstone lamps only"},
        "control_panel": {"enabled": True, "z": layout.control_z, "visual_only": True},
        "policy": "vanilla-first Stage Template system: pulse keeps transient note-block modules, classic_line keeps a readable one-row machine, minimal uses marker/particle-only feedback; v2.8 keeps drum-family placement, stable bass/keyboard/guitar/wind positioning, and smart velocity/density-aware FX",
    }
