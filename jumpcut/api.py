"""검토 화면용 로컬 서버. 127.0.0.1에만 열린다."""
import hashlib
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import media as mediatools
from . import project, render

OUT_DIR = Path.home() / "Movies" / "JUMPCUT"
CACHE = Path.home() / "Library" / "Caches" / "JUMPCUT"
WEB = Path(__file__).parent / "web"

app = FastAPI(title="JUMPCUT")
_paths: dict[str, str] = {}   # 프로젝트 id → 원본 경로
_jobs: dict[str, dict] = {}
_busy = threading.Lock()      # 받아쓰기·렌더는 한 번에 하나(메모리·GPU 보호)
_edit = threading.Lock()      # 컷 저장과 재검출이 서로의 결과를 덮어쓰지 않게


def _pid(path: str) -> str:
    return hashlib.sha1(path.encode()).hexdigest()[:12]


def _src(pid: str) -> str:
    if pid not in _paths:
        raise HTTPException(404, "열린 영상이 없습니다.")
    return _paths[pid]


def _project(pid: str) -> dict:
    data = project.load(_src(pid))
    if data is None:
        raise HTTPException(409, "아직 분석하지 않았습니다.")
    return data


def _public(pid: str, data: dict) -> dict:
    return {"id": pid, **{k: v for k, v in data.items() if k not in ("source_mtime", "source_size")}}


def _run(fn) -> str:
    jid = uuid.uuid4().hex[:8]
    job = _jobs[jid] = {"stage": "wait", "progress": 0.0, "done": False, "error": None, "result": None}

    def step(stage, frac):
        job["stage"], job["progress"] = stage, round(frac, 3)

    def worker():
        with _busy:
            try:
                job["result"] = fn(step)
            except Exception as e:  # noqa: BLE001 — 화면에 그대로 보여 준다
                job["error"] = str(e)
            job["done"] = True

    threading.Thread(target=worker, daemon=True).start()
    return jid


class OpenReq(BaseModel):
    path: str


class AnalyzeReq(BaseModel):
    language: str | None = "ko"


class CutsReq(BaseModel):
    cuts: list[dict]


class ParamsReq(BaseModel):
    params: dict
    cuts: list[dict] | None = None   # 화면의 최신 컷. 아직 저장 전인 편집도 살린다


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/open")
def open_video(req: OpenReq):
    path = str(Path(req.path).expanduser().resolve())
    if not Path(path).is_file():
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    pid = _pid(path)
    _paths[pid] = path
    data = project.load(path)
    return {"id": pid, "name": Path(path).name, "project": _public(pid, data) if data else None}


@app.post("/api/upload")
def upload(file: UploadFile):
    """브라우저로 끌어다 놓은 파일. 경로를 모르니 출력 폴더 아래로 복사해 둔다."""
    dest = OUT_DIR / "원본" / Path(file.filename or "video.mp4").name
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return open_video(OpenReq(path=str(dest)))


@app.post("/api/project/{pid}/analyze")
def analyze(pid: str, req: AnalyzeReq):
    src = _src(pid)
    return {"job": _run(lambda step: _public(pid, project.analyze(src, req.language, step)))}


@app.get("/api/project/{pid}")
def get_project(pid: str):
    return _public(pid, _project(pid))


@app.put("/api/project/{pid}/cuts")
def save_cuts(pid: str, req: CutsReq):
    with _edit:
        data = _project(pid)
        data["cuts"] = req.cuts
        project.save(data)
    return {"ok": True}


@app.post("/api/project/{pid}/redetect")
def redetect(pid: str, req: ParamsReq):
    with _edit:
        data = _project(pid)
        if req.cuts is not None:
            data["cuts"] = req.cuts
        return _public(pid, project.redetect(data, req.params))


@app.post("/api/project/{pid}/export")
def export(pid: str):
    data = _project(pid)
    src = Path(data["source"])
    out = OUT_DIR / f"{src.stem}_cut.mp4"

    def job(step):
        step("export", 0)
        render.render(str(src), str(out), data["cuts"], lambda f: step("export", f))
        return {"path": str(out)}

    return {"job": _run(job)}


@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    if jid not in _jobs:
        raise HTTPException(404)
    job = _jobs[jid]
    if job["done"]:
        _jobs.pop(jid)   # 화면은 done을 받은 뒤 다시 묻지 않는다
    return job


@app.post("/api/reveal")
def reveal(req: OpenReq):
    if Path(req.path).exists():
        subprocess.run(["open", "-R", req.path])
    return {"ok": True}


@app.get("/api/project/{pid}/thumbs")
def thumbs(pid: str, n: int = 40):
    """타임라인 썸네일 줄. n장을 가로로 이어 붙인 한 장짜리 이미지(장당 96x54)."""
    src = _src(pid)
    info = mediatools.probe(src)
    if not info["has_video"]:
        raise HTTPException(404, "영상 트랙이 없습니다.")
    n = max(4, min(n, 200))
    st = Path(src).stat()
    out = CACHE / f"{pid}-{int(st.st_mtime)}-{n}.jpg"
    if not out.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        # 긴 영상은 키프레임만 읽어 빠르게(키프레임 간격이 길면 비슷한 장면이 반복될 수 있음)
        fast = ["-skip_frame", "nokey"] if info["duration"] > 300 else []
        subprocess.run([
            mediatools.ffmpeg(), "-v", "error", "-y", *fast, "-i", src,
            "-vf", f"fps={n / info['duration']:.5f},scale=96:54:force_original_aspect_ratio=increase,crop=96:54,tile={n}x1",
            "-frames:v", "1", "-q:v", "5", str(out),
        ], check=True)
    return FileResponse(out)


@app.get("/media/{pid}")
def media(pid: str):
    return FileResponse(_src(pid))


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
