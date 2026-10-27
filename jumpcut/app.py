"""맥 앱 진입점. 로컬 서버를 띄우고 그 화면을 앱 창(WKWebView)에 연다."""
import json
import socket
import threading
import time
import urllib.request

import uvicorn
import webview
from webview.dom import DOMEventHandler

from .api import app as api_app
from .transcribe import require_apple_silicon

VIDEO_TYPES = ("영상과 오디오 (*.mp4;*.mov;*.m4v;*.mkv;*.webm;*.avi;*.mp3;*.wav;*.m4a;*.aac)", "모든 파일 (*.*)")
window = None


class Bridge:
    """화면의 window.pywebview.api.* 로 불린다."""

    def pick_file(self):
        picked = window.create_file_dialog(webview.FileDialog.OPEN, file_types=VIDEO_TYPES)
        return picked[0] if picked else None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(port: int) -> None:
    server = uvicorn.Server(uvicorn.Config(api_app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5)
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("내부 서버가 시작되지 않았습니다.")


def _on_drop(event):
    # 끌어다 놓은 파일의 실제 경로는 파이썬 쪽 이벤트에만 실려 온다
    files = event.get("dataTransfer", {}).get("files", [])
    path = next((f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")), None)
    if path:
        window.evaluate_js(f"window.jumpcutOpen({json.dumps(path)})")


def _bind(win):
    win.dom.document.events.drop += DOMEventHandler(_on_drop, prevent_default=True, stop_propagation=True)


def main():
    global window
    require_apple_silicon()
    port = _free_port()
    _serve(port)
    window = webview.create_window(
        "JUMPCUT", f"http://127.0.0.1:{port}/", js_api=Bridge(),
        width=1440, height=900, min_size=(1100, 700), background_color="#0f0f11",
    )
    webview.start(_bind, window)


if __name__ == "__main__":
    main()
