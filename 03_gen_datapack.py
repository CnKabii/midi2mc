#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
03_gen_datapack.py

读取 temp/sound_events.json，生成 Minecraft Java 数据包：

  out/datapack/
  out/config.json
  out/README.txt

默认按 Minecraft Java 1.21+ 数据包目录生成：

  data/minecraft/tags/function/load.json
  data/minecraft/tags/function/tick.json
  data/<namespace>/function/*.mcfunction

常用：
  直接运行：
    python 03_gen_datapack.py

  命令行：
    python 03_gen_datapack.py --events temp/sound_events.json --mapping mappings/vanilla.json --yes
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_EVENTS = Path("temp/sound_events.json")
DEFAULT_MIDI_INFO = Path("temp/midi_info.json")
DEFAULT_SOUND_INFO = Path("temp/sound_info.json")
DEFAULT_MAPPING = Path("mappings/vanilla.json")
DEFAULT_OUT = Path("out/datapack")
DEFAULT_BUILD_CONFIG = Path("out/config.json")
DEFAULT_README = Path("out/README.txt")


VALID_NAMESPACE_RE = re.compile(r"^[a-z0-9_.-]+$")


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


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(f"找不到文件：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def validate_namespace(namespace: str) -> str:
    namespace = namespace.strip().lower()
    if not namespace:
        raise ValueError("namespace 不能为空。")
    if not VALID_NAMESPACE_RE.match(namespace):
        raise ValueError("namespace 只能包含小写字母、数字、下划线、点和减号。")
    return namespace


def group_events_by_tick(events: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    grouped: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[int(event["tick"])].append(event)
    return dict(grouped)


def get_recommended_tick_rate(mapping: Dict[str, Any], midi_info: Dict[str, Any], sound_info: Dict[str, Any]) -> int:
    """
    v0.4：推荐 tick rate 优先来自 MIDI BPM 分析。

    注意它只是提示用户执行 /tick rate N；数据包不会自动修改世界速度。
    生成事件使用的 TPS 另见 midi_info.generation_ticks_per_second。
    """

    # 手动覆盖，给高级用户留后门。
    for key in ("recommended_tick_rate_override", "force_recommended_tick_rate"):
        if key in mapping:
            try:
                value = int(mapping[key])
                if value > 0:
                    return value
            except (TypeError, ValueError):
                pass

    # 最重要：MIDI BPM 计算结果。
    for key in ("recommended_tick_rate", "bpm_based_tick_rate"):
        if isinstance(midi_info, dict) and key in midi_info:
            try:
                value = int(midi_info[key])
                if value > 0:
                    return value
            except (TypeError, ValueError):
                pass

    # 兼容旧版中间文件。
    for source in (sound_info, mapping):
        if not isinstance(source, dict):
            continue
        for key in ("recommended_tick_rate", "ticks_per_second", "generation_ticks_per_second"):
            if key in source:
                try:
                    value = int(source[key])
                    if value > 0:
                        return value
                except (TypeError, ValueError):
                    pass
    return 20


def is_player_position_mode(mapping: Dict[str, Any]) -> bool:
    mode = str(mapping.get("sound_position_mode", "player")).strip().lower()
    return mode in {"player", "players", "at_player", "at_players", "listener", "listener_position"}


def get_stop_sound_command(mapping: Dict[str, Any]) -> str:
    if not bool(mapping.get("stop_sound_on_stop", False)):
        return ""
    target = str(mapping.get("target_selector", "@a"))
    source = str(mapping.get("sound_source", "master"))

    if is_player_position_mode(mapping):
        return f"execute as {target} run stopsound @s {source}"

    return f"stopsound {target} {source}"


def build_pack_mcmeta(mapping: Dict[str, Any]) -> str:
    pack_format = int(mapping.get("pack_format", 48))
    description = str(mapping.get("pack_description", "MIDI to Minecraft playsound datapack"))
    data = {"pack": {"pack_format": pack_format, "description": description}}
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def build_load_function(namespace: str) -> str:
    return f"""# {namespace}:internal/load
# 内部函数：/reload 后自动调用
# 作用：创建本数据包需要的 scoreboard

scoreboard objectives add {namespace}.state dummy
scoreboard objectives add {namespace}.timer dummy
scoreboard objectives add {namespace}.info dummy

scoreboard players set #playing {namespace}.state 0
scoreboard players set #time {namespace}.timer 0
"""


def build_start_function(namespace: str, recommended_tick_rate: int) -> str:
    return f"""# {namespace}:start
# 用户函数：从当前位置继续播放

scoreboard players set #playing {namespace}.state 1
tellraw @a {{"text":"[midi2mc] playback started","color":"green"}}
tellraw @a {{"text":"[midi2mc] 建议游戏 tick rate = {recommended_tick_rate}。如果还没设置，请执行 /tick rate {recommended_tick_rate}","color":"aqua"}}
"""


def build_pause_function(namespace: str) -> str:
    return f"""# {namespace}:pause
# 用户函数：暂停播放，保留当前时间

scoreboard players set #playing {namespace}.state 0
tellraw @a {{"text":"[midi2mc] playback paused","color":"yellow"}}
"""


def build_restart_function(namespace: str, recommended_tick_rate: int, stop_sound_command: str) -> str:
    stop_line = stop_sound_command + "\n" if stop_sound_command else ""
    return f"""# {namespace}:restart
# 用户函数：从头播放

{stop_line}scoreboard players set #time {namespace}.timer 0
scoreboard players set #playing {namespace}.state 1
tellraw @a {{"text":"[midi2mc] playback restarted","color":"green"}}
tellraw @a {{"text":"[midi2mc] 建议游戏 tick rate = {recommended_tick_rate}。如果还没设置，请执行 /tick rate {recommended_tick_rate}","color":"aqua"}}
"""


def build_stop_function(namespace: str, stop_sound_command: str) -> str:
    stop_line = stop_sound_command + "\n" if stop_sound_command else ""
    return f"""# {namespace}:stop
# 用户函数：停止播放，并把时间归零

{stop_line}scoreboard players set #playing {namespace}.state 0
scoreboard players set #time {namespace}.timer 0
tellraw @a {{"text":"[midi2mc] playback stopped","color":"red"}}
"""


def build_status_function(namespace: str, end_tick: int, recommended_tick_rate: int) -> str:
    return f"""# {namespace}:status
# 用户函数：查看当前播放状态

tellraw @a [{{"text":"[midi2mc] playing = "}},{{"score":{{"name":"#playing","objective":"{namespace}.state"}}}},{{"text":"，time = "}},{{"score":{{"name":"#time","objective":"{namespace}.timer"}}}},{{"text":" / {end_tick} ticks，推荐 tick rate = {recommended_tick_rate}"}}]
"""


def build_tickrate_hint_function(namespace: str, recommended_tick_rate: int) -> str:
    return f"""# {namespace}:tickrate_hint
# 用户函数：显示推荐 tick rate，不会自动修改世界速度

tellraw @a {{"text":"[midi2mc] 本数据包按 {recommended_tick_rate} tick/s 生成。播放前建议执行：/tick rate {recommended_tick_rate}","color":"aqua"}}
tellraw @a {{"text":"[midi2mc] 播完后想恢复原版速度，可以执行：/tick rate 20","color":"gray"}}
"""


def build_tick_function(namespace: str) -> str:
    return f"""# {namespace}:internal/tick
# 内部函数：每 tick 自动调用

execute if score #playing {namespace}.state matches 1 run function {namespace}:internal/play_tick
"""


def build_play_tick_function(namespace: str, ticks_with_events: List[int], end_tick: int) -> str:
    lines: List[str] = [
        f"# {namespace}:internal/play_tick",
        "# 内部函数：根据当前 #time 播放这一 tick 的音效事件",
        "",
    ]

    for tick in ticks_with_events:
        lines.append(
            f"execute if score #time {namespace}.timer matches {tick} run function {namespace}:internal/events/tick_{tick:06d}"
        )

    lines.extend(
        [
            "",
            f"scoreboard players add #time {namespace}.timer 1",
            f"execute if score #time {namespace}.timer matches {end_tick}.. run function {namespace}:stop",
            "",
        ]
    )
    return "\n".join(lines)


def format_playsound(event: Dict[str, Any], mapping: Dict[str, Any]) -> str:
    sound = str(event["sound"])
    source = str(event.get("source", mapping.get("sound_source", "master")))
    target = str(event.get("target", mapping.get("target_selector", "@a")))
    volume = float(event.get("volume", 1.0))
    pitch = float(event.get("pitch", 1.0))

    if is_player_position_mode(mapping):
        # 关键：让每个玩家在自己所在那一格听到声音。
        # 不能直接用 playsound ... @a ~ ~ ~，因为数据包 tick 函数的执行位置不等于玩家位置。
        return f"execute as {target} at @s run playsound {sound} {source} @s ~ ~ ~ {volume:g} {pitch:g}"

    fixed_pos = mapping.get("fixed_sound_position", "~ ~ ~")
    if isinstance(fixed_pos, list):
        fixed_pos = " ".join(str(part) for part in fixed_pos)
    return f"playsound {sound} {source} {target} {fixed_pos} {volume:g} {pitch:g}"


def format_stopsound(event: Dict[str, Any], mapping: Dict[str, Any]) -> str:
    sound = str(event["sound"])
    source = str(event.get("source", mapping.get("sound_source", "master")))
    target = str(event.get("target", mapping.get("target_selector", "@a")))

    if is_player_position_mode(mapping):
        return f"execute as {target} run stopsound @s {source} {sound}"

    return f"stopsound {target} {source} {sound}"


def build_note_stop_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    根据 sound_events.json 里的 needs_stop / stop_tick 生成 stopsound 事件。

    同一个 sound 如果发生重叠，不能在第一个 note_off 时直接 stopsound，
    否则会把后面仍在响的同音高一起切掉。这里按 target/source/sound 合并重叠区间。
    """

    intervals_by_key: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)

    for event in events:
        if not bool(event.get("needs_stop", False)):
            continue

        start = int(event.get("tick", 0))
        end = int(event.get("stop_tick", start + int(event.get("duration_game_tick", 1))))
        if end <= start:
            end = start + 1

        key = (
            str(event.get("target", "@a")),
            str(event.get("source", "master")),
            str(event.get("sound")),
        )

        intervals_by_key[key].append(
            {
                "start": start,
                "end": end,
                "event": event,
            }
        )

    stop_events: List[Dict[str, Any]] = []

    for (target, source, sound), intervals in intervals_by_key.items():
        intervals.sort(key=lambda item: (int(item["start"]), int(item["end"])))

        merged: List[Dict[str, Any]] = []
        for item in intervals:
            if not merged:
                merged.append(dict(item))
                continue

            current = merged[-1]

            # 只有真正重叠才合并。若前一个 end == 后一个 start，
            # 同 tick 内 stopsound 会先执行，playsound 后执行，不会切掉新音。
            if int(item["start"]) < int(current["end"]):
                current["end"] = max(int(current["end"]), int(item["end"]))
            else:
                merged.append(dict(item))

        for item in merged:
            original = item["event"]
            stop_events.append(
                {
                    "event_type": "stop",
                    "tick": int(item["end"]),
                    "sound": sound,
                    "source": source,
                    "target": target,
                    "channel": original.get("channel"),
                    "program": original.get("program"),
                    "midi_note": original.get("midi_note"),
                    "note_name": original.get("note_name"),
                    "velocity": original.get("velocity"),
                }
            )

    stop_events.sort(key=lambda item: (int(item["tick"]), str(item["sound"])))
    return stop_events


def build_event_function(namespace: str, tick: int, events: List[Dict[str, Any]], mapping: Dict[str, Any]) -> str:
    stop_events = [event for event in events if event.get("event_type") == "stop"]
    play_events = [event for event in events if event.get("event_type", "play") != "stop"]

    lines: List[str] = [
        f"# {namespace}:internal/events/tick_{tick:06d}",
        f"# 本 tick 播放音效：{len(play_events)}，停止长音：{len(stop_events)}",
        "",
    ]

    # 先 stop，后 play。这样同一 tick 内“旧音结束 + 新音开始”不会把新音切掉。
    for event in stop_events:
        lines.append(
            f"# STOP ch={event.get('channel')} program={event.get('program')} note={event.get('note_name', event.get('midi_note'))}"
        )
        lines.append(format_stopsound(event, mapping))

    if stop_events and play_events:
        lines.append("")

    for event in play_events:
        lines.append(
            f"# PLAY ch={event.get('channel')} program={event.get('program')} note={event.get('note_name', event.get('midi_note'))} velocity={event.get('velocity')} duration_tick={event.get('duration_game_tick')}"
        )
        lines.append(format_playsound(event, mapping))

    lines.append("")
    return "\n".join(lines)


def generate_function_tags(datapack_dir: Path, namespace: str) -> None:
    tag_dir = datapack_dir / "data" / "minecraft" / "tags" / "function"

    write_json(tag_dir / "load.json", {"values": [f"{namespace}:internal/load"]})
    write_json(tag_dir / "tick.json", {"values": [f"{namespace}:internal/tick"]})


def generate_functions(datapack_dir: Path, namespace: str, grouped_events: Dict[int, List[Dict[str, Any]]], end_tick: int, recommended_tick_rate: int, stop_sound_command: str, mapping: Dict[str, Any]) -> None:
    function_dir = datapack_dir / "data" / namespace / "function"
    internal_dir = function_dir / "internal"
    events_dir = internal_dir / "events"

    ticks_with_events = sorted(grouped_events.keys())

    write_text(internal_dir / "load.mcfunction", build_load_function(namespace))
    write_text(internal_dir / "tick.mcfunction", build_tick_function(namespace))
    write_text(internal_dir / "play_tick.mcfunction", build_play_tick_function(namespace, ticks_with_events, end_tick))

    write_text(function_dir / "start.mcfunction", build_start_function(namespace, recommended_tick_rate))
    write_text(function_dir / "pause.mcfunction", build_pause_function(namespace))
    write_text(function_dir / "restart.mcfunction", build_restart_function(namespace, recommended_tick_rate, stop_sound_command))
    write_text(function_dir / "stop.mcfunction", build_stop_function(namespace, stop_sound_command))
    write_text(function_dir / "status.mcfunction", build_status_function(namespace, end_tick, recommended_tick_rate))
    write_text(function_dir / "tickrate_hint.mcfunction", build_tickrate_hint_function(namespace, recommended_tick_rate))

    for tick in ticks_with_events:
        write_text(events_dir / f"tick_{tick:06d}.mcfunction", build_event_function(namespace, tick, grouped_events[tick], mapping))


def make_readme(namespace: str, events: List[Dict[str, Any]], midi_info: Dict[str, Any], sound_info: Dict[str, Any], mapping: Dict[str, Any], out_dir: Path) -> str:
    duration_sec = float(midi_info.get("duration_sec", 0.0)) if midi_info else 0.0
    input_name = str(midi_info.get("input", "unknown")) if midi_info else "unknown"
    last_tick = int(sound_info.get("last_tick", 0)) if sound_info else (max([int(e["tick"]) for e in events], default=0))
    recommended_tick_rate = get_recommended_tick_rate(mapping, midi_info, sound_info)
    generation_tps = int(midi_info.get("generation_ticks_per_second", midi_info.get("ticks_per_second", 20))) if midi_info else 20
    tempo_mode = str(midi_info.get("tempo_mode", mapping.get("tempo_mode", "unknown"))) if midi_info else str(mapping.get("tempo_mode", "unknown"))
    main_bpm = midi_info.get("midi_main_bpm", "unknown") if midi_info else "unknown"
    avg_bpm = midi_info.get("midi_average_bpm", "unknown") if midi_info else "unknown"
    base_bpm = midi_info.get("base_bpm_for_tick_rate", mapping.get("base_bpm_for_tick_rate", 120)) if midi_info else mapping.get("base_bpm_for_tick_rate", 120)
    base_tick_rate = midi_info.get("base_tick_rate", mapping.get("base_tick_rate", 20)) if midi_info else mapping.get("base_tick_rate", 20)
    note_stop_count = int(sound_info.get("note_stop_count", 0)) if sound_info else sum(1 for e in events if bool(e.get("needs_stop", False)))
    long_sound_count = int(sound_info.get("long_sound_count", 0)) if sound_info else sum(1 for e in events if str(e.get("sound", "")).split(".")[0].endswith("c"))
    short_sound_count = int(sound_info.get("short_sound_count", 0)) if sound_info else max(0, len(events) - long_sound_count)
    long_note_min_ticks = None
    try:
        soma_options = mapping.get("soma", {}) if isinstance(mapping.get("soma", {}), dict) else {}
        long_note_min_ticks = soma_options.get("long_note_min_ticks", mapping.get("long_note_min_ticks", 8))
    except Exception:
        long_note_min_ticks = 8
    position_mode = str(mapping.get("sound_position_mode", "player"))

    return f"""Midi2Mc 音乐数据包生成结果

生成信息
- namespace: {namespace}
- 输入 MIDI: {input_name}
- 模式: {mapping.get('mode', 'unknown')}
- pack_format: {mapping.get('pack_format', 48)}
- 音符 / 音效事件数量: {len(events)}
- MIDI 时长: {duration_sec:.2f} 秒
- 最后事件 tick: {last_tick}
- 生成事件 TPS: {generation_tps}
- tempo 模式: {tempo_mode}
- MIDI 主 BPM: {main_bpm}
- MIDI 平均 BPM: {avg_bpm}
- sound source: {mapping.get('sound_source', 'master')}
- target: {mapping.get('target_selector', '@a')}
- 声音位置模式: {position_mode}
- 短采样事件数: {short_sound_count}
- c 长采样事件数: {long_sound_count}
- 长音 stop 事件数: {note_stop_count}
- 长音判断阈值: {long_note_min_ticks} tick
- 推荐 tick rate: {recommended_tick_rate}

Tick Rate / BPM 提示
- 数据包不会自动修改世界 tick rate。
- 本数据包的事件 tick 按 {generation_tps} TPS 生成。
- 推荐 tick rate 根据 MIDI 的 BPM 信息计算，规则是：{base_bpm} BPM -> /tick rate {base_tick_rate}。
- 播放前建议在游戏内执行：
  /tick rate {recommended_tick_rate}
- 然后播放：
  /function {namespace}:restart
- 播完后如需恢复原版速度：
  /tick rate 20
- 如果觉得速度不对，可以优先微调 /tick rate，而不用重新生成数据包。

Soma 长短音判断
- v0.6 默认按每个 MIDI 音符的 duration 自动选择。
- duration < {long_note_min_ticks} tick：使用短采样，例如 1.60，不生成 stopsound。
- duration >= {long_note_min_ticks} tick：如果该乐器有 c 采样，使用长采样，例如 1c.60，并按 note_off 生成 stopsound。
- 如果某个乐器没有 c 采样，会自动回退短采样，避免生成不存在的 sound id。
- 想调整判断灵敏度，可以改 mappings/soma_gm.json 里的 soma.long_note_min_ticks，然后重新生成。

声音位置
- 默认使用玩家位置模式：每个播放命令都会变成 execute as @a at @s run playsound ... @s ~ ~ ~。
- 这样声音会在玩家自己所在那一格播放，而不是跑到数据包函数的执行坐标附近。

放置方式
1. 把这个文件夹复制到你的世界 datapacks 目录：
   {out_dir}

   例子：
   .minecraft/saves/你的世界/datapacks/datapack

2. 进游戏执行：
   /reload

游戏内命令
- /function {namespace}:restart
  从头播放。

- /function {namespace}:start
  从当前位置继续播放。

- /function {namespace}:pause
  暂停播放，保留当前时间。

- /function {namespace}:stop
  停止播放，并把时间归零。

- /function {namespace}:status
  查看当前播放时间。

- /function {namespace}:tickrate_hint
  在游戏里显示推荐 tick rate。

注意
- 第一版使用 playsound，不会生成音符盒实体，也不需要红石。
- 如果 /reload 提示 pack_format 不匹配，请打开映射 JSON 修改 pack_format 后重新生成。
- 如果没有声音，先确认游戏声音里的“主音量”和对应分类音量没有关闭。
- 如果 MIDI 太大，生成的 mcfunction 文件会很多，这是正常现象。
- Soma 模式默认使用自动长短音判断。
- v0.6 会按照 MIDI 的 note_off / duration 只为真正选中的 c 长音生成 stopsound，减少长音互相糊在一起的问题。
- 停止或重新开始时仍会执行一次全局 stopsound，对残留音做兜底清理。
"""

def generate_datapack(events: List[Dict[str, Any]], mapping: Dict[str, Any], midi_info: Dict[str, Any], sound_info: Dict[str, Any], out_dir: Path, build_config_path: Path, readme_path: Path, clear: bool) -> None:
    namespace = validate_namespace(str(mapping.get("namespace", "midi2mc")))

    if clear and out_dir.exists():
        shutil.rmtree(out_dir)

    out_dir.mkdir(parents=True, exist_ok=True)

    stop_events = build_note_stop_events(events)
    all_timed_events = list(events) + stop_events

    grouped_events = group_events_by_tick(all_timed_events)
    ticks = sorted(grouped_events.keys())
    play_ticks = [int(event["tick"]) for event in events]
    stop_ticks = [int(event["tick"]) for event in stop_events]
    last_tick = max(play_ticks + stop_ticks, default=0)
    end_tick = last_tick + 40

    recommended_tick_rate = get_recommended_tick_rate(mapping, midi_info, sound_info)
    stop_sound_command = get_stop_sound_command(mapping)

    write_text(out_dir / "pack.mcmeta", build_pack_mcmeta(mapping))
    generate_function_tags(out_dir, namespace)
    generate_functions(out_dir, namespace, grouped_events, end_tick, recommended_tick_rate, stop_sound_command, mapping)

    build_config = {
        "namespace": namespace,
        "datapack_dir": str(out_dir),
        "event_count": len(events),
        "note_stop_count": len(stop_events),
        "active_tick_count": len(grouped_events),
        "last_tick": last_tick,
        "end_tick": end_tick,
        "recommended_tick_rate": recommended_tick_rate,
        "tick_rate_command": f"/tick rate {recommended_tick_rate}",
        "stop_sound_command": stop_sound_command,
        "sound_position_mode": mapping.get("sound_position_mode", "player"),
        "mapping": mapping,
        "midi_info": midi_info,
        "sound_info": sound_info,
    }
    write_json(build_config_path, build_config)
    write_text(readme_path, make_readme(namespace, events, midi_info, sound_info, mapping, out_dir))

    print("完成。")
    print(f"数据包目录：{out_dir}")
    print(f"namespace：{namespace}")
    print(f"播放事件数量：{len(events)}")
    print(f"长音 stop 事件数量：{len(stop_events)}")
    print(f"活跃 tick 数：{len(grouped_events)}")
    print(f"结束 tick：{end_tick}")
    print(f"推荐游戏 tick rate：{recommended_tick_rate}")
    print(f"游戏内建议执行：/tick rate {recommended_tick_rate}")
    print(f"说明文件：{readme_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="temp/sound_events.json -> out/datapack")
    parser.add_argument("--events", default=str(DEFAULT_EVENTS), help="输入 sound_events.json，默认 temp/sound_events.json")
    parser.add_argument("--mapping", default=str(DEFAULT_MAPPING), help="映射配置 JSON，默认 mappings/vanilla.json")
    parser.add_argument("--midi-info", default=str(DEFAULT_MIDI_INFO), help="midi_info.json，默认 temp/midi_info.json")
    parser.add_argument("--sound-info", default=str(DEFAULT_SOUND_INFO), help="sound_info.json，默认 temp/sound_info.json")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="输出数据包目录，默认 out/datapack")
    parser.add_argument("--build-config", default=str(DEFAULT_BUILD_CONFIG), help="生成配置记录，默认 out/config.json")
    parser.add_argument("--readme", default=str(DEFAULT_README), help="生成说明文件，默认 out/README.txt")
    parser.add_argument("--no-clear", action="store_true", help="不清空旧数据包目录")
    parser.add_argument("--yes", action="store_true", help="非交互模式，直接使用参数")
    args = parser.parse_args()

    if not args.yes:
        print("=== 03 数据包生成：sound_events.json -> datapack ===")
        print("直接回车使用方括号里的默认值。")
        print()
        events_path = Path(ask_str("sound_events.json 输入路径", args.events))
        mapping_path = Path(ask_str("映射文件路径", args.mapping))
        midi_info_path = Path(ask_str("midi_info.json 路径", args.midi_info))
        sound_info_path = Path(ask_str("sound_info.json 路径", args.sound_info))
        out_dir = Path(ask_str("数据包输出目录", args.out))
        clear = ask_bool("生成前清空旧数据包目录", not args.no_clear)
        build_config_path = Path(args.build_config)
        readme_path = Path(args.readme)
        print()
    else:
        events_path = Path(args.events)
        mapping_path = Path(args.mapping)
        midi_info_path = Path(args.midi_info)
        sound_info_path = Path(args.sound_info)
        out_dir = Path(args.out)
        clear = not args.no_clear
        build_config_path = Path(args.build_config)
        readme_path = Path(args.readme)

    events = load_json(events_path)
    mapping = load_json(mapping_path)
    midi_info = load_json(midi_info_path, default={})
    sound_info = load_json(sound_info_path, default={})

    generate_datapack(events, mapping, midi_info, sound_info, out_dir, build_config_path, readme_path, clear)

    print()
    print("游戏内常用命令：")
    namespace = validate_namespace(str(mapping.get("namespace", "midi2mc")))
    print(f"  /function {namespace}:tickrate_hint")
    print(f"  /function {namespace}:restart")
    print(f"  /function {namespace}:pause")
    print(f"  /function {namespace}:stop")


if __name__ == "__main__":
    main()
