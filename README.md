# KDrama Auto Editing Agent

A narration-first K-drama Shorts editor. Give it **raw video + Hindi/English narration audio + background music + optional script** and it returns a vertical MP4.

## What the agent does

- Detects visual scene boundaries locally with FFmpeg scene-change analysis.
- Uses the narration duration as the master clock.
- **Video longer than narration:** removes complete scenes first, then trims the last scene.
- **Video slightly longer/shorter:** retimes the complete scene sequence between 0.8x and 1.25x.
- **Video much shorter than narration:** loops scene units in order and trims the final repeat instead of producing extreme slow motion.
- Always mutes the source video's original audio.
- Keeps narration primary and mixes BGM quietly at approximately -26 dB.
- Sidechain-ducks BGM under narration, then applies a final loudness pass.
- Produces 1080x1920, 30 fps, H.264/AAC MP4 with fast start.
- Optionally asks the Manus API to semantically reorder detected scenes using the supplied script. If the API is unavailable or returns an unsafe timeline, the local deterministic plan is used automatically.

## Manus API mode

Copy `.env.example` to `.env` and set:

```bash
MANUS_API_KEY=your_key
MANUS_API_BASE=https://api.manus.ai
```

The API is used only for **planning/scene selection**. Rendering remains local FFmpeg so the app can recover safely from API timeouts and does not depend on a model to produce the final media file.

## Run locally

Install FFmpeg, then:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

## Docker

```bash
docker build -t kdrama-auto-editor .
docker run --rm -p 8000:8000 \
  -v "$PWD/uploads:/app/uploads" \
  -v "$PWD/outputs:/app/outputs" \
  --env-file .env \
  kdrama-auto-editor
```

## API

`POST /api/render` multipart fields:

- `video`: raw video
- `voice`: narration audio
- `bgm`: background music
- `script`: optional narration text for Manus semantic planning

`GET /api/health` reports whether `MANUS_API_KEY` is configured. `POST /api/inspect` returns source durations before rendering.

## Production next steps

For long videos, place `/api/render` behind a job queue and store uploads/outputs in object storage. For stronger semantic matching, add sampled scene thumbnails or low-resolution proxy video as Manus file attachments; the current API adapter deliberately uses timecoded scene metadata and validates every returned timestamp before rendering.
