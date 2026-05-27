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
        DatapackOptions(show_id="Particle Fix", out_dir=tmp_path, zip_output=False, piano_roll=False),
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
    note_lines = [line for line in particle_lines if "particle minecraft:note" in line]
    assert note_lines
    for line in note_lines:
        assert line.endswith(" 0 force")
        assert not line.endswith(" 1 force")


def test_v030_writes_user_facing_how_to_and_manifest_stats(tmp_path: Path) -> None:
    midi_path = write_demo_midi(tmp_path / "demo.mid")
    song = parse_midi(midi_path)
    result = export_datapack(
        song,
        DatapackOptions(show_id="Helpful Demo", out_dir=tmp_path, tick_rate=24, zip_output=True),
    )

    external_readme = tmp_path / f"{result.namespace}_HOW_TO_PLAY.txt"
    assert external_readme.exists()
    external_text = external_readme.read_text("utf-8")
    assert "最快使用步骤" in external_text
    assert "/tick rate 24" in external_text
    assert "MIDI 信息摘要" in external_text
    assert "音源引擎: vanilla" in external_text

    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))
    assert manifest["format"] == "midi2mc.show.v1.9.0"
    assert manifest["sound_engine"] == "vanilla"
    assert manifest["engine"]["name"] == "vanilla"
    assert manifest["note_range"] == "C4..C5 (60..72)"
    assert manifest["max_polyphony_raw"] >= 1
    assert manifest["quality"] == "medium"
    assert manifest["stage_particles"] is True
    assert manifest["dropped_notes_due_to_cap"] == 0


def test_soma_sound_engine_generates_soma_playsound_and_manifest(tmp_path: Path) -> None:
    midi_path = write_demo_midi(tmp_path / "demo.mid")
    song = parse_midi(midi_path)
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="Soma Demo",
            out_dir=tmp_path,
            sound_engine="soma",
            mode="play",
            soma_namespace="soma",
            zip_output=False,
        ),
    )

    event_files = sorted((result.pack_dir / "data" / result.namespace / "function" / "events").glob("*.mcfunction"))
    assert event_files
    event_text = "\n".join(path.read_text("utf-8") for path in event_files)
    assert "playsound 1.60 voice" in event_text
    assert "playsound 1c.60 voice" in event_text
    assert "stopsound @s voice 1c.60" in event_text
    assert "minecraft:block.note_block" not in event_text
    assert "particle minecraft:note" not in event_text

    readme = (result.pack_dir / "README.txt").read_text("utf-8")
    assert "当前音源: soma" in readme
    assert "Soma sound category: voice" in readme

    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))
    assert manifest["format"] == "midi2mc.show.v1.9.0"
    assert manifest["sound_engine"] == "soma"
    assert manifest["engine"]["name"] == "soma"
    assert manifest["engine"]["map_mode"] == "soma_v20"
    assert manifest["engine"]["long_note_beats"] == 1.0


def test_soma_concert_stage_generates_module_feedback(tmp_path: Path) -> None:
    midi_path = write_demo_midi(tmp_path / "demo.mid")
    song = parse_midi(midi_path)
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="Soma Concert",
            out_dir=tmp_path,
            sound_engine="soma",
            mode="command_stage",
            stage_profile="soma_concert",
            zip_output=False,
        ),
    )

    fn_dir = result.pack_dir / "data" / result.namespace / "function"
    setup_text = (fn_dir / "stage" / "setup.mcfunction").read_text("utf-8")
    clear_text = (fn_dir / "stage" / "clear.mcfunction").read_text("utf-8")
    event_text = "\n".join(
        path.read_text("utf-8")
        for path in sorted((fn_dir / "events").glob("*.mcfunction"))
    )
    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))

    assert manifest["stage_profile"] == "soma_concert"
    assert "Soma spacious layered concert stage" in setup_text
    assert "minecraft:smooth_quartz" in setup_text
    assert "minecraft:amethyst_block" in setup_text
    assert "redstone_lamp[lit=false]" in clear_text
    assert "playsound 1.60 voice" in event_text
    assert "particle minecraft:note" in event_text
    assert "minecraft:note_block" not in setup_text


