from __future__ import annotations

from collections import Counter

from ..mapping import dust_particle_for_note
from ..model import CompiledNote
from .noteblock_machine import NoteblockLayout, drum_family_for, noteblock_position_for
from .soma_concert import MODULES, soma_module_for

FX_CHOICES = {"auto", "none", "lightshow", "fireworks", "both"}
FX_PROFILE_CHOICES = {"clean", "redstone", "concert", "magic"}
FX_LAYER_CHOICES = {"note", "drum", "bass", "chord", "beat", "lead", "fireworks", "finale"}


def normalize_fx_intensity(raw: float | int | str | None) -> float:
    try:
        value = float(raw if raw is not None else 1.0)
    except (TypeError, ValueError):
        value = 1.0
    return max(0.0, min(3.0, value))


def normalize_fx_layers(raw: str | None) -> set[str]:
    value = (raw or "all").strip().lower()
    if value in {"", "all", "default"}:
        return set(FX_LAYER_CHOICES)
    selected = {part.strip().lower().replace("-", "_") for part in value.split(",") if part.strip()}
    selected &= FX_LAYER_CHOICES
    return selected or set(FX_LAYER_CHOICES)


def normalize_fx_profile(raw: str | None) -> str:
    value = (raw or "concert").strip().lower()
    return value if value in FX_PROFILE_CHOICES else "concert"


