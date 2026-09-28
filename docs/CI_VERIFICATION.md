# CI verification — 2026-09-28

The Ubuntu 22.04 / Python 3.10 job runs the entire unittest suite. Install
`onnx==1.19.1` explicitly: graph creation/checking differs from ONNX Runtime
inference. This version is already used on the Windows workstation; no model
or production runtime upgrade is required by the repair.

GUI tests run in a dedicated Xvfb screen with Openbox. Xvfb alone lacks the
window-manager behavior needed for transient ownership/stacking assertions.
`scripts/run_ci_tests.sh` starts only its own Openbox, waits up to five seconds
for EWMH registration, fails if unavailable, and cleans up its process on exit.
Invoke only through `xvfb-run` as in the workflow, not on an operator's desktop.
Do not skip stacking/grab/size assertions to hide failures.

The Windows-only camera guard test mocks both platform and CREATE_NO_WINDOW
on Linux. The production Windows gate stays intact; a new test proves rejection
before any socket/process access on unsupported platforms.

Full Windows regression also runs on temporary fixture projects. Do not train,
export or alter the user's real project/workspace for CI verification.

## References checked 2026-09-28

- [Python subprocess](https://docs.python.org/3/library/subprocess.html):
  CREATE_NO_WINDOW is Windows-specific.
- [Openbox autostart](https://openbox.org/help/Autostart): plain `openbox` does
  not start desktop-session autostart programs.
- [GitHub runner isolation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job):
  declare the full environment for each job.

## Post-push evidence

Verify remote SHA and read Actions for that exact SHA. Report push, local tests
and CI separately. Pending, missing, cancelled or failed runs are not success.
Repair failures rather than skipping assertions or muting notifications.

Original failures: [run 36242276720](https://github.com/CaoHoaiSang/SmartLabelStudio/actions/runs/36242276720).
Final Windows/Linux results and limits are in the AI_KL handoff audit. No merge,
branch deletion or application restart is implied.
