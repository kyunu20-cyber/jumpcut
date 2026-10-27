"""앱 아이콘(packaging/JUMPCUT.icns) 생성. 노란 바탕에 파형 막대, 가운데가 잘려 나간 모양.
외부 이미지 라이브러리 없이 numpy로 그린 뒤 macOS sips·iconutil로 icns를 만든다."""
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

import numpy as np

N = 1024
HERE = Path(__file__).parent


def rounded_rect(img, x0, y0, x1, y1, r, color):
    yy, xx = np.mgrid[0:N, 0:N]
    cx = np.clip(xx, x0 + r, x1 - r)
    cy = np.clip(yy, y0 + r, y1 - r)
    inside = ((xx - cx) ** 2 + (yy - cy) ** 2 <= r * r) & (xx >= x0) & (xx <= x1) & (yy >= y0) & (yy <= y1)
    img[inside] = color


def png(path, rgba):
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    img = np.zeros((N, N, 4), np.uint8)
    rounded_rect(img, 100, 100, 924, 924, 185, (255, 210, 63, 255))       # macOS 아이콘 격자에 맞춘 여백
    heights = [150, 280, 420, 330, 210, None, None, 260, 400, 300, 180]   # None = 잘린 자리
    bar, gap = 44, 22
    x = (N - (len(heights) * bar + (len(heights) - 1) * gap)) // 2
    for h in heights:
        if h:
            rounded_rect(img, x, N // 2 - h // 2, x + bar, N // 2 + h // 2, bar // 2, (20, 20, 22, 255))
        x += bar + gap
    # 잘린 자리 위아래의 가위 표시(짧은 점선)
    cut_x = (N - (len(heights) * bar + (len(heights) - 1) * gap)) // 2 + 5 * (bar + gap) + bar + gap // 2
    for y in range(250, 780, 48):
        rounded_rect(img, cut_x - 7, y, cut_x + 7, y + 26, 7, (20, 20, 22, 255))

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base.png"
        png(base, img)
        iconset = Path(tmp) / "JUMPCUT.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(["sips", "-z", str(size * scale), str(size * scale), str(base), "--out", str(iconset / name)],
                               check=True, capture_output=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "JUMPCUT.icns")], check=True)
        png(HERE / "icon.png", img)
    print(HERE / "JUMPCUT.icns")


if __name__ == "__main__":
    main()
