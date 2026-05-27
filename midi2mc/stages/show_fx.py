from __future__ import annotations

from collections import Counter

from ..mapping import dust_particle_for_note
from ..model import CompiledNote
from .noteblock_machine import NoteblockLayout, noteblock_position_for
from .soma_concert import MODULES, soma_module_for

FX_CHOICES = {"auto", "none", "lightshow", "fireworks", "both"}


def resolve_show_fx(raw: str | None, *, mode: str, stage_profile: str, quality: str) -> str:
    """Resolve the user-facing show_fx option into an effective profile.

    v1.6 keeps fireworks opt-in, but vanilla Pulse Stage now gets a subtle
    lightshow by default in medium/high/insane because it has become the main
    project path. Safe mode and low quality still resolve to none.
    """
    if mode != "command_stage":
        return "none"
    value = (raw or "auto").strip().lower()
    if value not in FX_CHOICES:
        value = "auto"
    if value != "auto":
        return value
    if quality == "low":
        return "none"
    if stage_profile in {"soma_concert", "noteblock_machine"}:
        return "lightshow"
    return "none"


def _note_xz(compiled: CompiledNote, stage_profile: str, noteblock_layout: NoteblockLayout | None = None) -> tuple[float, float]:
    if stage_profile == "soma_concert":
        module = MODULES[soma_module_for(compiled)]
        return float(module["x"]), float(module["z"])
    x, z = noteblock_position_for(compiled, noteblock_layout)
    return float(x), float(z)


def _is_strong_note(compiled: CompiledNote) -> bool:
    n = compiled.note
    if n.velocity >= 112:
        return True
    if n.is_drum and n.note in {35, 36, 38, 39, 40, 49, 57}:
        return True
    return False


def _is_major_moment(compiled: CompiledNote) -> bool:
    # Keep burst counts bounded. Strong notes, drum hits, and continuous notes
    # feel like reasonable musical accents.
    return _is_strong_note(compiled) or compiled.used_continuous


def _dust_line(
    namespace: str,
    compiled: CompiledNote,
    min_note: int,
    max_note: int,
    x: float,
    y: float,
    z: float,
    *,
    scale: float = 1.0,
    spread: float = 0.08,
    speed: float = 0.003,
    count: int = 4,
    force: bool = True,
) -> str:
    particle = dust_particle_for_note(compiled.note.note, min_note=min_note, max_note=max_note, scale=scale)
    mode = "force" if force else "normal"
    return (
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] "
        f"run particle {particle} ~{x:g} ~{y:.2f} ~{z:g} {spread:g} {spread:g} {spread:g} {speed:g} {count} {mode}"
    )


def _center_of(notes: list[CompiledNote], stage_profile: str, layout: NoteblockLayout | None) -> tuple[float, float]:
    coords = [_note_xz(note, stage_profile, layout) for note in notes]
    if not coords:
        return 0.0, 0.0
    return sum(x for x, _ in coords) / len(coords), sum(z for _, z in coords) / len(coords)


def _strongest(notes: list[CompiledNote]) -> CompiledNote | None:
    if not notes:
        return None
    return max(notes, key=lambda note: (note.note.velocity, note.note.note))


def _unique_pitch_count(notes: list[CompiledNote]) -> int:
    return len({note.note.note for note in notes})


