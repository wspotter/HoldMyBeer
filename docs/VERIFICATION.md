# Reproducing checks

Use a Python 3.10+ source checkout and install the development dependencies:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m playwright install chromium
python -m pytest
```

The suite includes local application and browser checks. A successful local suite describes the checkout tested; it does not establish behavior on every operating system, acceptance by every MCP client, or general workflow replay. Browser tests use the bundled fixture and should not use personal accounts or recordings.

To inspect the runtime prerequisites without changing application data, run:

```sh
likethis doctor
```

The doctor checks required imports and Playwright's Chromium executable. It does not install them. Recording-frame extraction also requires `ffmpeg` and `ffprobe` on `PATH`.

For the fixture's procedure shape and observable retained result, see [the fixture example](FIXTURE_EXAMPLE.md). Do not describe a client as connected based only on a configuration file or a successful MCP handshake; verify the client can retrieve the intended data and, where image review is claimed, receives and interprets actual images.
