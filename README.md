# KDrama Auto Editor

Automatic K-drama Shorts renderer.

## MVP
- Raw video + Hindi voice-over + BGM + optional script
- Original video audio is always muted
- Voice is primary
- BGM is low and ducked under voice
- 1080x1920 (9:16) MP4 output
- FFmpeg renderer
- AI planner is isolated in `app/planner.py`

## Docker
```bash
docker build -t kdrama-auto-editor .
docker run --rm -p 8000:8000 -v "$PWD/uploads:/app/uploads" -v "$PWD/outputs:/app/outputs" kdrama-auto-editor
```

Open `http://localhost:8000`.

## Local
Install FFmpeg, then:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
