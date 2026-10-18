# HoldMyBeer workflow and integration notes

**Status:** Design notes with a current implementation boundary, updated 2026-10-18. This document is not a release acceptance report. Historical sections and candidate names below describe intent at the time; they do not certify that proposed behavior shipped.

## Current user path

The novice path is deliberately direct: record in the browser or import a video, enter the app and task names, choose **Save recording**, then reopen it under **Saved tasks**. It ends with a retained recording. The recording is not a verified procedure, and there is no Easy mode completion or ready-to-run state.

A connected assistant can use the HoldMyBeer MCP server to retrieve bounded session information and selected recording frames, then submit a review-only teaching proposal. Review is not dispatched automatically. Media metadata does not create observations or approval. Multiple-choice answers produce a template with `status: saved_for_review` and `execution_ready: false`. A client configuration snippet or exported skill does not prove a client connected or consumed the tools.

## Implemented execution boundaries

The hybrid file runner has deterministic implementations for:

- `file_rename_batch`
- `file_organize_by_ext`
- `csv_summary_report`

These operations can use sample files for execution checks and can preview changes in a temporary sandbox. Live file operations require explicit approval. The runner pauses with `needs_agent_assist` for generic browser, GUI, terminal, and other unsupported actions; those paths do not emit fabricated success evidence.

Browser procedure execution is a separate, fixed local fixture. Its reviewed procedure uses the fixture-specific `select_media` or `upload`, `fill`, `click`, and `verify_draft` sequence. A retained fixture receipt establishes that bounded fixture run only. It does not establish replay of the user's recording or arbitrary websites. A distinct approved GitHub issue-brief workflow has its own constrained plan, approval, and result record.

## Design intent and deferred work

An earlier mass-adoption sprint brief proposed a broader system: inspect demonstrations to infer typed parameters, compile general GUI/browser/file procedures, run them in a mandatory sandbox, and expose approved recipes through universal dynamic MCP and CLI adapters. Those are design goals, not current capabilities. In particular, HoldMyBeer does not claim native video pixel understanding, automatic generic recipe compilation, arbitrary GUI replay, universal agent installation, a general `holdmybeer run` workflow interface, or a zero-form flow that reports a task ready to execute.

The durable product direction is to make a demonstrated workflow easy to retain and review, then add execution only where the action and its success condition can be checked with evidence. A future feature should name its supported boundary, the evidence it retains, and what remains outside its scope before it is presented as working.

## Historical baseline

The prior candidate was `holdmybeer 0.3.0a3`, organized as App → Task → Versioned Recording → Connected-Agent Review. Historical test, browser, MCP, and Hermes receipts are recorded in [the release candidate notes](../RELEASE-CANDIDATE.md). They apply to their identified checkout and date; they are not evidence for later staged changes.
