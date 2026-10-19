# Preview release notes

LikeThis is an experimental source preview. Install from the [public GitHub repository](https://github.com/wspotter/LikeThis) using the instructions in the [README](../README.md). No wheel download or release asset is assumed here.

The current interface has **Start**, **Saved tasks**, and **Settings**. A saved recording belongs to a task version; prior versions remain available for review. Saving edits creates a new version. Archiving is reversible and preserves the task's recordings and history.

Assistant review is a manual step through an MCP client: the assistant can inspect selected frames and submit a separate proposal, and the person reviews that proposal in LikeThis. Supported execution includes deterministic file recipes with a preview and explicit approval, the bundled local fixture, and a public GitHub issue brief whose exact plan must be approved before it runs. Automatic review dispatch and general replay of personal recordings are unavailable.

See [status and capability limits](STATUS.md), [client setup](CLIENTS.md), and [verification](VERIFICATION.md). Client examples and source test results do not establish that a particular user's installation or client connection works.
