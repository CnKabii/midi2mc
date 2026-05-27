from __future__ import annotations

import json
import math
import re
import shutil
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .mapping import lane_for_note
from .engines import SoundEngineOptions, build_sound_engine
from .stages.noteblock_machine import stage_note_lines as noteblock_stage_note_lines, noteblock_setup_lines, noteblock_clear_lines, noteblock_stage_usage_report
from .stages.soma_concert import (
    soma_concert_clear_lines,
    soma_concert_note_lines,
    soma_concert_reset_lines,
    soma_concert_setup_lines,
    soma_concert_stop_lines,
    soma_stage_usage_report,
)
from .model import CompiledNote, MidiSong, NoteEvent
from .recommend import recommend_tick_rate
from .quality import quality_profile
from .stages.piano_roll import piano_roll_note_lines, piano_roll_usage_report
from .stages.show_fx import resolve_show_fx, show_fx_note_lines, show_fx_usage_report
from .summary import build_song_stats, format_midi_summary_text, warning_lines


@dataclass(frozen=True)
class DatapackOptions:
    show_id: str
    out_dir: Path
    # Minecraft Java 1.21.11 uses Data Pack version 94.1. Modern pack.mcmeta
    # writes this as min_format [94, 1] plus max_format 94, matching Mojang's
    # generated 1.21.11 datapacks. Set pack_format for legacy single-integer mcmeta.
    pack_format: int | None = None
    pack_min_format: Any = (94, 1)
    pack_max_format: Any = 94
    tick_rate: int = 20
    mode: str = "command_stage"  # play | command_stage
    gain: float = 1.0
    sound_engine: str = "vanilla"  # vanilla | soma
    stage_profile: str = "auto"  # auto | noteblock_machine | soma_concert
    soma_namespace: str = ""
    soma_map: Path | None = None
    soma_reference_note: int = 60
    soma_long_note_beats: float = 1.0
    quality: str = "medium"
    max_notes_per_tick: int = 24
    stage_particles: bool = True
    piano_roll: bool | None = None
    show_fx: str = "auto"  # auto | none | lightshow | fireworks | both
    zip_output: bool = True
    minecraft_1_21_layout: bool = True


@dataclass(frozen=True)
class DatapackResult:
    pack_dir: Path
    zip_path: Path | None
    namespace: str
    total_ticks: int
    compiled_note_count: int
    parsed_note_count: int


def _normalize_stage_options(options: DatapackOptions) -> DatapackOptions:
    if options.mode != "command_stage":
        return options
    profile = (options.stage_profile or "auto").strip().lower()
    if profile == "auto":
        profile = "soma_concert" if options.sound_engine == "soma" else "noteblock_machine"
    if profile not in {"noteblock_machine", "soma_concert"}:
        profile = "noteblock_machine"
    if profile == options.stage_profile:
        return options
    return DatapackOptions(
        show_id=options.show_id,
        out_dir=options.out_dir,
        pack_format=options.pack_format,
        pack_min_format=options.pack_min_format,
        pack_max_format=options.pack_max_format,
        tick_rate=options.tick_rate,
        mode=options.mode,
        gain=options.gain,
        sound_engine=options.sound_engine,
        stage_profile=profile,
        soma_namespace=options.soma_namespace,
        soma_map=options.soma_map,
        soma_reference_note=options.soma_reference_note,
        soma_long_note_beats=options.soma_long_note_beats,
        quality=options.quality,
        max_notes_per_tick=options.max_notes_per_tick,
        stage_particles=options.stage_particles,
        piano_roll=options.piano_roll,
        show_fx=options.show_fx,
        zip_output=options.zip_output,
        minecraft_1_21_layout=options.minecraft_1_21_layout,
    )


