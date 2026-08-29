---
name: triage
description: Reads incoming issues and drafts replies
tools: Read, Grep, mcp__github__get_issue, mcp__slack__post_message, WebFetch
---

Read the reported issue, look up related code, and post a summary to Slack.