def test_soma_overlap_long_notes_fall_back_to_short_sound(tmp_path: Path) -> None:
    from midi2mc.model import MidiSong, NoteEvent, TempoEvent

    # Two long C4 notes overlap. v1.2.0 should keep the first as 1c.60,
    # downgrade the second to 1.60, and emit only one stopsound for 1c.60.
    song = MidiSong(
        format_type=1,
        ticks_per_quarter=480,
        tempo_events=[TempoEvent(0, 500_000)],
        notes=[
            NoteEvent(0, 960, 0.0, 1.0, 1, 0, 60, 96, program=0),
            NoteEvent(480, 1440, 0.5, 1.0, 1, 0, 60, 96, program=0),
        ],
    )
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="Soma Overlap",
            out_dir=tmp_path,
            sound_engine="soma",
            mode="play",
            tick_rate=20,
            zip_output=False,
        ),
    )

    event_text = "\n".join(
        path.read_text("utf-8")
        for path in sorted((result.pack_dir / "data" / result.namespace / "function" / "events").glob("*.mcfunction"))
    )
    assert event_text.count("playsound 1c.60 voice") == 1
    assert event_text.count("playsound 1.60 voice") == 1
    assert event_text.count("stopsound @s voice 1c.60") == 1

    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))
    report = manifest["soma_report"]
    assert report["continuous_notes"] == 1
    assert report["requested_continuous_notes"] == 2
    assert report["overlap_short_fallbacks"] == 1
    assert report["stopsound_count"] == 1


def test_soma_out_of_range_drum_notes_are_clamped_and_reported(tmp_path: Path) -> None:
    from midi2mc.model import MidiSong, NoteEvent, TempoEvent

    song = MidiSong(
        format_type=1,
        ticks_per_quarter=480,
        tempo_events=[TempoEvent(0, 500_000)],
        notes=[NoteEvent(0, 120, 0.0, 0.125, 1, 9, 1, 96, program=0)],
    )
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="Soma Clamp",
            out_dir=tmp_path,
            sound_engine="soma",
            mode="play",
            tick_rate=20,
            zip_output=False,
        ),
    )
    event_text = "\n".join(
        path.read_text("utf-8")
        for path in sorted((result.pack_dir / "data" / result.namespace / "function" / "events").glob("*.mcfunction"))
    )
    # Soma v20 drum range is 27..87, so MIDI note 1 is clamped to 27; v0.12 auto drum kit may use 0p for small percussion.
    assert "playsound 0p.27 voice" in event_text

    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))
    report = manifest["soma_report"]
    assert report["clamped_notes"] == 1
    assert report["clamped_examples"][0]["from"] == 1
    assert report["clamped_examples"][0]["to"] == 27


def test_soma_concert_stage_keeps_continuous_notes_lit_until_note_off(tmp_path: Path) -> None:
    from midi2mc.model import MidiSong, NoteEvent, TempoEvent

    song = MidiSong(
        format_type=1,
        ticks_per_quarter=480,
        tempo_events=[TempoEvent(0, 500_000)],
        notes=[NoteEvent(0, 960, 0.0, 1.0, 1, 0, 60, 96, program=0)],
    )
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="Soma Hold Light",
            out_dir=tmp_path,
            sound_engine="soma",
            mode="command_stage",
            stage_profile="soma_concert",
            tick_rate=20,
            zip_output=False,
        ),
    )

    fn_dir = result.pack_dir / "data" / result.namespace / "function"
    clear_text = (fn_dir / "stage" / "clear.mcfunction").read_text("utf-8")
    reset_text = (fn_dir / "stage" / "reset.mcfunction").read_text("utf-8")
    play_text = (fn_dir / "play.mcfunction").read_text("utf-8")
    event_text = "\n".join(
        path.read_text("utf-8")
        for path in sorted((fn_dir / "events").glob("*.mcfunction"))
    )
    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))

    assert "function soma_hold_light:stage/reset" in play_text
    assert "scoreboard players set $soma_piano midi2mc 0" in reset_text
    assert "unless score $soma_piano midi2mc matches 1.." in clear_text
    assert "scoreboard players add $soma_piano midi2mc 1" in event_text
    assert "scoreboard players remove $soma_piano midi2mc 1" in event_text
    assert manifest["stage_report"]["sustained_light_policy"] == "continuous_notes_light_from_next_tick_until_note_off_with_handoff_gap"
    assert manifest["stage_report"]["sustained_modules"]["piano"] == 1



