from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..model import NoteEvent


@dataclass(frozen=True)
class ResolvedSound:
    sound_id: str
    volume: float
    pitch: float
    instrument_key: str
    sound_label: str
    stop_sound_id: str | None = None
    used_continuous: bool = False
    requested_continuous: bool = False
    original_note: int | None = None
    resolved_note: int | None = None
    note_was_clamped: bool = False
    fallback_reason: str | None = None
    fallback_program: int | None = None
    drum_variant: str | None = None
    mapping_category: str | None = None
    soma_class: str | None = None


@dataclass(frozen=True)
class SoundEngineOptions:
    name: str = "vanilla"
    gain: float = 1.0
    soma_namespace: str = ""
    soma_map: Path | None = None
    soma_reference_note: int = 60
    soma_long_note_beats: float = 1.0
    soma_drum_kit: str = "auto"
    ticks_per_quarter: int = 480


class SoundEngine:
    name = "base"

    def resolve(self, note: NoteEvent) -> ResolvedSound:  # pragma: no cover - interface
        raise NotImplementedError

    def resolve_short(self, note: NoteEvent) -> ResolvedSound:
        """Resolve a note without using a continuous/stop-controlled variant.

        Most engines have no separate continuous sound, so the default is the
        normal resolve path. Soma overrides this to protect overlapping long
        notes from cutting each other off with stopsound.
        """
        return self.resolve(note)

    def readme_notes(self) -> list[str]:
        return []

    def manifest(self) -> dict[str, object]:
        return {"name": self.name}


def build_sound_engine(options: SoundEngineOptions) -> SoundEngine:
    name = (options.name or "vanilla").strip().lower()
    if name == "vanilla":
        from .vanilla import VanillaSoundEngine

        return VanillaSoundEngine(gain=options.gain)
    if name == "soma":
        from .soma import SomaSoundEngine

        return SomaSoundEngine(
            namespace=options.soma_namespace,
            gain=options.gain,
            map_path=options.soma_map,
            reference_note=options.soma_reference_note,
            long_note_beats=options.soma_long_note_beats,
            drum_kit=options.soma_drum_kit,
            ticks_per_quarter=options.ticks_per_quarter,
        )
    raise ValueError(f"Unknown sound engine: {options.name!r}")
