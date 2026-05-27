from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .export_datapack import DatapackOptions, export_datapack, sanitize_namespace
from .midi import MidiParseError, parse_midi
from .recommend import recommend_tick_rate
from .quality import quality_choice_items, quality_profile
from .summary import format_midi_summary_lines, warning_lines


def _input(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def run_interactive_wizard(args: argparse.Namespace | None = None) -> int:
    print("=" * 60)
    print("midi2mc v0.9.0 交互式生成器 / Minecraft Java 1.21.11")
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
        print(f"[midi2mc] MIDI 解析失败: {midi_path}", file=sys.stderr)
        print(f"  原因: {exc}", file=sys.stderr)
        print("  提示: 确认这是标准 .mid/.midi 文件；当前版本不支持 SMPTE division。", file=sys.stderr)
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

    print("\n" + "-" * 60)
    print("MIDI 摘要预览")
    print("-" * 60)
    for line in format_midi_summary_lines(song, recommendation, recommendation.tick_rate, (getattr(args, "max_notes_per_tick", None) or 24) if args else 24):
        print(line)

    default_show_id = sanitize_namespace(midi_path.stem)
    show_id = _ask_text("Show ID / 数据包命名空间", default_show_id)
    show_id = sanitize_namespace(show_id)

    default_out = getattr(args, "out", "output") if args else "output"
    out_dir = Path(_ask_text("输出目录", str(default_out)))

    preset = _ask_choice(
        "生成模式",
        [
            ("vanilla_machine", "原版音符盒音乐机：不需要资源包，带伪红石舞台（推荐）"),
            ("soma_concert", "Soma 演出舞台：需要 Soma 资源包，生成分层乐器区舞台"),
            ("soma_play", "Soma 只播放：需要 Soma 资源包，不生成舞台"),
            ("custom", "高级自定义：手动选择音源和舞台"),
        ],
        default="vanilla_machine",
    )
    stage_profile = "noteblock_machine"
    if preset == "vanilla_machine":
        sound_engine = "vanilla"
        mode = "command_stage"
        stage_profile = "noteblock_machine"
    elif preset == "soma_concert":
        sound_engine = "soma"
        mode = "command_stage"
        stage_profile = "soma_concert"
    elif preset == "soma_play":
        sound_engine = "soma"
        mode = "play"
        stage_profile = "none"
    else:
        sound_engine = _ask_choice(
            "音源引擎",
            [("vanilla", "原版 note block sounds"), ("soma", "Soma 资源包音源")],
            default=getattr(args, "sound_engine", "vanilla") if args else "vanilla",
        )
        mode = _ask_choice(
            "输出模式",
            [
                ("command_stage", "舞台 + 播放声音"),
                ("play", "只播放声音，不生成舞台"),
            ],
            default="command_stage",
        )
        if mode == "command_stage":
            if sound_engine == "soma":
                stage_profile = _ask_choice(
                    "舞台配置",
                    [
                        ("soma_concert", "Soma layered concert stage：分层乐器区舞台"),
                        ("noteblock_machine", "原版音符盒机器风格舞台"),
                    ],
                    default="soma_concert",
                )
            else:
                stage_profile = "noteblock_machine"
        else:
            stage_profile = "none"

    soma_namespace = getattr(args, "soma_namespace", "") if args else ""
    soma_map = Path(getattr(args, "soma_map", "")) if args and getattr(args, "soma_map", None) else None
    soma_reference_note = getattr(args, "soma_reference_note", 60) if args else 60
    soma_long_note_beats = getattr(args, "soma_long_note_beats", 1.0) if args else 1.0
    if sound_engine == "soma":
        print("\n[midi2mc] Soma 音源提示：")
        print("  - 需要玩家启用包含对应 sound event 的 Soma 资源包。")
        print("  - v0.9.0 已支持 Soma layered concert stage：drums / bass / piano / guitar / strings / wind / synth / other 八个乐器区。")
        print("  - 默认使用 Soma v20 表格规则：短音 编号.音高，长音 编号c.音高；长音灯会从下一 tick 亮起，连续长音交接会自然闪断。")
        print("  - 如果你的 Soma sound event 命名不同，可以之后用命令行 --soma-map 指定 JSON。")
        soma_namespace = _ask_text("Soma namespace", str(soma_namespace))
        soma_reference_note = _ask_int("Soma 旋律采样参考音 MIDI note（旧 simple map 用，v20 可直接回车）", int(soma_reference_note), minimum=0, maximum=127)
        soma_long_note_beats = _ask_float("Soma 长音阈值：多少拍以上使用 c 音色并 stopsound", float(soma_long_note_beats), minimum=0.0)

    default_quality = getattr(args, "quality", "medium") if args else "medium"
    quality = _ask_choice(
        "质量档 / 性能预设",
        quality_choice_items(),
        default=default_quality,
    )
    profile = quality_profile(quality)
    stage_particles = (not getattr(args, "no_stage_particles", False)) and profile.stage_particles
    arg_piano_roll = getattr(args, "piano_roll", None) if args else None
    piano_roll = profile.piano_roll if arg_piano_roll is None else bool(arg_piano_roll)
    if mode != "command_stage":
        piano_roll = False
    print(f"[midi2mc] 质量档：{profile.label}")
    print(f"          默认同 tick 复音上限：{profile.max_notes_per_tick}；舞台粒子：{'开启' if stage_particles else '关闭'}；Piano Roll：{'开启' if piano_roll else '关闭'}")
    show_fx = getattr(args, "show_fx", "auto") if args else "auto"
    if mode == "command_stage":
        piano_roll = _ask_yes_no("是否启用 Piano Roll / 舞台前方粒子光带？", default=piano_roll)
        show_fx = _ask_choice(
            "Show FX / 额外灯光烟花效果",
            [
                ("auto", "自动：Soma 演出舞台默认 lightshow，low 档关闭"),
                ("none", "关闭额外效果，只保留基础舞台反馈"),
                ("lightshow", "轻量灯光：每个音符生成彩色 dust 灯光"),
                ("fireworks", "彩色 dust 烟花风格粒子：只在重音/长音触发，不召唤真实烟花实体"),
                ("both", "lightshow + 烟花风格粒子"),
            ],
            default=str(show_fx or "auto"),
        )
    else:
        show_fx = "none"

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
    default_max_notes = (getattr(args, "max_notes_per_tick", None) if args else None) or profile.max_notes_per_tick
    max_notes = _ask_int(
        "同一 tick 最大复音数（防止超密 MIDI 刷爆命令）",
        default_max_notes,
        minimum=1,
        maximum=256,
    )
    warnings = warning_lines(song, tick_rate, max_notes)
    if warnings:
        print("\n[midi2mc] 生成前风险提示：")
        for line in warnings:
            print(f"  - {line}")
    zip_output = _ask_yes_no("是否同时生成 .zip 数据包？", default=True)

    options = DatapackOptions(
        show_id=show_id,
        out_dir=out_dir,
        pack_format=getattr(args, "pack_format", None) if args else None,
        tick_rate=tick_rate,
        mode=mode,
        gain=gain,
        sound_engine=sound_engine,
        stage_profile=stage_profile if stage_profile != "none" else "noteblock_machine",
        soma_namespace=soma_namespace,
        soma_map=soma_map,
        soma_reference_note=soma_reference_note,
        soma_long_note_beats=soma_long_note_beats,
        quality=quality,
        max_notes_per_tick=max_notes,
        stage_particles=stage_particles,
        piano_roll=piano_roll,
        show_fx=show_fx,
        zip_output=zip_output,
        minecraft_1_21_layout=not getattr(args, "legacy_1_20", False) if args else True,
    )
    result = export_datapack(song, options)

    print("\n[midi2mc] 生成完成！")
    print(f"  目标版本: Minecraft Java 1.21.11")
    print(f"  Show ID: {result.namespace}")
    print(f"  音源引擎: {sound_engine}")
    print(f"  输出模式: {mode}")
    print(f"  质量档: {quality}")
    print(f"  舞台粒子: {'开启' if stage_particles else '关闭'}")
    print(f"  Piano Roll: {'开启' if piano_roll else '关闭'}")
    print(f"  Show FX: {show_fx}")
    print(f"  音符: {song.note_count} parsed / {result.compiled_note_count} compiled")
    print(f"  时长: {song.duration_sec:.2f}s / {result.total_ticks} ticks @ {tick_rate} TPS")
    print(f"  数据包文件夹: {result.pack_dir}")
    if result.zip_path:
        print(f"  数据包 zip: {result.zip_path}")
    print(f"  说明文件: {result.pack_dir.parent / (result.namespace + '_HOW_TO_PLAY.txt')}")

    print("\n最终 MIDI 摘要：")
    for line in format_midi_summary_lines(song, recommendation, tick_rate, max_notes):
        print(line)

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
