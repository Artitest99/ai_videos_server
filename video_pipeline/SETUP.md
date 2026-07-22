# Local development setup

1. Create and activate a Python 3.13 virtual environment.
2. Install packages with `python -m pip install -r requirements.txt`.
3. Install the Playwright browser only if using `generate_images_online.py`: `python -m playwright install chromium`.
4. Install FFmpeg and ensure it is available to MoviePy.
5. Copy `.env.example` to `.env` and add new ElevenLabs and Runware keys.
6. Run `python manage.py migrate`.
7. Start the local server with `python manage.py runserver 127.0.0.1:8000`.

The ElevenLabs and Runware keys previously embedded in source must be rotated in their provider dashboards. Do not reuse exposed keys.

## Rendering and hardware notes

- MoviePy uses the FFmpeg executable bundled by `imageio_ffmpeg` in the active virtual environment.
- At startup, `create_video.py` probes AMD `h264_amf`. If it succeeds, final H.264 output and working-video preparation use AMD hardware encoding.
- Intel-only and other unsupported machines automatically use `libx264` with the `veryfast` preset. The early crop, single resize, static fast path, and H.264 working cache still apply on those systems.
- Uploaded videos receive reusable duration-limited portrait working files in `assets/media/<project>/.render_cache/`. The first render may spend time preparing this cache; later renders reuse it while the source file and duration are unchanged.
- Render cache files are derived artifacts. They may be removed while no render is running; the next render recreates them.
- Final output remains vertical 1080x1920 H.264/AAC MP4.