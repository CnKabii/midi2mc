from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

from . import __version__
from .export_datapack import sanitize_namespace
from .midi import MidiParseError, parse_midi
from .preset_profiles import PRESETS
from .project import PROJECT_FORMAT
from .quality import quality_choices, quality_profile
from .recommend import recommend_tick_rate
from .safety import analyze_safety, format_safety_report
from .summary import format_midi_summary_lines, warning_lines

SHOW_FX_CHOICES = ["auto", "none", "lightshow", "fireworks", "both"]
FX_PROFILE_CHOICES = ["clean", "redstone", "concert", "magic"]
STAGE_LAYOUT_CHOICES = ["auto", "compact", "wide", "huge"]
STAGE_TEMPLATE_CHOICES = ["pulse", "classic_line", "minimal"]
SOUND_ENGINE_CHOICES = ["vanilla", "soma"]
STAGE_PROFILE_CHOICES = ["auto", "noteblock_machine", "soma_concert"]
SOMA_DRUM_CHOICES = ["auto", "normal", "electronic", "percussion"]


def run_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as exc:  # pragma: no cover - depends on local Python build.
        print(f"[midi2mc] GUI unavailable: {exc}", file=sys.stderr)
        print("[midi2mc] Try the interactive wizard instead: python -m midi2mc", file=sys.stderr)
        return 2

    root = tk.Tk()
    root.title(f"midi2mc {__version__} GUI")
    root.geometry("1040x820")
    root.minsize(960, 720)

    q: queue.Queue[tuple[str, str]] = queue.Queue()
    worker: threading.Thread | None = None

    base_dir = Path.cwd()
    default_out = str(base_dir / "output")

    midi_var = tk.StringVar()
    project_var = tk.StringVar()
    out_var = tk.StringVar(value=default_out)
    show_id_var = tk.StringVar()
    preset_names = list(PRESETS.keys())
    preset_var = tk.StringVar(value="vanilla_fx" if "vanilla_fx" in preset_names else preset_names[0])

    sound_engine_var = tk.StringVar(value="vanilla")
    stage_profile_var = tk.StringVar(value="noteblock_machine")
    stage_layout_var = tk.StringVar(value="wide")
    stage_template_var = tk.StringVar(value="pulse")
    quality_var = tk.StringVar(value="medium")
    show_fx_var = tk.StringVar(value="lightshow")
    fx_profile_var = tk.StringVar(value="concert")
    fx_intensity_var = tk.StringVar(value="1.0")
    fx_layers_var = tk.StringVar(value="all")
    module_hold_var = tk.StringVar(value="")
    max_notes_var = tk.StringVar(value="")
    gain_var = tk.StringVar(value="1.0")
    soma_long_var = tk.StringVar(value="1.0")
    soma_drum_var = tk.StringVar(value="auto")

    safe_var = tk.BooleanVar(value=False)
    report_var = tk.BooleanVar(value=True)
    zip_var = tk.BooleanVar(value=True)
    legacy_var = tk.BooleanVar(value=False)
    stage_particles_var = tk.BooleanVar(value=True)
    piano_roll_var = tk.BooleanVar(value=False)

    last_report_path = tk.StringVar(value="")

    def append(text: str, tag: str = "normal") -> None:
        log.configure(state="normal")
        log.insert("end", text, tag)
        log.see("end")
        log.configure(state="disabled")

    def replace_summary(text: str) -> None:
        summary_box.configure(state="normal")
        summary_box.delete("1.0", "end")
        summary_box.insert("end", text)
        summary_box.configure(state="disabled")

    def set_running(running: bool) -> None:
        generate_btn.configure(state="disabled" if running else "normal")
        analyze_btn.configure(state="disabled" if running else "normal")
        save_project_btn.configure(state="disabled" if running else "normal")
        for widget in inputs:
            try:
                widget.configure(state="disabled" if running else "normal")
            except tk.TclError:
                pass

    def apply_preset_to_form(*_args: Any) -> None:
        profile = PRESETS.get(preset_var.get())
        if not profile:
            return
        values = profile.values
        sound_engine_var.set(str(values.get("sound_engine", sound_engine_var.get())))
        stage_profile_var.set(str(values.get("stage_profile", stage_profile_var.get())))
        stage_layout_var.set(str(values.get("stage_layout", stage_layout_var.get())))
        stage_template_var.set(str(values.get("stage_template", stage_template_var.get())))
        quality_var.set(str(values.get("quality", quality_var.get())))
        show_fx_var.set(str(values.get("show_fx", show_fx_var.get())))
        fx_profile_var.set(str(values.get("fx_profile", fx_profile_var.get())))
        fx_intensity_var.set(str(values.get("fx_intensity", fx_intensity_var.get())))
        fx_layers_var.set(str(values.get("fx_layers", fx_layers_var.get())))
        module_hold = values.get("module_hold_ticks", "")
        module_hold_var.set("" if module_hold in (None, 0, "0", "") else str(module_hold))
        safe_var.set(bool(values.get("safe_mode", False)))
        stage_particles_var.set(not bool(values.get("no_stage_particles", False)))
        piano_roll_var.set(bool(values.get("piano_roll", False)))
        max_notes = values.get("max_notes_per_tick", None)
        max_notes_var.set("" if max_notes in (None, "") else str(max_notes))
        preset_label.configure(text=profile.description)

    def browse_midi() -> None:
        path = filedialog.askopenfilename(
            title="选择 MIDI 文件",
            filetypes=[("MIDI files", "*.mid *.midi"), ("All files", "*.*")],
        )
        if path:
            midi_var.set(path)
            if not show_id_var.get().strip():
                show_id_var.set(Path(path).stem)
            analyze_midi(silent=True)

    def _load_project_data(path: Path) -> dict[str, Any]:
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("project JSON must be an object")
        return data

    def populate_from_project(path: Path) -> None:
        data = _load_project_data(path)
        base = path.resolve().parent
        preset_name = data.get("preset") or data.get("base_preset")
        if preset_name in PRESETS:
            preset_var.set(str(preset_name))
            apply_preset_to_form()

        def resolve(value: Any) -> str:
            if value in (None, ""):
                return ""
            p = Path(str(value)).expanduser()
            if not p.is_absolute():
                p = base / p
            return str(p)

        midi_var.set(resolve(data.get("midi")))
        out_var.set(resolve(data.get("out", "output")) or default_out)
        show_id_var.set(str(data.get("show_id") or ""))
        if data.get("sound_engine"):
            sound_engine_var.set(str(data["sound_engine"]))
        if data.get("stage_profile"):
            stage_profile_var.set(str(data["stage_profile"]))
        if data.get("stage_layout"):
            stage_layout_var.set(str(data["stage_layout"]))
        if data.get("stage_template"):
            stage_template_var.set(str(data["stage_template"]))
        if data.get("quality"):
            quality_var.set(str(data["quality"]))
        if data.get("show_fx"):
            show_fx_var.set(str(data["show_fx"]))
        if data.get("fx_profile"):
            fx_profile_var.set(str(data["fx_profile"]))
        if data.get("fx_intensity") is not None:
            fx_intensity_var.set(str(data.get("fx_intensity")))
        if data.get("fx_layers"):
            fx_layers_var.set(str(data.get("fx_layers")))
        module_hold_var.set("" if data.get("module_hold_ticks") in (None, 0, "0", "") else str(data.get("module_hold_ticks")))
        safe_var.set(bool(data.get("safe_mode", safe_var.get())))
        stage_particles_var.set(bool(data.get("stage_particles", not data.get("no_stage_particles", False))))
        piano_roll_var.set(bool(data.get("piano_roll", False)))
        report_var.set(bool(data.get("report_html", True)))
        zip_var.set(bool(data.get("zip_output", True)))
        max_notes_var.set("" if data.get("max_notes_per_tick") in (None, "") else str(data.get("max_notes_per_tick")))
        gain_var.set(str(data.get("gain", "1.0")))
        soma = data.get("soma") if isinstance(data.get("soma"), dict) else {}
        soma_long_var.set(str(soma.get("long_note_beats", data.get("soma_long_note_beats", "1.0"))))
        soma_drum_var.set(str(soma.get("drum_kit", data.get("soma_drum_kit", "auto"))))
        minecraft = data.get("minecraft") if isinstance(data.get("minecraft"), dict) else {}
        legacy_var.set(bool(minecraft.get("legacy_1_20", data.get("legacy_1_20", False))))
        analyze_midi(silent=True)

    def browse_project() -> None:
        path = filedialog.askopenfilename(
            title="选择 .m2mc.json 项目配置",
            filetypes=[("midi2mc project", "*.m2mc.json *.json"), ("All files", "*.*")],
        )
        if path:
            project_var.set(path)
            try:
                populate_from_project(Path(path))
                append(f"[GUI] 已加载项目配置：{path}\n", "ok")
            except Exception as exc:
                messagebox.showerror("midi2mc", f"无法加载项目配置：{exc}")

    def browse_out() -> None:
        path = filedialog.askdirectory(title="选择输出文件夹")
        if path:
            out_var.set(path)

    def effective_max_notes() -> int:
        raw = max_notes_var.get().strip()
        if raw:
            try:
                return max(1, int(raw))
            except ValueError:
                return quality_profile(quality_var.get()).max_notes_per_tick
        if safe_var.get():
            return 8
        return quality_profile(quality_var.get()).max_notes_per_tick

    def current_show_id() -> str:
        raw = show_id_var.get().strip() or (Path(midi_var.get().strip()).stem if midi_var.get().strip() else "midi2mc_show")
        return sanitize_namespace(raw)

    def analyze_midi(silent: bool = False) -> None:
        midi = midi_var.get().strip()
        if not midi:
            if not silent:
                messagebox.showwarning("midi2mc", "请先选择 MIDI 文件。")
            return
        path = Path(midi)
        try:
            song = parse_midi(path)
            recommendation = recommend_tick_rate(song)
            max_notes = effective_max_notes()
            tick_rate = recommendation.tick_rate
            profile_name = "low" if safe_var.get() else quality_var.get()
            fx = "none" if safe_var.get() else show_fx_var.get()
            safety = analyze_safety(
                song,
                tick_rate=tick_rate,
                max_notes_per_tick=max_notes,
                quality=profile_name,
                mode="command_stage",
                sound_engine=sound_engine_var.get(),
                stage_profile=stage_profile_var.get(),
                show_fx=fx,
                piano_roll=piano_roll_var.get(),
            )
            lines = format_midi_summary_lines(song, recommendation, tick_rate, max_notes)
            warnings = warning_lines(song, tick_rate, max_notes)
            text = "\n".join(lines)
            text += "\n\n安全评估:\n" + format_safety_report(safety)
            if warnings:
                text += "\n\n风险提示:\n" + "\n".join(f"  - {w}" for w in warnings)
            text += "\n\n推荐游戏内命令:\n"
            ns = current_show_id()
            text += f"/reload\n/function {ns}:setup\n"
            if tick_rate != 20:
                text += f"/tick rate {tick_rate}\n"
            text += f"/function {ns}:play"
            if tick_rate != 20:
                text += "\n# 演出结束后：/tick rate 20"
            replace_summary(text)
        except (OSError, MidiParseError, ValueError) as exc:
            replace_summary(f"无法读取 MIDI：{exc}")
            if not silent:
                messagebox.showerror("midi2mc", f"无法读取 MIDI：{exc}")

    def make_project_dict() -> dict[str, Any]:
        max_notes_text = max_notes_var.get().strip()
        try:
            max_notes: int | None = int(max_notes_text) if max_notes_text else None
        except ValueError:
            max_notes = None
        try:
            gain = float(gain_var.get().strip() or "1.0")
        except ValueError:
            gain = 1.0
        try:
            fx_intensity = max(0.0, min(3.0, float(fx_intensity_var.get().strip() or "1.0")))
        except ValueError:
            fx_intensity = 1.0
        try:
            module_hold_ticks = int(module_hold_var.get().strip() or "0")
        except ValueError:
            module_hold_ticks = 0
        try:
            long_beats = float(soma_long_var.get().strip() or "1.0")
        except ValueError:
            long_beats = 1.0
        return {
            "format": PROJECT_FORMAT,
            "midi": midi_var.get().strip(),
            "show_id": show_id_var.get().strip() or None,
            "base_preset": preset_var.get(),
            "preset": None,
            "out": out_var.get().strip() or "output",
            "minecraft_version": "1.21.11",
            "mode": "command_stage",
            "sound_engine": sound_engine_var.get(),
            "stage_profile": stage_profile_var.get(),
            "stage_layout": stage_layout_var.get(),
            "stage_template": stage_template_var.get(),
            "module_hold_ticks": max(0, module_hold_ticks),
            "quality": quality_var.get(),
            "safe_mode": bool(safe_var.get()),
            "tick_rate": "auto",
            "gain": gain,
            "max_notes_per_tick": max_notes,
            "stage_particles": bool(stage_particles_var.get()),
            "piano_roll": bool(piano_roll_var.get()),
            "show_fx": show_fx_var.get(),
            "fx_profile": fx_profile_var.get(),
            "fx_intensity": fx_intensity,
            "fx_layers": fx_layers_var.get().strip() or "all",
            "zip_output": bool(zip_var.get()),
            "report_html": bool(report_var.get()),
            "soma": {
                "long_note_beats": long_beats,
                "namespace": "",
                "reference_note": 60,
                "drum_kit": soma_drum_var.get(),
                "map": None,
            },
            "minecraft": {
                "legacy_1_20": bool(legacy_var.get()),
                "pack_format": None,
            },
        }

    def save_project() -> None:
        if not midi_var.get().strip():
            messagebox.showwarning("midi2mc", "保存项目配置前请先选择 MIDI 文件。")
            return
        initial = f"{current_show_id()}.m2mc.json"
        path = filedialog.asksaveasfilename(
            title="保存 .m2mc.json 项目配置",
            initialfile=initial,
            defaultextension=".m2mc.json",
            filetypes=[("midi2mc project", "*.m2mc.json"), ("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            data = make_project_dict()
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
            project_var.set(path)
            append(f"[GUI] 项目配置已保存：{path}\n", "ok")
            messagebox.showinfo("midi2mc", "项目配置已保存。")
        except Exception as exc:
            messagebox.showerror("midi2mc", f"保存失败：{exc}")

    def build_command() -> list[str] | None:
        midi = midi_var.get().strip()
        if not midi:
            messagebox.showwarning("midi2mc", "请先选择一个 .mid/.midi 文件。")
            return None
        out = out_var.get().strip() or "output"
        cmd = [sys.executable, "-m", "midi2mc", midi, "--out", out, "--mode", "command_stage"]
        show_id = show_id_var.get().strip()
        if show_id:
            cmd.extend(["--show-id", show_id])
        cmd.extend(["--sound-engine", sound_engine_var.get()])
        cmd.extend(["--stage-profile", stage_profile_var.get()])
        cmd.extend(["--stage-layout", stage_layout_var.get()])
        cmd.extend(["--stage-template", stage_template_var.get()])
        cmd.extend(["--quality", quality_var.get()])
        cmd.extend(["--show-fx", show_fx_var.get()])
        cmd.extend(["--fx-profile", fx_profile_var.get()])
        cmd.extend(["--fx-intensity", fx_intensity_var.get().strip() or "1.0"])
        cmd.extend(["--fx-layers", fx_layers_var.get().strip() or "all"])
        hold_raw = module_hold_var.get().strip()
        if hold_raw:
            try:
                int(hold_raw)
            except ValueError:
                messagebox.showwarning("midi2mc", "Pulse 模块保持 tick 必须是整数，或留空。")
                return None
            cmd.extend(["--module-hold-ticks", hold_raw])
        cmd.extend(["--gain", gain_var.get().strip() or "1.0"])
        cmd.extend(["--soma-long-note-beats", soma_long_var.get().strip() or "1.0"])
        cmd.extend(["--soma-drum-kit", soma_drum_var.get()])
        raw_max = max_notes_var.get().strip()
        if raw_max:
            try:
                int(raw_max)
            except ValueError:
                messagebox.showwarning("midi2mc", "最大同 tick 复音数必须是整数，或留空。")
                return None
            cmd.extend(["--max-notes-per-tick", raw_max])
        if safe_var.get():
            cmd.append("--safe-mode")
        if not stage_particles_var.get():
            cmd.append("--no-stage-particles")
        if piano_roll_var.get():
            cmd.append("--piano-roll")
        else:
            cmd.append("--no-piano-roll")
        if not report_var.get():
            cmd.append("--no-report")
        if not zip_var.get():
            cmd.append("--no-zip")
        if legacy_var.get():
            cmd.append("--legacy-1-20")
        return cmd

    def guess_report_path() -> Path:
        return Path(out_var.get().strip() or "output") / current_show_id() / "report.html"

    def worker_run(cmd: list[str]) -> None:
        try:
            repo_root = Path(__file__).resolve().parents[1]
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            result = subprocess.run(
                cmd,
                cwd=str(repo_root),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                env=env,
            )
            if result.stdout:
                q.put((result.stdout, "normal"))
            if result.stderr:
                q.put((result.stderr, "error"))
            q.put((f"\n[midi2mc GUI] 生成结束，退出码：{result.returncode}\n", "ok" if result.returncode == 0 else "error"))
            q.put(("__DONE_OK__" if result.returncode == 0 else "__DONE_ERR__", "control"))
        except Exception as exc:
            q.put((f"\n[midi2mc GUI] 运行失败：{exc}\n", "error"))
            q.put(("__DONE_ERR__", "control"))

    def poll_queue() -> None:
        nonlocal worker
        try:
            while True:
                text, tag = q.get_nowait()
                if tag == "control":
                    set_running(False)
                    worker = None
                    if text == "__DONE_OK__":
                        report_path = guess_report_path()
                        last_report_path.set(str(report_path) if report_path.exists() else "")
                        messagebox.showinfo("midi2mc", "生成完成！可以打开输出目录或 report.html。")
                    elif text == "__DONE_ERR__":
                        messagebox.showerror("midi2mc", "生成失败，请查看下方日志。")
                else:
                    append(text, tag)
        except queue.Empty:
            pass
        root.after(100, poll_queue)

    def generate() -> None:
        nonlocal worker
        if worker is not None:
            return
        cmd = build_command()
        if not cmd:
            return
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.configure(state="disabled")
        append("[midi2mc GUI] 将执行：\n", "ok")
        append(" ".join(cmd) + "\n\n", "normal")
        set_running(True)
        worker = threading.Thread(target=worker_run, args=(cmd,), daemon=True)
        worker.start()

    def open_path(path: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("midi2mc", f"无法打开：{exc}")

    def open_output_dir() -> None:
        target = Path(out_var.get().strip() or "output")
        target.mkdir(parents=True, exist_ok=True)
        open_path(target)

    def open_report() -> None:
        path = Path(last_report_path.get().strip() or guess_report_path())
        if not path.exists():
            messagebox.showwarning("midi2mc", "还没有找到 report.html。请先生成，且确认没有勾选“不生成 report.html”。")
            return
        webbrowser.open(path.resolve().as_uri())

    main = ttk.Frame(root, padding=14)
    main.pack(fill="both", expand=True)
    main.columnconfigure(1, weight=1)
    main.columnconfigure(3, weight=1)

    ttk.Label(main, text=f"midi2mc v{__version__} GUI", font=("TkDefaultFont", 16, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
    ttk.Label(main, text="选择 MIDI，套用 preset，按需微调配置；也可以保存/读取 .m2mc.json 项目。", foreground="#555").grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 10))

    row = 2
    ttk.Label(main, text="MIDI 文件").grid(row=row, column=0, sticky="w", pady=4)
    midi_entry = ttk.Entry(main, textvariable=midi_var)
    midi_entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
    midi_btn = ttk.Button(main, text="浏览…", command=browse_midi)
    midi_btn.grid(row=row, column=3, padx=(8, 0), pady=4, sticky="ew")

    row += 1
    ttk.Label(main, text="Project 文件").grid(row=row, column=0, sticky="w", pady=4)
    project_entry = ttk.Entry(main, textvariable=project_var)
    project_entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
    project_btn = ttk.Button(main, text="读取…", command=browse_project)
    project_btn.grid(row=row, column=3, padx=(8, 0), pady=4, sticky="ew")

    row += 1
    ttk.Label(main, text="输出目录").grid(row=row, column=0, sticky="w", pady=4)
    out_entry = ttk.Entry(main, textvariable=out_var)
    out_entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
    out_btn = ttk.Button(main, text="浏览…", command=browse_out)
    out_btn.grid(row=row, column=3, padx=(8, 0), pady=4, sticky="ew")

    row += 1
    ttk.Label(main, text="Show ID").grid(row=row, column=0, sticky="w", pady=4)
    show_entry = ttk.Entry(main, textvariable=show_id_var)
    show_entry.grid(row=row, column=1, sticky="ew", pady=4)
    ttk.Label(main, text="留空则使用 MIDI 文件名", foreground="#666").grid(row=row, column=2, columnspan=2, sticky="w", padx=(8, 0), pady=4)

    row += 1
    ttk.Label(main, text="Preset").grid(row=row, column=0, sticky="w", pady=4)
    preset_combo = ttk.Combobox(main, textvariable=preset_var, values=preset_names, state="readonly")
    preset_combo.grid(row=row, column=1, sticky="ew", pady=4)
    preset_label = ttk.Label(main, text="", foreground="#666", wraplength=420)
    preset_label.grid(row=row, column=2, columnspan=2, sticky="w", padx=(8, 0), pady=4)

    row += 1
    adv = ttk.LabelFrame(main, text="配置编辑器", padding=8)
    adv.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(8, 8))
    for c in range(6):
        adv.columnconfigure(c, weight=1)

    ttk.Label(adv, text="音源").grid(row=0, column=0, sticky="w")
    sound_combo = ttk.Combobox(adv, textvariable=sound_engine_var, values=SOUND_ENGINE_CHOICES, state="readonly", width=12)
    sound_combo.grid(row=0, column=1, sticky="ew", padx=(4, 10))
    ttk.Label(adv, text="舞台").grid(row=0, column=2, sticky="w")
    stage_combo = ttk.Combobox(adv, textvariable=stage_profile_var, values=STAGE_PROFILE_CHOICES, state="readonly", width=16)
    stage_combo.grid(row=0, column=3, sticky="ew", padx=(4, 10))
    ttk.Label(adv, text="布局").grid(row=0, column=4, sticky="w")
    layout_combo = ttk.Combobox(adv, textvariable=stage_layout_var, values=STAGE_LAYOUT_CHOICES, state="readonly", width=10)
    layout_combo.grid(row=0, column=5, sticky="ew", padx=(4, 0))

    ttk.Label(adv, text="舞台模板").grid(row=1, column=0, sticky="w", pady=(8, 0))
    template_combo = ttk.Combobox(adv, textvariable=stage_template_var, values=STAGE_TEMPLATE_CHOICES, state="readonly", width=12)
    template_combo.grid(row=1, column=1, sticky="ew", padx=(4, 10), pady=(8, 0))
    ttk.Label(adv, text="质量").grid(row=1, column=2, sticky="w", pady=(8, 0))
    quality_combo = ttk.Combobox(adv, textvariable=quality_var, values=quality_choices(), state="readonly", width=12)
    quality_combo.grid(row=1, column=3, sticky="ew", padx=(4, 10), pady=(8, 0))
    ttk.Label(adv, text="Show FX").grid(row=1, column=4, sticky="w", pady=(8, 0))
    fx_combo = ttk.Combobox(adv, textvariable=show_fx_var, values=SHOW_FX_CHOICES, state="readonly", width=16)
    fx_combo.grid(row=1, column=5, sticky="ew", padx=(4, 0), pady=(8, 0))

    ttk.Label(adv, text="最大复音").grid(row=2, column=0, sticky="w", pady=(8, 0))
    max_entry = ttk.Entry(adv, textvariable=max_notes_var, width=10)
    max_entry.grid(row=2, column=1, sticky="ew", padx=(4, 10), pady=(8, 0))

    ttk.Label(adv, text="增益").grid(row=2, column=2, sticky="w", pady=(8, 0))
    gain_entry = ttk.Entry(adv, textvariable=gain_var, width=12)
    gain_entry.grid(row=2, column=3, sticky="ew", padx=(4, 10), pady=(8, 0))
    ttk.Label(adv, text="Soma 长音拍数").grid(row=2, column=4, sticky="w", pady=(8, 0))
    soma_long_entry = ttk.Entry(adv, textvariable=soma_long_var, width=12)
    soma_long_entry.grid(row=2, column=5, sticky="ew", padx=(4, 0), pady=(8, 0))
    ttk.Label(adv, text="Soma 鼓组").grid(row=3, column=0, sticky="w", pady=(8, 0))
    soma_drum_combo = ttk.Combobox(adv, textvariable=soma_drum_var, values=SOMA_DRUM_CHOICES, state="readonly", width=12)
    soma_drum_combo.grid(row=3, column=1, sticky="ew", padx=(4, 10), pady=(8, 0))
    ttk.Label(adv, text="FX 风格").grid(row=3, column=2, sticky="w", pady=(8, 0))
    fx_profile_combo = ttk.Combobox(adv, textvariable=fx_profile_var, values=FX_PROFILE_CHOICES, state="readonly", width=12)
    fx_profile_combo.grid(row=3, column=3, sticky="ew", padx=(4, 10), pady=(8, 0))
    ttk.Label(adv, text="FX 强度").grid(row=3, column=4, sticky="w", pady=(8, 0))
    fx_intensity_entry = ttk.Entry(adv, textvariable=fx_intensity_var, width=12)
    fx_intensity_entry.grid(row=3, column=5, sticky="ew", padx=(4, 0), pady=(8, 0))

    ttk.Label(adv, text="FX Layers").grid(row=4, column=0, sticky="w", pady=(8, 0))
    fx_layers_entry = ttk.Entry(adv, textvariable=fx_layers_var, width=24)
    fx_layers_entry.grid(row=4, column=1, columnspan=2, sticky="ew", padx=(4, 10), pady=(8, 0))
    ttk.Label(adv, text="all 或 note,drum,bass,chord,beat,lead,fireworks,finale", foreground="#666").grid(row=4, column=3, columnspan=3, sticky="w", pady=(8, 0))

    ttk.Label(adv, text="Pulse 保持 tick").grid(row=5, column=0, sticky="w", pady=(8, 0))
    module_hold_entry = ttk.Entry(adv, textvariable=module_hold_var, width=10)
    module_hold_entry.grid(row=5, column=1, sticky="ew", padx=(4, 10), pady=(8, 0))
    ttk.Label(adv, text="留空/0=自动，建议 2-12", foreground="#666").grid(row=5, column=2, columnspan=4, sticky="w", pady=(8, 0))

    safe_check = ttk.Checkbutton(adv, text="Safe Mode", variable=safe_var)
    safe_check.grid(row=6, column=0, sticky="w", pady=(8, 0))
    particles_check = ttk.Checkbutton(adv, text="舞台粒子", variable=stage_particles_var)
    particles_check.grid(row=6, column=1, sticky="w", pady=(8, 0))
    piano_check = ttk.Checkbutton(adv, text="Piano Roll", variable=piano_roll_var)
    piano_check.grid(row=6, column=2, sticky="w", pady=(8, 0))
    report_check = ttk.Checkbutton(adv, text="生成 report.html", variable=report_var)
    report_check.grid(row=6, column=3, sticky="w", pady=(8, 0))
    zip_check = ttk.Checkbutton(adv, text="打包 zip", variable=zip_var)
    zip_check.grid(row=6, column=4, sticky="w", pady=(8, 0))
    legacy_check = ttk.Checkbutton(adv, text="旧版 1.20 结构", variable=legacy_var)
    legacy_check.grid(row=6, column=5, sticky="w", pady=(8, 0))

    row += 1
    button_frame = ttk.Frame(main)
    button_frame.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(2, 8))
    analyze_btn = ttk.Button(button_frame, text="分析 MIDI", command=lambda: analyze_midi(silent=False))
    analyze_btn.pack(side="left")
    generate_btn = ttk.Button(button_frame, text="生成数据包", command=generate)
    generate_btn.pack(side="left", padx=(8, 0))
    save_project_btn = ttk.Button(button_frame, text="保存项目配置", command=save_project)
    save_project_btn.pack(side="left", padx=(8, 0))
    open_btn = ttk.Button(button_frame, text="打开输出目录", command=open_output_dir)
    open_btn.pack(side="left", padx=(8, 0))
    report_btn = ttk.Button(button_frame, text="打开 report.html", command=open_report)
    report_btn.pack(side="left", padx=(8, 0))

    row += 1
    panes = ttk.Panedwindow(main, orient="vertical")
    panes.grid(row=row, column=0, columnspan=4, sticky="nsew")
    main.rowconfigure(row, weight=1)

    summary_frame = ttk.LabelFrame(panes, text="MIDI 摘要 / 风险 / 推荐命令", padding=6)
    summary_box = tk.Text(summary_frame, height=10, wrap="word", state="disabled")
    summary_box.pack(fill="both", expand=True)
    panes.add(summary_frame, weight=1)

    log_frame = ttk.LabelFrame(panes, text="生成日志", padding=6)
    log = tk.Text(log_frame, height=13, wrap="word", state="disabled")
    log.pack(side="left", fill="both", expand=True)
    scroll = ttk.Scrollbar(log_frame, orient="vertical", command=log.yview)
    scroll.pack(side="right", fill="y")
    log.configure(yscrollcommand=scroll.set)
    panes.add(log_frame, weight=1)
    log.tag_configure("error", foreground="#b00020")
    log.tag_configure("ok", foreground="#176b2c")

    inputs = [
        midi_entry, midi_btn, project_entry, project_btn, out_entry, out_btn, show_entry,
        preset_combo, sound_combo, stage_combo, layout_combo, template_combo, quality_combo, fx_combo, fx_profile_combo, fx_intensity_entry, fx_layers_entry, module_hold_entry,
        max_entry, gain_entry, soma_long_entry, soma_drum_combo, safe_check, particles_check,
        piano_check, report_check, zip_check, legacy_check, open_btn, report_btn,
    ]

    preset_var.trace_add("write", apply_preset_to_form)
    apply_preset_to_form()
    root.after(100, poll_queue)
    root.mainloop()
    return 0
