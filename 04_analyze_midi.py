#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
04_analyze_midi.py

辅助工具：查看 MIDI 文件的大致信息，不参与主生成流程。

依赖：
  pip install mido

常用：
  直接运行：
    python 04_analyze_midi.py

  命令行：
    python 04_analyze_midi.py --input in/example.mid --yes
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import mido
    from mido import MidiFile, tick2second, tempo2bpm
except ImportError as exc:
    raise SystemExit(
        "缺少依赖 mido。请先运行：python -m pip install -r requirements.txt"
    ) from exc


DEFAULT_IN_DIR = Path("in")


def ask_str(prompt: str, default: Optional[str] = None) -> str:
    if default is None:
        while True:
            raw = input(f"{prompt}: ").strip().strip('"')
            if raw:
                return raw
            print("不能为空。")
    raw = input(f"{prompt} [{default}]: ").strip().strip('"')
    return default if raw == "" else raw


def list_midi_files(input_dir: Path) -> List[Path]:
    files: List[Path] = []
    for pattern in ("*.mid", "*.midi", "*.MID", "*.MIDI"):
        files.extend(input_dir.glob(pattern))
    return sorted(set(files), key=lambda p: p.name.lower())


def choose_midi_file(input_dir: Path) -> Path:
    files = list_midi_files(input_dir)
    if files:
        print("在 in/ 中找到 MIDI 文件：")
        for i, path in enumerate(files, start=1):
            print(f"  {i}. {path}")
        print("  0. 手动输入其他路径")
        print()

        while True:
            raw = input("选择 MIDI 文件 [1]: ").strip()
            if raw == "":
                return files[0]
            try:
                index = int(raw)
            except ValueError:
                print("请输入编号，比如 1。")
                continue
            if index == 0:
                break
            if 1 <= index <= len(files):
                return files[index - 1]
            print("编号超出范围。")

    return Path(ask_str("请输入 MIDI 文件路径"))


def note_name(note: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    octave = note // 12 - 1
    return f"{names[note % 12]}{octave}"


def analyze_midi(input_path: Path) -> None:
    if not input_path.exists():
        raise FileNotFoundError(f"找不到 MIDI 文件：{input_path}")

    mid = MidiFile(input_path)
    ppq = mid.ticks_per_beat
    tempo = 500000
    abs_tick = 0
    abs_sec = 0.0

    programs: Dict[int, int] = {ch: 0 for ch in range(16)}
    note_counts_by_channel: Counter = Counter()
    note_ranges_by_channel: Dict[int, List[int]] = defaultdict(list)
    programs_by_channel: Dict[int, set] = defaultdict(set)
    velocity_counter: Counter = Counter()
    tempo_changes: List[Tuple[float, float]] = []

    merged = mido.merge_tracks(mid.tracks)

    for msg in merged:
        delta_ticks = int(msg.time)
        abs_tick += delta_ticks
        abs_sec += tick2second(delta_ticks, ppq, tempo)

        if msg.type == "set_tempo":
            tempo = int(msg.tempo)
            tempo_changes.append((abs_sec, float(tempo2bpm(tempo))))
            continue

        if msg.type == "program_change":
            programs[int(msg.channel)] = int(msg.program)
            programs_by_channel[int(msg.channel)].add(int(msg.program))
            continue

        if msg.type == "note_on" and int(msg.velocity) > 0:
            ch = int(msg.channel)
            n = int(msg.note)
            note_counts_by_channel[ch] += 1
            note_ranges_by_channel[ch].append(n)
            programs_by_channel[ch].add(programs.get(ch, 0))
            velocity_counter[int(msg.velocity)] += 1

    total_notes = sum(note_counts_by_channel.values())
    all_notes: List[int] = []
    for values in note_ranges_by_channel.values():
        all_notes.extend(values)

    print()
    print("=== MIDI 分析结果 ===")
    print(f"文件：{input_path}")
    print(f"MIDI type：{mid.type}")
    print(f"track 数量：{len(mid.tracks)}")
    print(f"ticks_per_beat：{ppq}")
    print(f"估算总时长：{abs_sec:.2f} 秒")
    print(f"note_on 数量：{total_notes}")

    if all_notes:
        print(f"整体音域：{min(all_notes)}({note_name(min(all_notes))}) ~ {max(all_notes)}({note_name(max(all_notes))})")

    print()
    print("Channel 概览：")
    if not note_counts_by_channel:
        print("  没有检测到 note_on 事件。")
    else:
        for ch in sorted(note_counts_by_channel.keys()):
            notes = note_ranges_by_channel[ch]
            programs = sorted(programs_by_channel.get(ch, set()))
            label = "percussion / drums" if ch == 9 else "melody/instrument"
            print(
                f"  channel {ch:2d}: notes={note_counts_by_channel[ch]:5d}, "
                f"range={min(notes)}({note_name(min(notes))})~{max(notes)}({note_name(max(notes))}), "
                f"programs={programs}, {label}"
            )

    print()
    print("Tempo 变化：")
    if tempo_changes:
        for i, (sec, bpm) in enumerate(tempo_changes[:20], start=1):
            print(f"  {i:2d}. {sec:8.3f}s -> {bpm:.3f} BPM")
        if len(tempo_changes) > 20:
            print(f"  ... 还有 {len(tempo_changes) - 20} 个 tempo 变化")
    else:
        print("  未检测到 set_tempo，按默认 120 BPM 理解。")

    print()
    print("建议：")
    if 9 in note_counts_by_channel:
        print("- 检测到 channel 9，02 脚本会按打击乐处理。")
    if all_notes and (min(all_notes) < 36 or max(all_notes) > 96):
        print("- 音域比较宽，原版 playsound pitch 会折叠八度，听感可能和原曲不同。")
    if total_notes > 10000:
        print("- 音符数量较大，生成的数据包会比较大，建议先用短 MIDI 测试。")
    if len(tempo_changes) > 10:
        print("- tempo 变化较多，01 会按 tempo 变化计算时间，但复杂 MIDI 仍建议进游戏听一下。")
    if total_notes == 0:
        print("- 这个 MIDI 可能不是标准 note_on/note_off 文件，或者内容为空。")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="分析 MIDI 文件")
    parser.add_argument("--input", "-i", default=None, help="输入 MIDI 文件，默认交互选择 in/ 里的 .mid/.midi")
    parser.add_argument("--yes", action="store_true", help="非交互模式，直接使用参数")
    args = parser.parse_args()

    DEFAULT_IN_DIR.mkdir(parents=True, exist_ok=True)

    if args.yes:
        if args.input:
            input_path = Path(args.input)
        else:
            files = list_midi_files(DEFAULT_IN_DIR)
            if not files:
                raise FileNotFoundError("没有指定 --input，并且 in/ 里没有 .mid/.midi 文件。")
            input_path = files[0]
    else:
        print("=== 04 MIDI 分析工具 ===")
        print()
        input_path = Path(args.input) if args.input else choose_midi_file(DEFAULT_IN_DIR)

    analyze_midi(input_path)


if __name__ == "__main__":
    main()
