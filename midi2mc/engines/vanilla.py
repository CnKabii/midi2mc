from __future__ import annotations

from ..mapping import (
    INSTRUMENT_LABELS,
    instrument_key_for,
    vanilla_pitch_for,
    vanilla_sound_for,
    volume_for,
)
from ..model import NoteEvent
from .base import ResolvedSound, SoundEngine


class VanillaSoundEngine(SoundEngine):
    """Original Minecraft note block sound engine.

    This is the best match for the pseudo-redstone note block machine stage.
    """

    name = "vanilla"

    def __init__(self, gain: float = 1.0) -> None:
        self.gain = gain

    def resolve(self, note: NoteEvent) -> ResolvedSound:
        instrument_key = instrument_key_for(note)
        return ResolvedSound(
            sound_id=vanilla_sound_for(note),
            volume=volume_for(note.velocity, self.gain),
            pitch=vanilla_pitch_for(note.note),
            instrument_key=instrument_key,
            sound_label=INSTRUMENT_LABELS.get(instrument_key, instrument_key),
        )

    def readme_notes(self) -> list[str]:
        return [
            "当前音源: vanilla / 原版 note block sounds。",
            "该音源不需要额外资源包，最适合 command_stage 伪红石音乐机。",
        ]

    def manifest(self) -> dict[str, object]:
        return {"name": self.name, "gain": self.gain}
