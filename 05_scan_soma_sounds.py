#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
05_scan_soma_sounds.py

辅助工具：扫描 Soma 资源包的 sounds.json，确认 sound id 命名规律。

它不参与主生成流程，只负责输出：

  temp/soma_sounds_index.json
  out/soma_sound_report.txt

常用：
  直接运行：
    python 05_scan_soma_sounds.py

  命令行：
    python 05_scan_soma_sounds.py --sounds-json sounds.json --yes
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_SOUNDS_JSON = Path("sounds.json")
DEFAULT_INDEX_OUT = Path("temp/soma_sounds_index.json")
DEFAULT_REPORT_OUT = Path("out/soma_sound_report.txt")


def ask_str(prompt: str, default: Optional[str] = None) -> str:
    if default is None:
        while True:
            raw = input(f"{prompt}: ").strip().strip('"')
            if raw:
                return raw
            print("不能为空。")
    raw = input(f"{prompt} [{default}]: ").strip().strip('"')
    return default if raw == "" else raw


def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"找不到文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_soma_sounds(sounds: Dict[str, Any]) -> Dict[str, Any]:
    normal_instruments: Dict[str, List[int]] = defaultdict(list)
    continuous_instruments: Dict[str, List[int]] = defaultdict(list)
    percussion_standard: List[int] = []
    percussion_electronic: List[int] = []
    special_effects: Dict[str, List[int]] = defaultdict(list)
    unmatched: List[str] = []

    re_normal = re.compile(r"^(\d+)\.(\d+)$")
    re_continuous = re.compile(r"^(\d+)c\.(\d+)$")
    re_effect = re.compile(r"^(se|sec)\.(\d+)$")

    for key in sounds.keys():
        if key.startswith("0e."):
            try:
                percussion_electronic.append(int(key.split(".", 1)[1]))
            except ValueError:
                unmatched.append(key)
            continue

        if key.startswith("0."):
            try:
                percussion_standard.append(int(key.split(".", 1)[1]))
            except ValueError:
                unmatched.append(key)
            continue

        m = re_continuous.match(key)
        if m:
            continuous_instruments[m.group(1)].append(int(m.group(2)))
            continue

        m = re_normal.match(key)
        if m:
            normal_instruments[m.group(1)].append(int(m.group(2)))
            continue

        m = re_effect.match(key)
        if m:
            special_effects[m.group(1)].append(int(m.group(2)))
            continue

        unmatched.append(key)

    def summarize_note_list(values: List[int]) -> Dict[str, Any]:
        values = sorted(set(values))
        return {
            "count": len(values),
            "min": values[0] if values else None,
            "max": values[-1] if values else None,
            "complete_0_127": values == list(range(128)),
        }

    index = {
        "total_sound_ids": len(sounds),
        "percussion_standard": summarize_note_list(percussion_standard),
        "percussion_electronic": summarize_note_list(percussion_electronic),
        "normal_instruments": {
            k: summarize_note_list(v) for k, v in sorted(normal_instruments.items(), key=lambda kv: int(kv[0]))
        },
        "continuous_instruments": {
            k: summarize_note_list(v) for k, v in sorted(continuous_instruments.items(), key=lambda kv: int(kv[0]))
        },
        "special_effects": {
            k: summarize_note_list(v) for k, v in sorted(special_effects.items())
        },
        "unmatched": sorted(unmatched),
    }

    return index


