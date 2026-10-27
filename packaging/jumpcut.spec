# PyInstaller 설정: JUMPCUT.app 만들기.  실행: packaging/build.sh
import platform
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 — PyInstaller가 넣어 주는 값
ARM = platform.machine() == "arm64"

datas = [(str(ROOT / "jumpcut" / "web"), "jumpcut/web"), (str(ROOT / "jumpcut" / "models"), "jumpcut/models")]
binaries, hidden = [], []

# 동봉 ffmpeg, ONNX 런타임, 받아쓰기 엔진은 데이터·바이너리까지 통째로
for pkg in ["imageio_ffmpeg", "onnxruntime", "webview"] + (["mlx", "mlx_whisper"] if ARM else ["faster_whisper", "ctranslate2"]):
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
    console=False, upx=False, target_arch=None,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="JUMPCUT")  # noqa: F821
app = BUNDLE(  # noqa: F821
    coll,
    name="JUMPCUT.app",
    icon=str(ROOT / "packaging" / "JUMPCUT.icns"),
    bundle_identifier="io.github.jumpcut",
    info_plist={
        "CFBundleDisplayName": "JUMPCUT",
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "14.0",
        "NSRequiresAquaSystemAppearance": False,
    },
)
