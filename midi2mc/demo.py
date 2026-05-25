from __future__ import annotations

from pathlib import Path


def _varlen(value: int) -> bytes:
    buffer = value & 0x7F
    value >>= 7
    while value:
        buffer <<= 8
        buffer |= ((value & 0x7F) | 0x80)
        value >>= 7
    out = bytearray()
    while True:
        out.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            break
    return bytes(out)


def _event(delta: int, payload: bytes) -> bytes:
    return _varlen(delta) + payload


def write_demo_midi(path: str | Path) -> Path:
    """Write a tiny two-track demo MIDI used for smoke tests."""
    path = Path(path)
    tpq = 480
    header = b"MThd" + (6).to_bytes(4, "big") + (1).to_bytes(2, "big") + (2).to_bytes(2, "big") + tpq.to_bytes(2, "big")

    tempo_track = bytearray()
    tempo_track += _event(0, b"\xff\x03" + bytes([7]) + b"midi2mc")
    tempo_track += _event(0, b"\xff\x51\x03\x07\xa1\x20")  # 500000 us/qn = 120 BPM
    tempo_track += _event(0, b"\xff\x2f\x00")

    music = bytearray()
    music += _event(0, bytes([0xC0, 0]))  # Acoustic Grand Piano
    notes = [60, 62, 64, 65, 67, 69, 71, 72]
    for note in notes:
        music += _event(0, bytes([0x90, note, 96]))
        music += _event(tpq // 2, bytes([0x80, note, 64]))
    # final chord
    music += _event(0, bytes([0x90, 60, 90]))
    music += _event(0, bytes([0x90, 64, 90]))
    music += _event(0, bytes([0x90, 67, 90]))
    music += _event(tpq, bytes([0x80, 60, 64]))
    music += _event(0, bytes([0x80, 64, 64]))
    music += _event(0, bytes([0x80, 67, 64]))
    music += _event(0, b"\xff\x2f\x00")

    data = bytearray(header)
    for track in (tempo_track, music):
        data += b"MTrk" + len(track).to_bytes(4, "big") + track
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(data))
    return path


if __name__ == "__main__":
    write_demo_midi(Path("examples") / "demo_scale.mid")
