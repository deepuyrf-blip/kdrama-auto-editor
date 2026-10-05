import json
import os
import subprocess
from pathlib import Path
from .models import EditPlan

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-8000:])

def probe_duration(path):
    p = subprocess.run(
        [os.getenv("FFPROBE_BIN","ffprobe"), "-v","error",
         "-show_entries","format=duration","-of","json",path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True
    )
    return float(json.loads(p.stdout)["format"]["duration"])

def render(video, voice, bgm, plan: EditPlan, output):
    out = Path(output)
    work = out.parent / (out.stem + "_work")
    work.mkdir(parents=True, exist_ok=True)
    clips = []

    for i, s in enumerate(plan.segments):
        duration = max(0.05, s.source_end - s.source_start)
        clip = work / f"clip_{i:04d}.mp4"
        vf = (
            f"scale={plan.output_width}:{plan.output_height}:"
            "force_original_aspect_ratio=increase,"
            f"crop={plan.output_width}:{plan.output_height},setsar=1"
        )
        if abs(s.speed - 1.0) > 0.001:
            vf += f",setpts={1.0/s.speed}*PTS"

        run([
            os.getenv("FFMPEG_BIN","ffmpeg"), "-y",
            "-ss", str(s.source_start), "-t", str(duration),
            "-i", video, "-an", "-vf", vf, "-r", str(plan.fps),
            "-c:v","libx264","-preset","veryfast","-crf","20",str(clip)
        ])
        clips.append(clip)

    if not clips:
        raise RuntimeError("No video segments in edit plan.")

    concat = work / "concat.txt"
    concat.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in clips),
        encoding="utf-8"
    )
    joined = work / "joined.mp4"

    run([
        os.getenv("FFMPEG_BIN","ffmpeg"), "-y",
        "-f","concat","-safe","0","-i",str(concat),
        "-an","-c:v","libx264","-preset","veryfast","-crf","20",
        "-r",str(plan.fps),str(joined)
    ])

    if plan.bgm_ducking:
        af = (
            f"[1:a]volume={plan.voice_gain_db}dB[voice];"
            f"[2:a]volume={plan.bgm_gain_db}dB[music];"
            "[music][voice]sidechaincompress="
            "threshold=0.03:ratio=8:attack=20:release=350[ducked];"
            "[voice][ducked]amix=inputs=2:duration=first:dropout_transition=2[a]"
        )
    else:
        af = (
            f"[1:a]volume={plan.voice_gain_db}dB[voice];"
            f"[2:a]volume={plan.bgm_gain_db}dB[music];"
            "[voice][music]amix=inputs=2:duration=first:dropout_transition=2[a]"
        )

    run([
        os.getenv("FFMPEG_BIN","ffmpeg"), "-y",
        "-i",str(joined), "-i",voice,
        "-stream_loop","-1","-i",bgm,
        "-filter_complex",af,
        "-map","0:v:0","-map","[a]",
        "-c:v","copy","-c:a","aac","-b:a","192k",
        "-shortest",str(out)
    ])
    return str(out)
