from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QualityProfile:
    name: str
    label: str
    max_notes_per_tick: int
    stage_particles: bool
    piano_roll: bool
    description: str


QUALITY_PROFILES: dict[str, QualityProfile] = {
    "low": QualityProfile(
        name="low",
        label="Low / 稳定优先",
        max_notes_per_tick=8,
        stage_particles=False,
        piano_roll=False,
        description="适合大型 MIDI 或低性能环境：限制复音，关闭舞台粒子，只保留声音和灯光反馈。",
    ),
    "medium": QualityProfile(
        name="medium",
        label="Medium / 默认",
        max_notes_per_tick=24,
        stage_particles=True,
        piano_roll=False,
        description="默认推荐：保留舞台粒子和灯光，Piano Roll 默认关闭。",
    ),
    "high": QualityProfile(
        name="high",
        label="High / 效果优先",
        max_notes_per_tick=48,
        stage_particles=True,
        piano_roll=False,
        description="适合较强设备或较小 MIDI：允许更多同 tick 音符，保留完整舞台反馈；Piano Roll 仍默认关闭。",
    ),
    "insane": QualityProfile(
        name="insane",
        label="Insane / 不太讲武德",
        max_notes_per_tick=96,
        stage_particles=True,
        piano_roll=False,
        description="尽量保留复杂和弦；可能造成卡顿，Piano Roll 仍需手动开启。",
    ),
}


def quality_profile(name: str | None) -> QualityProfile:
    key = (name or "medium").strip().lower()
    return QUALITY_PROFILES.get(key, QUALITY_PROFILES["medium"])


def quality_choices() -> list[str]:
    return list(QUALITY_PROFILES.keys())


def quality_choice_items() -> list[tuple[str, str]]:
    return [(profile.name, f"{profile.label}：{profile.description}") for profile in QUALITY_PROFILES.values()]
