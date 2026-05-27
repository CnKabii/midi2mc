from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..mapping import drum_instrument, instrument_key_for, volume_for
from ..model import NoteEvent
from .base import ResolvedSound, SoundEngine

# Old/simple fallback for user-supplied maps from v0.3.0.
DEFAULT_SIMPLE_SOMA_MAP: dict[str, str] = {
    "harp": "1.60",
    "bass": "34.48",
    "guitar": "26.60",
    "flute": "74.72",
    "bell": "15.72",
    "chime": "10.72",
    "xylophone": "14.72",
    "iron_xylophone": "14.72",
    "cow_bell": "56.60",
    "didgeridoo": "44.36",
    "bit": "81.60",
    "banjo": "106.60",
    "pling": "1.60",
    "basedrum": "0.35",
    "snare": "0.38",
    "hat": "0.42",
}

SOMA_LABELS: dict[str, str] = {
    "harp": "Soma Piano",
    "bass": "Soma Bass",
    "guitar": "Soma Guitar",
    "flute": "Soma Flute",
    "bell": "Soma Bell",
    "chime": "Soma Chime",
    "xylophone": "Soma Xylophone",
    "iron_xylophone": "Soma Xylophone",
    "cow_bell": "Soma Bell",
    "didgeridoo": "Soma Low Wind/Bass",
    "bit": "Soma Square/Synth",
    "banjo": "Soma Plucked",
    "pling": "Soma Piano",
    "basedrum": "Soma Kick",
    "snare": "Soma Snare",
    "hat": "Soma Hat",
}


