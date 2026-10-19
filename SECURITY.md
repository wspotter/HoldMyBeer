# Security and local data

LikeThis is an experimental, single-user local application. Keep its server on loopback; it has no multi-user authentication or supported public-network deployment mode. Do not expose it to a LAN or the internet.

## Recordings and assistant access

Recordings, notes, proposals and run artifacts are private workspace data. The web app uses `LIKETHIS_DATA_DIR`, then `HMB_DATA_DIR`, then an existing `~/.local/share/holdmybeer` folder, otherwise `~/.local/share/likethis`. The MCP bridge and compatibility CLI still use `HMB_DATA_DIR` and the legacy default. Configure the same explicit directory for both processes; see [client setup](docs/CLIENTS.md).

Recording and decoding happen locally. When an assistant requests session text or selected frames, those results enter its conversation and may be processed by its model provider. Local storage does not guarantee local inference. Avoid sensitive recordings, and review the assistant provider's data handling before sharing frames.

Never commit runtime databases, recordings, screenshots, exported skills containing private task details, credentials, cookies, or customer data. Review any evidence before attaching it to a public issue.

## Execution boundaries

Teaching proposals are review-only: they do not approve or execute a recording. The MCP bridge can execute the separate GitHub issue-brief workflow only after its exact plan has been approved in the local UI. Browser trials are limited to the bundled fixture's action allowlist. Deterministic file recipes have separate explicit approval controls; general browser, GUI and terminal replay is unavailable. See [the contract](docs/CONTRACT.md) for the supported operations.

Frame decoding accepts stored session IDs rather than arbitrary paths or remote URLs, uses restricted decoder protocols, and has subprocess time limits. The native Hermes plugin is a separate status-only scaffold. None of these controls makes the server suitable for untrusted network access.

## Report a vulnerability

Use this repository's private vulnerability reporting if available. Otherwise contact a maintainer privately before disclosing an exploit. Include the impact, affected version and a sanitized reproduction; do not post secrets or personal recordings in a public issue.
