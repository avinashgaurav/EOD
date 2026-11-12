# EOD in Claude Code

**MCP server** (read-only, local; hide rules and redaction apply):

```sh
claude mcp add eod -- python3 "$HOME/Library/Application Support/EOD/bin/eod-mcp"
```

Tools: `eod_day`, `eod_week`, `eod_standup`, `eod_search`. Ask "what did I ship this week?" or "write my standup".

**Slash command:** copy `eod.md` to `~/.claude/commands/eod.md`, then type `/eod` in Claude Code.
