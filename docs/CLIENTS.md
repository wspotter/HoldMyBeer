# Connect an MCP client

LikeThis includes a stdio MCP server named `likethis-mcp`; the compatible `holdmybeer-mcp` executable and `holdmybeer` configuration names remain supported. Install from the [source repository](../README.md#install-from-source). The server and web app must share a data directory. For a custom directory, set `HMB_DATA_DIR` to the same absolute path for both processes. Start the app separately; the MCP server does not launch it.

A generic MCP client entry uses the executable from the virtual environment:

```json
{
  "mcpServers": {
    "likethis": {
      "command": "/absolute/path/to/HoldMyBeer/.venv/bin/likethis-mcp",
      "env": {
        "HMB_DATA_DIR": "/absolute/path/to/likethis-data"
      }
    }
  }
}
```

Adapt the key and environment syntax to your client's documented stdio configuration. Do not use `uvx` or assume a published PyPI package. Replace both absolute paths with paths on your machine. After editing the client configuration, reconnect it so it can discover the server. A saved configuration or successful handshake alone does not prove the client read LikeThis data.

In **Saved tasks**, select the current task and copy its review request. The request identifies the relevant session and version. Paste it to your connected assistant; LikeThis does not send it automatically. The assistant must inspect actual timestamped frames and submit a review proposal. Check that proposal in LikeThis before reviewing it. Selected images and session text are sent to the client host and follow that provider's data handling.

The MCP tools provide bounded session reads, timestamped frame retrieval, procedure history, review-only proposal submission, and public GitHub issue brief proposal/execution/status. No MCP tool approves understanding or approves an issue brief; those approvals happen in the UI. See [the issue brief guide](ISSUE-BRIEF.md) and [the product contract](CONTRACT.md).

Configuration examples are not client acceptance receipts. To claim image review works for a particular client, verify that it receives image content and that its proposal is grounded in the visible frames.
