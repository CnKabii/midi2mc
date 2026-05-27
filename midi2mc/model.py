from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class TempoEvent:
    tick: int
    microseconds_per_quarter: int


@dataclass(frozen=True)
class NoteEvent:
    start_tick: int
    end_tick: int
    start_sec: float
    duration_sec: float
    track_index: int
    channel: int
    note: int
    velocity: int
    program: int = 0
    track_name: str = ""

    @property
    def is_drum(self) -> bool:
        # MIDI channel 10 is zero-based channel 9.
        return self.channel == 9


@dataclass
class MidiSong:
    format_type: int
    ticks_per_quarter: int
    tempo_events: List[TempoEvent]
    notes: List[NoteEvent]
    track_names: Dict[int, str] = field(default_factory=dict)

    @property
    def duration_sec(self) -> float:
        if not self.notes:
            return 0.0
        return max(note.start_sec + note.duration_sec for note in self.notes)

    @property
    def duration_tick(self) -> int:
        if not self.notes:
            return 0
        return max(note.end_tick for note in self.notes)

    @property
    def note_count(self) -> int:
        return len(self.notes)


@dataclass(frozen=True)
class CompiledNote:
    mc_tick: int
    note: NoteEvent
    sound_id: str
    volume: float
    pitch: float
    lane: int
    sound_engine: str = "vanilla"
    instrument_key: str = "harp"
    sound_label: str = "Harp/Piano"
    stop_tick: int | None = None
    stop_sound_id: str | None = None
    used_continuous: bool = False
    requested_continuous: bool = False
    resolved_note: int | None = None
    note_was_clamped: bool = False
    continuous_conflict: bool = False
    fallback_reason: str | None = None
