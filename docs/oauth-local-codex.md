# Google invite OAuth + local Codex

`scripts/start-oauth-codex.ps1` keeps the existing `uhkegryo-oauth-local`
database and OAuth configuration while moving only the API and frontend to
Windows host processes. The script maps `app-db` to `127.0.0.1:55433`, stops
the Docker `api` and `frontend`, then starts the host API on
`127.0.0.1:8010` and frontend on `127.0.0.1:3110`.

The named database volume, SearXNG, MCP, and the separate Langfuse practice
containers are not deleted or started. The OAuth settings file remains at its
existing actual MSIX LocalCache path; it is not copied into the repository or
mounted into a container.

The settings file must contain the exact approved account as
`CODEX_OWNER_ACCOUNT_ID`. Missing or mismatched IDs fail closed before job
creation or quota reservation. The account must also remain active and admin.

The launcher disables login-test mode for the host API but does not import
OpenRouter, OpenAI, or Anthropic API keys. It reuses only the existing signed
host Codex login, fixes the model to `gpt-5.6-luna`, and leaves CLI tools,
MCP, web search, plugins, and write access disabled.

```powershell
.\scripts\start-oauth-codex.ps1
```

The command must be run from a normal local PowerShell session. It preserves
data and never runs `down -v`, deletes a volume, or applies a migration.
