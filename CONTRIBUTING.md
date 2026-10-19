# Contributing

Thanks for helping make LikeThis clearer and safer. Focused bug reports, documentation improvements, accessibility feedback, and small code changes are welcome. Use GitHub issues or pull requests in [wspotter/LikeThis](https://github.com/wspotter/LikeThis); include what you expected, what happened, and concise reproduction steps.

For local development, use Python 3.10 or newer:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m playwright install chromium
python -m pytest
```

Tests that exercise the browser use the matching Playwright Chromium. Some media checks also require `ffmpeg` and `ffprobe`. See [DEVELOPER.md](DEVELOPER.md) for the project layout and [docs/VERIFICATION.md](docs/VERIFICATION.md) for reproducible capability checks.

Use the bundled fixture and fictional names, captions, and repositories in examples. Do not submit recordings, screenshots with personal information, account access, credentials, cookies, customer data, or private URLs. Redact sensitive values from logs.
