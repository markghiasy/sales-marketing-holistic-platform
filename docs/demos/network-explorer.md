# Network Explorer: five-minute demonstration

This demo uses fictional people and messages. It is a working deterministic prototype, not live extraction or a production data migration.

## Run

From this checkout with the project's dependencies installed:

```powershell
python -m scripts.network_demo --port 5055
```

Open http://127.0.0.1:5055/inbox?focus=person:maya to begin inside the familiar Inbox. The full explorer is at http://127.0.0.1:5055/network. The local process binds only to loopback. Keep it running during the presentation.

On Eva's current machine the existing interpreter is `C:\Users\Eva Ng\Desktop\ironman\repo\.venv\Scripts\python.exe`; the isolated checkout is `C:\Users\Eva Ng\Desktop\ironman\network-demo-worktree`.

## Presentation

**0:00-1:00 - A relationship in context.** Open Maya's conversation. Explain that this is the existing Inbox layout using the new shared graph component. Select a relationship and View evidence. Maya can be both a client and a collaborator; the assertions remain separate. All content here is fictional.

**1:00-2:00 - Expand to the network.** Click Open full network. The same person, time and graph data carry over. Clear filters if necessary, select Accounting and Harbour expansion. Compare Maya and Priya. The shortlist follows explicit project/function evidence; it is not a natural-language or LLM recommendation.

**2:00-3:00 - History and immediate relevance.** Select Maya, then Priya. Maya has substantial older two-way interaction; Priya has little but recent interaction. Switch Current relevance / Relationship history. Neither activity measure is a trust score. Leo's frequent cold inbound is explicitly marked as having no observed two-way exchange.

**3:00-4:00 - Time and changing roles.** Clear filters; select Alex Morgan, Operations director (the researcher with the same name is a different ID). Change Known by to 20 August, then 27 September. The September message reports an August employer change and continuing advisory work at the former organization. History view retains the superseded role and its evidence.

**4:00-5:00 - New information and return.** Return to 27 September. Click Simulate reply; Maya's recent activity rises. Reset scenario restores the initial content while advancing the snapshot version. Use Return to conversation to show the embedded view again.

## What to ask Mark after the demo

- Which real business task should this support first, and which people would he expect to find?
- Is the connection and evidence useful enough to act on? What is missing?
- Does the compact view provide sufficient context without interrupting the conversation?

Record these answers separately from technical correctness results. No external message is sent by any demo action.

## Reproduce checks

```powershell
python -m pytest tests/test_network_projection.py tests/test_network_demo.py tests/test_network_browser.py tests/test_network_evaluation.py -q
python -m scripts.evaluate_network_demo --output docs/research/network-demo
python -m scripts.probe_graphiti
```

Browser tests use headless Microsoft Edge, installed on the current Windows machine. Other environments need an installed compatible browser and an adjusted Playwright channel. This is documented as an environment requirement, not a silent test skip.