def test_low_quality_disables_stage_particles_and_caps_notes(tmp_path: Path) -> None:
    from midi2mc.model import MidiSong, NoteEvent, TempoEvent

    notes = [NoteEvent(0, 120, 0.0, 0.125, 1, 0, 60 + i, 127 - i, program=0) for i in range(12)]
    song = MidiSong(format_type=1, ticks_per_quarter=480, tempo_events=[TempoEvent(0, 500_000)], notes=notes)
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="Low Quality",
            out_dir=tmp_path,
            sound_engine="vanilla",
            mode="command_stage",
            quality="low",
            max_notes_per_tick=8,
            stage_particles=False,
            piano_roll=False,
            zip_output=False,
        ),
    )

    event_text = "\n".join(
        path.read_text("utf-8")
        for path in sorted((result.pack_dir / "data" / result.namespace / "function" / "events").glob("*.mcfunction"))
    )
    assert "particle minecraft:note" not in event_text
    assert event_text.count("playsound minecraft:block.note_block") == 8

    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))
    assert manifest["quality"] == "low"
    assert manifest["stage_particles"] is False
    assert manifest["compiled_notes"] == 8
    assert manifest["dropped_notes_due_to_cap"] == 4


def test_soma_continuous_light_is_delayed_to_next_tick_for_articulation(tmp_path: Path) -> None:
    from midi2mc.model import MidiSong, NoteEvent, TempoEvent

    song = MidiSong(
        format_type=1,
        ticks_per_quarter=480,
        tempo_events=[TempoEvent(0, 500_000)],
        notes=[NoteEvent(0, 960, 0.0, 1.0, 1, 0, 60, 96, program=0)],
    )
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="Soma Delayed Light",
            out_dir=tmp_path,
            sound_engine="soma",
            mode="command_stage",
            stage_profile="soma_concert",
            tick_rate=20,
            zip_output=False,
        ),
    )

    fn_dir = result.pack_dir / "data" / result.namespace / "function"
    clear_text = (fn_dir / "stage" / "clear.mcfunction").read_text("utf-8")
    start_event = (fn_dir / "events" / "000000.mcfunction").read_text("utf-8")
    assert "if score $soma_piano midi2mc matches 1.." in clear_text
    assert "scoreboard players add $soma_piano midi2mc 1" in start_event
    # The first tick starts the long sound and counter but does not immediately light the module;
    # stage/clear on the next tick turns it on. This makes back-to-back long notes articulate.
    assert "redstone_lamp[lit=true]" not in start_event


def test_piano_roll_visualizer_generates_end_rod_strips_and_manifest(tmp_path: Path) -> None:
    midi_path = write_demo_midi(tmp_path / "demo.mid")
    song = parse_midi(midi_path)
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="Piano Roll",
            out_dir=tmp_path,
            sound_engine="soma",
            mode="command_stage",
            stage_profile="soma_concert",
            piano_roll=True,
            zip_output=False,
        ),
    )

    fn_dir = result.pack_dir / "data" / result.namespace / "function"
    event_text = "\n".join(
        path.read_text("utf-8")
        for path in sorted((fn_dir / "events").glob("*.mcfunction"))
    )
    assert "particle minecraft:end_rod" in event_text
    assert "particle minecraft:note" in event_text

    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))
    assert manifest["format"] == "midi2mc.show.v1.9.0"
    assert manifest["piano_roll"] is True
    assert manifest["visualizer_report"]["enabled"] is True
    assert manifest["visualizer_report"]["profile"] == "particle_piano_roll_v1"


