from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from .model import MidiSong, NoteEvent, TempoEvent


class MidiParseError(ValueError):
    """Raised when a MIDI file cannot be parsed by the v0.1 parser."""


@dataclass
class _RawNote:
    start_tick: int
    end_tick: int
    track_index: int
    channel: int
    note: int
    velocity: int
    program: int
    track_name: str


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def read(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise MidiParseError("Unexpected end of MIDI data")
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out

    def read_u16(self) -> int:
        return int.from_bytes(self.read(2), "big")

    def read_u32(self) -> int:
        return int.from_bytes(self.read(4), "big")

    def read_varlen(self) -> int:
        value = 0
        for _ in range(4):
            b = self.read(1)[0]
            value = (value << 7) | (b & 0x7F)
            if not (b & 0x80):
                return value
        raise MidiParseError("Invalid variable length quantity")


def parse_midi(path: str | Path) -> MidiSong:
    data = Path(path).read_bytes()
    reader = _Reader(data)

    if reader.read(4) != b"MThd":
        raise MidiParseError("Not a Standard MIDI File: missing MThd header")
    header_length = reader.read_u32()
    if header_length < 6:
        raise MidiParseError("Invalid MIDI header length")

    format_type = reader.read_u16()
    track_count = reader.read_u16()
    division = reader.read_u16()
    if header_length > 6:
        reader.read(header_length - 6)

    if division & 0x8000:
        raise MidiParseError("SMPTE time division is not supported in midi2mc v0.1")
    ticks_per_quarter = division
    if ticks_per_quarter <= 0:
        raise MidiParseError("Invalid ticks-per-quarter value")

    tempo_events: List[TempoEvent] = [TempoEvent(0, 500_000)]
    raw_notes: List[_RawNote] = []
    track_names: Dict[int, str] = {}

    for track_index in range(track_count):
        if reader.remaining() < 8:
            raise MidiParseError(f"Missing MTrk header for track {track_index}")
        chunk_type = reader.read(4)
        length = reader.read_u32()
        chunk = reader.read(length)
        if chunk_type != b"MTrk":
            # Unknown top-level chunks are rare in MIDI files, but skip them.
            continue
        track_tempos, track_notes, track_name = _parse_track(
            chunk, track_index=track_index
        )
        tempo_events.extend(track_tempos)
        raw_notes.extend(track_notes)
        if track_name:
            track_names[track_index] = track_name

    # Deduplicate tempo events at tick 0, keeping the last declared value for that tick.
    tempo_events = _normalize_tempos(tempo_events)
    notes = _materialize_notes(raw_notes, tempo_events, ticks_per_quarter)
    notes.sort(key=lambda n: (n.start_tick, n.track_index, n.channel, n.note, n.velocity))

    return MidiSong(
        format_type=format_type,
        ticks_per_quarter=ticks_per_quarter,
        tempo_events=tempo_events,
        notes=notes,
        track_names=track_names,
    )


def _parse_track(
    chunk: bytes, *, track_index: int
) -> Tuple[List[TempoEvent], List[_RawNote], str]:
    reader = _Reader(chunk)
    absolute_tick = 0
    running_status: int | None = None
    current_program = {channel: 0 for channel in range(16)}
    active_notes: Dict[Tuple[int, int], List[Tuple[int, int, int]]] = {}
    notes: List[_RawNote] = []
    tempos: List[TempoEvent] = []
    track_name = ""

    while reader.remaining() > 0:
        delta = reader.read_varlen()
        absolute_tick += delta

        status_or_data = reader.read(1)[0]
        if status_or_data < 0x80:
            if running_status is None:
                raise MidiParseError("Running status used before a status byte")
            status = running_status
            first_data = status_or_data
        else:
            status = status_or_data
            first_data = None
            if status < 0xF0:
                running_status = status

        if status == 0xFF:
            meta_type = reader.read(1)[0]
            length = reader.read_varlen()
            payload = reader.read(length)
            if meta_type == 0x2F:
                break
            if meta_type == 0x51 and length == 3:
                tempo = int.from_bytes(payload, "big")
                tempos.append(TempoEvent(absolute_tick, tempo))
            elif meta_type == 0x03:
                track_name = _decode_text(payload)
            continue

        if status in (0xF0, 0xF7):
            length = reader.read_varlen()
            reader.read(length)
            continue

        event_type = status & 0xF0
        channel = status & 0x0F
        data_len = 1 if event_type in (0xC0, 0xD0) else 2
        data = []
        if first_data is not None:
            data.append(first_data)
        while len(data) < data_len:
            data.append(reader.read(1)[0])

        if event_type == 0xC0:
            current_program[channel] = data[0]
        elif event_type == 0x90:
            note, velocity = data
            if velocity == 0:
                _finish_note(
                    active_notes,
                    notes,
                    channel,
                    note,
                    absolute_tick,
                    track_index,
                    track_name,
                )
            else:
                active_notes.setdefault((channel, note), []).append(
                    (absolute_tick, velocity, current_program[channel])
                )
        elif event_type == 0x80:
            note = data[0]
            _finish_note(
                active_notes,
                notes,
                channel,
                note,
                absolute_tick,
                track_index,
                track_name,
            )
        # Other channel events are intentionally ignored in v0.1.

    # Close hanging notes at the last known tick to avoid losing simple malformed files.
    for (channel, note), starts in list(active_notes.items()):
        for start_tick, velocity, program in starts:
            if absolute_tick > start_tick:
                notes.append(
                    _RawNote(
                        start_tick=start_tick,
                        end_tick=absolute_tick,
                        track_index=track_index,
                        channel=channel,
                        note=note,
                        velocity=velocity,
                        program=program,
                        track_name=track_name,
                    )
                )

    return tempos, notes, track_name


def _finish_note(
    active_notes: Dict[Tuple[int, int], List[Tuple[int, int, int]]],
    notes: List[_RawNote],
    channel: int,
    note: int,
    absolute_tick: int,
    track_index: int,
    track_name: str,
) -> None:
    starts = active_notes.get((channel, note))
    if not starts:
        return
    start_tick, velocity, program = starts.pop(0)
    if not starts:
        active_notes.pop((channel, note), None)
    if absolute_tick <= start_tick:
        return
    notes.append(
        _RawNote(
            start_tick=start_tick,
            end_tick=absolute_tick,
            track_index=track_index,
            channel=channel,
            note=note,
            velocity=velocity,
            program=program,
            track_name=track_name,
        )
    )


def _decode_text(payload: bytes) -> str:
    for encoding in ("utf-8", "cp932", "latin1"):
        try:
            return payload.decode(encoding).strip("\x00\r\n ")
        except UnicodeDecodeError:
            pass
    return ""


def _normalize_tempos(events: Iterable[TempoEvent]) -> List[TempoEvent]:
    by_tick: Dict[int, int] = {}
    for event in sorted(events, key=lambda e: e.tick):
        by_tick[event.tick] = event.microseconds_per_quarter
    return [TempoEvent(tick, tempo) for tick, tempo in sorted(by_tick.items())]


def _materialize_notes(
    raw_notes: Iterable[_RawNote],
    tempos: List[TempoEvent],
    ticks_per_quarter: int,
) -> List[NoteEvent]:
    return [
        NoteEvent(
            start_tick=raw.start_tick,
            end_tick=raw.end_tick,
            start_sec=ticks_to_seconds(raw.start_tick, tempos, ticks_per_quarter),
            duration_sec=max(
                0.0,
                ticks_to_seconds(raw.end_tick, tempos, ticks_per_quarter)
                - ticks_to_seconds(raw.start_tick, tempos, ticks_per_quarter),
            ),
            track_index=raw.track_index,
            channel=raw.channel,
            note=raw.note,
            velocity=raw.velocity,
            program=raw.program,
            track_name=raw.track_name,
        )
        for raw in raw_notes
    ]


def ticks_to_seconds(
    tick: int, tempo_events: List[TempoEvent], ticks_per_quarter: int
) -> float:
    if tick <= 0:
        return 0.0
    tempos = sorted(tempo_events, key=lambda e: e.tick)
    current_tick = 0
    current_tempo = 500_000
    seconds = 0.0

    for event in tempos:
        if event.tick <= 0:
            current_tempo = event.microseconds_per_quarter
            continue
        if event.tick >= tick:
            break
        delta_ticks = event.tick - current_tick
        seconds += delta_ticks * current_tempo / 1_000_000 / ticks_per_quarter
        current_tick = event.tick
        current_tempo = event.microseconds_per_quarter

    seconds += (tick - current_tick) * current_tempo / 1_000_000 / ticks_per_quarter
    return seconds