def build_report(index: Dict[str, Any], source_path: Path) -> str:
    normal = index["normal_instruments"]
    continuous = index["continuous_instruments"]
    normal_ids = sorted([int(k) for k in normal.keys()])
    continuous_ids = sorted([int(k) for k in continuous.keys()])

    missing_continuous = [i for i in normal_ids if str(i) not in continuous]

    lines: List[str] = []
    lines.append("Soma sounds.json 扫描报告")
    lines.append("=" * 40)
    lines.append("")
    lines.append(f"来源：{source_path}")
    lines.append(f"总 sound id 数：{index['total_sound_ids']}")
    lines.append("")
    lines.append("识别结果")
    lines.append("-" * 40)
    lines.append(f"标准鼓组 0.<note>：{index['percussion_standard']['count']} 个，范围 {index['percussion_standard']['min']}~{index['percussion_standard']['max']}")
    lines.append(f"电子鼓组 0e.<note>：{index['percussion_electronic']['count']} 个，范围 {index['percussion_electronic']['min']}~{index['percussion_electronic']['max']}")
    lines.append(f"普通短音 <instrument>.<note>：{len(normal_ids)} 组，编号 {normal_ids[0] if normal_ids else None}~{normal_ids[-1] if normal_ids else None}")
    lines.append(f"普通长音 <instrument>c.<note>：{len(continuous_ids)} 组，编号 {continuous_ids[0] if continuous_ids else None}~{continuous_ids[-1] if continuous_ids else None}")
    lines.append(f"特殊音效 se/sec：{', '.join(index['special_effects'].keys()) or '无'}")
    lines.append(f"未识别 key 数：{len(index['unmatched'])}")
    lines.append("")
    lines.append("关键结论")
    lines.append("-" * 40)
    lines.append("1. Soma 适合直接用 sound id 播放具体音高，不需要 playsound pitch 变调。")
    lines.append("2. MIDI program 是 0-based；Soma 乐器编号看起来是 1-based，所以默认使用 program + 1。")
    lines.append("3. 当前工具推荐先用短音版本：1.60、41.60 这种。")
    lines.append("4. 1c.60、41c.60 这种长音版本后续可以做，但最好配合 note_off 生成 stopsound。")
    lines.append("")
    lines.append("示例命令")
    lines.append("-" * 40)
    lines.append("/playsound 1.60 voice @a ~ ~ ~ 1 1")
    lines.append("/playsound 41.60 voice @a ~ ~ ~ 1 1")
    lines.append("/playsound 0.35 voice @a ~ ~ ~ 1 1")
    lines.append("")
    lines.append("缺少长音版本的普通乐器编号")
    lines.append("-" * 40)
    if missing_continuous:
        lines.append(", ".join(str(i) for i in missing_continuous))
    else:
        lines.append("无")
    lines.append("")
    lines.append("下一步")
    lines.append("-" * 40)
    lines.append("使用 mappings/soma_gm.json 生成 Soma 版数据包：")
    lines.append("  python run_all.py --mapping mappings/soma_gm.json")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="扫描 Soma sounds.json")
    parser.add_argument("--sounds-json", default=str(DEFAULT_SOUNDS_JSON), help="Soma sounds.json 路径")
    parser.add_argument("--index-out", default=str(DEFAULT_INDEX_OUT), help="输出索引 JSON")
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT), help="输出报告 txt")
    parser.add_argument("--yes", action="store_true", help="非交互模式，直接使用参数")
    args = parser.parse_args()

    if not args.yes:
        print("=== 05 Soma 资源包 sounds.json 扫描 ===")
        print("直接回车使用方括号里的默认值。")
        print()
        sounds_path = Path(ask_str("sounds.json 路径", args.sounds_json))
        index_out = Path(ask_str("索引 JSON 输出路径", args.index_out))
        report_out = Path(ask_str("报告 TXT 输出路径", args.report_out))
        print()
    else:
        sounds_path = Path(args.sounds_json)
        index_out = Path(args.index_out)
        report_out = Path(args.report_out)

    sounds = load_json(sounds_path)
    index = parse_soma_sounds(sounds)
    report = build_report(index, sounds_path)

    write_json(index_out, index)
    write_text(report_out, report)

    print("完成。")
    print(f"总 sound id：{index['total_sound_ids']}")
    print(f"普通短音乐器组：{len(index['normal_instruments'])}")
    print(f"普通长音乐器组：{len(index['continuous_instruments'])}")
    print(f"索引：{index_out}")
    print(f"报告：{report_out}")


if __name__ == "__main__":
    main()
