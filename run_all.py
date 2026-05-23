#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_all.py

一键执行：
  01_parse_midi.py
  02_gen_sound_events.py
  03_gen_datapack.py

v0.6：
  - 默认生成事件 TPS 固定 20。
  - Soma 映射默认从 MIDI BPM 推导推荐 /tick rate。
  - 数据包默认在每个玩家当前位置播放声音。
  - Soma 默认按 duration 自动选择短采样 / c 长采样。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_mapping(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def run_step(args: List[str]) -> None:
    print()
    print(">>>", " ".join(args))
    subprocess.run(args, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="一键生成 MIDI playsound 数据包")
    parser.add_argument("input", nargs="?", default=None, help="输入 MIDI 文件。省略时自动选择 in/ 里的第一个 .mid/.midi")
    parser.add_argument("--mapping", default="mappings/vanilla.json", help="映射文件，默认 mappings/vanilla.json")
    parser.add_argument("--out", default="out/datapack", help="输出数据包目录，默认 out/datapack")
    parser.add_argument("--ticks-per-second", type=int, default=None, help="生成事件使用的 TPS，默认读取 mapping 的 generation_ticks_per_second，通常是 20")
    parser.add_argument("--tempo-mode", default=None, help="midi 或 fixed_base_bpm。Soma 默认 fixed_base_bpm，原版默认 midi。")
    parser.add_argument("--base-bpm", type=float, default=None, help="推荐 tick rate 的基准 BPM，默认 120")
    parser.add_argument("--base-tick-rate", type=int, default=None, help="基准 BPM 对应的 tick rate，默认 20")
    parser.add_argument("--tick-rate", type=int, default=None, help="旧参数，v0.4 不再用它拉伸生成 tick；保留只是为了提醒兼容。请改用 --ticks-per-second。")
    args = parser.parse_args()

    mapping_path = Path(args.mapping)
    mapping = load_mapping(mapping_path)

    if args.tick_rate is not None:
        print("提示：v0.4 起 --tick-rate 不再用于拉伸生成 tick。")
        print("      工具会从 MIDI BPM 自动计算推荐 /tick rate；生成事件 TPS 仍默认 20。")

    generation_tps = args.ticks_per_second
    if generation_tps is None:
        generation_tps = int(mapping.get("generation_ticks_per_second", mapping.get("ticks_per_second", 20)))

    tempo_mode = args.tempo_mode or str(mapping.get("tempo_mode", "midi"))
    base_bpm = args.base_bpm if args.base_bpm is not None else float(mapping.get("base_bpm_for_tick_rate", 120.0))
    base_tick_rate = args.base_tick_rate if args.base_tick_rate is not None else int(mapping.get("base_tick_rate", 20))

    input_args: List[str] = []
    if args.input:
        input_args = ["--input", str(Path(args.input))]

    run_step(
        [
            sys.executable,
            "01_parse_midi.py",
            *input_args,
            "--ticks-per-second",
            str(generation_tps),
            "--tempo-mode",
            tempo_mode,
            "--base-bpm",
            str(base_bpm),
            "--base-tick-rate",
            str(base_tick_rate),
            "--yes",
        ]
    )
    run_step([sys.executable, "02_gen_sound_events.py", "--mapping", args.mapping, "--yes"])
    run_step([sys.executable, "03_gen_datapack.py", "--mapping", args.mapping, "--out", args.out, "--yes"])

    midi_info_path = Path("temp/midi_info.json")
    recommended = None
    main_bpm = None
    if midi_info_path.exists():
        try:
            midi_info = json.loads(midi_info_path.read_text(encoding="utf-8"))
            recommended = midi_info.get("recommended_tick_rate")
            main_bpm = midi_info.get("midi_main_bpm")
        except Exception:
            pass

    print()
    print("全部完成。")
    print(f"数据包目录：{args.out}")
    print(f"生成事件 TPS：{generation_tps}")
    if main_bpm is not None:
        print(f"MIDI 主 BPM：{main_bpm}")
    if recommended is not None:
        print(f"推荐游戏 tick rate：{recommended}")
        print("复制到世界 datapacks 目录后，进游戏执行：")
        print("  /reload")
        print(f"  /tick rate {recommended}")
        print("  /function midi2mc:restart")
        print("播放结束后如需恢复原版速度：")
        print("  /tick rate 20")
    else:
        print("复制到世界 datapacks 目录后，进游戏执行：")
        print("  /reload")
        print("  /function midi2mc:restart")


if __name__ == "__main__":
    main()
