from __future__ import annotations

import math
import colorsys
from .model import NoteEvent

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Minecraft note block sound event suffixes.
VANILLA_INSTRUMENTS = {
    "harp": "minecraft:block.note_block.harp",
    "basedrum": "minecraft:block.note_block.basedrum",
    "snare": "minecraft:block.note_block.snare",
    "hat": "minecraft:block.note_block.hat",
    "bass": "minecraft:block.note_block.bass",
    "flute": "minecraft:block.note_block.flute",
    "bell": "minecraft:block.note_block.bell",
    "guitar": "minecraft:block.note_block.guitar",
    "chime": "minecraft:block.note_block.chime",
    "xylophone": "minecraft:block.note_block.xylophone",
    "iron_xylophone": "minecraft:block.note_block.iron_xylophone",
    "cow_bell": "minecraft:block.note_block.cow_bell",
    "didgeridoo": "minecraft:block.note_block.didgeridoo",
    "bit": "minecraft:block.note_block.bit",
    "banjo": "minecraft:block.note_block.banjo",
    "pling": "minecraft:block.note_block.pling",
}

# Visual note block bases for the pseudo-redstone stage. These are vanilla note
# block instrument blocks: guitar on wool, bit/square-wave on emerald block, etc.
INSTRUMENT_BASE_BLOCKS = {
    "harp": "minecraft:dirt",
    "basedrum": "minecraft:stone",
    "snare": "minecraft:sand",
    "hat": "minecraft:glass",
    "bass": "minecraft:oak_planks",
    "flute": "minecraft:clay",
    "bell": "minecraft:gold_block",
    "guitar": "minecraft:white_wool",
    "chime": "minecraft:packed_ice",
    "xylophone": "minecraft:bone_block",
    "iron_xylophone": "minecraft:iron_block",
    "cow_bell": "minecraft:soul_sand",
    "didgeridoo": "minecraft:pumpkin",
    "bit": "minecraft:emerald_block",
    "banjo": "minecraft:hay_block",
    "pling": "minecraft:glowstone",
}

INSTRUMENT_LABELS = {
    "harp": "Harp/Piano",
    "basedrum": "Bass Drum",
    "snare": "Snare",
    "hat": "Hat",
    "bass": "Bass",
    "flute": "Flute",
    "bell": "Bell",
    "guitar": "Guitar",
    "chime": "Chime",
    "xylophone": "Xylophone",
    "iron_xylophone": "Iron Xylo",
    "cow_bell": "Cow Bell",
    "didgeridoo": "Didgeridoo",
    "bit": "Bit/Square",
    "banjo": "Banjo",
    "pling": "Pling",
}


def midi_note_name(note: int) -> str:
    octave = note // 12 - 1
    return f"{NOTE_NAMES[note % 12]}{octave}"


def vanilla_sound_for(note: NoteEvent) -> str:
    return VANILLA_INSTRUMENTS[instrument_key_for(note)]


def instrument_key_for(note: NoteEvent) -> str:
    if note.is_drum:
        return drum_instrument(note.note)

    program = note.program
    # General MIDI program ranges, zero-based. This is intentionally simple in v0.1.x.
    if 32 <= program <= 39:
        return "bass"
    if 24 <= program <= 31:
        return "guitar"
    if 40 <= program <= 47:
        return "harp"  # strings: harp is softer than pling
    if 56 <= program <= 63:
        return "bell"
    if 64 <= program <= 79:
        return "flute"
    if 80 <= program <= 87:
        return "bit"
    if 88 <= program <= 95:
        return "chime"
    if 104 <= program <= 111:
        return "banjo"
    return "harp"


def drum_instrument(drum_note: int) -> str:
    # General MIDI percussion map, simplified for Minecraft note block sounds.
    if drum_note in {35, 36, 41, 43, 45, 47}:  # kick / low toms
        return "basedrum"
    if drum_note in {38, 39, 40}:  # snare / clap
        return "snare"
    if drum_note in {42, 44, 46, 49, 51, 52, 55, 57, 59}:  # hats / cymbals
        return "hat"
    return "snare"


