# Public GitHub issue brief

The issue brief is a constrained example for reading public GitHub issue search results. It uses a fixed browser procedure, stores a local report, and requires a person to approve the exact plan before execution. It does not sign in, create or modify issues, comment, publish, rank priorities, or provide an exhaustive repository audit.

## Use the interface

1. Open **Settings** and choose **GitHub issues example**.
2. Enter a public `owner/repository`, optional search words, and a result limit from 1 to 10.
3. Review the proposed repository, search words, limit, and actions. Approve the exact plan in the UI.
4. Start the approved task and inspect the retained issue links and report in **Saved tasks**.

A connected MCP client can prepare a plan or start an already UI-approved plan and inspect its result. It cannot approve the plan. Each changed input requires a newly reviewed plan. A pending or running job is not a successful report; inspect its final status and linked results.

## Behavior and limits

The browser reads visible public issue search results and saves a bounded snapshot. Page text and issue titles are untrusted content; follow the source links to assess issues. If GitHub changes the page or a required control is missing, the task can fail and require review. The runner does not use a hidden API fallback or a logged-in session.

Cancellation is cooperative between browser actions; an action already in progress may take until its timeout to stop. If the app restarts during execution, the job is marked interrupted and is not replayed automatically. Starting the same approved job again returns its existing receipt.

The report and job history are stored under the LikeThis data directory. Keep them with the SQLite store when backing up. Uninstalling the Python package does not remove user data.