def export_datapack(song: MidiSong, options: DatapackOptions) -> DatapackResult:
    namespace = sanitize_namespace(options.show_id)
    root = options.out_dir / namespace
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    function_dir_name = "function" if options.minecraft_1_21_layout else "functions"
    tag_function_dir_name = "function" if options.minecraft_1_21_layout else "functions"
    ns_function_dir = root / "data" / namespace / function_dir_name
    tags_dir = root / "data" / "minecraft" / "tags" / tag_function_dir_name
    events_dir = ns_function_dir / "events"
    dispatch_dir = ns_function_dir / "dispatch"
    stage_dir = ns_function_dir / "stage"
    for directory in (ns_function_dir, tags_dir, events_dir, dispatch_dir, stage_dir):
        directory.mkdir(parents=True, exist_ok=True)

    options = _normalize_stage_options(options)
    compiled = compile_notes(song.notes, options, ticks_per_quarter=song.ticks_per_quarter)
    by_tick: Dict[int, List[CompiledNote]] = defaultdict(list)
    stop_by_tick: Dict[int, List[CompiledNote]] = defaultdict(list)
    for note in compiled:
        by_tick[note.mc_tick].append(note)
        if note.stop_tick is not None and note.stop_sound_id:
            stop_by_tick[note.stop_tick].append(note)

    total_ticks = max(1, math.ceil(song.duration_sec * options.tick_rate) + 2)

    _write_pack_mcmeta(root, options, namespace)
    _write_tags(tags_dir, namespace)
    _write_control_functions(ns_function_dir, namespace, options, total_ticks)
    _write_dispatch_functions(dispatch_dir, by_tick, namespace, total_ticks, stop_by_tick)
    _write_event_functions(events_dir, by_tick, options, stop_by_tick)
    if options.mode == "command_stage":
        _write_stage_functions(stage_dir, ns_function_dir, namespace, options.stage_profile)
    _write_readme(root, namespace, options, song, total_ticks, compiled)
    _write_external_readme(options.out_dir, namespace, root / "README.txt")
    _write_manifest(root, namespace, options, song, total_ticks, compiled)

    zip_path = None
    if options.zip_output:
        zip_path = options.out_dir / f"{namespace}.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in root.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(root))

    return DatapackResult(
        pack_dir=root,
        zip_path=zip_path,
        namespace=namespace,
        total_ticks=total_ticks,
        compiled_note_count=len(compiled),
        parsed_note_count=song.note_count,
    )


def compile_notes(notes: Iterable[NoteEvent], options: DatapackOptions, ticks_per_quarter: int = 480) -> List[CompiledNote]:
    compiled: List[CompiledNote] = []
    notes_by_tick: Dict[int, List[NoteEvent]] = defaultdict(list)
    active_continuous_until: Dict[str, int] = {}
    engine = build_sound_engine(
        SoundEngineOptions(
            name=options.sound_engine,
            gain=options.gain,
            soma_namespace=options.soma_namespace,
            soma_map=options.soma_map,
            soma_reference_note=options.soma_reference_note,
            soma_long_note_beats=options.soma_long_note_beats,
            ticks_per_quarter=ticks_per_quarter,
        )
    )
    for note in notes:
        mc_tick = max(0, round(note.start_sec * options.tick_rate))
        notes_by_tick[mc_tick].append(note)

    for mc_tick in sorted(notes_by_tick):
        # Expire continuous sounds that are no longer active. If an old note ends
        # exactly at this tick, a new note starting here is safe to use c again.
        active_continuous_until = {
            sound_id: stop_tick
            for sound_id, stop_tick in active_continuous_until.items()
            if stop_tick > mc_tick
        }

        group = notes_by_tick[mc_tick]
        # Prevent one dense tick from spamming hundreds of commands.
        group.sort(key=lambda n: (-n.velocity, n.track_index, n.channel, n.note))
        for note in group[: options.max_notes_per_tick]:
            sound = engine.resolve(note)
            continuous_conflict = False
            if sound.stop_sound_id and active_continuous_until.get(sound.stop_sound_id, -1) > mc_tick:
                # A later stopsound would cut both overlapping long notes. Use the
                # short Soma sample for this note instead, preserving the original
                # long note until its own note-off.
                sound = engine.resolve_short(note)
                continuous_conflict = True

            stop_tick = _stop_tick_for(note, mc_tick, options.tick_rate) if sound.stop_sound_id else None
            if sound.stop_sound_id and stop_tick is not None:
                active_continuous_until[sound.stop_sound_id] = max(
                    active_continuous_until.get(sound.stop_sound_id, 0), stop_tick
                )

            compiled.append(
                CompiledNote(
                    mc_tick=mc_tick,
                    note=note,
                    sound_id=sound.sound_id,
                    volume=sound.volume,
                    pitch=sound.pitch,
                    lane=lane_for_note(note.note),
                    sound_engine=engine.name,
                    instrument_key=sound.instrument_key,
                    sound_label=sound.sound_label,
                    stop_tick=stop_tick,
                    stop_sound_id=sound.stop_sound_id,
                    used_continuous=sound.used_continuous,
                    requested_continuous=sound.requested_continuous,
                    resolved_note=sound.resolved_note,
                    note_was_clamped=sound.note_was_clamped,
                    continuous_conflict=continuous_conflict,
                    fallback_reason=sound.fallback_reason,
                )
            )
    compiled.sort(key=lambda n: (n.mc_tick, n.note.track_index, n.note.channel, n.note.note))
    return compiled



