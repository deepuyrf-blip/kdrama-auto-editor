from .ffmpeg import probe_duration
from .models import EditPlan, EditSegment

def build_fallback_plan(video, voice):
    vd = probe_duration(video)
    ad = probe_duration(voice)
    if vd <= 0 or ad <= 0:
        raise ValueError("Invalid media duration.")
    speed = max(0.85, min(1.20, vd / ad))
    source_duration = min(vd, ad * speed)

    return EditPlan(
        segments=[EditSegment(
            source_start=0,
            source_end=source_duration,
            voice_start=0,
            voice_end=ad,
            speed=speed,
            reason="MVP fallback continuous timeline"
        )],
        notes=[
            "Semantic scene matching is not enabled yet.",
            "Replace make_plan() with Manus/VLM planning."
        ]
    )

async def make_plan(video, voice, script):
    return build_fallback_plan(video, voice)
