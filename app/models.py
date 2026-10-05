from pydantic import BaseModel, Field


class EditSegment(BaseModel):
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)
    target_start: float = Field(ge=0)
    target_end: float = Field(gt=0)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    repeat_index: int = Field(default=0, ge=0)
    reason: str = ""

    @property
    def target_duration(self) -> float:
        return max(0.05, self.target_end - self.target_start)


class EditPlan(BaseModel):
    segments: list[EditSegment]
    source_video_duration: float = 0.0
    voice_duration: float = 0.0
    timeline_duration: float = 0.0
    duration_strategy: str = "scene_cut"
    output_width: int = 1080
    output_height: int = 1920
    fps: int = 30
    mute_source_audio: bool = True
    voice_gain_db: float = 0.0
    bgm_gain_db: float = -26.0
    bgm_ducking: bool = True
    bgm_duck_threshold: float = 0.035
    bgm_duck_ratio: float = 10.0
    notes: list[str] = Field(default_factory=list)