def test_v080_piano_roll_default_off_but_show_fx_lightshow_auto_for_soma(tmp_path: Path) -> None:
    midi_path = write_demo_midi(tmp_path / "demo.mid")
    song = parse_midi(midi_path)
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="V081 FX",
            out_dir=tmp_path,
            sound_engine="soma",
            mode="command_stage",
            stage_profile="soma_concert",
            zip_output=False,
        ),
    )

    fn_dir = result.pack_dir / "data" / result.namespace / "function"
    event_text = "\n".join(
        path.read_text("utf-8")
        for path in sorted((fn_dir / "events").glob("*.mcfunction"))
    )
    # Piano Roll is the unpopular v0.7 strip and is now default-off.
    assert "~-1.65" not in event_text
    # Auto lightshow is lightweight and color-matches note particles on the Soma stage.
    assert "particle minecraft:note" in event_text
    assert "particle minecraft:dust{color:" in event_text

    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))
    assert manifest["format"] == "midi2mc.show.v1.9.0"
    assert manifest["piano_roll"] is False
    assert manifest["show_fx"] == "lightshow"
    assert manifest["show_fx_report"]["enabled"] is True
    assert manifest["show_fx_report"]["profile"] == "lightshow"
    assert "RGB dust" in manifest["show_fx_report"]["color_policy"]


def test_v080_firework_style_fx_is_opt_in_and_particle_only(tmp_path: Path) -> None:
    midi_path = write_demo_midi(tmp_path / "demo.mid")
    song = parse_midi(midi_path)
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="V081 Fireworks",
            out_dir=tmp_path,
            sound_engine="soma",
            mode="command_stage",
            stage_profile="soma_concert",
            show_fx="both",
            zip_output=False,
        ),
    )

    fn_dir = result.pack_dir / "data" / result.namespace / "function"
    event_text = "\n".join(
        path.read_text("utf-8")
        for path in sorted((fn_dir / "events").glob("*.mcfunction"))
    )
    assert "particle minecraft:dust{color:" in event_text
    assert "particle minecraft:end_rod" not in event_text
    assert "summon minecraft:firework_rocket" not in event_text

    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))
    assert manifest["show_fx"] == "both"
    assert manifest["show_fx_report"]["uses_real_firework_entities"] is False


def test_project_config_template_and_export(tmp_path: Path) -> None:
    from midi2mc.cli import main
    import json as _json

    midi_path = write_demo_midi(tmp_path / "demo.mid")
    project_path = tmp_path / "demo.m2mc.json"
    project_path.write_text(
        _json.dumps(
            {
                "format": "midi2mc.project.v1",
                "midi": "demo.mid",
                "show_id": "project_soma",
                "out": "out",
                "mode": "command_stage",
                "sound_engine": "soma",
                "stage_profile": "soma_concert",
                "quality": "medium",
                "tick_rate": "auto",
                "stage_particles": True,
                "piano_roll": False,
                "show_fx": "lightshow",
                "zip_output": False,
                "soma": {"long_note_beats": 1.0, "namespace": "", "reference_note": 60, "map": None},
            }
        ),
        "utf-8",
    )
    assert main(["--project", str(project_path)]) == 0
    manifest_path = tmp_path / "out" / "project_soma" / "midi2mc_manifest.json"
    assert manifest_path.exists()
    manifest = _json.loads(manifest_path.read_text("utf-8"))
    assert manifest["format"] == "midi2mc.show.v1.9.0"
    assert manifest["project_config_support"] == ".m2mc.json"
    assert manifest["sound_engine"] == "soma"
    assert manifest["stage_profile"] == "soma_concert"


