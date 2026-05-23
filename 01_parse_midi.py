#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
01_parse_midi.py

读取 MIDI 文件，解析成中间音符事件：

  temp/notes.json
  temp/midi_info.json

v0.4 重点：
  - 事件 tick 默认仍按 20 TPS 生成。
  - 可以从 MIDI tempo/BPM 里计算推荐 /tick rate。
  - Soma 模式推荐使用 fixed_base_bpm：按 120 BPM 的基准网格生成 tick，
    再根据 MIDI 主 BPM 提示玩家设置 /tick rate。

常用：
  python 01_parse_midi.py
  python 01_parse_midi.py --input in/example.mid --yes
  python 01_parse_midi.py --input in/example.mid --tempo-mode fixed_base_bpm --yes
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import mido
    from mido import MidiFile, tick2second, tempo2bpm
except ImportError as exc:
    raise SystemExit(
        "缺少依赖 mido。请先运行：python -m pip install -r requirements.txt"
    ) from exc


DEFAULT_IN_DIR = Path("in")
DEFAULT_TEMP_DIR = Path("temp")
DEFAULT_NOTES_OUT = DEFAULT_TEMP_DIR / "notes.json"
DEFAULT_INFO_OUT = DEFAULT_TEMP_DIR / "midi_info.json"


def ask_str(prompt: str, default: Optional[str] = None) -> str:
    if default is None:
        while True:
            raw = input(f"{prompt}: ").strip().strip('"')
            if raw:
                return raw
            print("不能为空。")
    raw = input(f"{prompt} [{default}]: ").strip().strip('"')
    return default if raw == "" else raw


def ask_int(prompt: str, default: int) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if raw == "":
            return default
        try:
            value = int(raw)
            if value <= 0:
                print("请输入大于 0 的整数。")
                continue
            return value
        except ValueError:
            print("请输入整数，比如 20。")


def ask_float(prompt: str, default: float) -> float:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if raw == "":
            return default
        try:
            value = float(raw)
            if value <= 0:
                print("请输入大于 0 的数字。")
                continue
            return value
        except ValueError:
            print("请输入数字，比如 120。")


def ensure_dirs() -> None:
    DEFAULT_IN_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_TEMP_DIR.mkdir(parents=True, exist_ok=True)


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

    raw_path = ask_str("请输入 MIDI 文件路径")
    return Path(raw_path)


