from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .model import MidiSong
from .summary import build_song_stats


@dataclass(frozen=True)
class SafetyReport:
    level: str
    score: int
    recommended_quality: str
    recommended_max_notes_per_tick: int
    recommended_show_fx: str
    recommended_stage_particles: bool
    recommended_piano_roll: bool
    reasons: list[str]
    advice: list[str]

    def manifest(self) -> dict[str, Any]:
        return asdict(self)


_LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _max_level(a: str, b: str) -> str:
    return a if _LEVEL_ORDER[a] >= _LEVEL_ORDER[b] else b


def analyze_safety(
    song: MidiSong,
    *,
    tick_rate: int,
    max_notes_per_tick: int,
    quality: str,
    mode: str,
    sound_engine: str,
    stage_profile: str,
    show_fx: str,
    piano_roll: bool,
) -> SafetyReport:
    """Heuristic safety/risk report for large or dense MIDI files.

    This deliberately avoids hard-failing normal exports. It gives the user a
    readable risk level and powers --safe-mode defaults.
    """
    stats = build_song_stats(song, tick_rate=tick_rate, max_notes_per_tick=max_notes_per_tick)
    score = 0
    level = "low"
    reasons: list[str] = []
    advice: list[str] = []

    if song.note_count > 50_000:
        score += 60
        level = _max_level(level, "critical")
        reasons.append(f"音符数量极高：{song.note_count}，数据包和游戏内执行压力都很大。")
    elif song.note_count > 20_000:
        score += 42
        level = _max_level(level, "high")
        reasons.append(f"音符数量很高：{song.note_count}，建议先用 safe-mode 或 low 档测试。")
    elif song.note_count > 8_000:
        score += 24
        level = _max_level(level, "medium")
        reasons.append(f"音符数量偏多：{song.note_count}。")

    if stats.max_polyphony_raw > 96:
        score += 45
        level = _max_level(level, "critical")
        reasons.append(f"同 tick 最高复音 {stats.max_polyphony_raw}，极易造成命令爆发。")
    elif stats.max_polyphony_raw > 48:
        score += 30
        level = _max_level(level, "high")
        reasons.append(f"同 tick 最高复音 {stats.max_polyphony_raw}，建议降低复音上限。")
    elif stats.max_polyphony_raw > 24:
        score += 15
        level = _max_level(level, "medium")
        reasons.append(f"同 tick 最高复音 {stats.max_polyphony_raw}，中等复杂度。")

    if max_notes_per_tick > 48:
        score += 12
        level = _max_level(level, "medium")
        reasons.append(f"当前同 tick 上限 {max_notes_per_tick} 较高。")
    if tick_rate > 40:
        score += 16
        level = _max_level(level, "medium")
        reasons.append(f"编译 TPS {tick_rate} 较高，会增加每秒执行次数。")
    if mode == "command_stage":
        score += 8
        if show_fx in {"fireworks", "both"}:
            score += 14
            reasons.append("已启用烟花风格粒子，复杂 MIDI 下建议谨慎。")
        elif show_fx == "lightshow":
            score += 7
        if piano_roll:
            score += 18
            level = _max_level(level, "medium")
            reasons.append("Piano Roll 已启用，可能增加粒子命令数量。")
    if sound_engine == "soma" and stage_profile == "soma_concert":
        score += 6

    if score >= 80:
        level = _max_level(level, "critical")
    elif score >= 48:
        level = _max_level(level, "high")
    elif score >= 22:
        level = _max_level(level, "medium")

    if level in {"high", "critical"}:
        recommended_quality = "low"
        recommended_max_notes = 8
        recommended_show_fx = "none"
        recommended_stage_particles = False
        recommended_piano_roll = False
        advice.extend([
            "建议先用 --safe-mode 生成一个低风险版本确认能播放。",
            "如果需要更完整的和弦，再逐步提高 --max-notes-per-tick。",
            "大型 MIDI 建议先关闭 Show FX / Piano Roll。",
        ])
    elif level == "medium":
        recommended_quality = "medium" if quality != "insane" else "high"
        recommended_max_notes = min(max_notes_per_tick, 24)
        recommended_show_fx = "lightshow" if show_fx not in {"fireworks", "both"} else "none"
        recommended_stage_particles = True
        recommended_piano_roll = False
        advice.extend([
            "建议保持 medium 档或手动限制同 tick 复音。",
            "如果游戏卡顿，优先关闭 fireworks 和 Piano Roll。",
        ])
    else:
        recommended_quality = quality
        recommended_max_notes = max_notes_per_tick
        recommended_show_fx = show_fx
        recommended_stage_particles = quality != "low"
        recommended_piano_roll = piano_roll
        advice.append("风险较低，可以按当前设置生成。")

    if not reasons:
        reasons.append("未检测到明显的大型 MIDI 风险。")

    return SafetyReport(
        level=level,
        score=score,
        recommended_quality=recommended_quality,
        recommended_max_notes_per_tick=recommended_max_notes,
        recommended_show_fx=recommended_show_fx,
        recommended_stage_particles=recommended_stage_particles,
        recommended_piano_roll=recommended_piano_roll,
        reasons=reasons,
        advice=advice,
    )


def format_safety_report(report: SafetyReport) -> str:
    lines = [
        f"风险等级: {report.level} (score={report.score})",
        f"建议质量档: {report.recommended_quality}",
        f"建议同 tick 复音上限: {report.recommended_max_notes_per_tick}",
        f"建议 Show FX: {report.recommended_show_fx}",
        f"建议舞台粒子: {'开启' if report.recommended_stage_particles else '关闭'}",
        f"建议 Piano Roll: {'开启' if report.recommended_piano_roll else '关闭'}",
        "原因:",
    ]
    lines.extend(f"  - {line}" for line in report.reasons)
    lines.append("建议:")
    lines.extend(f"  - {line}" for line in report.advice)
    return "\n".join(lines)