def _stop_tick_for(note: NoteEvent, start_tick: int, tick_rate: int) -> int:
    stop_tick = max(0, round((note.start_sec + note.duration_sec) * tick_rate))
    return max(start_tick + 1, stop_tick)

def sanitize_namespace(raw: str) -> str:
    value = raw.strip().lower()
    value = re.sub(r"[^a-z0-9_.-]+", "_", value)
    value = value.strip("._-") or "midi2mc_show"
    return value[:64]



def _piano_roll_enabled(options: DatapackOptions) -> bool:
    if options.mode != "command_stage":
        return False
    if options.piano_roll is not None:
        return bool(options.piano_roll)
    return bool(quality_profile(options.quality).piano_roll)


def _show_fx_enabled(options: DatapackOptions) -> str:
    return resolve_show_fx(options.show_fx, mode=options.mode, stage_profile=_effective_stage_profile(options), quality=options.quality)


def _write_pack_mcmeta(root: Path, options: DatapackOptions, namespace: str) -> None:
    pack: dict[str, object] = {
        "description": f"midi2mc v0.9.0 datapack for Minecraft Java 1.21.11: {namespace}",
    }
    if options.pack_format is not None:
        pack["pack_format"] = options.pack_format
    else:
        pack["min_format"] = _json_pack_format(options.pack_min_format)
        pack["max_format"] = _json_pack_format(options.pack_max_format)
    data = {"pack": pack}
    (root / "pack.mcmeta").write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _write_tags(tags_dir: Path, namespace: str) -> None:
    (tags_dir / "load.json").write_text(
        json.dumps({"values": [f"{namespace}:load"]}, indent=2), "utf-8"
    )
    (tags_dir / "tick.json").write_text(
        json.dumps({"values": [f"{namespace}:tick"]}, indent=2), "utf-8"
    )


def _write_control_functions(
    fn_dir: Path, namespace: str, options: DatapackOptions, total_ticks: int
) -> None:
    objective = "midi2mc"
    tick_tip = _tick_rate_tip(namespace, options.tick_rate)
    _write_function(
        fn_dir / "load.mcfunction",
        [
            "scoreboard objectives add midi2mc dummy",
            "scoreboard players set $time midi2mc -1",
            "scoreboard players set $playing midi2mc 0",
            "scoreboard players set $loop midi2mc 0",
            f"say [midi2mc] Loaded {namespace}. Run /function {namespace}:setup then /function {namespace}:play",
            tick_tip,
        ],
    )
    tick_lines = [
        "execute if score $playing midi2mc matches 1 run scoreboard players add $time midi2mc 1",
    ]
    if options.mode == "command_stage":
        tick_lines.append(
            "execute if score $playing midi2mc matches 1 run function "
            f"{namespace}:stage/clear"
        )
    tick_lines.extend(
        [
            f"execute if score $playing midi2mc matches 1 run function {namespace}:dispatch/root",
            f"execute if score $time midi2mc matches {total_ticks}.. if score $loop midi2mc matches 1 run function {namespace}:play",
            f"execute if score $time midi2mc matches {total_ticks}.. unless score $loop midi2mc matches 1 run function {namespace}:stop",
        ]
    )
    _write_function(fn_dir / "tick.mcfunction", tick_lines)
    play_lines = [
        "scoreboard players set $time midi2mc -1",
    ]
    if options.mode == "command_stage":
        play_lines.append(f"function {namespace}:stage/reset")
    play_lines.extend(
        [
            "scoreboard players set $playing midi2mc 1",
            f"say [midi2mc] Playing {namespace}",
            tick_tip,
        ]
    )
    _write_function(fn_dir / "play.mcfunction", play_lines)
    _write_function(
        fn_dir / "pause.mcfunction",
        [
            "scoreboard players set $playing midi2mc 0",
            f"say [midi2mc] Paused {namespace}",
        ],
    )
    _write_function(
        fn_dir / "resume.mcfunction",
        [
            "scoreboard players set $playing midi2mc 1",
            f"say [midi2mc] Resumed {namespace}",
        ],
    )
    _write_function(
        fn_dir / "stop.mcfunction",
        [
            "scoreboard players set $playing midi2mc 0",
            "scoreboard players set $time midi2mc -1",
            f"function {namespace}:stage/reset" if options.mode == "command_stage" else "",
            f"say [midi2mc] Stopped {namespace}",
        ],
    )
    _write_function(
        fn_dir / "loop_on.mcfunction",
        ["scoreboard players set $loop midi2mc 1", f"say [midi2mc] Loop on: {namespace}"],
    )
    _write_function(
        fn_dir / "loop_off.mcfunction",
        ["scoreboard players set $loop midi2mc 0", f"say [midi2mc] Loop off: {namespace}"],
    )

    setup_lines = []
    if options.mode == "command_stage":
        setup_lines.extend([f"function {namespace}:stage/setup", tick_tip])
    else:
        setup_lines.append(f"say [midi2mc] No stage needed for {namespace}; run /function {namespace}:play")
    _write_function(fn_dir / "setup.mcfunction", setup_lines)