def test_v010_dust_fx_uses_lower_denser_note_matched_palette(tmp_path: Path) -> None:
    midi_path = write_demo_midi(tmp_path / "demo.mid")
    song = parse_midi(midi_path)
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="V010 Dust",
            out_dir=tmp_path,
            sound_engine="soma",
            mode="command_stage",
            stage_profile="soma_concert",
            show_fx="lightshow",
            zip_output=False,
        ),
    )
    event_text = "\n".join(
        path.read_text("utf-8")
        for path in sorted((result.pack_dir / "data" / result.namespace / "function" / "events").glob("*.mcfunction"))
    )
    assert "particle minecraft:dust{color:" in event_text
    # v1.6 lightshow dust sits below the note sprite layer but above solid stage blocks.
    assert "~2." in event_text or "~3." in event_text
    assert " 10 force" in event_text or " 14 force" in event_text
    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))
    assert "same Minecraft note-particle hue" in manifest["show_fx_report"]["color_policy"]


def test_safe_mode_writes_conservative_manifest(tmp_path: Path) -> None:
    midi_path = write_demo_midi(tmp_path / "demo.mid")
    song = parse_midi(midi_path)
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="Safe Mode Demo",
            out_dir=tmp_path,
            sound_engine="soma",
            mode="command_stage",
            stage_profile="soma_concert",
            quality="low",
            safe_mode=True,
            max_notes_per_tick=8,
            stage_particles=False,
            piano_roll=False,
            show_fx="none",
            zip_output=False,
        ),
    )
    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))
    assert manifest["format"] == "midi2mc.show.v1.9.0"
    assert manifest["safe_mode"] is True
    assert manifest["quality"] == "low"
    assert manifest["max_notes_per_tick"] == 8
    assert manifest["stage_particles"] is False
    assert manifest["show_fx"] == "none"
    assert manifest["safety_report"]["level"] in {"low", "medium", "high", "critical"}


def test_soma_v012_missing_gm_sound_effect_program_falls_back(tmp_path: Path) -> None:
    from midi2mc.model import MidiSong, NoteEvent, TempoEvent

    # GM program 121 is zero-based 120 (Guitar Fret Noise), not present in the
    # Soma v20 spreadsheet. v0.12 maps it to a nearby available guitar program
    # rather than defaulting to piano.
    song = MidiSong(
        format_type=1,
        ticks_per_quarter=480,
        tempo_events=[TempoEvent(0, 500_000)],
        notes=[NoteEvent(0, 240, 0.0, 0.25, 1, 0, 64, 96, program=120)],
    )
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="Soma Program Fallback",
            out_dir=tmp_path,
            sound_engine="soma",
            mode="play",
            tick_rate=20,
            zip_output=False,
        ),
    )
    event_text = "\n".join(
        path.read_text("utf-8")
        for path in sorted((result.pack_dir / "data" / result.namespace / "function" / "events").glob("*.mcfunction"))
    )
    assert "playsound 25.64 voice" in event_text
    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))
    report = manifest["soma_report"]
    assert report["program_fallback_notes"] == 1
    assert report["program_fallback_examples"][0]["from_program"] == 121
    assert report["program_fallback_examples"][0]["to_program"] == 25


def test_soma_v012_drum_kit_normal_can_force_v011_style(tmp_path: Path) -> None:
    from midi2mc.model import MidiSong, NoteEvent, TempoEvent

    song = MidiSong(
        format_type=1,
        ticks_per_quarter=480,
        tempo_events=[TempoEvent(0, 500_000)],
        notes=[NoteEvent(0, 120, 0.0, 0.125, 1, 9, 42, 96, program=0)],
    )
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="Soma Drum Normal",
            out_dir=tmp_path,
            sound_engine="soma",
            mode="play",
            tick_rate=20,
            soma_drum_kit="normal",
            zip_output=False,
        ),
    )
    event_text = "\n".join(
        path.read_text("utf-8")
        for path in sorted((result.pack_dir / "data" / result.namespace / "function" / "events").glob("*.mcfunction"))
    )
    assert "playsound 0.42 voice" in event_text
    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))
    assert manifest["engine"]["drum_kit"] == "normal"
    assert manifest["soma_report"]["drum_variants"] == {"0": 1}


