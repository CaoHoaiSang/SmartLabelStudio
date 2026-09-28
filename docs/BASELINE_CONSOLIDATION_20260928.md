# Reviewed baseline candidate — 28/09/2026

Review branch: `integration/smartlabel-reviewed-baseline-20260928`.
Source baseline: `87dc7fd0` (CI-green dependency/platform test repair).
All 48 remote branch heads observed after that repair are ancestors of this
baseline, including main. Main has no unique commits and trails it by 74.
Do not merge these ancestral branches one by one.

This consolidation adds documentation only. Application code, dependencies,
tests, datasets, labels and model files are unchanged from `87dc7fd0`.
Previous verification: Windows 432/432; GitHub Linux 430 passed / 2 existing
skips. A fresh PR/branch CI run must still be checked for this exact head.

The five existing modified workspace project/split JSON files are user data.
They are excluded from this commit and preserved byte-for-byte; no train,
resplit, export, project migration or application restart is performed.
Legacy tracked workspace files remain history, not an invitation to upload
new data or untrack/rewrite the repository wholesale.

The PR is a proposed stable main baseline, not approval to merge. After owner
approval and green CI, prefer a history-preserving merge, establish a release
and rollback reference, and only then propose deleting already merged task
branches. Do not squash the existing multi-task history for this handoff.

Scope limitations: this does not certify Nano, real training after restart,
model accuracy or real-world capture/email delivery. Those remain separate
acceptance tasks described in CURRENT_INTEGRATION_STATUS.md.
