# This repo

Comms & outreach platform (Outlook + WhatsApp + LinkedIn ingest, identity
resolution, a small ops dashboard). Build plan and specs live under
`docs/`; day-to-day operational knowledge (deploying, connecting each
channel, troubleshooting a stuck sync) lives in `runbook.md` — read that
first for anything deployment-related.

**Deploying a new instance:** use the `deploy-comms-platform` skill
(`.claude/skills/deploy-comms-platform/`) rather than working through
`runbook.md` by hand — it walks each step with a verification command
attached, so a failure surfaces immediately instead of silently moving
on.

## `openspec/` and the `openspec-*` skills — not needed for deployment

`.claude/skills/openspec-explore`, `openspec-propose`, and the other
`openspec-*` skills are Eva's own internal dev workflow for planning
changes to this codebase (proposals, design docs, task lists under
`openspec/`). They require the `openspec` CLI (an npm package, not a
dependency of this project) to be installed separately — most sessions
working with this repo won't have it.

None of this is needed to deploy or run the platform itself. If a task
here is about deployment, connecting a channel, or fixing a running
instance, `openspec/`'s contents are historical planning record, not
something to run — use `runbook.md` and the `deploy-comms-platform`
skill instead. If an `openspec-*` skill's underlying `openspec` command
fails because the CLI isn't installed, that's expected on a machine that
isn't Eva's own dev setup; it's not a sign anything else is broken.
