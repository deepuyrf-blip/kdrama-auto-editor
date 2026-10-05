import asyncio
import json
import os
import time
from typing import Any

import httpx

from .ffmpeg import detect_scenes, probe
from .models import EditPlan, EditSegment

MANUS_BASE = os.getenv("MANUS_API_BASE", "https://api.manus.ai")
MANUS_KEY = os.getenv("MANUS_API_KEY", "")


def _sequential_segments(scenes: list[tuple[float, float]], target: float, source_duration: float, voice_duration: float) -> EditPlan:
    if target <= 0 or source_duration <= 0:
        raise ValueError("Invalid media duration")
    ratio = source_duration / target
    segments: list[EditSegment] = []
    cursor = 0.0
    repeat = 0

    # For moderate differences, preserve the complete story and globally retime.
    if 0.80 <= ratio <= 1.25:
        for start, end in scenes:
            if cursor >= target - 0.02:
                break
            wanted = min((end - start) / ratio, target - cursor)
            segments.append(EditSegment(
                source_start=start, source_end=min(end, start + wanted * ratio),
                target_start=cursor, target_end=cursor + wanted,
                speed=ratio, repeat_index=0,
                reason="Preserve scene order; global retime to narration duration",
            ))
            cursor += wanted
        strategy = "global_retime"
        notes = ["Video is retimed within the safe 0.8x–1.25x range."]
    elif ratio > 1.25:
        # Video is materially longer: cut at scene boundaries, then trim the last scene.
        strategy = "scene_cut"
        notes = ["Video longer than narration: removed excess scenes and trimmed the final scene."]
        for start, end in scenes:
            if cursor >= target - 0.02:
                break
            wanted = min(end - start, target - cursor)
            segments.append(EditSegment(
                source_start=start, source_end=start + wanted,
                target_start=cursor, target_end=cursor + wanted,
                speed=1.0, repeat_index=0,
                reason="Scene-aware cut to fit narration",
            ))
            cursor += wanted
    else:
        # Video is materially shorter: loop complete scenes in order instead of
        # creating an ugly 2x slow motion. The last repeated scene is trimmed.
        strategy = "scene_loop"
        notes = ["Video shorter than narration: looped scene units and trimmed the final repeat."]
        while cursor < target - 0.02 and repeat < max(8, len(scenes) * 8):
            for start, end in scenes:
                if cursor >= target - 0.02:
                    break
                wanted = min(end - start, target - cursor)
                segments.append(EditSegment(
                    source_start=start, source_end=start + wanted,
                    target_start=cursor, target_end=cursor + wanted,
                    speed=1.0, repeat_index=repeat,
                    reason="Loop scene to cover longer narration",
                ))
                cursor += wanted
            repeat += 1

    if not segments:
        raise ValueError("Could not create a timeline from detected scenes")
    # Floating-point and codec rounding can leave a tiny gap; make the last target exact.
    segments[-1].target_end = target
    return EditPlan(
        segments=segments,
        source_video_duration=source_duration,
        voice_duration=voice_duration,
        timeline_duration=target,
        duration_strategy=strategy,
        notes=notes + [f"Detected {len(scenes)} scene interval(s).", "Original video audio is muted."],
    )


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {"type": "array", "items": {"type": "object", "properties": {
            "source_start": {"type": "number"}, "source_end": {"type": "number"},
            "target_start": {"type": "number"}, "target_end": {"type": "number"},
            "speed": {"type": "number"}, "reason": {"type": "string"}
        }, "required": ["source_start", "source_end", "target_start", "target_end", "speed", "reason"], "additionalProperties": False}},
        "notes": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["segments", "notes"],
    "additionalProperties": False,
}


async def _manus_refine(local_plan: EditPlan, scenes: list[tuple[float, float]], script: str) -> EditPlan:
    """Ask Manus for a semantic scene order when an API key is configured.

    The local plan remains the safe fallback. The API receives timecoded scene
    intervals, narration text and hard timing constraints, then its result is
    validated against the local timeline before use.
    """
    if not MANUS_KEY or not script.strip():
        return local_plan
    prompt = {
        "role": "k-drama short video editor",
        "instruction": "Choose and order the supplied scene intervals to support the Hindi narration. Do not invent timestamps. Keep target time continuous from 0 to the narration duration. Prefer cuts at scene boundaries; only use speed between 0.8 and 1.25 unless a final trim is needed.",
        "narration_script": script,
        "voice_duration": local_plan.voice_duration,
        "video_duration": local_plan.source_video_duration,
        "local_plan": local_plan.model_dump(),
        "scene_intervals": [{"start": s, "end": e} for s, e in scenes],
    }
    headers = {"x-manus-api-key": MANUS_KEY, "content-type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f"{MANUS_BASE}/v2/task.create", headers=headers, json={
            "message": {"content": json.dumps(prompt, ensure_ascii=False)},
            "structured_output_schema": PLAN_SCHEMA,
        })
        response.raise_for_status()
        task = response.json()
        task_id = task.get("task_id") or task.get("data", {}).get("task_id")
        if not task_id:
            return local_plan
        for _ in range(40):
            await asyncio.sleep(2)
            messages = await client.get(f"{MANUS_BASE}/v2/task.listMessages", headers=headers, params={"task_id": task_id, "order": "asc"})
            messages.raise_for_status()
            payload = messages.json()
            events = payload.get("data", payload if isinstance(payload, list) else [])
            for event in events:
                result = event.get("structured_output_result") if isinstance(event, dict) else None
                if result and result.get("success"):
                    return _validate_manus_plan(result["value"], local_plan, scenes)
    return local_plan


def _validate_manus_plan(raw: dict[str, Any], fallback: EditPlan, scenes: list[tuple[float, float]]) -> EditPlan:
    allowed = [(round(a, 3), round(b, 3)) for a, b in scenes]
    segments: list[EditSegment] = []
    expected = 0.0
    for item in raw.get("segments", []):
        ss, se = float(item["source_start"]), float(item["source_end"])
        ts, te = float(item["target_start"]), float(item["target_end"])
        speed = max(0.8, min(1.25, float(item.get("speed", 1.0))))
        if se <= ss or ts < -0.02 or te <= ts or abs(ts - expected) > 0.15:
            return fallback
        if not any(ss >= a - 0.15 and se <= b + 0.15 for a, b in allowed):
            return fallback
        segments.append(EditSegment(source_start=ss, source_end=se, target_start=max(0, ts), target_end=te, speed=speed, reason=item.get("reason", "Manus semantic scene match")))
        expected = te
    if not segments or abs(expected - fallback.timeline_duration) > 0.25:
        return fallback
    fallback.segments = segments
    fallback.duration_strategy = "manus_scene_match"
    fallback.notes = list(dict.fromkeys(fallback.notes + raw.get("notes", []) + ["Scene order refined by Manus API structured output."]))
    return fallback


async def make_plan(video: str, voice: str, script: str) -> EditPlan:
    video_info, voice_info = probe(video), probe(voice)
    scenes = detect_scenes(video)
    local = _sequential_segments(scenes, voice_info["duration"], video_info["duration"], voice_info["duration"])
    try:
        return await _manus_refine(local, scenes, script)
    except Exception as exc:
        local.notes.append(f"Manus planner unavailable; deterministic planner used ({type(exc).__name__}).")
        return local
