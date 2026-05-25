import json
from pathlib import Path

from midi2mc.demo import write_demo_midi
from midi2mc.export_datapack import DatapackOptions, export_datapack
from midi2mc.midi import parse_midi


def test_demo_midi_parses_and_exports(tmp_path: Path) -> None:
    midi_path = write_demo_midi(tmp_path / "demo.mid")
    song = parse_midi(midi_path)
    assert song.note_count == 11
    assert song.duration_sec > 0

    result = export_datapack(
        song,
        DatapackOptions(show_id="Demo Song", out_dir=tmp_path, zip_output=True),
    )
    assert result.zip_path is not None
    assert result.zip_path.exists()
    assert (result.pack_dir / "pack.mcmeta").exists()
    assert (result.pack_dir / "data" / result.namespace / "function" / "play.mcfunction").exists()
    assert (result.pack_dir / "data" / "minecraft" / "tags" / "function" / "tick.json").exists()

    mcmeta = json.loads((result.pack_dir / "pack.mcmeta").read_text("utf-8"))
    assert mcmeta["pack"]["min_format"] == [94, 1]
    assert mcmeta["pack"]["max_format"] == 94


def test_command_stage_note_particles_are_valid_count_zero(tmp_path: Path) -> None:
    midi_path = write_demo_midi(tmp_path / "demo.mid")
    song = parse_midi(midi_path)
    result = export_datapack(
        song,
        DatapackOptions(show_id="Particle Fix", out_dir=tmp_path, zip_output=False),
    )

    event_files = sorted((result.pack_dir / "data" / result.namespace / "function" / "events").glob("*.mcfunction"))
    assert event_files
    particle_lines = [
        line
        for path in event_files
        for line in path.read_text("utf-8").splitlines()
        if " run particle " in line
    ]
    assert particle_lines
    for line in particle_lines:
        assert "particle minecraft:note" in line
        assert line.endswith(" 0 force")
        # The previous v0.1.3 bug omitted the integer count before force.
        assert not line.endswith(" 1 force")
