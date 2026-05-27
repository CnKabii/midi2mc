from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PresetProfile:
    name: str
    label: str
    description: str
    values: dict[str, Any]


PRESETS: dict[str, PresetProfile] = {
    "vanilla_clean": PresetProfile(
        "vanilla_clean",
        "Vanilla Clean / 原版干净模式",
        "原版音符盒 Pulse Stage，关闭额外 FX，适合第一次测试。",
        {
            "sound_engine": "vanilla",
            "mode": "command_stage",
            "stage_profile": "noteblock_machine",
            "stage_layout": "compact",
            "quality": "medium",
            "show_fx": "none",
            "piano_roll": False,
        },
    ),
    "vanilla_machine": PresetProfile(
        "vanilla_machine",
        "Vanilla Machine / 原版红石音乐机",
        "默认推荐：原版 Pulse Stage + 自动布局 + 轻量 lightshow。",
        {
            "sound_engine": "vanilla",
            "mode": "command_stage",
            "stage_profile": "noteblock_machine",
            "stage_layout": "auto",
            "quality": "medium",
            "show_fx": "auto",
            "piano_roll": False,
        },
    ),
    "vanilla_fx": PresetProfile(
        "vanilla_fx",
        "Vanilla FX / 原版演出效果",
        "原版 Pulse Stage + wide 布局 + lightshow，适合展示。",
        {
            "sound_engine": "vanilla",
            "mode": "command_stage",
            "stage_profile": "noteblock_machine",
            "stage_layout": "wide",
            "quality": "medium",
            "show_fx": "lightshow",
            "piano_roll": False,
        },
    ),
    "vanilla_fireworks": PresetProfile(
        "vanilla_fireworks",
        "Vanilla Fireworks / 原版强效果",
        "原版 Pulse Stage + both FX，适合短视频展示。",
        {
            "sound_engine": "vanilla",
            "mode": "command_stage",
            "stage_profile": "noteblock_machine",
            "stage_layout": "wide",
            "quality": "high",
            "show_fx": "both",
            "piano_roll": False,
        },
    ),
    "vanilla_safe": PresetProfile(
        "vanilla_safe",
        "Vanilla Safe / 原版安全模式",
        "大型 MIDI 起步测试：低质量、关闭粒子/FX。",
        {
            "sound_engine": "vanilla",
            "mode": "command_stage",
            "stage_profile": "noteblock_machine",
            "stage_layout": "compact",
            "quality": "low",
            "safe_mode": True,
            "show_fx": "none",
            "piano_roll": False,
            "no_stage_particles": True,
            "max_notes_per_tick": 8,
        },
    ),
    "soma_concert": PresetProfile(
        "soma_concert",
        "Soma Concert / Soma 演出舞台",
        "Soma v20 音源 + Soma concert 舞台，轻量 lightshow。",
        {
            "sound_engine": "soma",
            "mode": "command_stage",
            "stage_profile": "soma_concert",
            "stage_layout": "auto",
            "quality": "medium",
            "show_fx": "lightshow",
            "piano_roll": False,
        },
    ),
    "soma_fx": PresetProfile(
        "soma_fx",
        "Soma FX / Soma 强效果",
        "Soma concert 舞台 + both FX。",
        {
            "sound_engine": "soma",
            "mode": "command_stage",
            "stage_profile": "soma_concert",
            "stage_layout": "auto",
            "quality": "high",
            "show_fx": "both",
            "piano_roll": False,
        },
    ),
    "soma_safe": PresetProfile(
        "soma_safe",
        "Soma Safe / Soma 安全模式",
        "Soma 大型 MIDI 起步测试：低质量、关闭粒子/FX。",
        {
            "sound_engine": "soma",
            "mode": "command_stage",
            "stage_profile": "soma_concert",
            "quality": "low",
            "safe_mode": True,
            "show_fx": "none",
            "piano_roll": False,
            "no_stage_particles": True,
            "max_notes_per_tick": 8,
        },
    ),
}


def preset_choices() -> list[str]:
    return list(PRESETS.keys())


def preset_choice_items() -> list[tuple[str, str]]:
    return [(p.name, f"{p.label}: {p.description}") for p in PRESETS.values()]


def get_preset(name: str | None) -> PresetProfile | None:
    if not name:
        return None
    return PRESETS.get(str(name).strip().lower())


def apply_preset(args: Namespace) -> Namespace:
    preset = get_preset(getattr(args, "preset", None))
    if not preset:
        return args
    data = vars(args).copy()
    # In v1.9 presets are intentionally opinionated. Command-line flags like
    # --no-zip, --legacy-1-20, --pack-format and explicit MIDI/show paths still
    # remain untouched; the style-related generation settings come from preset.
    for key, value in preset.values.items():
        data[key] = value
    data["preset"] = preset.name
    return Namespace(**data)
