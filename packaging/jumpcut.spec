# PyInstaller 설정: JUMPCUT.app 만들기.  실행: packaging/build.sh
import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 — PyInstaller가 넣어 주는 값
if platform.machine() != "arm64":
    raise SystemExit("JUMPCUT은 Apple Silicon 전용입니다. arm64 맥에서 빌드하세요.")

datas = [(str(ROOT / "jumpcut" / "web"), "jumpcut/web"), (str(ROOT / "jumpcut" / "models"), "jumpcut/models")]
binaries, hidden = [], []

# 동봉 ffmpeg, ONNX 런타임, 받아쓰기 엔진은 데이터·바이너리까지 통째로
for pkg in ["imageio_ffmpeg", "onnxruntime", "webview", "mlx", "mlx_whisper"]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h
hidden += collect_submodules("uvicorn") + ["jumpcut.api"]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT)],
    datas=datas,
    binaries=binaries,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "torch"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [], exclude_binaries=True, name="JUMPCUT",
    console=False, upx=False, target_arch="arm64",
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="JUMPCUT")  # noqa: F821
app = BUNDLE(  # noqa: F821
    coll,
    name="JUMPCUT.app",
    icon=str(ROOT / "packaging" / "JUMPCUT.icns"),
    bundle_identifier="io.github.jumpcut",
    info_plist={
        "CFBundleDisplayName": "JUMPCUT",
        "CFBundleShortVersionString": "0.1.1",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "14.0",
        "LSArchitecturePriority": ["arm64"],  # arm64 전용 바이너리라 Intel 맥에서는 macOS가 실행을 거부
        "NSRequiresAquaSystemAppearance": False,
    },
)