def resolve_show_fx(raw: str | None, *, mode: str, stage_profile: str, quality: str) -> str:
    """Resolve the user-facing show_fx option into an effective profile.

    v2.8 keeps fireworks opt-in, but vanilla Pulse Stage now gets a subtle
    lightshow by default in medium/high/insane because it has become the main
    project path. v2.8 adds velocity/density-aware FX choreography on top of drum/instrument-aware placement. Safe mode and low quality still resolve to none.
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


def _profile_rgb(compiled: CompiledNote, min_note: int, max_note: int, fx_style: str) -> tuple[float, float, float]:
    """Return RGB for the selected FX profile.

    concert/clean follow the note color. redstone deliberately uses warm
    red/orange circuitry colors, and magic shifts the pitch color toward a
    violet/blue palette so it reads differently from the vanilla note sprite.
    """
    from ..mapping import rgb_for_note

    r, g, b = rgb_for_note(compiled.note.note, min_note=min_note, max_note=max_note)
    fx_style = normalize_fx_profile(fx_style)
    velocity = max(0.0, min(1.0, compiled.note.velocity / 127.0))
    if fx_style == "redstone":
        # Warm redstone/copper-like colors. Higher velocity gets more orange.
        return (round(0.78 + 0.18 * velocity, 3), round(0.08 + 0.30 * velocity, 3), round(0.03 + 0.04 * velocity, 3))
    if fx_style == "magic":
        # Keep some pitch variation, but bias it toward purple/blue magic.
        return (round(0.32 + r * 0.30, 3), round(0.10 + g * 0.22, 3), round(0.62 + b * 0.30, 3))
    return (r, g, b)


def _dust_particle_for_profile(compiled: CompiledNote, min_note: int, max_note: int, scale: float, fx_style: str) -> str:
    r, g, b = _profile_rgb(compiled, min_note, max_note, fx_style)
    return f"minecraft:dust{{color:[{r:.3f}f,{g:.3f}f,{b:.3f}f],scale:{scale:.2f}f}}"


def _particle_line(
    namespace: str,
    particle: str,
    x: float,
    y: float,
    z: float,
    *,
    spread: float = 0.08,
    speed: float = 0.003,
    count: int = 4,
    force: bool = True,
) -> str:
    mode = "force" if force else "normal"
    return (
        f"execute at @e[type=minecraft:marker,tag=midi2mc_{namespace}_stage,limit=1] "
        f"run particle {particle} ~{x:g} ~{y:.2f} ~{z:g} {spread:g} {spread:g} {spread:g} {speed:g} {count} {mode}"
    )


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
    fx_style: str = "concert",
    fx_intensity: float = 1.0,
) -> str:
    intensity = normalize_fx_intensity(fx_intensity)
    particle = _dust_particle_for_profile(compiled, min_note, max_note, scale * (0.82 + 0.18 * intensity), fx_style)
    adjusted_count = max(0, int(round(count * intensity)))
    adjusted_spread = spread * (0.85 + 0.15 * intensity)
    return _particle_line(namespace, particle, x, y, z, spread=adjusted_spread, speed=speed, count=adjusted_count, force=force)


def _accent_lines(
    namespace: str,
    x: float,
    y: float,
    z: float,
    *,
    fx_style: str,
    strength: str = "normal",
) -> list[str]:
    """Small non-dust accents for distinct profile identity.

    These are intentionally sparse: dust remains the safe, colorable core; the
    profile accents add identity without turning every MIDI into particle soup.
    """
    fx_style = normalize_fx_profile(fx_style)
    if fx_style == "clean":
        return []
    if fx_style == "redstone":
        count = 4 if strength == "normal" else 7
        return [_particle_line(namespace, "minecraft:electric_spark", x, y, z, spread=0.13, speed=0.010, count=count)]
    if fx_style == "magic":
        particle = "minecraft:reverse_portal" if strength == "burst" else "minecraft:enchant"
        count = 5 if strength == "normal" else 9
        return [_particle_line(namespace, particle, x, y, z, spread=0.20, speed=0.020, count=count)]
    # concert
    if strength == "burst":
        return [_particle_line(namespace, "minecraft:end_rod", x, y, z, spread=0.18, speed=0.018, count=5)]
    return []


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


def _tick_energy(notes: list[CompiledNote]) -> int:
    # A compact, explainable energy score used only for visual choreography.
    # Density matters, but velocity carries the musical accent.
    return sum(note.note.velocity for note in notes) + max(0, len(notes) - 1) * 36 + _unique_pitch_count(notes) * 18


def _velocity_factor(compiled: CompiledNote) -> float:
    return max(0.0, min(1.0, compiled.note.velocity / 127.0))


def show_fx_tick_lines(
    tick_notes: list[CompiledNote],
    namespace: str,
    min_note: int,
    max_note: int,
    stage_profile: str,
    fx_profile: str,
    noteblock_layout: NoteblockLayout | None = None,
    *,
    fx_style: str = "concert",
    fx_intensity: float = 1.0,
    fx_layers: str = "all",
    ticks_per_quarter: int = 480,
    current_tick: int | None = None,
    final_note_tick: int | None = None,
) -> list[str]:
    """Return v2.8 arrangement-level FX for a whole event tick.

    Per-note FX is still handled by show_fx_note_lines. This function adds
    musical direction: drum-family pulses, bass floor pressure, chord blooms,
    beat accents, and lead sparkle. It is intentionally particle-only so Pulse
    Stage cleanup stays simple and safe.
    """
    fx = resolve_show_fx(fx_profile, mode="command_stage", stage_profile=stage_profile, quality="medium")
    fx_style = normalize_fx_profile(fx_style)
    fx_intensity = normalize_fx_intensity(fx_intensity)
    layers = normalize_fx_layers(fx_layers)
    if fx == "none" or not tick_notes or fx_intensity <= 0:
        return []

    lines: list[str] = []

    def _dl(compiled: CompiledNote, min_note: int, max_note: int, x: float, y: float, z: float, **kwargs) -> str:
        return _dust_line(namespace, compiled, min_note, max_note, x, y, z, fx_style=fx_style, fx_intensity=fx_intensity, **kwargs)

    strongest = _strongest(tick_notes)
    if strongest is None:
        return lines

    # 1) Drum hit = family-aware rhythm pulse. v2.6+ splits kick/snare/hat/
    # cymbal/tom/percussion so the vanilla machine has an actual drum kit feel.
    drums = [note for note in tick_notes if note.note.is_drum]
    drum = _strongest(drums)
    if "drum" in layers and drum is not None and fx in {"lightshow", "both"}:
        x, z = _note_xz(drum, stage_profile, noteblock_layout)
        family = drum_family_for(drum) if stage_profile == "noteblock_machine" else None
        if family == "kick":
            lines.append(_dl(drum, min_note, max_note, x, 1.10, z, scale=1.45, spread=0.54, speed=0.020, count=22))
            lines.append(_dl(drum, min_note, max_note, x, 1.16, z, scale=1.05, spread=0.86, speed=0.011, count=14))
        elif family == "snare":
            lines.append(_dl(drum, min_note, max_note, x, 2.18, z, scale=1.16, spread=0.30, speed=0.018, count=18))
            lines.append(_dl(drum, min_note, max_note, x, 2.44, z, scale=0.76, spread=0.18, speed=0.022, count=7))
        elif family == "hat":
            lines.append(_dl(drum, min_note, max_note, x, 3.05, z, scale=0.66, spread=0.14, speed=0.018, count=10))
        elif family == "cymbal":
            lines.append(_dl(drum, min_note, max_note, x, 3.50, z, scale=0.92, spread=0.36, speed=0.024, count=14))
            lines.append(_dl(drum, min_note, max_note, x, 3.72, z, scale=0.58, spread=0.52, speed=0.018, count=8))
        elif family == "tom":
            direction = -0.42 if drum.note.note % 2 == 0 else 0.42
            lines.append(_dl(drum, min_note, max_note, x, 1.72, z, scale=1.00, spread=0.28, speed=0.017, count=13))
            lines.append(_dl(drum, min_note, max_note, x + direction, 1.94, z, scale=0.72, spread=0.18, speed=0.015, count=7))
        else:
            # Soma or unclassified percussion keeps the old safe fallback.
            lines.append(_dl(drum, min_note, max_note, x, 2.68, z, scale=0.82, spread=0.20, speed=0.014, count=10))

    # 1b) Bass floor pressure. Bass should feel grounded even when it is not a
    # drum; this helps the new placement read as a band rather than random lanes.
    bass_notes = [note for note in tick_notes if (not note.note.is_drum and note.instrument_key in {"bass", "didgeridoo"})]
    bass = _strongest(bass_notes)
    if "bass" in layers and bass is not None and fx in {"lightshow", "both"}:
        x, z = _note_xz(bass, stage_profile, noteblock_layout)
        bass_scale = 1.02 + _velocity_factor(bass) * 0.28
        lines.append(_dl(bass, min_note, max_note, x, 1.30, z, scale=bass_scale, spread=0.30 + _velocity_factor(bass) * 0.16, speed=0.012, count=10 + int(_velocity_factor(bass) * 8)))
        if bass.note.velocity >= 108:
            lines.append(_dl(bass, min_note, max_note, x, 0.92, z, scale=0.82, spread=0.62, speed=0.010, count=8))

    # 2) Chord bloom = one short bloom centered on the notes instead of adding
    # fireworks to every member of the chord. This makes harmony readable.
    unique_pitches = _unique_pitch_count(tick_notes)
    total_velocity = sum(note.note.velocity for note in tick_notes)
    tick_energy = _tick_energy(tick_notes)
    average_velocity = total_velocity / max(1, len(tick_notes))

    # 2) Chord bloom: v2.8 scales the bloom by density and velocity, so a dense
    # quiet pad does not explode like a fortissimo chord, while a true accent
    # gets a readable center bloom.
    if "chord" in layers and fx in {"lightshow", "both"} and unique_pitches >= 3 and total_velocity >= 220:
        cx, cz = _center_of(tick_notes, stage_profile, noteblock_layout)
        chord_color = strongest
        chord_size = min(8, unique_pitches)
        energy_bonus = 1.0 if tick_energy < 520 else 1.18 if tick_energy < 850 else 1.34
        base_y = 3.35 if stage_profile == "noteblock_machine" else 2.85
        lines.append(_dl(chord_color, min_note, max_note, cx, base_y, cz, scale=1.08 * energy_bonus, spread=0.26 + min(0.18, unique_pitches * 0.025), speed=0.010, count=7 + chord_size * 2 + int(max(0, average_velocity - 84) / 8)))
        if unique_pitches >= 5 or total_velocity >= 420:
            lines.append(_dl(chord_color, min_note, max_note, cx + 0.36, base_y + 0.16, cz, scale=0.82 * energy_bonus, spread=0.18, speed=0.012, count=6))
            lines.append(_dl(chord_color, min_note, max_note, cx - 0.36, base_y + 0.16, cz, scale=0.82 * energy_bonus, spread=0.18, speed=0.012, count=6))
            lines.extend(_accent_lines(namespace, cx, base_y + 0.22, cz, fx_style=fx_style, strength="burst"))
        if tick_energy >= 900:
            # A dense, high-energy tick gets one higher wash rather than many
            # separate firework bursts. This reads like a chorus hit without noise.
            lines.append(_dl(chord_color, min_note, max_note, cx, base_y + 0.48, cz, scale=0.72, spread=0.46, speed=0.012, count=10))

    # 3) Quarter-beat accent. MIDI files do not always have a time signature, so
    # use PPQ quarter boundaries as a conservative beat cue. Keep it tiny.
    if "beat" in layers and fx in {"lightshow", "both"} and ticks_per_quarter > 0:
        beat_notes = [note for note in tick_notes if note.note.start_tick % ticks_per_quarter == 0]
        if beat_notes:
            beat = _strongest(beat_notes) or strongest
            x, z = _note_xz(beat, stage_profile, noteblock_layout)
            y = 3.00 if stage_profile == "noteblock_machine" else 2.45
            lines.append(_dl(beat, min_note, max_note, x, y, z, scale=0.72, spread=0.20, speed=0.006, count=6))

    # 4) High lead sparkle. Strong high melodic notes get a very small upper
    # accent, separated from chord bloom and drum pulses.
    melodic = [note for note in tick_notes if not note.note.is_drum]
    lead = max(melodic, key=lambda note: (note.note.note, note.note.velocity), default=None)
    if "lead" in layers and fx in {"lightshow", "both"} and lead is not None and lead.note.note >= 72 and lead.note.velocity >= 92:
        x, z = _note_xz(lead, stage_profile, noteblock_layout)
        y = 4.05 if stage_profile == "noteblock_machine" else 3.30
        lines.append(_dl(lead, min_note, max_note, x, y, z, scale=0.62, spread=0.16, speed=0.010, count=6))

    # 4) Firework-style burst remains opt-in, but chord/accent-aware now. This
    # keeps 'both' from becoming too noisy on dense MIDI.
    if "fireworks" in layers and fx in {"fireworks", "both"} and (unique_pitches >= 4 or _is_major_moment(strongest)):
        cx, cz = _center_of(tick_notes, stage_profile, noteblock_layout)
        y = 4.45 if strongest.note.is_drum else 5.10
        burst_count = 10 if strongest.note.velocity < 112 else 16
        lines.extend(
            [
                _dl(strongest, min_note, max_note, cx, y, cz, scale=1.22, spread=0.32, speed=0.028, count=burst_count),
                _dl(strongest, min_note, max_note, cx + 0.42, y + 0.20, cz, scale=0.86, spread=0.15, speed=0.018, count=5),
                _dl(strongest, min_note, max_note, cx - 0.42, y + 0.20, cz, scale=0.86, spread=0.15, speed=0.018, count=5),
            ]
        )

    # 5) Finale burst. The last generated note event gets one restrained burst,
    # especially useful for vanilla demo videos. It is still particle-only.
    if "finale" in layers and fx in {"fireworks", "both"} and current_tick is not None and final_note_tick is not None and current_tick == final_note_tick:
        cx, cz = _center_of(tick_notes, stage_profile, noteblock_layout)
        y = 5.35 if stage_profile == "noteblock_machine" else 4.25
        lines.append(_dl(strongest, min_note, max_note, cx, y, cz, scale=1.50, spread=0.48, speed=0.032, count=24))
        lines.append(_dl(strongest, min_note, max_note, cx, y + 0.32, cz, scale=0.95, spread=0.70, speed=0.022, count=12))
    return lines


def show_fx_note_lines(
    compiled: CompiledNote,
    namespace: str,
    min_note: int,
    max_note: int,
    stage_profile: str,
    fx_profile: str,
    noteblock_layout: NoteblockLayout | None = None,
    *,
    fx_style: str = "concert",
    fx_intensity: float = 1.0,
    fx_layers: str = "all",
) -> list[str]:
    fx = resolve_show_fx(fx_profile, mode="command_stage", stage_profile=stage_profile, quality="medium")
    fx_style = normalize_fx_profile(fx_style)
    fx_intensity = normalize_fx_intensity(fx_intensity)
    layers = normalize_fx_layers(fx_layers)
    if fx == "none" or fx_intensity <= 0:
        return []
    x, z = _note_xz(compiled, stage_profile, noteblock_layout)
    velocity = max(1, min(127, compiled.note.velocity))
    lines: list[str] = []

    def _dl(compiled: CompiledNote, min_note: int, max_note: int, x: float, y: float, z: float, **kwargs) -> str:
        return _dust_line(namespace, compiled, min_note, max_note, x, y, z, fx_style=fx_style, fx_intensity=fx_intensity, **kwargs)

    if "note" in layers and fx in {"lightshow", "both"}:
        # v1.6: keep the readable v1.6 height, but make ordinary notes slightly
        # cleaner and let tick-level arrangement FX carry drums/chords/beats.
        if stage_profile == "noteblock_machine":
            height = 3.05 + min(0.18, velocity / 500.0)
            # Drums are carried by tick-level v2.6+ kit FX, so per-note dust stays
            # lighter to prevent clutter.
            count = 5 if compiled.note.is_drum else (8 if velocity < 88 else 11)
            spread = 0.07 if compiled.note.is_drum else (0.09 if velocity < 96 else 0.13)
        else:
            height = 2.20 + min(0.26, velocity / 390.0)
            count = 8 if velocity < 88 else 11
            spread = 0.09 if velocity < 96 else 0.13
        lines.append(_dl(compiled, min_note, max_note, x, height, z, scale=0.98, spread=spread, speed=0.004, count=count))
        if velocity >= 96 or compiled.used_continuous:
            lines.append(_dl(compiled, min_note, max_note, x, height + 0.18, z, scale=0.82, spread=0.12, speed=0.004, count=6))

    # Most firework work moved to tick-level logic in v1.6 so chords do not spawn
    # one burst per note. Keep a tiny per-note accent for isolated strong notes.
    if "fireworks" in layers and fx in {"fireworks", "both"} and _is_major_moment(compiled):
        y = 4.25 if compiled.note.is_drum else 4.95
        lines.append(_dl(compiled, min_note, max_note, x, y, z, scale=1.05, spread=0.20, speed=0.022, count=7))
    return lines


def show_fx_usage_report(compiled: list[CompiledNote], enabled_profile: str, stage_profile: str, *, fx_style: str = "concert", fx_intensity: float = 1.0, fx_layers: str = "all") -> dict[str, object]:
    fx_style = normalize_fx_profile(fx_style)
    fx_intensity = normalize_fx_intensity(fx_intensity)
    layers = sorted(normalize_fx_layers(fx_layers))
    if enabled_profile == "none" or fx_intensity <= 0:
        return {"enabled": False, "profile": "none", "fx_profile": fx_style, "fx_intensity": fx_intensity, "fx_layers": layers}
    strong = sum(1 for note in compiled if _is_strong_note(note))
    major = sum(1 for note in compiled if _is_major_moment(note))
    module_counts: Counter[str] = Counter()
    if stage_profile == "soma_concert":
        module_counts.update(soma_module_for(note) for note in compiled if note.sound_engine == "soma")
    return {
        "enabled": True,
        "profile": enabled_profile,
        "fx_profile": fx_style,
        "stage_profile": stage_profile,
        "note_count": len(compiled),
        "strong_note_count": strong,
        "firework_style_burst_candidates": major,
        "uses_real_firework_entities": False,
        "particle": "minecraft:dust{color:[r,g,b],scale:s} plus sparse profile accents",
        "available_fx_profiles": ["clean", "redstone", "concert", "magic"],
        "fx_intensity": fx_intensity,
        "fx_layers": layers,
        "available_fx_layers": sorted(FX_LAYER_CHOICES),
        "color_policy": "RGB dust: clean/concert follow the same Minecraft note-particle hue; redstone uses warm circuit colors; magic shifts toward purple/blue",
        "fade_policy": "visible_mid_stage_rgb_dust_above_blocks_below_note_sprite",
        "arrangement_policy": "v2.8 tick-level FX adds velocity-scaled dust, drum-family pulses, bass pressure, density-aware chord blooms, lead sparkle, quarter-beat accents, and finale bursts",
        "smart_dynamics": {
            "velocity_scaled_per_note_dust": True,
            "density_aware_chord_bloom": True,
            "bass_floor_pressure": True,
            "high_lead_sparkle": True,
            "finale_burst_in_fireworks_profiles": enabled_profile in {"fireworks", "both"},
        },
        "policy": "show_fx controls layers; fx_profile controls style/palette. lightshow=velocity-scaled dust plus drum/instrument/density-aware cues; fireworks=opt-in accent/chord/finale bursts following each stage module/lane",
        "soma_module_counts": dict(module_counts),
    }