def show_fx_tick_lines(
    tick_notes: list[CompiledNote],
    namespace: str,
    min_note: int,
    max_note: int,
    stage_profile: str,
    fx_profile: str,
    noteblock_layout: NoteblockLayout | None = None,
    *,
    ticks_per_quarter: int = 480,
) -> list[str]:
    """Return v1.6 arrangement-level FX for a whole event tick.

    Per-note FX is still handled by show_fx_note_lines. This function adds a
    small amount of musical direction: drum ground pulses, chord blooms, and
    beat accents. It is intentionally particle-only so Pulse Stage cleanup stays
    simple and safe.
    """
    fx = resolve_show_fx(fx_profile, mode="command_stage", stage_profile=stage_profile, quality="medium")
    if fx == "none" or not tick_notes:
        return []

    lines: list[str] = []
    strongest = _strongest(tick_notes)
    if strongest is None:
        return lines

    # 1) Drum hit = low, fast ground pulse. This is the most Minecraft-readable
    # rhythm cue and helps vanilla Pulse Stage feel less like random sparkles.
    drums = [note for note in tick_notes if note.note.is_drum]
    drum = _strongest(drums)
    if drum is not None and fx in {"lightshow", "both"}:
        x, z = _note_xz(drum, stage_profile, noteblock_layout)
        kick_like = drum.note.note in {35, 36, 41, 43, 45, 47}
        snare_like = drum.note.note in {38, 39, 40}
        if kick_like:
            lines.append(_dust_line(namespace, drum, min_note, max_note, x, 1.22, z, scale=1.35, spread=0.42, speed=0.018, count=16))
            lines.append(_dust_line(namespace, drum, min_note, max_note, x, 1.28, z, scale=0.95, spread=0.66, speed=0.010, count=10))
        elif snare_like:
            lines.append(_dust_line(namespace, drum, min_note, max_note, x, 2.35, z, scale=1.10, spread=0.24, speed=0.016, count=14))
        else:
            lines.append(_dust_line(namespace, drum, min_note, max_note, x, 2.78, z, scale=0.82, spread=0.18, speed=0.014, count=10))

    # 2) Chord bloom = one short bloom centered on the notes instead of adding
    # fireworks to every member of the chord. This makes harmony readable.
    unique_pitches = _unique_pitch_count(tick_notes)
    total_velocity = sum(note.note.velocity for note in tick_notes)
    if fx in {"lightshow", "both"} and unique_pitches >= 3 and total_velocity >= 220:
        cx, cz = _center_of(tick_notes, stage_profile, noteblock_layout)
        chord_color = strongest
        chord_size = min(7, unique_pitches)
        base_y = 3.35 if stage_profile == "noteblock_machine" else 2.85
        lines.append(_dust_line(namespace, chord_color, min_note, max_note, cx, base_y, cz, scale=1.18, spread=0.30, speed=0.010, count=8 + chord_size * 2))
        if unique_pitches >= 5 or total_velocity >= 420:
            lines.append(_dust_line(namespace, chord_color, min_note, max_note, cx + 0.36, base_y + 0.16, cz, scale=0.86, spread=0.18, speed=0.012, count=6))
            lines.append(_dust_line(namespace, chord_color, min_note, max_note, cx - 0.36, base_y + 0.16, cz, scale=0.86, spread=0.18, speed=0.012, count=6))

    # 3) Quarter-beat accent. MIDI files do not always have a time signature, so
    # use PPQ quarter boundaries as a conservative beat cue. Keep it tiny.
    if fx in {"lightshow", "both"} and ticks_per_quarter > 0:
        beat_notes = [note for note in tick_notes if note.note.start_tick % ticks_per_quarter == 0]
        if beat_notes:
            beat = _strongest(beat_notes) or strongest
            x, z = _note_xz(beat, stage_profile, noteblock_layout)
            y = 3.00 if stage_profile == "noteblock_machine" else 2.45
            lines.append(_dust_line(namespace, beat, min_note, max_note, x, y, z, scale=0.72, spread=0.20, speed=0.006, count=6))

    # 4) Firework-style burst remains opt-in, but chord/accent-aware now. This
    # keeps 'both' from becoming too noisy on dense MIDI.
    if fx in {"fireworks", "both"} and (unique_pitches >= 4 or _is_major_moment(strongest)):
        cx, cz = _center_of(tick_notes, stage_profile, noteblock_layout)
        y = 4.45 if strongest.note.is_drum else 5.10
        burst_count = 12 if strongest.note.velocity < 112 else 18
        lines.extend(
            [
                _dust_line(namespace, strongest, min_note, max_note, cx, y, cz, scale=1.30, spread=0.34, speed=0.030, count=burst_count),
                _dust_line(namespace, strongest, min_note, max_note, cx + 0.42, y + 0.20, cz, scale=0.90, spread=0.15, speed=0.018, count=5),
                _dust_line(namespace, strongest, min_note, max_note, cx - 0.42, y + 0.20, cz, scale=0.90, spread=0.15, speed=0.018, count=5),
            ]
        )
    return lines


