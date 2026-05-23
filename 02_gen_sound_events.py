#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
02_gen_sound_events.py

读取 temp/notes.json，把 MIDI 音符事件转换成 Minecraft playsound 事件：

  temp/sound_events.json
  temp/sound_info.json

依赖：
  只需要 Python 标准库。本脚本不直接读取 MIDI。

常用：
  直接运行：
    python 02_gen_sound_events.py

  命令行：
    python 02_gen_sound_events.py --notes temp/notes.json --mapping mappings/vanilla.json --yes
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_NOTES = Path("temp/notes.json")
DEFAULT_EVENTS = Path("temp/sound_events.json")
DEFAULT_INFO = Path("temp/sound_info.json")
DEFAULT_MAPPING = Path("mappings/vanilla.json")


def ask_str(prompt: str, default: Optional[str] = None) -> str:
    if default is None:
        while True:
            raw = input(f"{prompt}: ").strip().strip('"')
            if raw:
                return raw
            print("不能为空。")
    raw = input(f"{prompt} [{default}]: ").strip().strip('"')
    return default if raw == "" else raw


def ask_bool(prompt: str, default: bool) -> bool:
    default_text = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{default_text}]: ").strip().lower()
        if raw == "":
            return default
        if raw in {"y", "yes", "是", "对", "1", "true"}:
            return True
        if raw in {"n", "no", "否", "不", "0", "false"}:
            return False
        print("请输入 y 或 n，或者直接回车使用默认值。")


def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"找不到文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def midi_note_to_pitch(note: int, mapping: Dict[str, Any]) -> float:
    base_midi_note = int(mapping.get("base_midi_note", 66))
    min_pitch = float(mapping.get("min_pitch", 0.5))
    max_pitch = float(mapping.get("max_pitch", 2.0))
    fold_pitch = bool(mapping.get("fold_pitch_to_range", True))

    pitch = 2 ** ((int(note) - base_midi_note) / 12.0)

    if fold_pitch:
        while pitch < min_pitch:
            pitch *= 2
        while pitch > max_pitch:
            pitch /= 2
    else:
        pitch = clamp(pitch, min_pitch, max_pitch)

    return round(pitch, 6)


def velocity_to_volume(velocity: int, mapping: Dict[str, Any]) -> float:
    volume_scale = float(mapping.get("volume_scale", 1.0))
    min_volume = float(mapping.get("min_volume", 0.05))
    max_volume = float(mapping.get("max_volume", 1.0))

    volume = (int(velocity) / 127.0) * volume_scale
    volume = clamp(volume, min_volume, max_volume)
    return round(volume, 4)


def is_soma_numbered_mode(mapping: Dict[str, Any]) -> bool:
    """
    Soma 资源包的主规律：

      - 普通乐器短音：  1.60  -> soma/1/d/60
      - 普通乐器长音：  1c.60 -> soma/1/c/60
      - 标准鼓组：      0.35  -> soma/0standard/1/35
      - 电子鼓组：      0e.35 -> soma/0electronic/1/35

    所以它不需要 playsound pitch 变调，而是直接用 MIDI note 编号拼 sound id。
    """

    mode = str(mapping.get("mode", "")).lower()
    sound_id_mode = str(mapping.get("sound_id_mode", "")).lower()
    return mode in {"soma", "soma_gm", "soma_numbered"} or sound_id_mode == "soma_numbered"


def get_soma_options(mapping: Dict[str, Any]) -> Dict[str, Any]:
    options = mapping.get("soma", {})
    if not isinstance(options, dict):
        options = {}
    return options


def get_soma_instrument_number(program: int, mapping: Dict[str, Any]) -> int:
    """
    MIDI program 是 0-based；Soma 说明表和 sound id 是 1-based。

    例：
      MIDI program 0  Acoustic Grand Piano -> Soma 1 -> 1.60
      MIDI program 40 Violin               -> Soma 41 -> 41.60
    """

    options = get_soma_options(mapping)
    overrides = mapping.get("program_instruments", {}) or {}

    if str(program) in overrides:
        return int(overrides[str(program)])

    offset = int(options.get("program_to_soma_offset", 1))
    instrument = int(program) + offset

    min_instrument = int(options.get("min_instrument", 1))
    max_instrument = int(options.get("max_instrument", 120))
    fallback = int(options.get("fallback_instrument", 1))

    if instrument < min_instrument or instrument > max_instrument:
        return fallback

    return instrument


