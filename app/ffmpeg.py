import json
import os
import re
import subprocess
from pathlib import Path

from .models import EditPlan

FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and proc.returncode:
        raise RuntimeError(proc.stderr[-12000:] or "FFmpeg command failed")
    return proc


def probe(path: str) -> dict:
    proc = subprocess.run(
        [FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
    )
    data = json.loads(proc.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    return {
        "duration": float(fmt.get("duration") or 0),
        "has_video": video is not None,
        "has_audio": audio is not None,
        "width": int((video or {}).get("width") or 0),
        "height": int((video or {}).get("height") or 0),
        "fps": (video or {}).get("r_frame_rate", "0/1"),
    }


def probe_duration(path: str) -> float:
    return probe(path)["duration"]


def detect_scenes(path: str, threshold: float = 0.30, min_scene: float = 0.60) -> list[tuple[float, float]]:
    """Return scene intervals using FFmpeg's content-change detector.

    This is deliberately local and deterministic. A Manus planner can refine these
    intervals when MANUS_API_KEY is configured, but rendering never depends on it.
    """
    duration = probe_duration(path)
    if duration <= 0:
        raise ValueError("Video has no readable duration")
    proc = run([
        FFMPEG, "-hide_banner", "-i", path,
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-an", "-f", "null", "-"], check=False)
    points = [0.0]
    for match in re.finditer(r"pts_time:(\d+(?:\.\d+)?)", proc.stderr):
        point = float(match.group(1))
        if min_scene <= point < duration - 0.05 and point - points[-1] >= min_scene:
            points.append(point)
    points.append(duration)
    intervals = []
    for start, end in zip(points, points[1:]):
        if end - start >= 0.20:
            intervals.append((round(start, 3), round(end, 3)))
    return intervals or [(0.0, round(duration, 3))]


def _video_filter(plan: EditPlan, segment, target_duration: float) -> str:
    vf = (
        f"scale={plan.output_width}:{plan.output_height}:"
        "force_original_aspect_ratio=increase,"
        f"crop={plan.output_width}:{plan.output_height},setsar=1"
    )
    vf += f",setpts=PTS/{max(segment.speed, 0.01):.8f}"
    vf += f",trim=duration={max(target_duration, 0.05):.5f},setpts=PTS-STARTPTS"
    return vf


def render(video: str, voice: str, bgm: str, plan: EditPlan, output: str) -> str:
    out = Path(output)
    work = out.parent / (out.stem + "_work")
    work.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []

    if not plan.segments:
        raise RuntimeError("No video segments in edit plan")

    for i, segment in enumerate(plan.segments):
        source_duration = max(0.05, segment.source_end - segment.source_start)
        target_duration = segment.target_duration
        clip = work / f"clip_{i:04d}.mp4"
        vf = _video_filter(plan, segment, target_duration)
        run([
            FFMPEG, "-y", "-hide_banner",
            "-ss", f"{segment.source_start:.4f}", "-t", f"{source_duration:.4f}", "-i", video,
            "-an", "-vf", vf, "-r", str(plan.fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            str(clip),
        ])
        clips.append(clip)

    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in clips), encoding="utf-8")
    joined = work / "joined.mp4"
    run([
        FFMPEG, "-y", "-hide_banner", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(plan.fps),
        "-pix_fmt", "yuv420p", str(joined),
    ])

    # Voice is the master clock. Source audio is never mapped. BGM loops and is
    # kept quiet, then sidechain-compressed whenever the narration is present.
    filter_complex = (
        f"[1:a]volume={plan.voice_gain_db}dB,aresample=async=1:first_pts=0,asplit=2[narr][side];"
        f"[2:a]volume={plan.bgm_gain_db}dB,aresample=async=1:first_pts=0[mus];"
        f"[mus][side]sidechaincompress=threshold={plan.bgm_duck_threshold}:"
        f"ratio={plan.bgm_duck_ratio}:attack=15:release=500[ducked];"
        "[narr][ducked]amix=inputs=2:duration=first:dropout_transition=2,"
        "loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
    )
    run([
        FFMPEG, "-y", "-hide_banner",
        "-i", str(joined), "-i", voice, "-stream_loop", "-1", "-i", bgm,
        "-filter_complex", filter_complex,
        "-map", "0:v:0", "-map", "[aout]",
        "-t", f"{plan.timeline_duration:.4f}",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(out),
    ])
    return str(out)