class SomaSoundEngine(SoundEngine):
    """Soma resource-pack sound engine.

    v0.9.0 implements the Soma v20 naming rule from the user's spreadsheet:
    normal notes use ``<instrument_id>.<midi_note>``; sustained notes use
    ``<instrument_id>c.<midi_note>`` when a continuous variant exists and are
    stopped with ``stopsound`` at note-off time.

    Stability changes retained in v0.9.0:
    - notes outside the Soma v20 range are clamped to the nearest available note;
    - overlapping long notes with the same continuous sound are automatically
      downgraded to the short sound by the datapack compiler, avoiding accidental
      early ``stopsound`` cutoffs.
    """

    name = "soma"

    def __init__(
        self,
        namespace: str = "",
        gain: float = 1.0,
        map_path: Path | None = None,
        reference_note: int = 60,
        long_note_beats: float = 1.0,
        ticks_per_quarter: int = 480,
    ) -> None:
        # Soma v20 sound events are written without a namespace, e.g. 2.66, not soma:2.66.
        # Keep this attribute only for backward-compatible manifests/CLI plumbing.
        self.namespace = (namespace or "").strip()
        self.gain = gain
        # Kept for compatibility with old simple maps; the v20 map does not need pitch shifting.
        self.reference_note = reference_note
        self.long_note_beats = max(0.0, float(long_note_beats))
        self.ticks_per_quarter = max(1, int(ticks_per_quarter))
        self.map_path = Path(map_path) if map_path else None
        self.v20_map: dict[str, Any] | None = None
        self.simple_map = dict(DEFAULT_SIMPLE_SOMA_MAP)
        self.map_mode = "soma_v20"
        self._load_maps()

    def resolve(self, note: NoteEvent) -> ResolvedSound:
        if self.v20_map is not None:
            return self._resolve_v20(note, allow_continuous=True)
        return self._resolve_simple(note)

    def resolve_short(self, note: NoteEvent) -> ResolvedSound:
        if self.v20_map is not None:
            return self._resolve_v20(
                note,
                allow_continuous=False,
                fallback_reason="continuous_overlap_short_fallback",
            )
        return self._resolve_simple(note)

    def _resolve_v20(
        self,
        note: NoteEvent,
        allow_continuous: bool = True,
        fallback_reason: str | None = None,
    ) -> ResolvedSound:
        assert self.v20_map is not None
        if note.is_drum:
            drum = self.v20_map.get("drum", {})
            code = str(drum.get("normal") or "0")
            resolved_note, was_clamped = _clamp_note_with_flag(note.note, drum.get("note_min"), drum.get("note_max"))
            path = f"{code}.{resolved_note}"
            return ResolvedSound(
                sound_id=path,
                volume=volume_for(note.velocity, self.gain),
                pitch=1.0,
                instrument_key=drum_instrument(note.note),
                sound_label=str(drum.get("name") or "Soma Drum"),
                original_note=note.note,
                resolved_note=resolved_note,
                note_was_clamped=was_clamped,
                fallback_reason=fallback_reason,
            )

        programs = self.v20_map.get("programs", {})
        info = programs.get(str(note.program)) or programs.get("0") or {}
        normal = str(info.get("normal") or "1")
        continuous = info.get("continuous")
        resolved_note, was_clamped = _clamp_note_with_flag(note.note, info.get("note_min"), info.get("note_max"))
        requested_continuous = bool(continuous) and self._is_long_note(note)
        use_continuous = requested_continuous and allow_continuous
        code = str(continuous if use_continuous else normal)
        path = f"{code}.{resolved_note}"
        return ResolvedSound(
            sound_id=path,
            volume=volume_for(note.velocity, self.gain),
            pitch=1.0,
            instrument_key=instrument_key_for(note),
            sound_label=str(info.get("label") or info.get("name") or f"Soma program {note.program + 1}"),
            stop_sound_id=path if use_continuous else None,
            used_continuous=use_continuous,
            requested_continuous=requested_continuous,
            original_note=note.note,
            resolved_note=resolved_note,
            note_was_clamped=was_clamped,
            fallback_reason=fallback_reason,
        )

    def _resolve_simple(self, note: NoteEvent) -> ResolvedSound:
        instrument_key = drum_instrument(note.note) if note.is_drum else instrument_key_for(note)
        event_path = self.simple_map.get(instrument_key, self.simple_map.get("harp", "1.60"))
        return ResolvedSound(
            sound_id=event_path,
            volume=volume_for(note.velocity, self.gain),
            pitch=1.0,
            instrument_key=instrument_key,
            sound_label=SOMA_LABELS.get(instrument_key, f"Soma {instrument_key}"),
            original_note=note.note,
            resolved_note=note.note,
        )

    def _is_long_note(self, note: NoteEvent) -> bool:
        if self.long_note_beats <= 0:
            return False
        duration_ticks = max(0, note.end_tick - note.start_tick)
        return duration_ticks >= self.ticks_per_quarter * self.long_note_beats

    def _load_maps(self) -> None:
        if self.map_path:
            data = _load_json(self.map_path)
        else:
            data = _load_json(_default_v20_map_path())

        if isinstance(data, dict) and "programs" in data:
            self.v20_map = data
            self.map_mode = "soma_v20"
            return

        # Backward compatibility: v0.3.0 user maps were {sound_map: {harp: piano1}}.
        sound_map = data.get("sound_map") if isinstance(data, dict) else data
        if isinstance(sound_map, dict):
            self.simple_map.update(_clean_simple_map(sound_map))
            self.v20_map = None
            self.map_mode = "simple"
            return
        raise ValueError("Soma map JSON must contain either a programs object or a sound_map object")

    def readme_notes(self) -> list[str]:
        notes = [
            "当前音源: soma / Soma 资源包音源。",
            "请确认玩家已启用 Soma 资源包，否则游戏会静音或日志提示 unknown sound event。",
            "v0.9.0 使用 Soma v20 表格规则：短音 <编号>.<音高>，长音 <编号>c.<音高>，不添加 soma: 命名空间。",
            "长音会在 MIDI note off 时间自动生成 stopsound。",
            "v0.9.0 保留稳定性保护：重叠长音会自动降级为短音，避免 stopsound 提前切断后续长音。",
            "v0.9.0 保留音域 fallback：超出表格音域的音会夹取到最近可用音，并写入 manifest 统计。",
            "v0.9.0 支持质量档与舞台粒子开关；Soma 舞台长音灯会从下一 tick 亮起，连续长音交接时会自然闪断。",
            "Soma sound category: voice",
            f"Soma map mode: {self.map_mode}",
            f"Soma long note threshold: {self.long_note_beats:g} beat(s)",
        ]
        if self.map_path:
            notes.append(f"Soma map override: {self.map_path}")
        else:
            notes.append("Soma map: built-in soma_v20_map.json（来自使用说明soma资源包v20.xls）。")
        return notes

    def manifest(self) -> dict[str, object]:
        return {
            "name": self.name,
            "gain": self.gain,
            "namespace": self.namespace,
            "sound_category": "voice",
            "reference_note": self.reference_note,
            "map_path": str(self.map_path) if self.map_path else None,
            "map_mode": self.map_mode,
            "long_note_beats": self.long_note_beats,
            "ticks_per_quarter": self.ticks_per_quarter,
            "stability": {
                "long_note_overlap_policy": "downgrade_overlapping_continuous_notes_to_short",
                "note_range_fallback": "clamp_to_nearest_available_note",
            },
        }


def _default_v20_map_path() -> Path:
    return Path(__file__).resolve().parents[1] / "presets" / "soma_v20_map.json"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except OSError as exc:
        raise ValueError(f"Cannot read Soma map file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid Soma map JSON: {path}: {exc}") from exc


def _clean_simple_map(data: dict[Any, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        clean_key = key.strip().lower()
        clean_value = value.strip().lower()
        if clean_key and clean_value:
            result[clean_key] = clean_value
    return result


def _clamp_note_with_flag(note: int, raw_min: Any, raw_max: Any) -> tuple[int, bool]:
    try:
        min_note = int(raw_min) if raw_min is not None else 0
    except (TypeError, ValueError):
        min_note = 0
    try:
        max_note = int(raw_max) if raw_max is not None else 127
    except (TypeError, ValueError):
        max_note = 127
    original = int(note)
    resolved = max(min_note, min(max_note, original))
    return resolved, resolved != original
