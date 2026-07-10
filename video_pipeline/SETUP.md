# Local development setup

1. Create and activate a Python 3.13 virtual environment.
2. Install packages with `python -m pip install -r requirements.txt`.
3. Install the Playwright browser only if using `generate_images_online.py`: `python -m playwright install chromium`.
4. Install FFmpeg and ensure it is available to MoviePy.
5. Copy `.env.example` to `.env` and add new ElevenLabs and Runware keys.
6. Run `python manage.py migrate`.
7. Start the local server with `python manage.py runserver 127.0.0.1:8000`.

The ElevenLabs and Runware keys previously embedded in source must be rotated in their provider dashboards. Do not reuse exposed keys.
