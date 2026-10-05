from pydantic import BaseModel, Field

class EditSegment(BaseModel):
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)
    voice_start: float = Field(ge=0)
    voice_end: float = Field(ge=0)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    reason: str = ""

class EditPlan(BaseModel):
    segments: list[EditSegment]
    output_width: int = 1080
    output_height: int = 1920
    fps: int = 30
    mute_source_audio: bool = True
    voice_gain_db: float = 0.0
    bgm_gain_db: float = -20.0
    bgm_ducking: bool = True
    notes: list[str] = []
