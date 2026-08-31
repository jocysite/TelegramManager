from __future__ import annotations

import struct
from pathlib import Path


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Not a PNG file")
    width = struct.unpack(">I", data[16:20])[0]
    height = struct.unpack(">I", data[20:24])[0]
    return width, height


def build_ico(source_paths: list[Path], output_path: Path) -> None:
    images = []
    for path in source_paths:
        data = path.read_bytes()
        width, height = png_size(data)
        images.append((width, height, data))

    header_size = 6 + len(images) * 16
    offset = header_size
    entries = []
    payload = []

    for width, height, data in images:
        entries.append(
            struct.pack(
                "<BBBBHHII",
                width if width < 256 else 0,
                height if height < 256 else 0,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        payload.append(data)
        offset += len(data)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as fh:
        fh.write(struct.pack("<HHH", 0, 1, len(images)))
        for entry in entries:
            fh.write(entry)
        for data in payload:
            fh.write(data)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    sources = [root / "assets" / name for name in ("logo_32.png", "logo_64.png", "logo.png")]
    build_ico(sources, root / "build" / "branding" / "TeleManager.ico")
