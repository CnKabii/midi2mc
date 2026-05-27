from __future__ import annotations

from ..mapping import note_particle_color_for_note
from ..model import CompiledNote


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _pitch_x(midi_note: int, min_note: int, max_note: int, width: float = 16.0) -> float:
    if max_note <= min_note:
        normalized = 0.5
    else:
        normalized = (max(min_note, min(max_note, midi_note)) - min_note) / (max_note - min_note)
    return round(-width / 2.0 + normalized * width, 2)


def _segments_for(compiled: CompiledNote) -> int:
    # Long notes should visibly have a longer tail, but keep the command count bounded.
    # A 0.2s grace keeps short ornament notes from getting oversized.
    duration = max(0.0, compiled.note.duration_sec)
    if compiled.used_continuous:
        return int(_clamp(round(duration * 5) + 3, 4, 10))
    return int(_clamp(round(duration * 3) + 2, 2, 5))


def piano_roll_note_lines(
    compiled: CompiledNote,
    namespace: str,
    min_note: int,
    max_note: int,
) -> list[str]:
    """Generate a small particle piano-roll strip in front of the stage.

    v0.9.0 keeps this visualizer intentionally lightweight: every note start draws
    a short end-rod strip at a horizontal position derived from pitch. It does not
    create entities or refresh active notes every tick, so the visual cost stays
    close to the number of note-on events.
    """
    x = _pitch_x(compiled.note.note, min_note, max_note)
    velocity_boost = max(0, compiled.note.velocity - 64) / 127
    y = round(3.15 + min(0.75, velocity_boost), 2)
    color = note_particle_color_for_note(compiled.note.note, min_note=min_note, max_note=max_note)
    segments = _segments_for(compiled)
    lines = [
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run particle minecraft:note ~{x:g} ~{y:g} ~-1.25 {color:g} 0 0 1 0 force"
    ]
    for i in range(segments):
        z = -1.65 - i * 0.32
        # Stronger notes get slightly denser particles. Count stays tiny to keep v0.7 safe.
        count = 2 if compiled.note.velocity >= 96 else 1
        lines.append(
            f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] run particle minecraft:end_rod ~{x:g} ~{y:g} ~{z:.2f} 0.03 0.03 0.03 0.005 {count} force"
        )
    return lines


def piano_roll_usage_report(compiled: list[CompiledNote], enabled: bool) -> dict[str, object]:
    if not enabled:
        return {"enabled": False}
    if not compiled:
        return {"enabled": True, "note_count": 0, "min_note": None, "max_note": None}
    notes = [note.note.note for note in compiled]
    sustained = sum(1 for note in compiled if note.used_continuous)
    return {
        "enabled": True,
        "profile": "particle_piano_roll_v1",
        "note_count": len(compiled),
        "sustained_note_count": sustained,
        "min_note": min(notes),
        "max_note": max(notes),
        "visual_policy": "note_on_draws_pitch_mapped_end_rod_strip; sustained_notes_draw_longer_strips",
    }
