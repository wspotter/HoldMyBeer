# Example: save a fictional fixture draft

Goal: retain `demo-orbit.mp4` with the caption `A paper moon over a fictional
harbour.` in the bundled practice app. This creates a **local fixture draft**,
not a social post, and does not upload or preserve actual video bytes. The
runner supplies harmless generated text bytes under that filename.

The executable procedure is [examples/fixture-draft.json](examples/fixture-draft.json).
Each step records a goal and an observable check:

| Step | Goal | Observable result |
| --- | --- | --- |
| `select_media` / `Media` | Choose the requested filename | Fixture file input receives `demo-orbit.mp4` |
| `fill` / `Caption` | Enter the fresh caption | Caption field contains the supplied fictional text |
| `click` / `Save draft` | Store the local draft | A saved receipt appears |
| `verify_draft` | Check retained evidence | Receipt ID, filename and caption match `/api/fixture/drafts` |

`check` is explanatory text, not arbitrary executable code. The four supported
actions perform the actual checks; no external URL, selector or shell command
is accepted by this procedure.

## Try it in the workspace

1. Follow the [source setup](../README.md#try-the-local-preview), keeping runtime
   data in a private directory outside the checkout.
2. Create a workflow and inspect the bundled practice task. In **Explain the why**,
   review the four action rows above (the JSON is an API/reference artifact, not
   a claim that the UI has a JSON-import button). Save the procedure revision.
3. Authorise one procedure trial with new media, the fictional filename and caption.
   Inspect the retained draft ID and trial receipt; do not equate a button click
   alone with a verified save.
4. For a changed fixture, the save button is `Store draft`. The old `Save draft`
   target stops with `needs_teaching`; do not guess a replacement automatically.
   Review the observed button, edit only that target, save a new revision and
   authorise a new trial. Earlier run snapshots retain the old target.

## Reviewer reproduction

Checked against source base `cc608b177e8d37d70164fdf049af707a38604b2f` with this
example and its test added. In the activated source environment with matching
Playwright Chromium installed, run:

```sh
python -m pytest -q tests/test_backend.py -k documented_fixture_example
```

The test reads the exact JSON above, starts an isolated loopback app and drives
real Chromium. It verifies a normal save, a changed-label stop with no extra
draft, a reviewed target correction, and the immutable earlier procedure snapshot.
All captions/files are fictional; credentials, private recordings and browser
profiles are not used. Generated SQLite data and screenshots are temporary test
artifacts and must not be committed.

This verifies the bundled fixture only. Screen-picker permissions, arbitrary
websites, automatic recording analysis, original-video reuse, live publishing
and production Hermes installation are outside this example.