def instrument_base_block_for(note: NoteEvent) -> str:
    return INSTRUMENT_BASE_BLOCKS[instrument_key_for(note)]


def note_block_state_for(note: NoteEvent) -> str:
    instrument = instrument_key_for(note)
    note_value = note_block_note_value(note.note)
    return f"minecraft:note_block[instrument={instrument},note={note_value},powered=false]"


def note_block_note_value(midi_note: int) -> int:
    # Vanilla note blocks have 25 visible note states. For the stage we use the
    # nearest repeating visual state; actual pitch still comes from playsound.
    return max(0, min(24, (midi_note - 54) % 25))


def vanilla_pitch_for(midi_note: int) -> float:
    # Playsound pitch is a float, but note block sounds are pleasant in roughly 0.5..2.0.
    # MIDI note 66 (F#4) maps to pitch 1.0, then shifts by semitones.
    pitch = math.pow(2.0, (midi_note - 66) / 12.0)
    while pitch < 0.5:
        pitch *= 2.0
    while pitch > 2.0:
        pitch /= 2.0
    return round(max(0.5, min(2.0, pitch)), 4)


def volume_for(velocity: int, gain: float = 1.0) -> float:
    velocity = max(1, min(127, velocity))
    volume = (0.25 + 0.75 * velocity / 127.0) * gain
    return round(max(0.0, min(3.0, volume)), 3)



def note_particle_color_for_note(
    midi_note: int,
    min_note: int | None = None,
    max_note: int | None = None,
) -> float:
    """Return the Java note particle color parameter for a MIDI pitch.

    For the vanilla note particle, count=0 makes delta X select the color.
    0.0 and 1.0 are both green, so keep away from exact endpoints to make
    low/high notes visibly different.
    """
    low = 21 if min_note is None else min_note
    high = 108 if max_note is None else max_note
    if high <= low:
        normalized = 0.5
    else:
        normalized = (max(low, min(high, midi_note)) - low) / (high - low)
    return round(0.05 + normalized * 0.90, 4)



def rgb_for_note(
    midi_note: int,
    min_note: int | None = None,
    max_note: int | None = None,
) -> tuple[float, float, float]:
    """Return RGB matching Minecraft's note-particle hue as closely as possible.

    The stage still uses vanilla note particles for the tiny note sprite. Dust FX
    should feel like the same color family rather than a separate blue-to-red
    gradient, so v0.10 derives RGB from the same note color parameter and the
    classic Minecraft note-particle sine palette.
    """
    hue = note_particle_color_for_note(midi_note, min_note=min_note, max_note=max_note)
    # Minecraft note particles use a cyclic sine palette. This approximation
    # makes dust FX visually line up with the note particles that sit above it.
    tau = math.tau
    r = max(0.0, math.sin((hue + 0.0) * tau) * 0.65 + 0.35)
    g = max(0.0, math.sin((hue + 1.0 / 3.0) * tau) * 0.65 + 0.35)
    b = max(0.0, math.sin((hue + 2.0 / 3.0) * tau) * 0.65 + 0.35)
    return (round(r, 3), round(g, 3), round(b, 3))

def dust_particle_for_note(
    midi_note: int,
    min_note: int | None = None,
    max_note: int | None = None,
    scale: float = 1.0,
) -> str:
    """Return a Java 1.21.x dust particle id with SNBT color parameters."""
    r, g, b = rgb_for_note(midi_note, min_note=min_note, max_note=max_note)
    return f"minecraft:dust{{color:[{r:.3f}f,{g:.3f}f,{b:.3f}f],scale:{scale:.2f}f}}"


def lane_for_note(midi_note: int, width: int = 17) -> int:
    # Keep the stage compact: map notes into repeated lanes around center.
    width = max(3, width)
    left = -(width // 2)
    return left + (midi_note % width)


def wool_for_note(midi_note: int) -> str:
    colors = [
        "red_wool",
        "orange_wool",
        "yellow_wool",
        "lime_wool",
        "green_wool",
        "cyan_wool",
        "light_blue_wool",
        "blue_wool",
        "purple_wool",
        "magenta_wool",
        "pink_wool",
        "white_wool",
    ]
    return f"minecraft:{colors[midi_note % len(colors)]}"
