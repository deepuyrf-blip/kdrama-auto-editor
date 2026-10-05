import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .ffmpeg import probe
from .ffmpeg import render as render_media
from .planner import make_plan

BASE = Path(__file__).resolve().parent.parent
UPLOADS = BASE / "uploads"
OUTPUTS = BASE / "outputs"
UPLOADS.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)

app = FastAPI(title="KDrama Auto Editing Agent", version="1.0.0")
app.mount("/ui", StaticFiles(directory=str(BASE / "web")), name="ui")


@app.get("/")
async def root():
    return FileResponse(BASE / "web" / "index.html")


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "kdrama-auto-editor",
        "version": "1.0.0",
        "manus_planner_enabled": bool(os.getenv("MANUS_API_KEY")),
    }


async def save_upload(file: UploadFile, folder: Path) -> Path:
    suffix = Path(file.filename or "").suffix.lower()
    allowed = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
    if suffix not in allowed:
        raise HTTPException(400, f"Unsupported file type: {suffix or 'missing extension'}")
    path = folder / (uuid.uuid4().hex + suffix)
    with path.open("wb") as handle:
        while chunk := await file.read(1024 * 1024):
            handle.write(chunk)
    return path


@app.post("/api/render")
async def render_video(
    video: UploadFile = File(...),
    voice: UploadFile = File(...),
    bgm: UploadFile = File(...),
    script: str = Form(""),
):
    job = uuid.uuid4().hex
    folder = UPLOADS / job
    folder.mkdir(parents=True)
    v = await save_upload(video, folder)
    a = await save_upload(voice, folder)
    m = await save_upload(bgm, folder)
    try:
        plan = await make_plan(str(v), str(a), script)
        output = OUTPUTS / f"{job}.mp4"
        render_media(str(v), str(a), str(m), plan, str(output))
    except Exception as exc:
        raise HTTPException(500, f"Render failed: {exc}") from exc
    return {
        "job_id": job,
        "status": "completed",
        "download": f"/api/download/{job}",
        "plan": plan.model_dump(),
    }


@app.post("/api/inspect")
async def inspect_media(video: UploadFile = File(...), voice: UploadFile = File(...)):
    """Quickly inspect durations before rendering, useful for debugging timing."""
    folder = UPLOADS / ("inspect-" + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    v, a = await save_upload(video, folder), await save_upload(voice, folder)
    return {"video": probe(str(v)), "voice": probe(str(a))}


@app.get("/api/download/{job_id}")
async def download(job_id: str):
    path = OUTPUTS / f"{job_id}.mp4"
    if not path.exists():
        raise HTTPException(404, "Output not found")
    return FileResponse(path, media_type="video/mp4", filename=f"kdrama-edit-{job_id}.mp4")