def _write_dispatch_functions(
    dispatch_dir: Path,
    by_tick: Dict[int, List[CompiledNote]],
    namespace: str,
    total_ticks: int,
    stop_by_tick: Dict[int, List[CompiledNote]] | None = None,
) -> None:
    active_ticks = sorted(set(by_tick) | set(stop_by_tick or {}))
    chunk_size = 100
    chunks: Dict[int, List[int]] = defaultdict(list)
    for tick in active_ticks:
        chunks[tick // chunk_size].append(tick)

    root_lines = []
    max_chunk = max(chunks.keys(), default=0)
    for chunk in range(max_chunk + 1):
        start = chunk * chunk_size
        end = start + chunk_size - 1
        if chunk in chunks:
            root_lines.append(
                f"execute if score $time midi2mc matches {start}..{end} run function {namespace}:dispatch/{chunk:04d}"
            )
    if not root_lines:
        root_lines.append("# No note events were generated.")
    _write_function(dispatch_dir / "root.mcfunction", root_lines)

    for chunk, ticks in chunks.items():
        lines = [
            f"execute if score $time midi2mc matches {tick} run function {namespace}:events/{tick:06d}"
            for tick in ticks
        ]
        _write_function(dispatch_dir / f"{chunk:04d}.mcfunction", lines)


def _write_event_functions(events_dir: Path, by_tick: Dict[int, List[CompiledNote]], options: DatapackOptions, stop_by_tick: Dict[int, List[CompiledNote]] | None = None) -> None:
    namespace = sanitize_namespace(options.show_id)
    note_values = [compiled.note.note for notes in by_tick.values() for compiled in notes]
    min_note = min(note_values) if note_values else 21
    max_note = max(note_values) if note_values else 108
    all_ticks = sorted(set(by_tick) | set(stop_by_tick or {}))
    for tick in all_ticks:
        notes = by_tick.get(tick, [])
        stops = (stop_by_tick or {}).get(tick, [])
        lines: List[str] = []
        for compiled in stops:
            if compiled.stop_sound_id:
                category = "voice" if compiled.sound_engine == "soma" else "master"
                lines.append(
                    "execute as @a run stopsound "
                    f"@s {category} {compiled.stop_sound_id}"
                )
            if options.mode == "command_stage":
                lines.extend(_stage_stop_lines(compiled, namespace, options.stage_profile))
        for compiled in notes:
            category = "voice" if compiled.sound_engine == "soma" else "master"
            lines.append(
                "execute as @a at @s run playsound "
                f"{compiled.sound_id} {category} @s ~ ~ ~ {compiled.volume:g} {compiled.pitch:g}"
            )
            if options.mode == "command_stage":
                lines.extend(_stage_note_lines(compiled, namespace, min_note, max_note, options.stage_profile, options.stage_particles))
                if _piano_roll_enabled(options):
                    lines.extend(piano_roll_note_lines(compiled, namespace, min_note, max_note))
                fx_profile = _show_fx_enabled(options)
                if fx_profile != "none":
                    lines.extend(show_fx_note_lines(compiled, namespace, min_note, max_note, options.stage_profile, fx_profile))
        _write_function(events_dir / f"{tick:06d}.mcfunction", lines)


def _write_stage_functions(stage_dir: Path, fn_dir: Path, namespace: str, stage_profile: str) -> None:
    _write_function(stage_dir / "setup.mcfunction", _stage_setup_lines(namespace, stage_profile))
    _write_function(stage_dir / "clear.mcfunction", _stage_clear_lines(namespace, stage_profile))
    _write_function(stage_dir / "reset.mcfunction", _stage_reset_lines(namespace, stage_profile))


def _stage_setup_lines(namespace: str, stage_profile: str) -> list[str]:
    if stage_profile == "soma_concert":
        return soma_concert_setup_lines(namespace)
    return noteblock_setup_lines(namespace)


def _stage_clear_lines(namespace: str, stage_profile: str) -> list[str]:
    if stage_profile == "soma_concert":
        return soma_concert_clear_lines(namespace)
    return noteblock_clear_lines(namespace)


def _stage_reset_lines(namespace: str, stage_profile: str) -> list[str]:
    if stage_profile == "soma_concert":
        return soma_concert_reset_lines(namespace)
    return noteblock_clear_lines(namespace)


def _stage_note_lines(compiled: CompiledNote, namespace: str, min_note: int, max_note: int, stage_profile: str, stage_particles: bool) -> list[str]:
    if stage_profile == "soma_concert":
        return soma_concert_note_lines(compiled, namespace, min_note, max_note, stage_particles=stage_particles)
    return noteblock_stage_note_lines(compiled, namespace, min_note, max_note, stage_particles=stage_particles)


def _stage_stop_lines(compiled: CompiledNote, namespace: str, stage_profile: str) -> list[str]:
    if stage_profile == "soma_concert":
        return soma_concert_stop_lines(compiled, namespace)
    return []


def _write_readme(root: Path, namespace: str, options: DatapackOptions, song: MidiSong, total_ticks: int, compiled: List[CompiledNote]) -> None:
    recommendation = recommend_tick_rate(song)
    stats = build_song_stats(song, tick_rate=options.tick_rate, max_notes_per_tick=options.max_notes_per_tick)
    warnings = warning_lines(song, tick_rate=options.tick_rate, max_notes_per_tick=options.max_notes_per_tick)
    tick_command = f"/tick rate {options.tick_rate}"
    reset_command = "/tick rate 20"
    if options.tick_rate == 20:
        tick_step = "当前按原版 20 TPS 编译，不需要执行 /tick rate。"
    else:
        tick_step = f"播放前建议执行：{tick_command}\n播放结束想恢复原版速度：{reset_command}"
    pack_format_text = (
        f"legacy pack_format {options.pack_format}"
        if options.pack_format is not None
        else "min_format [94, 1] / max_format 94"
    )
    warnings_text = "\n".join(f"- {line}" for line in warnings) if warnings else "- 未检测到明显风险。"
    summary_text = format_midi_summary_text(song, recommendation, options.tick_rate, options.max_notes_per_tick)
    engine = build_sound_engine(SoundEngineOptions(name=options.sound_engine, gain=options.gain, soma_namespace=options.soma_namespace, soma_map=options.soma_map, soma_reference_note=options.soma_reference_note, soma_long_note_beats=options.soma_long_note_beats, ticks_per_quarter=song.ticks_per_quarter))
    engine_text = "\n".join(f"- {line}" for line in engine.readme_notes())
    soma_report_text = _format_soma_report(_soma_usage_report(compiled))

    text = f"""midi2mc v0.9.0 数据包说明：{namespace}

这是一个由 midi2mc 自动生成的 Minecraft Java 1.21.11 MIDI 音乐数据包。
当前版本目标是：小工具 + 数据包 + 质量档/性能保护 + 轻量灯光/烟花风格粒子效果。

====================
最快使用步骤
====================
1. 把这个文件夹或同名 .zip 放入世界的 datapacks 文件夹。
2. 进入世界后执行：/reload
3. 站在想生成舞台的位置，执行：/function {namespace}:setup
4. {tick_step}
5. 开始播放：/function {namespace}:play

====================
控制命令
====================
/function {namespace}:setup
/function {namespace}:play
/function {namespace}:pause
/function {namespace}:resume
/function {namespace}:stop
/function {namespace}:loop_on
/function {namespace}:loop_off

====================
本曲 MIDI 摘要
====================
{summary_text}

====================
生成设置
====================
- 目标版本: Minecraft Java 1.21.11
- pack.mcmeta: {pack_format_text}
- Show ID / namespace: {namespace}
- 输出模式: {options.mode}
- 音源引擎: {options.sound_engine}
- 舞台配置: {_effective_stage_profile(options)}
- 质量档: {options.quality}
- 舞台粒子: {"开启" if options.stage_particles else "关闭"}
- Piano Roll 粒子光带: {"开启" if _piano_roll_enabled(options) else "关闭"}
- Show FX / 灯光烟花效果: {_show_fx_enabled(options)}
- Soma sound category: voice
- Soma sound event: 不添加 soma: 命名空间，示例 2.66 / 2c.66
- 编译 TPS: {options.tick_rate}
- 建议 tick 指令: {tick_command}
- 最大同 tick 复音数: {options.max_notes_per_tick}
- 原始音符数: {song.note_count}
- 编译后音符数: {sum(min(len(group), options.max_notes_per_tick) for group in _notes_grouped_by_tick(song.notes, options.tick_rate).values())}
- Minecraft 总 tick: {total_ticks}
- 预计时长: {stats.duration_text} ({song.duration_sec:.2f}s)

====================
音源说明
====================
{engine_text}

====================
Soma 使用报告
====================
{soma_report_text}

====================
风险提示 / 调试提示
====================
{warnings_text}

如果 /reload 报错：
- 先确认 Minecraft 版本是 Java 1.21.11。
- 如果你用的是旧版 MC，请重新导出时加 --legacy-1-20 和对应 --pack-format。
- 如果日志指向某个 .mcfunction，把那一行日志贴给开发者最容易修。

如果播放不同步：
- 确认播放前执行了推荐的 /tick rate。
- 如果不想改变游戏速度，可以重新导出时手动选择 20 TPS。

如果游戏卡顿：
- 重新导出并降低“同一 tick 最大复音数”。
- 超大 MIDI 建议先用只播放模式或较低复音上限测试。

====================
command_stage 说明
====================
command_stage 是“伪红石音乐”舞台，不是真红石电路。
实际声音由 playsound 播放，舞台只负责视觉反馈。

舞台核心区域：
- 音符盒：显示当前触发的音符/乐器。
- 音符盒下方方块：按乐器切换，例如 guitar=羊毛，bit/方波=绿宝石块。
- 红石灯：当前 lane 的短暂脉冲反馈。
- note 粒子：按音高变化颜色。

当前限制：
- v0.8 已支持质量档：low / medium / high / insane。Piano Roll 默认关闭，可手动开启。Show FX 支持 none / lightshow / fireworks / both；v0.9.0 起 lightshow/fireworks 使用可染色 minecraft:dust 粒子，不再用 note/end_rod 作为主体；fireworks 是彩色粒子爆发，不召唤真实烟花实体。原版/Soma 舞台都使用更宽的分组布局，特效会跟随对应 lane / 乐器模块触发。Soma 长音灯光会从下一 tick 持续亮起，连续长音交接时会自然闪断一下。
- Soma 默认 sound event 使用 v20 表格规则：<编号>.<音高>，长音使用 <编号>c.<音高> 并自动 stopsound。Soma concert stage 会按 drums / bass / piano / guitar / strings / wind / synth / other 分区闪灯；长音 c 会保持对应区域常亮直到 note off。
- 暂时忽略 sustain pedal、pitch bend、expression 等高级 MIDI 控制。
- 数据包不会自动执行 /tick rate；这个命令需要玩家/管理员自己执行。
"""
    (root / "README.txt").write_text(text, "utf-8")


def _write_external_readme(out_dir: Path, namespace: str, readme_path: Path) -> None:
    """Copy the generated instructions next to the zip/folder for easier sharing."""
    if readme_path.exists():
        (out_dir / f"{namespace}_HOW_TO_PLAY.txt").write_text(readme_path.read_text("utf-8"), "utf-8")


def _notes_grouped_by_tick(notes: Iterable[NoteEvent], tick_rate: int) -> Dict[int, List[NoteEvent]]:
    groups: Dict[int, List[NoteEvent]] = defaultdict(list)
    for note in notes:
        groups[max(0, round(note.start_sec * tick_rate))].append(note)
    return groups



def _effective_stage_profile(options: DatapackOptions) -> str:
    return options.stage_profile if options.mode == "command_stage" else "none"

def _write_manifest(
    root: Path,
    namespace: str,
    options: DatapackOptions,
    song: MidiSong,
    total_ticks: int,
    compiled: List[CompiledNote],
) -> None:
    recommendation = recommend_tick_rate(song)
    stats = build_song_stats(song, tick_rate=options.tick_rate, max_notes_per_tick=options.max_notes_per_tick)
    data = {
        "format": "midi2mc.show.v0.9.0",
        "namespace": namespace,
        "target_minecraft": "Java 1.21.11",
        "pack_format": options.pack_format,
        "pack_min_format": _json_pack_format(options.pack_min_format),
        "pack_max_format": _json_pack_format(options.pack_max_format),
        "tick_rate": options.tick_rate,
        "recommended_tick_rate": recommendation.tick_rate,
        "suggested_tick_command": f"/tick rate {options.tick_rate}",
        "mode": options.mode,
        "sound_engine": options.sound_engine,
        "stage_profile": _effective_stage_profile(options),
        "engine": build_sound_engine(SoundEngineOptions(name=options.sound_engine, gain=options.gain, soma_namespace=options.soma_namespace, soma_map=options.soma_map, soma_reference_note=options.soma_reference_note, soma_long_note_beats=options.soma_long_note_beats, ticks_per_quarter=song.ticks_per_quarter)).manifest(),
        "duration_seconds": round(song.duration_sec, 3),
        "duration_text": stats.duration_text,
        "duration_ticks": total_ticks,
        "midi_notes": song.note_count,
        "compiled_notes": len(compiled),
        "dropped_notes_due_to_cap": stats.dropped_note_count,
        "max_polyphony_raw": stats.max_polyphony_raw,
        "quality": options.quality,
        "quality_profile": quality_profile(options.quality).__dict__,
        "max_notes_per_tick": options.max_notes_per_tick,
        "stage_particles": options.stage_particles,
        "piano_roll": _piano_roll_enabled(options),
        "show_fx": _show_fx_enabled(options),
        "note_range": stats.note_range,
        "used_track_count": stats.used_track_count,
        "used_channel_count": stats.used_channel_count,
        "drum_note_count": stats.drum_note_count,
        "melodic_note_count": stats.melodic_note_count,
        "track_names": song.track_names,
        "top_instruments": stats.top_instruments,
        "soma_report": _soma_usage_report(compiled),
        "stage_report": _stage_usage_report(compiled, options.stage_profile),
        "visualizer_report": piano_roll_usage_report(compiled, _piano_roll_enabled(options) and options.mode == "command_stage"),
        "show_fx_report": show_fx_usage_report(compiled, _show_fx_enabled(options), _effective_stage_profile(options)),
        "arrangement_report": _arrangement_report(compiled),
        "warnings": warning_lines(song, options.tick_rate, options.max_notes_per_tick),
    }
    (root / "midi2mc_manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _stage_usage_report(compiled: List[CompiledNote], stage_profile: str) -> dict[str, object]:
    if stage_profile == "soma_concert":
        return soma_stage_usage_report(compiled)
    return noteblock_stage_usage_report(compiled) if stage_profile == "noteblock_machine" else {"profile": stage_profile, "enabled": stage_profile != "none"}


def _soma_usage_report(compiled: List[CompiledNote]) -> dict[str, object]:
    soma_notes = [note for note in compiled if note.sound_engine == "soma"]
    if not soma_notes:
        return {"enabled": False}
    unique_sounds = sorted({note.sound_id for note in soma_notes})
    unique_stop_sounds = sorted({note.stop_sound_id for note in soma_notes if note.stop_sound_id})
    program_counts: Dict[str, int] = defaultdict(int)
    label_counts: Dict[str, int] = defaultdict(int)
    for note in soma_notes:
        program_counts[str(note.note.program + 1)] += 1
        label_counts[note.sound_label] += 1
    clamped_examples = []
    for note in soma_notes:
        if note.note_was_clamped:
            clamped_examples.append(
                {
                    "tick": note.mc_tick,
                    "program": note.note.program + 1,
                    "from": note.note.note,
                    "to": note.resolved_note,
                    "sound": note.sound_id,
                }
            )
            if len(clamped_examples) >= 12:
                break
    return {
        "enabled": True,
        "total_soma_notes": len(soma_notes),
        "short_notes": sum(1 for note in soma_notes if not note.used_continuous),
        "continuous_notes": sum(1 for note in soma_notes if note.used_continuous),
        "requested_continuous_notes": sum(1 for note in soma_notes if note.requested_continuous),
        "stopsound_count": sum(1 for note in soma_notes if note.stop_sound_id),
        "overlap_short_fallbacks": sum(1 for note in soma_notes if note.continuous_conflict),
        "clamped_notes": sum(1 for note in soma_notes if note.note_was_clamped),
        "clamped_examples": clamped_examples,
        "unique_sound_count": len(unique_sounds),
        "unique_stop_sound_count": len(unique_stop_sounds),
        "top_programs": sorted(program_counts.items(), key=lambda item: (-item[1], item[0]))[:10],
        "top_labels": sorted(label_counts.items(), key=lambda item: (-item[1], item[0]))[:10],
        "policies": {
            "long_note_overlap": "downgrade_overlapping_continuous_notes_to_short",
            "out_of_range_note": "clamp_to_nearest_available_note",
        },
    }



def _arrangement_report(compiled: List[CompiledNote]) -> dict[str, object]:
    """Summarize MIDI track/channel/program grouping for v0.9 stage work."""
    track_counts: Dict[str, int] = defaultdict(int)
    channel_counts: Dict[str, int] = defaultdict(int)
    program_counts: Dict[str, int] = defaultdict(int)
    instrument_counts: Dict[str, int] = defaultdict(int)
    for note in compiled:
        track_name = note.note.track_name or f"Track {note.note.track_index}"
        track_counts[track_name] += 1
        channel_counts[str(note.note.channel + 1)] += 1
        label = note.sound_label or note.instrument_key
        program_counts[f"{note.note.program + 1}: {label}"] += 1
        instrument_counts[note.instrument_key] += 1
    def top(counter: Dict[str, int], limit: int = 16) -> list[dict[str, object]]:
        return [{"name": name, "notes": count} for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]]
    return {
        "profile": "channel_track_program_summary_v0.9",
        "track_groups": top(track_counts),
        "channel_groups": top(channel_counts),
        "program_groups": top(program_counts),
        "instrument_groups": top(instrument_counts),
        "stage_policy": "visual FX follow the noteblock lane or Soma module for each triggered note; spacious stage reduces overlap",
    }

def _format_soma_report(report: dict[str, object]) -> str:
    if not report.get("enabled"):
        return "- 当前不是 Soma 音源，未生成 Soma 使用报告。"
    lines = [
        f"- Soma 音符数: {report['total_soma_notes']}",
        f"- 短音数量: {report['short_notes']}",
        f"- 长音 c 数量: {report['continuous_notes']}",
        f"- stopsound 数量: {report['stopsound_count']}",
        f"- 重叠长音降级为短音: {report['overlap_short_fallbacks']}",
        f"- 音域夹取 fallback: {report['clamped_notes']}",
        f"- 使用 sound event 种类: {report['unique_sound_count']}",
    ]
    top_labels = report.get("top_labels") or []
    if top_labels:
        readable = ", ".join(f"{label}×{count}" for label, count in top_labels[:5])
        lines.append(f"- 主要 Soma 乐器: {readable}")
    if report.get("clamped_examples"):
        lines.append("- 音域夹取示例已写入 midi2mc_manifest.json 的 soma_report.clamped_examples。")
    return "\n".join(lines)


def _tick_rate_tip(namespace: str, tick_rate: int) -> str:
    if tick_rate == 20:
        return f"say [midi2mc] Compiled for vanilla 20 TPS. No /tick rate change needed for {namespace}."
    return (
        f"say [midi2mc] Best sync for {namespace}: run /tick rate {tick_rate} before play; "
        "run /tick rate 20 after the show if you want vanilla speed."
    )

def _json_pack_format(value: Any) -> object:
    if isinstance(value, tuple):
        return list(value)
    return value


def _write_function(path: Path, lines: Iterable[str]) -> None:
    cleaned = [line for line in lines if line is not None and str(line).strip()]
    if not cleaned:
        cleaned = ["# empty"]
    path.write_text("\n".join(cleaned) + "\n", "utf-8")
