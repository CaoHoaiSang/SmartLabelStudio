# SmartLabel development context

SmartLabel is the company's technical tool for collecting/importing images,
labeling, review, dataset QA, training, evaluation and model delivery. Prioritize
operator throughput and label/model quality while preserving existing projects.
Hydro households consume provider models; they need not label data or import QA reports.

Read `docs/CURRENT_INTEGRATION_STATUS.md` and relevant source before extending it.
On the owner's workstation also read `D:/DeltaX/AI_KL/SYSTEM_CONTEXT.md` and the
latest audit. This local memory may be absent elsewhere; source remains authoritative.

Owner's Git workflow requirement (2026-09-11): implement each new feature or major
change on a dedicated task branch, created or selected before editing. After
relevant checks pass, commit the task changes and push that branch to GitHub.
The owner has authorized this normal branch/commit/push workflow; do not ask for
the same permission again. Stage only task-owned changes; preserve existing
workspace/project edits and keep datasets, runtime artifacts and secrets out of
new commits. Verify the remote received the commit and report the branch, commit
and GitHub link. This does not authorize merging the main branch or force-pushing.

Check Git status before edits. Existing tracked `workspace/` data and model artifacts
are legacy; do not rewrite history, untrack them wholesale, overwrite labels, or
discard user changes during routine work. Do not add new runtime data to Git.

Keep Hydro dataset/bundle contracts compatible and DeltaX RKNN exports distinct.
Reuse the existing job ownership and project-switch protections for background work.
Dataset split integrity does not establish model accuracy; `validated_holdout`
currently reflects dataset QA and must not be described as a measured accuracy guarantee.

Run relevant tests with `python -m unittest discover -s tests -v`; these create
temporary projects. Do not use customer projects for test mutations. Update current
documentation and record what was tested locally versus on deployment hardware.