def get_note_duration_game_tick(note: Dict[str, Any], mapping: Dict[str, Any]) -> int:
    """
    读取 / 估算该音符在“生成事件时间轴”里的持续 tick。

    01_parse_midi.py 会优先写 duration_game_tick；如果没有，就用 duration_sec * TPS 兜底。
    """

    if "duration_game_tick" in note:
        try:
            return max(1, int(note["duration_game_tick"]))
        except (TypeError, ValueError):
            pass

    generated_tps = int(
        note.get(
            "ticks_per_second",
            mapping.get("generation_ticks_per_second", mapping.get("ticks_per_second", 20)),
        )
    )

    try:
        duration_sec = float(note.get("duration_sec", 0.0))
    except (TypeError, ValueError):
        duration_sec = 0.0

    return max(1, round(duration_sec * generated_tps))


def soma_long_variant_available(instrument: int, mapping: Dict[str, Any]) -> bool:
    options = get_soma_options(mapping)
    long_variant_max = int(options.get("long_variant_max_instrument", 100))
    return int(instrument) <= long_variant_max


def choose_soma_variant_for_note(note: Dict[str, Any], mapping: Dict[str, Any], instrument: int) -> str:
    """
    v0.6：Soma 普通乐器不再统一使用 c 长音。

    默认策略：
      - 短音：使用不带 c 的短采样，例如 1.60。
      - 长音：如果该乐器有 c 采样，使用 1c.60，并配合 stopsound。
      - 如果该乐器没有 c 采样，自动回退短采样，避免生成不存在的 sound id。

    可在 mappings/soma_gm.json 中调整：
      soma.variant = "auto"
      soma.long_note_min_ticks = 8
      soma.force_long_programs = []
      soma.force_short_programs = []
    """

    options = get_soma_options(mapping)
    variant = str(options.get("variant", "auto")).strip().lower()

    long_names = {"c", "continuous", "long", "sustain"}
    short_names = {"d", "default", "short", "normal"}

    if variant in short_names:
        return "d"

    if variant in long_names:
        return "c" if soma_long_variant_available(instrument, mapping) else "d"

    # auto / duration / smart：按每个 MIDI 音符的长度决定。
    program = int(note.get("program", 0))

    force_long = {int(x) for x in options.get("force_long_programs", []) or []}
    force_short = {int(x) for x in options.get("force_short_programs", []) or []}

    # 这里用 MIDI program 编号，0-based；例如钢琴是 0，小提琴是 40。
    if program in force_short:
        return "d"
    if program in force_long:
        return "c" if soma_long_variant_available(instrument, mapping) else "d"

    duration_ticks = get_note_duration_game_tick(note, mapping)

    # 默认 8 tick：120 BPM 下略短于一个四分音符，八分/十六分多半走短音，拖长音走 c。
    long_min_ticks = int(options.get("long_note_min_ticks", mapping.get("long_note_min_ticks", 8)))
    long_min_ticks = max(1, long_min_ticks)

    use_long = duration_ticks >= long_min_ticks

    # 也允许用秒做兜底阈值；默认 0 表示关闭。
    long_min_seconds = float(options.get("long_note_min_seconds", mapping.get("long_note_min_seconds", 0.0)))
    if long_min_seconds > 0:
        try:
            duration_sec = float(note.get("duration_sec", 0.0))
            use_long = use_long or duration_sec >= long_min_seconds
        except (TypeError, ValueError):
            pass

    if use_long and soma_long_variant_available(instrument, mapping):
        return "c"

    return "d"


def build_soma_sound_id(note: Dict[str, Any], mapping: Dict[str, Any]) -> str:
    channel = int(note.get("channel", 0))
    program = int(note.get("program", 0))
    midi_note = int(note.get("note", 60))

    options = get_soma_options(mapping)

    # MIDI channel 9，也就是第 10 通道，通常是打击乐。
    if channel == 9:
        percussion_notes: Dict[str, str] = mapping.get("percussion_notes", {}) or {}
        if str(midi_note) in percussion_notes:
            return str(percussion_notes[str(midi_note)])

        kit = str(options.get("percussion_kit", "standard")).lower()
        if kit in {"electronic", "e", "0e"}:
            return f"0e.{midi_note}"
        return f"0.{midi_note}"

    instrument = get_soma_instrument_number(program, mapping)
    chosen_variant = choose_soma_variant_for_note(note, mapping, instrument)

    if chosen_variant == "c":
        return f"{instrument}c.{midi_note}"

    return f"{instrument}.{midi_note}"