def test_v190_vanilla_stage_has_dynamic_rows_control_panel_and_meter_only(tmp_path: Path) -> None:
    midi_path = write_demo_midi(tmp_path / "demo.mid")
    song = parse_midi(midi_path)
    result = export_datapack(
        song,
        DatapackOptions(
            show_id="Vanilla V120 Stage",
            out_dir=tmp_path,
            sound_engine="vanilla",
            mode="command_stage",
            stage_profile="noteblock_machine",
            zip_output=False,
        ),
    )
    fn_dir = result.pack_dir / "data" / result.namespace / "function"
    setup_text = (fn_dir / "stage" / "setup.mcfunction").read_text("utf-8")
    meter_text = (fn_dir / "stage" / "meter.mcfunction").read_text("utf-8")
    tick_text = (fn_dir / "tick.mcfunction").read_text("utf-8")
    event_text = "\n".join(
        path.read_text("utf-8")
        for path in sorted((fn_dir / "events").glob("*.mcfunction"))
    )
    manifest = json.loads((result.pack_dir / "midi2mc_manifest.json").read_text("utf-8"))

    assert "Vanilla v1.9 Pulse Stage" in setup_text
    assert "auto: small/solo arrangement" in setup_text
    assert "minecraft:white_concrete" in setup_text  # active keyboard row marker.
    assert "fill ~" not in setup_text  # v1.6 setup is sparse; pulses are cleared by event cleanup.
    assert "minecraft:lime_concrete" in setup_text  # compact visual control panel.
    assert "stage/playhead" not in tick_text
    assert "stage/meter" in tick_text
    assert "stage/clear" not in tick_text
    assert "scoreboard players set $beat_ticks midi2mc 10" in meter_text
    assert "title @a actionbar" not in meter_text
    assert "redstone_lamp[lit=true]" in meter_text
    assert "~3.85" in event_text  # note particle is above the 2D machine rows.
    assert manifest["format"] == "midi2mc.show.v1.9.0"
    assert manifest["stage_layout"] == "auto"
    assert manifest["stage_report"]["layout"] == "vanilla_machine_v1.9_pulse_stage_compact"
    assert manifest["stage_report"]["layout_resolved"] == "compact"
    assert manifest["stage_report"]["playhead"]["enabled"] is False
    assert manifest["stage_report"]["beat_meter"]["enabled"] is True
    assert manifest["beat_report"]["enabled"] is True


def test_v190_preset_and_html_report(tmp_path: Path) -> None:
    from midi2mc.cli import main
    midi_path = write_demo_midi(tmp_path / "demo.mid")
    assert main([str(midi_path), "--show-id", "Preset Demo", "--out", str(tmp_path / "out"), "--preset", "vanilla_fx", "--no-zip"]) == 0
    manifest_path = tmp_path / "out" / "preset_demo" / "midi2mc_manifest.json"
    report_path = tmp_path / "out" / "preset_demo" / "report.html"
    assert manifest_path.exists()
    assert report_path.exists()
    manifest = json.loads(manifest_path.read_text("utf-8"))
    assert manifest["format"] == "midi2mc.show.v1.9.0"
    assert manifest["preset"] == "vanilla_fx"
    assert manifest["sound_engine"] == "vanilla"
    assert manifest["stage_layout"] == "wide"
    assert manifest["show_fx"] == "lightshow"
    html = report_path.read_text("utf-8")
    assert "midi2mc v1.9.0 Report" in html
    assert "Preset Demo" in html or "preset_demo" in html

def test_v190_no_report_flag(tmp_path: Path) -> None:
    from midi2mc.cli import main
    midi_path = write_demo_midi(tmp_path / "demo.mid")
    assert main([str(midi_path), "--show-id", "No Report", "--out", str(tmp_path / "out"), "--no-report", "--no-zip"]) == 0
    assert not (tmp_path / "out" / "no_report" / "report.html").exists()
