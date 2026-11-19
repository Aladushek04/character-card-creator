"""PNG character-card I/O.

CT's own exports put the card JSON in both `ccv3` and `chara` tEXt chunks,
immediately before IEND, plus compressed zTXt copies in newer files. We mirror
that layout exactly. Writing chunks by hand (rather than relying on Pillow's
PngInfo placement) guarantees the ordering.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import struct
import zlib
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _iter_chunks(data: bytes):
    if not data.startswith(PNG_SIG):
        raise ValueError("not a PNG file")
    pos = 8
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        yield ctype.decode("latin1"), body, pos
        pos += 12 + length


def read_text_chunks(path: str | Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for ctype, body, _ in _iter_chunks(Path(path).read_bytes()):
        if ctype == "tEXt":
            key, _, value = body.partition(b"\x00")
            result[key.decode("latin1")] = value.decode("latin1")
        elif ctype == "zTXt":
            key, _, rest = body.partition(b"\x00")
            if rest and rest[0] == 0:
                result.setdefault(key.decode("latin1"), zlib.decompress(rest[1:]).decode("utf-8"))
    return result


def read_card(path: str | Path) -> dict[str, Any]:
    chunks = read_text_chunks(path)
    raw = chunks.get("ccv3") or chunks.get("chara")
    if not raw:
        raise ValueError(f"no card data in {path}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(base64.b64decode(raw).decode("utf-8"))


def _make_chunk(ctype: bytes, body: bytes) -> bytes:
    return (
        struct.pack(">I", len(body))
        + ctype
        + body
        + struct.pack(">I", binascii.crc32(ctype + body) & 0xFFFFFFFF)
    )


def make_portrait(
    source: str | Path | None, width: int, height: int, label: str = ""
) -> bytes:
    """Return PNG bytes for a 2:3 portrait, cropped from source or generated."""
    if source:
        with Image.open(source) as im:
            if im.mode == "P" and "transparency" in im.info:
                rgba = im.convert("RGBA")
                background = Image.new("RGB", rgba.size, (0, 0, 0))
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = im.convert("RGB")
    else:
        image = Image.new("RGB", (width, height), (24, 18, 34))
        draw = ImageDraw.Draw(image)
        for y in range(height):
            t = y / max(1, height - 1)
            draw.line((0, y, width, y), fill=(int(28 + 24 * t), int(20 + 12 * t), int(42 + 26 * t)))
        draw.text((24, height - 40), label[:40], fill=(220, 210, 230))

    src_w, src_h = image.size
    target_ratio = width / height
    if src_w / src_h > target_ratio:
        new_w = round(src_h * target_ratio)
        left = (src_w - new_w) // 2
        image = image.crop((left, 0, left + new_w, src_h))
    elif src_w / src_h < target_ratio:
        new_h = round(src_w / target_ratio)
        top = (src_h - new_h) // 2
        image = image.crop((0, top, src_w, top + new_h))
    image = image.resize((width, height), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def write_card_png(
    card: dict[str, Any],
    portrait_png: bytes,
    out_path: str | Path,
    *,
    embed_ztxt: bool = True,
) -> Path:
    if not portrait_png.startswith(PNG_SIG):
        raise ValueError("portrait_png is not PNG data")

    payload = base64.b64encode(
        json.dumps(card, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    data = bytearray(portrait_png)
    iend_pos = None
    for _ctype, _body, pos in _iter_chunks(bytes(data)):
        if _ctype == "IEND":
            iend_pos = pos
            break
    if iend_pos is None:
        raise ValueError("portrait PNG has no IEND chunk")

    extra = bytearray()
    for keyword in ("ccv3", "chara"):
        extra += _make_chunk(b"tEXt", keyword.encode("ascii") + b"\x00" + payload)
    if embed_ztxt:
        compressed = zlib.compress(payload, 9)
        for keyword in ("ccv3", "chara"):
            body = keyword.encode("ascii") + b"\x00" + b"\x00" + compressed
            extra += _make_chunk(b"zTXt", body)

    data[iend_pos:iend_pos] = extra
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(data))
    return out
