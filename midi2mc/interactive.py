from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .export_datapack import DatapackOptions, export_datapack, sanitize_namespace
from .midi import MidiParseError, parse_midi
from .recommend import recommend_tick_rate


def _input(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def run_interactive_wizard(args: argparse.Namespace | None = None) -> int:
    print("=" * 60)
    print("midi2mc 交互式生成器 / Minecraft Java 1.21.11")
    print("=" * 60)
    print("把 MIDI 编译成数据包 zip，然后放进世界 datapacks 文件夹。\n")

    midi_path = _ask_midi_path(args.midi if args else None)
    if midi_path is None:
        print("[midi2mc] 已取消。")
        return 2

    print("\n[midi2mc] 开始解析 MIDI...")
    try:
        song = parse_midi(midi_path)
    except MidiParseError as exc:
        print(f"[midi2mc] MIDI 解析失败: {exc}", file=sys.stderr)
        return 1

    recommendation = recommend_tick_rate(song)
    print(f"[midi2mc] MIDI 解析完成：{song.note_count} 个音符，时长 {song.duration_sec:.2f}s")
    print(
        f"[midi2mc] BPM 建议：主 tempo 约 {recommendation.primary_bpm:.2f} BPM，"
        f"推荐 /tick rate {recommendation.tick_rate}"
    )
    print(
        f"          在 {recommendation.tick_rate} TPS 下："
        f"1拍≈{recommendation.beat_ticks:.2f}tick，"
        f"1/8≈{recommendation.eighth_ticks:.2f}tick，"
        f"1/16≈{recommendation.sixteenth_ticks:.2f}tick"
    )

    default_show_id = sanitize_namespace(midi_path.stem)
    show_id = _ask_text("Show ID / 数据包命名空间", default_show_id)
    show_id = sanitize_namespace(show_id)

    default_out = getattr(args, "out", "output") if args else "output"
    out_dir = Path(_ask_text("输出目录", str(default_out)))

    mode = _ask_choice(
        "输出模式",
        [
            ("command_stage", "伪红石舞台 + 播放声音（推荐）"),
            ("play", "只播放声音，不生成舞台"),
        ],
        default="command_stage",
    )

    arg_tick_rate = str(getattr(args, "tick_rate", "auto") if args else "auto").strip().lower()
    default_tick_rate = recommendation.tick_rate if arg_tick_rate in {"", "auto", "a"} else _safe_int(arg_tick_rate, recommendation.tick_rate)
    tick_rate = _ask_int(
        "编译 TPS / 游戏内建议 /tick rate",
        default_tick_rate,
        minimum=1,
        maximum=240,
    )
    if tick_rate != 20:
        print(f"[midi2mc] 生成后请在播放前执行：/tick rate {tick_rate}")
        print("          播放结束想恢复原版速度：/tick rate 20")
    else:
        print("[midi2mc] 选择 20 TPS：保持原版速度，不需要额外 /tick rate。")

    gain = _ask_float("音量倍率", getattr(args, "gain", 1.0) if args else 1.0, minimum=0.0)
    max_notes = _ask_int(
        "同一 tick 最大复音数（防止超密 MIDI 刷爆命令）",
        getattr(args, "max_notes_per_tick", 24) if args else 24,
        minimum=1,
        maximum=256,
    )
    zip_output = _ask_yes_no("是否同时生成 .zip 数据包？", default=True)

    options = DatapackOptions(
        show_id=show_id,
        out_dir=out_dir,
        pack_format=getattr(args, "pack_format", None) if args else None,
        tick_rate=tick_rate,
        mode=mode,
        gain=gain,
        max_notes_per_tick=max_notes,
        zip_output=zip_output,
        minecraft_1_21_layout=not getattr(args, "legacy_1_20", False) if args else True,
    )
    result = export_datapack(song, options)

    print("\n[midi2mc] 生成完成！")
    print(f"  目标版本: Minecraft Java 1.21.11")
    print(f"  Show ID: {result.namespace}")
    print(f"  音符: {song.note_count} parsed / {result.compiled_note_count} compiled")
    print(f"  时长: {song.duration_sec:.2f}s / {result.total_ticks} ticks @ {tick_rate} TPS")
    print(f"  数据包文件夹: {result.pack_dir}")
    if result.zip_path:
        print(f"  数据包 zip: {result.zip_path}")

    print("\n游戏内使用：")
    print("  /reload")
    print(f"  /function {result.namespace}:setup")
    if tick_rate != 20:
        print(f"  /tick rate {tick_rate}")
    print(f"  /function {result.namespace}:play")
    if tick_rate != 20:
        print("  # 播放结束恢复：/tick rate 20")
    print("\n控制：")
    print(f"  /function {result.namespace}:pause")
    print(f"  /function {result.namespace}:resume")
    print(f"  /function {result.namespace}:stop")
    print(f"  /function {result.namespace}:loop_on")
    print(f"  /function {result.namespace}:loop_off")
    return 0


def _ask_midi_path(default_path: str | None = None) -> Path | None:
    candidates = sorted(Path.cwd().glob("*.mid")) + sorted(Path.cwd().glob("*.midi"))
    if default_path:
        p = Path(default_path.strip().strip('"'))
        if p.exists():
            return p

    if candidates:
        print("当前目录检测到 MIDI：")
        for i, path in enumerate(candidates, 1):
            print(f"  {i}. {path.name}")
        print("  0. 手动输入路径")
        while True:
            raw = _input("选择 MIDI [1]: ").strip()
            if raw == "":
                raw = "1"
            if raw.isdigit():
                idx = int(raw)
                if idx == 0:
                    break
                if 1 <= idx <= len(candidates):
                    return candidates[idx - 1]
            print("请输入列表编号，或者选 0 手动输入。")

    while True:
        raw = _input("MIDI 文件路径（留空取消）: ").strip().strip('"')
        if not raw:
            return None
        path = Path(raw)
        if path.exists() and path.is_file():
            return path
        print(f"找不到文件：{path}")


def _ask_text(prompt: str, default: str) -> str:
    raw = _input(f"{prompt} [{default}]: ").strip()
    return raw or default


def _ask_choice(prompt: str, choices: list[tuple[str, str]], default: str) -> str:
    print(prompt + ":")
    default_index = 1
    for i, (value, label) in enumerate(choices, 1):
        if value == default:
            default_index = i
        print(f"  {i}. {label}")
    while True:
        raw = _input(f"选择 [{default_index}]: ").strip()
        if raw == "":
            return choices[default_index - 1][0]
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(choices):
                return choices[idx - 1][0]
        print("请输入有效编号。")


def _ask_yes_no(prompt: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = _input(f"{prompt} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes", "是", "好", "1", "true"}:
            return True
        if raw in {"n", "no", "否", "不", "0", "false"}:
            return False
        print("请输入 y 或 n。")


def _ask_int(prompt: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    while True:
        raw = _input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("请输入整数。")
            continue
        if minimum is not None and value < minimum:
            print(f"不能小于 {minimum}。")
            continue
        if maximum is not None and value > maximum:
            print(f"不能大于 {maximum}。")
            continue
        return value


def _ask_float(prompt: str, default: float, minimum: float | None = None) -> float:
    while True:
        raw = _input(f"{prompt} [{default:g}]: ").strip()
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            print("请输入数字。")
            continue
        if minimum is not None and value < minimum:
            print(f"不能小于 {minimum:g}。")
            continue
        return value


def _safe_int(raw: str, default: int) -> int:
    try:
        return int(raw)
    except ValueError:
        return default
