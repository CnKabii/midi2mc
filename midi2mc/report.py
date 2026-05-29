from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .model import CompiledNote, MidiSong
from .recommend import recommend_tick_rate
from .summary import build_song_stats, warning_lines
from .safety import analyze_safety
from .stages.show_fx import resolve_show_fx


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _table(rows: list[tuple[str, Any]]) -> str:
    return "\n".join(
        f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in rows
    )


def _top_items(items: Any, key_name: str = "name", value_name: str = "notes") -> str:
    if not items:
        return "<p class='muted'>No data.</p>"
    rows = []
    for item in items[:12]:
        if isinstance(item, dict):
            name = item.get(key_name, item.get("name", "?"))
            value = item.get(value_name, item.get("notes", item.get("count", "")))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            name, value = item[0], item[1]
        else:
            name, value = item, ""
        rows.append((name, value))
    return "<table>" + _table(rows) + "</table>"


def write_html_report(
    root: Path,
    *,
    namespace: str,
    options: Any,
    song: MidiSong,
    total_ticks: int,
    compiled: list[CompiledNote],
    manifest: dict[str, Any],
) -> Path:
    """Write a small standalone HTML report for users and issue reports."""
    recommendation = recommend_tick_rate(song)
    stats = build_song_stats(song, tick_rate=options.tick_rate, max_notes_per_tick=options.max_notes_per_tick)
    safety = analyze_safety(
        song,
        tick_rate=options.tick_rate,
        max_notes_per_tick=options.max_notes_per_tick,
        quality=options.quality,
        mode=options.mode,
        sound_engine=options.sound_engine,
        stage_profile=manifest.get("stage_profile", options.stage_profile),
        show_fx=manifest.get("show_fx", options.show_fx),
        piano_roll=bool(manifest.get("piano_roll", False)),
    )
    arrangement = manifest.get("arrangement_report", {})
    soma = manifest.get("soma_report", {})
    warnings = warning_lines(song, options.tick_rate, options.max_notes_per_tick)
    used_preset = manifest.get("preset") or "none"
    style = """
    body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.5;margin:28px;max-width:1100px;color:#1d1d1f;background:#fafafa}
    h1{font-size:28px;margin-bottom:4px} h2{margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:6px}
    .muted{color:#666}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin:18px 0}
    .card{background:white;border:1px solid #e5e5e5;border-radius:12px;padding:14px;box-shadow:0 2px 8px #00000008}
    table{border-collapse:collapse;width:100%;background:white;border:1px solid #e5e5e5;border-radius:10px;overflow:hidden;margin:10px 0}
    th,td{padding:8px 10px;border-bottom:1px solid #eee;text-align:left;vertical-align:top} th{width:260px;background:#f5f5f5}
    code{background:#eee;padding:2px 5px;border-radius:5px}.risk-low{color:#147a2e}.risk-medium{color:#966400}.risk-high,.risk-critical{color:#b00020}
    pre{white-space:pre-wrap;background:#1f2328;color:#f6f8fa;padding:14px;border-radius:12px;overflow:auto}
    """
    rows = [
        ("Namespace / Show ID", namespace),
        ("Preset", used_preset),
        ("Mode", options.mode),
        ("Sound engine", options.sound_engine),
        ("Stage profile", manifest.get("stage_profile", options.stage_profile)),
        ("Stage template", manifest.get("stage_template", getattr(options, "stage_template", "pulse"))),
        ("Pulse hold ticks", manifest.get("module_hold_ticks", getattr(options, "module_hold_ticks", 0)) or "auto"),
        ("Quality", options.quality),
        ("Show FX", manifest.get("show_fx", options.show_fx)),
        ("FX Profile", manifest.get("fx_profile", getattr(options, "fx_profile", "concert"))),
        ("FX intensity", manifest.get("fx_intensity", getattr(options, "fx_intensity", 1.0))),
        ("FX layers", manifest.get("fx_layers", getattr(options, "fx_layers", "all"))),
        ("Safe Mode", options.safe_mode),
        ("Duration", f"{stats.duration_text} / {total_ticks} ticks @ {options.tick_rate} TPS"),
        ("Recommended /tick rate", recommendation.tick_rate),
    ]
    midi_rows = [
        ("MIDI format", song.format_type),
        ("PPQ", song.ticks_per_quarter),
        ("Notes parsed", song.note_count),
        ("Notes compiled", len(compiled)),
        ("Note range", stats.note_range),
        ("Tracks used", stats.used_track_count),
        ("Channels used", stats.used_channel_count),
        ("Max raw polyphony", stats.max_polyphony_raw),
        ("Dropped by cap", stats.dropped_note_count),
    ]
    safety_rows = [
        ("Risk level", safety.level),
        ("Score", safety.score),
        ("Recommended quality", safety.recommended_quality),
        ("Recommended max notes/tick", safety.recommended_max_notes_per_tick),
        ("Recommended Show FX", safety.recommended_show_fx),
        ("Recommended stage particles", safety.recommended_stage_particles),
    ]
    command_text = f"/reload\n/function {namespace}:setup\n"
    if options.tick_rate != 20:
        command_text += f"/tick rate {options.tick_rate}\n"
    command_text += f"/function {namespace}:play"
    if options.tick_rate != 20:
        command_text += "\n# after show: /tick rate 20"
    html_text = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>midi2mc report - {_esc(namespace)}</title><style>{style}</style></head>
<body>
<h1>midi2mc v3.0.0 Report</h1>
<p class="muted">Generated for <strong>{_esc(namespace)}</strong>. Attach this file or <code>midi2mc_manifest.json</code> when reporting issues.</p>
<div class="cards">
  <div class="card"><strong>Risk</strong><br><span class="risk-{_esc(safety.level)}">{_esc(safety.level)} / {safety.score}</span></div>
  <div class="card"><strong>Notes</strong><br>{song.note_count} parsed / {len(compiled)} compiled</div>
  <div class="card"><strong>Tick Rate</strong><br>{options.tick_rate} TPS, suggested <code>/tick rate {options.tick_rate}</code></div>
  <div class="card"><strong>Preset</strong><br>{_esc(used_preset)}</div>
</div>
<h2>Quick Start</h2><pre>{_esc(command_text)}</pre>
<h2>Build Settings</h2><table>{_table(rows)}</table>
<h2>MIDI Summary</h2><table>{_table(midi_rows)}</table>
<h2>Safety Report</h2><table>{_table(safety_rows)}</table>
<p><strong>Reasons:</strong></p><ul>{''.join(f'<li>{_esc(x)}</li>' for x in safety.reasons)}</ul>
<p><strong>Advice:</strong></p><ul>{''.join(f'<li>{_esc(x)}</li>' for x in safety.advice)}</ul>
<h2>Arrangement</h2>
<h3>Top tracks</h3>{_top_items(arrangement.get('track_groups'))}
<h3>Top channels</h3>{_top_items(arrangement.get('channel_groups'))}
<h3>Top instruments</h3>{_top_items(arrangement.get('instrument_groups'))}
<h2>Soma Report</h2><pre>{_esc(json.dumps(soma, ensure_ascii=False, indent=2))}</pre>
<h2>Warnings</h2><ul>{''.join(f'<li>{_esc(x)}</li>' for x in warnings) if warnings else '<li>No major warnings.</li>'}</ul>
</body></html>"""
    path = root / "report.html"
    path.write_text(html_text, "utf-8")
    return path