def note_name(note: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    octave = note // 12 - 1
    return f"{names[note % 12]}{octave}"


def bpm_to_tempo(bpm: float) -> int:
    return int(round(60_000_000 / float(bpm)))


def normalize_tempo_mode(mode: str) -> str:
    mode = str(mode).strip().lower().replace("-", "_")
    if mode in {"fixed", "fixed_bpm", "fixed_base", "fixed_base_bpm", "bpm_hint"}:
        return "fixed_base_bpm"
    return "midi"


def tick_rate_from_bpm(bpm: float, base_bpm: float, base_tick_rate: int) -> int:
    if bpm <= 0 or base_bpm <= 0 or base_tick_rate <= 0:
        return 20
    value = round(float(bpm) / float(base_bpm) * int(base_tick_rate))
    return max(1, int(value))


def build_tempo_summary(
    tempo_changes: List[Dict[str, Any]],
    duration_sec: float,
    base_bpm: float,
    base_tick_rate: int,
) -> Dict[str, Any]:
    """
    从 MIDI tempo 事件推导主 BPM 和推荐 tick rate。

    约定：base_bpm -> base_tick_rate。
    默认就是 120 BPM -> /tick rate 20。
    所以 180 BPM -> 30，90 BPM -> 15。
    """

    points: List[Dict[str, float]] = [{"time_sec": 0.0, "bpm": 120.0}]

    for change in tempo_changes:
        t = float(change.get("time_sec", 0.0))
        bpm = float(change.get("bpm", 120.0))
        if points and abs(t - points[-1]["time_sec"]) < 1e-9:
            points[-1]["bpm"] = bpm
        else:
            points.append({"time_sec": t, "bpm": bpm})

    points.sort(key=lambda item: item["time_sec"])

    segments: List[Dict[str, float]] = []
    for i, point in enumerate(points):
        start = max(0.0, float(point["time_sec"]))
        end = duration_sec if i == len(points) - 1 else max(start, float(points[i + 1]["time_sec"]))
        dur = max(0.0, end - start)
        segments.append(
            {
                "start_sec": round(start, 6),
                "end_sec": round(end, 6),
                "duration_sec": round(dur, 6),
                "bpm": round(float(point["bpm"]), 3),
            }
        )

    if segments:
        dominant = max(segments, key=lambda item: item["duration_sec"])
        main_bpm = float(dominant["bpm"])
    else:
        main_bpm = 120.0

    total_weight = sum(float(s["duration_sec"]) for s in segments)
    if total_weight > 0:
        average_bpm = sum(float(s["bpm"]) * float(s["duration_sec"]) for s in segments) / total_weight
    else:
        average_bpm = main_bpm

    bpms = [float(s["bpm"]) for s in segments] or [main_bpm]
    recommended = tick_rate_from_bpm(main_bpm, base_bpm, base_tick_rate)

    return {
        "base_bpm": round(float(base_bpm), 3),
        "base_tick_rate": int(base_tick_rate),
        "main_bpm": round(main_bpm, 3),
        "average_bpm": round(average_bpm, 3),
        "min_bpm": round(min(bpms), 3),
        "max_bpm": round(max(bpms), 3),
        "recommended_tick_rate": recommended,
        "tick_rate_command": f"/tick rate {recommended}",
        "rule": f"{base_bpm:g} BPM -> /tick rate {base_tick_rate}",
        "segments": segments,
    }


def parse_midi(
    input_path: Path,
    ticks_per_second: int,
    tempo_mode: str = "midi",
    base_bpm: float = 120.0,
    base_tick_rate: int = 20,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not input_path.exists():
        raise FileNotFoundError(f"找不到 MIDI 文件：{input_path}")

    tempo_mode = normalize_tempo_mode(tempo_mode)

    mid = MidiFile(input_path)
    ppq = mid.ticks_per_beat

    actual_tempo = 500000  # MIDI 默认 120 BPM
    fixed_tempo = bpm_to_tempo(base_bpm)
    timing_tempo = fixed_tempo if tempo_mode == "fixed_base_bpm" else actual_tempo

    abs_midi_tick = 0
    abs_sec = 0.0

    programs: Dict[int, int] = {ch: 0 for ch in range(16)}
    active_notes: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    notes: List[Dict[str, Any]] = []

    tempo_changes: List[Dict[str, Any]] = []
    program_changes: List[Dict[str, Any]] = []

    merged = mido.merge_tracks(mid.tracks)

    for msg in merged:
        delta_ticks = int(msg.time)
        abs_midi_tick += delta_ticks
        abs_sec += tick2second(delta_ticks, ppq, timing_tempo)

        if msg.type == "set_tempo":
            actual_tempo = int(msg.tempo)
            bpm = float(tempo2bpm(actual_tempo))
            tempo_changes.append(
                {
                    "midi_tick": abs_midi_tick,
                    "time_sec": round(abs_sec, 6),
                    "tempo": actual_tempo,
                    "bpm": round(bpm, 3),
                }
            )

            # midi 模式：MIDI tempo 决定事件 tick。
            # fixed_base_bpm 模式：事件 tick 保持基准网格，MIDI tempo 只用于推荐 /tick rate。
            if tempo_mode == "midi":
                timing_tempo = actual_tempo
            continue

        if msg.type == "program_change":
            programs[int(msg.channel)] = int(msg.program)
            program_changes.append(
                {
                    "midi_tick": abs_midi_tick,
                    "time_sec": round(abs_sec, 6),
                    "channel": int(msg.channel),
                    "program": int(msg.program),
                }
            )
            continue

        if msg.type == "note_on" and int(msg.velocity) > 0:
            channel = int(msg.channel)
            midi_note = int(msg.note)
            key = (channel, midi_note)
            active_notes.setdefault(key, []).append(
                {
                    "start_midi_tick": abs_midi_tick,
                    "start_sec": abs_sec,
                    "start_game_tick": round(abs_sec * ticks_per_second),
                    "start_tick_20": round(abs_sec * 20),
                    "channel": channel,
                    "program": programs.get(channel, 0),
                    "note": midi_note,
                    "note_name": note_name(midi_note),
                    "velocity": int(msg.velocity),
                }
            )
            continue

        is_note_off = msg.type == "note_off" or (msg.type == "note_on" and int(getattr(msg, "velocity", 0)) == 0)
        if is_note_off:
            channel = int(msg.channel)
            midi_note = int(msg.note)
            key = (channel, midi_note)
            if key not in active_notes or not active_notes[key]:
                continue

            start = active_notes[key].pop(0)
            duration_sec = max(0.0, abs_sec - float(start["start_sec"]))
            duration_midi_tick = max(0, abs_midi_tick - int(start["start_midi_tick"]))
            duration_game_tick = max(1, round(duration_sec * ticks_per_second))

            notes.append(
                {
                    "start_sec": round(float(start["start_sec"]), 6),
                    "start_game_tick": int(start["start_game_tick"]),
                    "start_tick_20": int(start["start_tick_20"]),
                    "start_midi_tick": int(start["start_midi_tick"]),
                    "duration_sec": round(duration_sec, 6),
                    "duration_game_tick": duration_game_tick,
                    "duration_midi_tick": duration_midi_tick,
                    "channel": int(start["channel"]),
                    "program": int(start["program"]),
                    "note": int(start["note"]),
                    "note_name": str(start["note_name"]),
                    "velocity": int(start["velocity"]),
                    "ticks_per_second": ticks_per_second,
                    "tempo_mode": tempo_mode,
                    "ended_by": "note_off",
                }
            )

    # 有些 MIDI 会缺少 note_off。这里把残留音符在文件末尾收掉，避免直接丢失。
    dangling_count = 0
    for _key, queue in active_notes.items():
        for start in queue:
            dangling_count += 1
            duration_sec = max(0.0, abs_sec - float(start["start_sec"]))
            duration_midi_tick = max(0, abs_midi_tick - int(start["start_midi_tick"]))
            duration_game_tick = max(1, round(duration_sec * ticks_per_second))
            notes.append(
                {
                    "start_sec": round(float(start["start_sec"]), 6),
                    "start_game_tick": int(start["start_game_tick"]),
                    "start_tick_20": int(start["start_tick_20"]),
                    "start_midi_tick": int(start["start_midi_tick"]),
                    "duration_sec": round(duration_sec, 6),
                    "duration_game_tick": duration_game_tick,
                    "duration_midi_tick": duration_midi_tick,
                    "channel": int(start["channel"]),
                    "program": int(start["program"]),
                    "note": int(start["note"]),
                    "note_name": str(start["note_name"]),
                    "velocity": int(start["velocity"]),
                    "ticks_per_second": ticks_per_second,
                    "tempo_mode": tempo_mode,
                    "ended_by": "end_of_file",
                }
            )

    notes.sort(key=lambda item: (item["start_sec"], item["channel"], item["note"]))

    channels = sorted({int(n["channel"]) for n in notes})
    used_programs_by_channel: Dict[str, List[int]] = {}
    for n in notes:
        ch = str(int(n["channel"]))
        used_programs_by_channel.setdefault(ch, [])
        program = int(n["program"])
        if program not in used_programs_by_channel[ch]:
            used_programs_by_channel[ch].append(program)

    for ch in used_programs_by_channel:
        used_programs_by_channel[ch].sort()

    if notes:
        min_note = min(int(n["note"]) for n in notes)
        max_note = max(int(n["note"]) for n in notes)
        duration_sec = max(float(n["start_sec"]) + float(n["duration_sec"]) for n in notes)
        duration_game_tick = max(int(n.get("start_game_tick", 0)) + int(n.get("duration_game_tick", 0)) for n in notes)
    else:
        min_note = max_note = 0
        duration_sec = 0.0
        duration_game_tick = 0

    tempo_summary = build_tempo_summary(tempo_changes, duration_sec, base_bpm, base_tick_rate)

    info: Dict[str, Any] = {
        "input": str(input_path),
        "midi_type": mid.type,
        "track_count": len(mid.tracks),
        "ticks_per_beat": ppq,
        "generation_ticks_per_second": ticks_per_second,
        "ticks_per_second": ticks_per_second,
        "tempo_mode": tempo_mode,
        "base_bpm_for_tick_rate": round(float(base_bpm), 3),
        "base_tick_rate": int(base_tick_rate),
        "midi_main_bpm": tempo_summary["main_bpm"],
        "midi_average_bpm": tempo_summary["average_bpm"],
        "bpm_based_tick_rate": tempo_summary["recommended_tick_rate"],
        "recommended_tick_rate": tempo_summary["recommended_tick_rate"],
        "tick_rate_command": tempo_summary["tick_rate_command"],
        "note_count": len(notes),
        "duration_sec": round(duration_sec, 6),
        "duration_game_tick": duration_game_tick,
        "duration_tick_20": duration_game_tick,
        "channels": channels,
        "programs_by_channel": used_programs_by_channel,
        "note_range": {
            "min": min_note,
            "min_name": note_name(min_note),
            "max": max_note,
            "max_name": note_name(max_note),
        },
        "tempo_changes": tempo_changes,
        "tempo_summary": tempo_summary,
        "program_changes": program_changes,
        "dangling_notes_closed_at_eof": dangling_count,
    }

    return notes, info


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="MIDI -> temp/notes.json")
    parser.add_argument("--input", "-i", default=None, help="输入 MIDI 文件，默认交互选择 in/ 里的 .mid/.midi")
    parser.add_argument("--out", default=str(DEFAULT_NOTES_OUT), help="输出 notes.json，默认 temp/notes.json")
    parser.add_argument("--info", default=str(DEFAULT_INFO_OUT), help="输出 midi_info.json，默认 temp/midi_info.json")
    parser.add_argument("--ticks-per-second", type=int, default=20, help="生成事件使用的 TPS，默认 20。注意这不是推荐 /tick rate。")
    parser.add_argument("--tempo-mode", default="midi", choices=["midi", "fixed_base_bpm", "fixed", "bpm_hint"], help="midi=按 MIDI 原始 tempo 生成 tick；fixed_base_bpm=按基准 BPM 生成 tick，再从 MIDI BPM 推荐 /tick rate")
    parser.add_argument("--base-bpm", type=float, default=120.0, help="fixed_base_bpm 模式的基准 BPM，默认 120")
    parser.add_argument("--base-tick-rate", type=int, default=20, help="基准 BPM 对应的 tick rate，默认 20")
    parser.add_argument("--yes", action="store_true", help="非交互模式，直接使用参数")
    args = parser.parse_args()

    ensure_dirs()

    if not args.yes:
        print("=== 01 MIDI 解析：MIDI -> notes.json ===")
        print("直接回车使用方括号里的默认值。")
        print()
        input_path = Path(args.input) if args.input else choose_midi_file(DEFAULT_IN_DIR)
        ticks_per_second = ask_int("生成事件使用的 TPS", args.ticks_per_second)
        tempo_mode = ask_str("tempo 模式：midi 或 fixed_base_bpm", args.tempo_mode)
        base_bpm = ask_float("基准 BPM（用于推荐 tick rate）", args.base_bpm)
        base_tick_rate = ask_int("基准 BPM 对应的 tick rate", args.base_tick_rate)
        out_path = Path(ask_str("notes.json 输出路径", args.out))
        info_path = Path(ask_str("midi_info.json 输出路径", args.info))
        print()
    else:
        if not args.input:
            files = list_midi_files(DEFAULT_IN_DIR)
            if not files:
                raise FileNotFoundError("没有指定 --input，并且 in/ 里没有 .mid/.midi 文件。")
            input_path = files[0]
        else:
            input_path = Path(args.input)
        ticks_per_second = args.ticks_per_second
        tempo_mode = args.tempo_mode
        base_bpm = args.base_bpm
        base_tick_rate = args.base_tick_rate
        out_path = Path(args.out)
        info_path = Path(args.info)

    notes, info = parse_midi(input_path, ticks_per_second, tempo_mode, base_bpm, base_tick_rate)
    write_json(out_path, notes)
    write_json(info_path, info)

    print("完成。")
    print(f"MIDI 文件：{input_path}")
    print(f"音符数量：{len(notes)}")
    print(f"生成事件 TPS：{info['generation_ticks_per_second']}")
    print(f"tempo 模式：{info['tempo_mode']}")
    print(f"MIDI 主 BPM：{info['midi_main_bpm']}")
    print(f"总时长：{info['duration_sec']:.2f} 秒")
    print(f"音域：{info['note_range']['min_name']} ~ {info['note_range']['max_name']}")
    print(f"推荐游戏 tick rate：{info['recommended_tick_rate']}")
    print(f"游戏内可执行：{info['tick_rate_command']}")
    print(f"输出：{out_path}")
    print(f"信息：{info_path}")
    print()
    print("下一步：python 02_gen_sound_events.py")


if __name__ == "__main__":
    main()