def show_fx_note_lines(
    compiled: CompiledNote,
    namespace: str,
    min_note: int,
    max_note: int,
    stage_profile: str,
    fx_profile: str,
    noteblock_layout: NoteblockLayout | None = None,
) -> list[str]:
    fx = resolve_show_fx(fx_profile, mode="command_stage", stage_profile=stage_profile, quality="medium")
    if fx == "none":
        return []
    x, z = _note_xz(compiled, stage_profile, noteblock_layout)
    velocity = max(1, min(127, compiled.note.velocity))
    lines: list[str] = []

    if fx in {"lightshow", "both"}:
        # v1.6: keep the readable v1.6 height, but make ordinary notes slightly
        # cleaner and let tick-level arrangement FX carry drums/chords/beats.
        if stage_profile == "noteblock_machine":
            height = 3.20 + min(0.20, velocity / 460.0)
        else:
            height = 2.20 + min(0.26, velocity / 390.0)
        count = 8 if velocity < 88 else 11
        spread = 0.09 if velocity < 96 else 0.13
        lines.append(_dust_line(namespace, compiled, min_note, max_note, x, height, z, scale=0.98, spread=spread, speed=0.004, count=count))
        if velocity >= 96 or compiled.used_continuous:
            lines.append(_dust_line(namespace, compiled, min_note, max_note, x, height + 0.18, z, scale=0.82, spread=0.12, speed=0.004, count=6))

    # Most firework work moved to tick-level logic in v1.6 so chords do not spawn
    # one burst per note. Keep a tiny per-note accent for isolated strong notes.
    if fx in {"fireworks", "both"} and _is_major_moment(compiled):
        y = 4.25 if compiled.note.is_drum else 4.95
        lines.append(_dust_line(namespace, compiled, min_note, max_note, x, y, z, scale=1.05, spread=0.20, speed=0.022, count=7))
    return lines


def show_fx_usage_report(compiled: list[CompiledNote], enabled_profile: str, stage_profile: str) -> dict[str, object]:
    if enabled_profile == "none":
        return {"enabled": False, "profile": "none"}
    strong = sum(1 for note in compiled if _is_strong_note(note))
    major = sum(1 for note in compiled if _is_major_moment(note))
    module_counts: Counter[str] = Counter()
    if stage_profile == "soma_concert":
        module_counts.update(soma_module_for(note) for note in compiled if note.sound_engine == "soma")
    return {
        "enabled": True,
        "profile": enabled_profile,
        "stage_profile": stage_profile,
        "note_count": len(compiled),
        "strong_note_count": strong,
        "firework_style_burst_candidates": major,
        "uses_real_firework_entities": False,
        "particle": "minecraft:dust{color:[r,g,b],scale:s}",
        "color_policy": "RGB dust color is derived from the same Minecraft note-particle hue used by stage note particles",
        "fade_policy": "visible_mid_stage_rgb_dust_above_blocks_below_note_sprite",
        "arrangement_policy": "v1.6 tick-level FX adds drum ground pulses, chord blooms, quarter-beat accents, and chord-aware firework-style bursts",
        "policy": "lightshow=per-note RGB dust plus v1.6 arrangement cues; fireworks=opt-in accent/chord dust bursts following each stage module/lane",
        "soma_module_counts": dict(module_counts),
    }
