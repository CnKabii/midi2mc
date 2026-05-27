from __future__ import annotations

from collections import Counter

from ..mapping import dust_particle_for_note
from ..model import CompiledNote
from .noteblock_machine import noteblock_lane_for
from .soma_concert import MODULES, soma_module_for

FX_CHOICES = {"auto", "none", "lightshow", "fireworks", "both"}


def resolve_show_fx(raw: str | None, *, mode: str, stage_profile: str, quality: str) -> str:
    """Resolve the user-facing show_fx option into an effective profile.

    v0.9 uses colorable dust particles for FX. "fireworks" still means
    firework-style particle bursts, not firework entities.
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
    if stage_profile == "soma_concert":
        return "lightshow"
    return "none"


def _note_xz(compiled: CompiledNote, stage_profile: str) -> tuple[float, float]:
    if stage_profile == "soma_concert":
        module = MODULES[soma_module_for(compiled)]
        return float(module["x"]), float(module["z"])
    return float(noteblock_lane_for(compiled)), 0.0


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


def show_fx_note_lines(
    compiled: CompiledNote,
    namespace: str,
    min_note: int,
    max_note: int,
    stage_profile: str,
    fx_profile: str,
) -> list[str]:
    fx = resolve_show_fx(fx_profile, mode="command_stage", stage_profile=stage_profile, quality="medium")
    if fx == "none":
        return []
    x, z = _note_xz(compiled, stage_profile)
    velocity = max(1, min(127, compiled.note.velocity))
    lines: list[str] = []

    if fx in {"lightshow", "both"}:
        # v0.9: replace the v0.8 note-particle lightshow with RGB dust. Dust
        # can be colorized directly and fades fast, so it looks more like stage
        # lighting and less like musical-note bubbles.
        height = 2.75 + min(0.8, velocity / 160.0)
        count = 3 if velocity < 88 else 5
        spread = 0.05 if velocity < 96 else 0.08
        lines.append(_dust_line(namespace, compiled, min_note, max_note, x, height, z, scale=0.85, spread=spread, speed=0.002, count=count))
        if velocity >= 96 or compiled.used_continuous:
            lines.append(_dust_line(namespace, compiled, min_note, max_note, x, height + 0.34, z, scale=0.75, spread=0.06, speed=0.002, count=3))
        if _is_strong_note(compiled):
            lines.append(_dust_line(namespace, compiled, min_note, max_note, x, height + 0.72, z, scale=0.65, spread=0.05, speed=0.003, count=3))

    if fx in {"fireworks", "both"} and _is_major_moment(compiled):
        # Firework-style colored dust burst. Still no entities and no item
        # components, but now the burst color follows the same MIDI pitch color.
        y = 4.65 if compiled.note.is_drum else 5.35
        burst_count = 7 if velocity < 112 else 11
        lines.extend(
            [
                _dust_line(namespace, compiled, min_note, max_note, x, y, z, scale=1.25, spread=0.32, speed=0.028, count=burst_count),
                _dust_line(namespace, compiled, min_note, max_note, x + 0.34, y + 0.22, z, scale=0.85, spread=0.12, speed=0.016, count=3),
                _dust_line(namespace, compiled, min_note, max_note, x - 0.34, y + 0.22, z, scale=0.85, spread=0.12, speed=0.016, count=3),
                _dust_line(namespace, compiled, min_note, max_note, x, y + 0.42, z + 0.34, scale=0.85, spread=0.12, speed=0.016, count=3),
                _dust_line(namespace, compiled, min_note, max_note, x, y + 0.42, z - 0.34, scale=0.85, spread=0.12, speed=0.016, count=3),
            ]
        )
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
        "color_policy": "RGB dust color follows the same pitch mapping as note color: low=blue/cyan, high=orange/red",
        "fade_policy": "fast_fade_low_count_dust_particles_no_end_rod",
        "policy": "lightshow=colored dust per note; fireworks=accent-only colored dust bursts following each stage module/lane",
        "soma_module_counts": dict(module_counts),
    }
