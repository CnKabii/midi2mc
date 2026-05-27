from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

from .mapping import instrument_key_for, midi_note_name
from .model import MidiSong, NoteEvent
from .recommend import TickRateRecommendation


@dataclass(frozen=True)
class SongStats:
    duration_text: str
    note_range: str
    min_note: int | None
    max_note: int | None
    used_track_count: int
    used_channel_count: int
    drum_note_count: int
    melodic_note_count: int
    max_polyphony_raw: int
    max_polyphony_compiled: int
    dropped_note_count: int
    busiest_ticks: list[tuple[int, int]]
    top_instruments: list[tuple[str, int]]
    top_tracks: list[tuple[str, int]]


def format_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    whole = int(round(seconds))
    minutes, sec = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def build_song_stats(song: MidiSong, tick_rate: int, max_notes_per_tick: int) -> SongStats:
    notes = list(song.notes)
    note_values = [n.note for n in notes]
    min_note = min(note_values) if note_values else None
    max_note = max(note_values) if note_values else None
    if min_note is None or max_note is None:
        note_range = "无音符"
    else:
        note_range = f"{midi_note_name(min_note)}..{midi_note_name(max_note)} ({min_note}..{max_note})"

    raw_by_tick: dict[int, list[NoteEvent]] = defaultdict(list)
    for note in notes:
        raw_by_tick[max(0, round(note.start_sec * tick_rate))].append(note)
    raw_counts = sorted(((tick, len(group)) for tick, group in raw_by_tick.items()), key=lambda item: (-item[1], item[0]))
    max_polyphony_raw = raw_counts[0][1] if raw_counts else 0
    max_polyphony_compiled = min(max_polyphony_raw, max_notes_per_tick) if raw_counts else 0
    dropped_note_count = sum(max(0, count - max_notes_per_tick) for _, count in raw_counts)

    instruments = Counter(instrument_key_for(note) for note in notes)
    tracks = Counter(_track_label(song, note) for note in notes)

    return SongStats(
        duration_text=format_duration(song.duration_sec),
        note_range=note_range,
        min_note=min_note,
        max_note=max_note,
        used_track_count=len({n.track_index for n in notes}),
        used_channel_count=len({n.channel for n in notes}),
        drum_note_count=sum(1 for n in notes if n.is_drum),
        melodic_note_count=sum(1 for n in notes if not n.is_drum),
        max_polyphony_raw=max_polyphony_raw,
        max_polyphony_compiled=max_polyphony_compiled,
        dropped_note_count=dropped_note_count,
        busiest_ticks=raw_counts[:5],
        top_instruments=instruments.most_common(8),
        top_tracks=tracks.most_common(8),
    )


def _track_label(song: MidiSong, note: NoteEvent) -> str:
    name = note.track_name or song.track_names.get(note.track_index, "")
    if name:
        return f"Track {note.track_index}: {name}"
    return f"Track {note.track_index}"


def format_midi_summary_lines(
    song: MidiSong,
    recommendation: TickRateRecommendation | None,
    tick_rate: int,
    max_notes_per_tick: int,
) -> list[str]:
    stats = build_song_stats(song, tick_rate=tick_rate, max_notes_per_tick=max_notes_per_tick)
    lines = [
        "MIDI 信息摘要:",
        f"  时长: {stats.duration_text} ({song.duration_sec:.2f}s)",
        f"  MIDI 格式: type {song.format_type}, PPQ={song.ticks_per_quarter}",
        f"  音符数量: {song.note_count}",
        f"  音域: {stats.note_range}",
        f"  使用轨道: {stats.used_track_count}，使用声道: {stats.used_channel_count}",
        f"  旋律音符: {stats.melodic_note_count}，鼓组音符: {stats.drum_note_count}",
        f"  编译 TPS: {tick_rate}",
        f"  最大同 tick 复音: {stats.max_polyphony_raw}，当前上限: {max_notes_per_tick}",
    ]
    if stats.dropped_note_count:
        lines.append(f"  复音裁剪: {stats.dropped_note_count} 个音符会因上限被跳过")
    else:
        lines.append("  复音裁剪: 无")
    if recommendation:
        lines.extend(
            [
                f"  主 BPM: {recommendation.primary_bpm:.2f}",
                f"  推荐 /tick rate: {recommendation.tick_rate}",
                f"  节拍换算: 1拍≈{recommendation.beat_ticks:.2f}tick，1/8≈{recommendation.eighth_ticks:.2f}tick，1/16≈{recommendation.sixteenth_ticks:.2f}tick",
            ]
        )
    if stats.top_instruments:
        lines.append("  主要 MC 乐器: " + ", ".join(f"{name}×{count}" for name, count in stats.top_instruments[:5]))
    if stats.top_tracks:
        lines.append("  主要轨道: " + ", ".join(f"{name}×{count}" for name, count in stats.top_tracks[:5]))
    return lines


def format_midi_summary_text(
    song: MidiSong,
    recommendation: TickRateRecommendation | None,
    tick_rate: int,
    max_notes_per_tick: int,
) -> str:
    return "\n".join(format_midi_summary_lines(song, recommendation, tick_rate, max_notes_per_tick))


def warning_lines(song: MidiSong, tick_rate: int, max_notes_per_tick: int) -> list[str]:
    stats = build_song_stats(song, tick_rate=tick_rate, max_notes_per_tick=max_notes_per_tick)
    warnings: list[str] = []
    if song.note_count == 0:
        warnings.append("这个 MIDI 没有解析到音符；生成的数据包可以加载，但不会播放声音。")
    if song.note_count > 20_000:
        warnings.append("音符数量非常多，建议先用 low/较低复音上限测试，避免游戏卡顿。")
    elif song.note_count > 8_000:
        warnings.append("音符数量偏多，如果游戏卡顿，可以降低同 tick 最大复音数。")
    if stats.max_polyphony_raw > max_notes_per_tick:
        warnings.append(
            f"检测到同 tick 最高 {stats.max_polyphony_raw} 个音符，当前上限 {max_notes_per_tick}，会裁剪 {stats.dropped_note_count} 个低优先级音符。"
        )
    if tick_rate > 40:
        warnings.append("推荐 TPS 高于 40，节奏会更细，但游戏世界速度也会更快，性能压力更大。")
    if len(song.tempo_events) > 8:
        warnings.append("这个 MIDI 有较多 tempo 变化；当前版本按秒编译可以播放，但只提示一个主 BPM。")
    return warnings
