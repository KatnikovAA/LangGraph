# Execution ledger — plan: 2026-10-21-web-application.md

Architecture and implementation plan approved 2026-10-21; inline execution.
Baseline: 126 tests OK, 36.938s. Existing stage10 changes preserved.
Ruling: work in explicitly selected current workspace, no worktree reset or commits;
this preserves uncommitted stage10 dependencies. User requested this application here.
Pre-flight: tasks1/3 share Store lifecycle; tasks3/4 share server Chat seed;
tasks4/6/7 share request_id and Run IDs; tasks5/7 share checkpoint pin.
No interface conflicts. Native server Store custom path confirmed in installed code.
Ruling: use port 2025 for web Agent Server, because 2024 already belongs to the
existing Studio server; do not interrupt it. BFF remains 8080.
Task 1: custom Store native startup/shutdown confirmed; native web runtime isolated
under data_root/runtime. Initial launcher used repo cwd only for a startup probe;
no CLI workflows/data were run there. Subsequent runs use isolated runtime.
Tasks 2–6: real HTTP Research, Review/edit/cancel, Chat, Tools/Store, Fork/pin,
Summary, SSE/reconnect, owners and enqueue-after-error: 9 tests OK, 65.081s.
Double Texting: all four strategies verified on real server, no-effects Graph.
Task 8: orderly restart test OK, 10.806s; Threads/checkpoints/messages/Reports,
Profile/Notes and Assistants survived. PowerShell 5.1 needed ASCII script messages.
Ruling: native runtime merges saved Thread config over a new Assistant config;
switching on the same Thread initially kept brief (SDK assertion RED). BFF now
reads selected Assistant config and passes its style explicitly in Runtime Context.
This preserves server Assistant semantics and avoids stale Thread defaults.

Final 2026-10-21: implementation tasks 1–9 locally delivered. Acceptance evidence
and H1–H16 matrix: ../../final-walkthrough.md, final verification section.
137 ordinary tests + 10 HTTP + 1 restart + 1 clean-source case passed separately;
legacy environment 135 passed/14 optional skipped. Independent review was partial:
three reported findings fixed and regression checked, reviewer then hit usage limit.
Browser E2E and responsive checks passed. No paid calls, cloud deployment or commits.
Manual learning/Studio practice, Live quality and production deployment remain open.
