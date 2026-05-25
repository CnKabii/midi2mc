from __future__ import annotations

import math
from dataclasses import dataclass

from .model import MidiSong, TempoEvent


@dataclass(frozen=True)
class TickRateRecommendation:
    tick_rate: int
    primary_bpm: float
    beat_ticks: float
    eighth_ticks: float
    sixteenth_ticks: float
    tempo_count: int
    reason: str


def bpm_from_tempo(event: TempoEvent) -> float:
    if event.microseconds_per_quarter <= 0:
        return 120.0
    return 60_000_000.0 / event.microseconds_per_quarter


def primary_bpm(song: MidiSong) -> float:
    tempos = sorted(song.tempo_events, key=lambda e: e.tick)
    if not tempos:
        return 120.0
    if song.duration_tick <= 0:
        return bpm_from_tempo(tempos[0])

    best = tempos[0]
    best_span = -1
    for index, event in enumerate(tempos):
        next_tick = tempos[index + 1].tick if index + 1 < len(tempos) else song.duration_tick
        span = max(0, next_tick - event.tick)
        if span > best_span:
            best_span = span
            best = event
    return bpm_from_tempo(best)


def recommend_tick_rate(song: MidiSong, minimum: int = 20, maximum: int = 60) -> TickRateRecommendation:
    """Suggest an integer /tick rate that makes common MIDI subdivisions cleaner.

    The goal is not to chase the highest TPS. We favor rates where the dominant
    BPM maps quarter/eighth/sixteenth notes near integer Minecraft ticks, then
    add a small penalty for rates above vanilla 20 TPS so the recommendation
    stays practical.
    """
    bpm = primary_bpm(song)
    tempos = sorted(song.tempo_events, key=lambda e: e.tick) or [TempoEvent(0, 500_000)]

    weighted_tempos: list[tuple[float, float]] = []
    if song.duration_tick > 0:
        for index, event in enumerate(tempos):
            next_tick = tempos[index + 1].tick if index + 1 < len(tempos) else song.duration_tick
            span = max(0, next_tick - event.tick)
            if span:
                weighted_tempos.append((bpm_from_tempo(event), float(span)))
    if not weighted_tempos:
        weighted_tempos = [(bpm, 1.0)]

    total_weight = sum(weight for _, weight in weighted_tempos) or 1.0

    def nearest_integer_error(value: float) -> float:
        nearest = round(value)
        if nearest <= 0:
            return 9.0
        return abs(value - nearest)

    best_rate = 20
    best_score = math.inf
    for rate in range(minimum, maximum + 1):
        score = 0.0
        for tempo_bpm, weight in weighted_tempos:
            beat = rate * 60.0 / tempo_bpm
            eighth = beat / 2.0
            sixteenth = beat / 4.0
            triplet_eighth = beat / 3.0
            # Favor sixteenth and eighth alignment, but do not fully ignore beats/triplets.
            local = (
                1.8 * nearest_integer_error(sixteenth)
                + 1.2 * nearest_integer_error(eighth)
                + 0.7 * nearest_integer_error(beat)
                + 0.35 * nearest_integer_error(triplet_eighth)
            )
            score += local * weight / total_weight
        # Practicality penalty: huge tick rates are expensive and change the world speed a lot.
        score += max(0, rate - 30) * 0.018
        # Prefer familiar rates if they tie closely.
        if rate in {20, 24, 25, 30, 40, 48, 60}:
            score -= 0.015
        if score < best_score - 1e-9:
            best_score = score
            best_rate = rate

    beat = best_rate * 60.0 / bpm
    eighth = beat / 2.0
    sixteenth = beat / 4.0
    reason = (
        f"dominant BPM {bpm:.2f}; at {best_rate} TPS: "
        f"quarter={beat:.2f} ticks, eighth={eighth:.2f}, sixteenth={sixteenth:.2f}"
    )
    return TickRateRecommendation(
        tick_rate=best_rate,
        primary_bpm=bpm,
        beat_ticks=beat,
        eighth_ticks=eighth,
        sixteenth_ticks=sixteenth,
        tempo_count=len(song.tempo_events),
        reason=reason,
    )
