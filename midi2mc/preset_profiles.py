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
            "stage_template": "minimal",
            "quality": "medium",
            "show_fx": "none",
            "fx_profile": "clean",
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
            "stage_template": "pulse",
            "quality": "medium",
            "show_fx": "auto",
            "fx_profile": "concert",
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
            "stage_template": "pulse",
            "quality": "medium",
            "show_fx": "lightshow",
            "fx_profile": "concert",
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
            "stage_template": "pulse",
            "quality": "high",
            "show_fx": "both",
            "fx_profile": "concert",
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
            "stage_template": "minimal",
            "quality": "low",
            "safe_mode": True,
            "show_fx": "none",
            "fx_profile": "clean",
            "piano_roll": False,
            "no_stage_particles": True,
            "max_notes_per_tick": 8,
        },
    ),
    "vanilla_classic_line": PresetProfile(
        "vanilla_classic_line",
        "Vanilla Classic Line / 原版经典一排",
        "复古一排音符盒机器，适合简单 MIDI 和红石音乐展示。",
        {
            "sound_engine": "vanilla",
            "mode": "command_stage",
            "stage_profile": "noteblock_machine",
            "stage_layout": "wide",
            "stage_template": "classic_line",
            "quality": "medium",
            "show_fx": "lightshow",
            "fx_profile": "redstone",
            "piano_roll": False,
        },
    ),
    "vanilla_minimal": PresetProfile(
        "vanilla_minimal",
        "Vanilla Minimal / 原版极简舞台",
        "几乎不生成方块，只保留 marker、节拍器和粒子，适合建筑党自己装修。",
        {
            "sound_engine": "vanilla",
            "mode": "command_stage",
            "stage_profile": "noteblock_machine",
            "stage_layout": "auto",
            "stage_template": "minimal",
            "quality": "medium",
            "show_fx": "lightshow",
            "fx_profile": "clean",
            "piano_roll": False,
        },
    ),

    "vanilla_redstone": PresetProfile(
        "vanilla_redstone",
        "Vanilla Redstone FX / 原版红石电火花",
        "原版 Pulse Stage + redstone FX profile：暖色 dust + electric_spark，偏机械感。",
        {
            "sound_engine": "vanilla",
            "mode": "command_stage",
            "stage_profile": "noteblock_machine",
            "stage_layout": "wide",
            "stage_template": "pulse",
            "quality": "medium",
            "show_fx": "lightshow",
            "fx_profile": "redstone",
            "piano_roll": False,
        },
    ),
    "vanilla_magic": PresetProfile(
        "vanilla_magic",
        "Vanilla Magic FX / 原版魔法粒子",
        "原版 Pulse Stage + magic FX profile：紫蓝 dust + enchant/portal 点缀。",
        {
            "sound_engine": "vanilla",
            "mode": "command_stage",
            "stage_profile": "noteblock_machine",
            "stage_layout": "wide",
            "stage_template": "pulse",
            "quality": "medium",
            "show_fx": "both",
            "fx_profile": "magic",
            "piano_roll": False,
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
            "stage_template": "pulse",
            "quality": "medium",
            "show_fx": "lightshow",
            "fx_profile": "concert",
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
            "stage_template": "pulse",
            "quality": "high",
            "show_fx": "both",
            "fx_profile": "concert",
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
            "stage_template": "pulse",
            "quality": "low",
            "safe_mode": True,
            "show_fx": "none",
            "fx_profile": "clean",
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
