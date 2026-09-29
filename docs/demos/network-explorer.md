# Network Explorer: five-minute demonstration

This demo uses fictional people and messages. Graph projection and quick search are deterministic; the optional strategy assistant makes real Anthropic calls over those fictional records. This is not live extraction or a production data migration.

## Run

From this checkout with the project's dependencies installed:

```powershell
python -m scripts.network_demo --port 5055
```

To enable Claude using an existing local env file (the key stays server-side):

```powershell
python -m scripts.network_demo --port 5055 --env-file ../repo/.env
```

Uses `ANTHROPIC_MODEL` when set, otherwise `claude-haiku-4-5-20251001`.
The installed project dependencies must include `anthropic`. There are at most
two model calls per question and twenty questions per server session; reset
scenario does not reset this API budget. No background model calls occur.

Open http://127.0.0.1:5055/inbox to begin inside the familiar Inbox. The left sidebar's Graph entry opens the full knowledge graph at http://127.0.0.1:5055/network. The search bar (or Ctrl/Cmd+K) opens contact discovery. The local process binds only to loopback. Keep it running during the presentation.

On Eva's current machine the existing interpreter is `C:\Users\Eva Ng\Desktop\ironman\repo\.venv\Scripts\python.exe`; the isolated checkout is `C:\Users\Eva Ng\Desktop\ironman\network-demo-worktree`.

## Presentation

**0:00-1:00 - Start with a business question.** Click the top search bar and enter: `Find an accountant with logistics experience, preferably someone I worked with before`. Inspect Required Accounting, Required Logistics and Preferred Collaborator. Maya appears before Priya because the collaboration preference is supported. Inspect the matching evidence; the source messages are fictional. Change `preferably` to `must` to require collaboration.

**1:00-2:00 - Inspect the person, then the network.** Open Maya's conversation from the results. The list shows several labels and a +N control; the detail exposes all labels and their evidence. Current topic remains separate. Maya can be both a client and a collaborator. Open full network from the embedded graph, or use View in graph from search. The same person and observation date carry over. Discovery uses a constrained language parser and explicit assertions, not open-ended semantic inference or a language model.

**2:00-3:00 - History and immediate relevance.** Select Maya, then Priya. Maya has substantial older two-way interaction; Priya has little but recent interaction. Switch Current relevance / Relationship history. Neither activity measure is a trust score. Leo's frequent cold inbound is explicitly marked as having no observed two-way exchange.

**3:00-4:00 - Time and changing roles.** Clear filters; select Alex Morgan, Operations director (the researcher with the same name is a different ID). Change Known by to 20 August, then 27 September. The September message reports an August employer change and continuing advisory work at the former organization. History view retains the superseded role and its evidence.

**4:00-5:00 - New information and return.** Return to 27 September. Click Simulate reply; Maya's recent activity rises. Reset scenario restores the initial content while advancing the snapshot version. Use Return to conversation to show the embedded view again.

## Three new interactions to show

1. Search Sam, select **Focus neighborhood**, then change **Graph distance**
   from one to two or three hops. Priya and shared university/project contexts
   can appear outside the original name search. Activity is a separate threshold;
   a shared university is not proof that two people know each other.
2. In **Browse entities**, choose **Projects**, then **Harbour expansion**.
   Inspect team responsibilities, Maya's recorded delivery, Priya's blocked and
   overdue cost review, and Alex's follow-up. Open Source update. Change Known by
   to February: the September work updates disappear. Organizations instead show
   their people/functions; person views show tags and shared context.
3. Click **Ask your network**, or **Ask Claude about this project/person**.
   Try the Cybertest example. Claude plans local queries, reads bounded sources,
   then suggests next steps and evidence gaps. Actual source text and graph links
   are derived from cited records. Continue with a follow-up in the same panel.
   Inbox search also has **Ask Claude about a goal or strategy** for questions the
   quick condition parser cannot handle. A failed provider or unsupported citation
   shows an error, never a fabricated fallback answer.

## What to ask Mark after the demo

- Which real business task should this support first, and which people would he expect to find?
- Is the connection and evidence useful enough to act on? What is missing?
- Does the compact view provide sufficient context without interrupting the conversation?

Record these answers separately from technical correctness results. No external message is sent by any demo action.

## Search scope

Supported facets are names, functions, industries, organizations, projects and owner-relative relationships. Both English and Chinese aliases are supported; for example, `找懂物流的会计，最好之前跟我合作过`. The interface displays required and preferred conditions and asks for clarification on unsupported terms instead of silently ignoring them. `Find accountants in Sydney` therefore asks for clarification: this fixture has no location evidence. Tags are derived, read-only projections with sources; editing tags and connecting production data are separate future work.

## Reproduce checks

```powershell
python -m pytest tests/test_network_projection.py tests/test_network_demo.py tests/test_network_browser.py tests/test_network_evaluation.py -q
python -m scripts.evaluate_network_demo --output docs/research/network-demo
python -m scripts.probe_graphiti
```

Browser tests use headless Microsoft Edge, installed on the current Windows machine. Other environments need an installed compatible browser and an adjusted Playwright channel. This is documented as an environment requirement, not a silent test skip.
