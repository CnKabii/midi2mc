# CHANGELOG

## v1.9.0 - Presets, HTML Report, Compatibility Cleanup

- Combined the planned v1.7, v1.8, and v1.9 work into one release.
- Added built-in presets:
  - `vanilla_clean`
  - `vanilla_machine`
  - `vanilla_fx`
  - `vanilla_fireworks`
  - `vanilla_safe`
  - `soma_concert`
  - `soma_fx`
  - `soma_safe`
- Added `--preset` and `--list-presets`.
- Added default `report.html` generation.
- Added `--no-report`.
- Project files support `preset` and `report_html`.
- Removed vanilla actionbar Bar/Beat text.
- Removed the moving playhead from vanilla Pulse Stage tick updates.
- Kept beat meter lamps as the timing UI.
- Updated docs, examples, and tests.

## v1.6.0 - Vanilla Beat Meter

- Added 4/4 beat meter lamps and downbeat lamp.
- Added Bar/Beat actionbar display. Removed again in v1.9.

## v1.5.0 - Vanilla FX Arrangement

- Added drum pulses, chord blooms, beat accents, and smarter firework-style FX.

## v1.4.0 - Vanilla Pulse Stage

- Replaced carpet-like stage with pulse modules that appear briefly and clear automatically.
