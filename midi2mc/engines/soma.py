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

# Soma v20 spreadsheet contains 120 melodic programs. GM programs 121-128
# (zero-based 120..127) are sound-effect programs, so v0.12 maps them to the
# closest available Soma v20 effect/instrument instead of falling all the way
# back to piano.
SOMA_V20_MISSING_PROGRAM_FALLBACKS: dict[int, int] = {
    120: 24,   # Guitar Fret Noise -> Acoustic Guitar (nylon)
    121: 76,   # Breath Noise -> Bottle Blow
    122: 96,   # Seashore -> FX 1 (rain)
    123: 78,   # Bird Tweet -> Whistle
    124: 103,  # Telephone Ring -> FX 8 (sci-fi)
    125: 103,  # Helicopter -> FX 8 (sci-fi)
    126: 118,  # Applause -> Synth Drum
    127: 119,  # Gunshot -> Reverse Cymbal
}

DRUM_KIT_CHOICES = {"auto", "normal", "electronic", "percussion"}


class SomaSoundEngine(SoundEngine):
    """Soma resource-pack sound engine.

    v1.1.0 keeps the Soma v20 naming rule from the user's spreadsheet:
    normal notes use ``<instrument_id>.<midi_note>``; sustained notes use
    ``<instrument_id>c.<midi_note>`` when a continuous variant exists and are
    stopped with ``stopsound`` at note-off time.

    Mapping enhancements in v1.1.0:
    - GM sound-effect programs 121-128 fall back to near Soma v20 substitutes;
    - drum notes can use Soma v20 drum variants 0 / 0e / 0p via --soma-drum-kit;
    - resolved category/class/fallback metadata is written into manifest reports.
    """

    name = "soma"

    def __init__(
        self,
        namespace: str = "",
        gain: float = 1.0,
        map_path: Path | None = None,
        reference_note: int = 60,
        long_note_beats: float = 1.0,
        drum_kit: str = "auto",
        ticks_per_quarter: int = 480,
    ) -> None:
        # Soma v20 sound events are written without a namespace, e.g. 2.66, not soma:2.66.
        # Keep this attribute only for backward-compatible manifests/CLI plumbing.
        self.namespace = (namespace or "").strip()
        self.gain = gain
        # Kept for compatibility with old simple maps; the v20 map does not need pitch shifting.
        self.reference_note = reference_note
        self.long_note_beats = max(0.0, float(long_note_beats))
        self.drum_kit = (drum_kit or "auto").strip().lower()
        if self.drum_kit not in DRUM_KIT_CHOICES:
            self.drum_kit = "auto"
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
            code = self._drum_code_for(note.note, drum)
            resolved_note, was_clamped = _clamp_note_with_flag(note.note, drum.get("note_min"), drum.get("note_max"))
            path = f"{code}.{resolved_note}"
            return ResolvedSound(
                sound_id=path,
                volume=volume_for(note.velocity, self.gain),
                pitch=1.0,
                instrument_key=drum_instrument(note.note),
                sound_label=_drum_label(note.note, code),
                original_note=note.note,
                resolved_note=resolved_note,
                note_was_clamped=was_clamped,
                fallback_reason=fallback_reason,
                drum_variant=code,
                mapping_category="DRUM 鼓组",
                soma_class="drum",
            )

        programs = self.v20_map.get("programs", {})
        raw_program = int(note.program)
        resolved_program, program_fallback = self._resolve_program(raw_program, programs)
        info = programs.get(str(resolved_program)) or programs.get("0") or {}
        normal = str(info.get("normal") or "1")
        continuous = info.get("continuous")
        resolved_note, was_clamped = _clamp_note_with_flag(note.note, info.get("note_min"), info.get("note_max"))
        requested_continuous = bool(continuous) and self._is_long_note(note)
        use_continuous = requested_continuous and allow_continuous
        code = str(continuous if use_continuous else normal)
        path = f"{code}.{resolved_note}"
        reason = fallback_reason
        if program_fallback is not None and reason is None:
            reason = "missing_program_nearest_soma_fallback"
        return ResolvedSound(
            sound_id=path,
            volume=volume_for(note.velocity, self.gain),
            pitch=1.0,
            instrument_key=_instrument_key_for_soma_info(note, info),
            sound_label=str(info.get("label") or info.get("name") or f"Soma program {resolved_program + 1}"),
            stop_sound_id=path if use_continuous else None,
            used_continuous=use_continuous,
            requested_continuous=requested_continuous,
            original_note=note.note,
            resolved_note=resolved_note,
            note_was_clamped=was_clamped,
            fallback_reason=reason,
            fallback_program=program_fallback,
            mapping_category=str(info.get("category") or ""),
            soma_class=str(info.get("class") or ""),
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

    def _resolve_program(self, program: int, programs: dict[str, Any]) -> tuple[int, int | None]:
        if str(program) in programs:
            return program, None
        fallback = SOMA_V20_MISSING_PROGRAM_FALLBACKS.get(program)
        if fallback is not None and str(fallback) in programs:
            return fallback, fallback
        # If a custom map is missing a program, fall back to the closest lower
        # available program in the same 8-program GM family; otherwise piano.
        family_start = max(0, (program // 8) * 8)
        family = [p for p in range(family_start, family_start + 8) if str(p) in programs]
        if family:
            nearest = min(family, key=lambda p: abs(p - program))
            return nearest, nearest
        available = [int(key) for key in programs if str(key).isdigit()]
        if available:
            nearest = min(available, key=lambda p: abs(p - program))
            return nearest, nearest
        return 0, 0

    def _drum_code_for(self, drum_note: int, drum_map: dict[str, Any]) -> str:
        normal = str(drum_map.get("normal") or "0")
        variants = {str(v) for v in drum_map.get("variants", [])}
        if self.drum_kit == "normal":
            return normal
        if self.drum_kit == "electronic":
            return "0e" if "0e" in variants else normal
        if self.drum_kit == "percussion":
            return "0p" if "0p" in variants else normal
        # auto: kick/toms keep normal punch; snare/clap use 0e; hats/cymbals and
        # small percussion use 0p when available. Users can force normal if they
        # prefer the v0.11 behavior.
        if drum_note in {35, 36, 41, 43, 45, 47, 48, 50}:
            return normal
        if drum_note in {38, 39, 40, 56} and "0e" in variants:
            return "0e"
        if "0p" in variants:
            return "0p"
        return normal

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
            "v1.1.0 使用 Soma v20 表格规则：短音 <编号>.<音高>，长音 <编号>c.<音高>，不添加 soma: 命名空间。",
            "长音会在 MIDI note off 时间自动生成 stopsound。",
            "v1.1.0 保留稳定性保护：重叠长音会自动降级为短音，避免 stopsound 提前切断后续长音。",
            "v1.1.0 保留音域 fallback：超出表格音域的音会夹取到最近可用音，并写入 manifest 统计。",
            "v1.1.0 增强 Soma 映射：GM 121-128 音效类 program 会映射到最接近的 Soma v20 可用音色；鼓组可使用 0/0e/0p 变体。",
            "v1.1.0 支持质量档与舞台粒子开关；Soma 舞台长音灯会从下一 tick 亮起，连续长音交接时会自然闪断。",
            "Soma sound category: voice",
            f"Soma map mode: {self.map_mode}",
            f"Soma long note threshold: {self.long_note_beats:g} beat(s)",
            f"Soma drum kit policy: {self.drum_kit}",
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
            "drum_kit": self.drum_kit,
            "ticks_per_quarter": self.ticks_per_quarter,
            "program_fallbacks": {str(k + 1): v + 1 for k, v in SOMA_V20_MISSING_PROGRAM_FALLBACKS.items()},
            "stability": {
                "long_note_overlap_policy": "downgrade_overlapping_continuous_notes_to_short",
                "note_range_fallback": "clamp_to_nearest_available_note",
                "missing_program_fallback": "map_GM_121_128_to_nearest_Soma_v20_substitute_then_nearest_family",
            },
        }


def _instrument_key_for_soma_info(note: NoteEvent, info: dict[str, Any]) -> str:
    if note.is_drum:
        return drum_instrument(note.note)
    label = str(info.get("label") or info.get("name") or "").lower()
    category = str(info.get("category") or "").lower()
    program = note.program
    if "bass" in category or "bass" in label or 32 <= program <= 39:
        return "bass"
    if "guitar" in category or "guitar" in label or 24 <= program <= 31:
        return "guitar"
    if "string" in category or "violin" in label or "cello" in label:
        return "harp"
    if "brass" in category or "reed" in category or "pipe" in category or "wind" in label or 56 <= program <= 79:
        return "flute"
    if "synth" in category or 80 <= program <= 103:
        return "bit"
    if "percussive" in category or "chromatic" in category:
        return "bell"
    if "ethnic" in category:
        return "banjo"
    return instrument_key_for(note)


def _drum_label(drum_note: int, code: str) -> str:
    family = drum_instrument(drum_note)
    suffix = {"0": "normal", "0e": "electronic", "0p": "percussion"}.get(code, code)
    return f"Soma Drum {family} ({suffix})"


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