def get_sound_for_note(note: Dict[str, Any], mapping: Dict[str, Any]) -> str:
    if is_soma_numbered_mode(mapping):
        return build_soma_sound_id(note, mapping)

    channel = int(note.get("channel", 0))
    program = int(note.get("program", 0))
    midi_note = int(note.get("note", 60))

    default_sound = str(mapping.get("default_sound", "minecraft:block.note_block.harp"))
    percussion_sound = str(mapping.get("percussion_sound", "minecraft:block.note_block.basedrum"))
    program_sounds: Dict[str, str] = mapping.get("program_sounds", {}) or {}
    percussion_notes: Dict[str, str] = mapping.get("percussion_notes", {}) or {}

    # MIDI channel 9，也就是第 10 通道，通常是打击乐。
    if channel == 9:
        return str(percussion_notes.get(str(midi_note), percussion_sound))

    return str(program_sounds.get(str(program), default_sound))



SOMA_LONG_SOUND_RE = re.compile(r"^\d+c\.\d+$")


def is_long_soma_sound_id(sound_id: str) -> bool:
    return bool(SOMA_LONG_SOUND_RE.match(str(sound_id)))


def should_generate_note_stop(sound_id: str, channel: int, mapping: Dict[str, Any]) -> bool:
    """
    对 Soma 的 c 长音生成 note-off stopsound。

    原因：
      playsound 只负责播放，不会自动按照 MIDI note_off 停止。
      c 长音如果不 stopsound，会在长音多的曲子里互相糊成一团。
    """

    policy = str(mapping.get("generate_note_stops", "soma_long_only")).strip().lower()

    if policy in {"0", "false", "no", "off", "none", "never"}:
        return False
    if policy in {"1", "true", "yes", "on", "all", "always"}:
        return True

    # 默认：只给 Soma 普通乐器的 c 长音加 stopsound；鼓组和短音不加。
    if channel == 9:
        return False
    return is_soma_numbered_mode(mapping) and is_long_soma_sound_id(sound_id)


def map_notes_to_sound_events(notes: List[Dict[str, Any]], mapping: Dict[str, Any]) -> List[Dict[str, Any]]:
    sound_source = str(mapping.get("sound_source", "master"))
    target_selector = str(mapping.get("target_selector", "@a"))
    ticks_per_second = int(mapping.get("ticks_per_second", 20))

    events: List[Dict[str, Any]] = []

    for note in notes:
        channel = int(note.get("channel", 0))
        midi_note = int(note.get("note", 60))
        velocity = int(note.get("velocity", 80))

        # 01 会写 start_game_tick；老版本字段叫 start_tick_20。
        # 这里的 tick 实际上是“按推荐游戏 tick rate 量化后的播放 tick”。
        if "start_game_tick" in note:
            tick = int(note["start_game_tick"])
        elif "start_tick_20" in note:
            tick = int(note["start_tick_20"])
        else:
            tick = round(float(note.get("start_sec", 0.0)) * ticks_per_second)

        generated_tps = int(note.get("ticks_per_second", mapping.get("generation_ticks_per_second", mapping.get("ticks_per_second", ticks_per_second))))

        duration_game_tick = get_note_duration_game_tick(note, mapping)
        duration_game_tick = max(1, duration_game_tick)

        # 给 build_soma_sound_id 一个带 duration_game_tick 的副本，用于 v0.6 的“短音/长音自动判断”。
        note_for_sound = dict(note)
        note_for_sound["duration_game_tick"] = duration_game_tick

        sound = get_sound_for_note(note_for_sound, mapping)

        if is_soma_numbered_mode(mapping):
            # Soma 已经为每个 MIDI note 准备了独立采样，pitch 固定 1.0。
            pitch = float(mapping.get("soma_pitch", 1.0))
        elif channel == 9:
            pitch = float(mapping.get("percussion_pitch", 1.0))
        else:
            pitch = midi_note_to_pitch(midi_note, mapping)

        volume = velocity_to_volume(velocity, mapping)

        stop_delay_ticks = int(mapping.get("note_stop_delay_ticks", 0))
        stop_tick = max(tick + 1, tick + duration_game_tick + stop_delay_ticks)
        needs_stop = should_generate_note_stop(sound, channel, mapping)

        events.append(
            {
                "tick": tick,
                "sound": sound,
                "source": sound_source,
                "target": target_selector,
                "volume": volume,
                "pitch": pitch,
                "channel": channel,
                "program": int(note.get("program", 0)),
                "midi_note": midi_note,
                "note_name": str(note.get("note_name", midi_note)),
                "velocity": velocity,
                "duration_sec": float(note.get("duration_sec", 0.0)),
                "duration_game_tick": duration_game_tick,
                "sound_variant": "long_c" if is_long_soma_sound_id(sound) else "short",
                "stop_tick": stop_tick if needs_stop else None,
                "needs_stop": bool(needs_stop),
                "ticks_per_second": generated_tps,
            }
        )

    events.sort(key=lambda item: (int(item["tick"]), int(item["channel"]), int(item["midi_note"])))
    return events


