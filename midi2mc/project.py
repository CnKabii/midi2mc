from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any

PROJECT_FORMAT = "midi2mc.project.v1"


def _get(data: dict[str, Any], key: str, default: Any = None) -> Any:
    return data[key] if key in data else default


def _as_path(value: Any, base_dir: Path, *, keep_none: bool = True) -> str | None:
    if value is None:
        return None if keep_none else ""
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return str(path)


def _nested(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def load_project_namespace(project_path: Path, cli_args: Namespace | None = None) -> Namespace:
    """Load a .m2mc.json project into the same Namespace used by CLI export.

    Paths inside the project file are resolved relative to the project file.
    The project file is intentionally simple and stable; GUI/Web frontends can
    generate the same JSON later without depending on Python-specific details.
    """
    path = project_path.expanduser()
    if not path.exists():
        raise FileNotFoundError(f"project config not found: {path}")
    base_dir = path.resolve().parent
    try:
        data = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in project config: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("project config must be a JSON object")

    soma = _nested(data, "soma")
    minecraft = _nested(data, "minecraft")

    midi = _get(data, "midi")
    if cli_args is not None and getattr(cli_args, "midi", None):
        midi = cli_args.midi
    if not midi:
        raise ValueError("project config needs a 'midi' path")

    show_id = _get(data, "show_id", None)
    if cli_args is not None and getattr(cli_args, "show_id", None):
        show_id = cli_args.show_id

    out = _get(data, "out", "output")
    if cli_args is not None and getattr(cli_args, "out", "output") != "output":
        out = cli_args.out

    # Support both a friendly positive flag and the existing CLI negative flag.
    stage_particles = bool(_get(data, "stage_particles", True))
    no_stage_particles = bool(_get(data, "no_stage_particles", not stage_particles))
    zip_output = bool(_get(data, "zip_output", True))

    soma_map_raw = _get(soma, "map", _get(data, "soma_map", None))
    namespace = Namespace(
        midi=_as_path(midi, base_dir, keep_none=False),
        out=_as_path(out, base_dir, keep_none=False),
        show_id=show_id,
        preset=_get(data, "preset", None),
        mode=_get(data, "mode", "command_stage"),
        sound_engine=_get(data, "sound_engine", "vanilla"),
        stage_profile=_get(data, "stage_profile", "auto"),
        stage_layout=_get(data, "stage_layout", "auto"),
        soma_namespace=_get(soma, "namespace", _get(data, "soma_namespace", "")),
        soma_map=_as_path(soma_map_raw, base_dir) if soma_map_raw else None,
        soma_reference_note=int(_get(soma, "reference_note", _get(data, "soma_reference_note", 60))),
        soma_long_note_beats=float(_get(soma, "long_note_beats", _get(data, "soma_long_note_beats", 1.0))),
        soma_drum_kit=str(_get(soma, "drum_kit", _get(data, "soma_drum_kit", "auto"))),
        tick_rate=_get(data, "tick_rate", "auto"),
        pack_format=_get(minecraft, "pack_format", _get(data, "pack_format", None)),
        quality=_get(data, "quality", "medium"),
        safe_mode=bool(_get(data, "safe_mode", False)),
        no_stage_particles=no_stage_particles,
        piano_roll=_get(data, "piano_roll", None),
        show_fx=_get(data, "show_fx", "auto"),
        gain=float(_get(data, "gain", 1.0)),
        max_notes_per_tick=_get(data, "max_notes_per_tick", None),
        no_zip=not zip_output,
        no_report=not bool(_get(data, "report_html", True)),
        legacy_1_20=bool(_get(minecraft, "legacy_1_20", _get(data, "legacy_1_20", False))),
        project=str(path),
    )

    # A few explicit CLI flags may override project values. We avoid overriding
    # quality/show_fx/etc. with argparse defaults because argparse cannot tell
    # whether the user typed them in this simple v0.10 implementation.
    if cli_args is not None:
        if getattr(cli_args, "pack_format", None) is not None:
            namespace.pack_format = cli_args.pack_format
        if getattr(cli_args, "no_zip", False):
            namespace.no_zip = True
        if getattr(cli_args, "legacy_1_20", False):
            namespace.legacy_1_20 = True
        if getattr(cli_args, "piano_roll", None) is not None:
            namespace.piano_roll = cli_args.piano_roll
    return namespace


def default_project_template() -> dict[str, Any]:
    return {
        "format": PROJECT_FORMAT,
        "midi": "../demo_scale.mid",
        "show_id": "demo_soma_concert",
        "preset": "soma_concert",
        "out": "../../output",
        "minecraft_version": "1.21.11",
        "mode": "command_stage",
        "sound_engine": "soma",
        "stage_profile": "soma_concert",
        "stage_layout": "auto",
        "quality": "medium",
        "safe_mode": False,
        "tick_rate": "auto",
        "gain": 1.0,
        "max_notes_per_tick": None,
        "stage_particles": True,
        "piano_roll": False,
        "show_fx": "lightshow",
        "zip_output": True,
        "report_html": True,
        "soma": {
            "long_note_beats": 1.0,
            "namespace": "",
            "reference_note": 60,
            "drum_kit": "auto",
            "map": None,
        },
        "minecraft": {
            "legacy_1_20": False,
            "pack_format": None,
        },
    }


def write_project_template(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(default_project_template(), ensure_ascii=False, indent=2), "utf-8")
    return path