def build_info(events: List[Dict[str, Any]], mapping: Dict[str, Any]) -> Dict[str, Any]:
    sound_counts = Counter(str(event["sound"]) for event in events)
    channel_counts = Counter(str(event["channel"]) for event in events)
    ticks = [int(event["tick"]) for event in events]
    generated_tick_rates = sorted({int(event.get("ticks_per_second", mapping.get("recommended_tick_rate", mapping.get("ticks_per_second", 20)))) for event in events})
    grouped = defaultdict(int)
    for event in events:
        grouped[int(event["tick"])] += 1

    max_events_in_one_tick = max(grouped.values(), default=0)
    note_stop_count = sum(1 for event in events if bool(event.get("needs_stop", False)))
    long_sound_count = sum(1 for event in events if is_long_soma_sound_id(str(event.get("sound", ""))))
    short_sound_count = len(events) - long_sound_count

    return {
        "mode": mapping.get("mode", "unknown"),
        "namespace": mapping.get("namespace", "midi2mc"),
        "pack_format": mapping.get("pack_format", 48),
        "event_count": len(events),
        "active_tick_count": len(grouped),
        "last_tick": max(ticks) if ticks else 0,
        "generation_ticks_per_second": generated_tick_rates[0] if generated_tick_rates else int(mapping.get("generation_ticks_per_second", mapping.get("ticks_per_second", 20))),
        "generated_tick_rates": generated_tick_rates,
        "recommended_tick_rate": None,
        "tick_rate_command": None,
        "max_events_in_one_tick": max_events_in_one_tick,
        "note_stop_count": note_stop_count,
        "long_sound_count": long_sound_count,
        "short_sound_count": short_sound_count,
        "soma_long_note_min_ticks": get_soma_options(mapping).get("long_note_min_ticks", mapping.get("long_note_min_ticks", None)),
        "sounds": dict(sound_counts.most_common()),
        "channels": dict(channel_counts.most_common()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="temp/notes.json -> temp/sound_events.json")
    parser.add_argument("--notes", default=str(DEFAULT_NOTES), help="输入 notes.json，默认 temp/notes.json")
    parser.add_argument("--mapping", default=str(DEFAULT_MAPPING), help="映射配置 JSON，默认 mappings/vanilla.json")
    parser.add_argument("--out", default=str(DEFAULT_EVENTS), help="输出 sound_events.json，默认 temp/sound_events.json")
    parser.add_argument("--info", default=str(DEFAULT_INFO), help="输出 sound_info.json，默认 temp/sound_info.json")
    parser.add_argument("--yes", action="store_true", help="非交互模式，直接使用参数")
    args = parser.parse_args()

    if not args.yes:
        print("=== 02 音效映射：notes.json -> sound_events.json ===")
        print("直接回车使用方括号里的默认值。")
        print()
        notes_path = Path(ask_str("notes.json 输入路径", args.notes))
        mapping_path = Path(ask_str("映射文件路径", args.mapping))
        out_path = Path(ask_str("sound_events.json 输出路径", args.out))
        info_path = Path(ask_str("sound_info.json 输出路径", args.info))
        print()
    else:
        notes_path = Path(args.notes)
        mapping_path = Path(args.mapping)
        out_path = Path(args.out)
        info_path = Path(args.info)

    notes = load_json(notes_path)
    mapping = load_json(mapping_path)

    events = map_notes_to_sound_events(notes, mapping)
    info = build_info(events, mapping)

    write_json(out_path, events)
    write_json(info_path, info)

    print("完成。")
    print(f"输入音符数量：{len(notes)}")
    print(f"输出音效事件：{len(events)}")
    print(f"活跃 tick 数：{info['active_tick_count']}")
    print(f"生成事件 TPS：{info['generation_ticks_per_second']}")
    print("推荐游戏 tick rate 会在 03 阶段根据 MIDI BPM 输出。")
    print(f"最大同 tick 事件数：{info['max_events_in_one_tick']}")
    print(f"短音事件数：{info.get('short_sound_count', 0)}")
    print(f"长音 c 事件数：{info.get('long_sound_count', 0)}")
    print(f"长音 stopsound 数：{info['note_stop_count']}")
    print(f"输出：{out_path}")
    print(f"信息：{info_path}")
    print()
    print("下一步：python 03_gen_datapack.py")


if __name__ == "__main__":
    main()
