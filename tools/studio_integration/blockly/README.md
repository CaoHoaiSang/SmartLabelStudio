# Studio Blockly packing repair

Build from a fresh, reviewed copy of Radxa files with `prepare_patch.py BASELINE OUTPUT`.
The baseline paths are relative to `/home/radxa`. It patches selected Pick methods,
the script executor, loop generators and Blockly toolbox, and adds `packing-blocks.ts`.
It does not modify Template Matching, AIX angles, Tracking, robot calibration or models.

The MiGoi workspace keeps its original mechanics and tool offset arithmetic unless
an explicit measurement is supplied with `--tool-dx`. This sets the symmetric X
offset and the grid X pitch to twice that measurement; it never guesses geometry
from the model. For this operator's measured 63 mm on each side, use `--tool-dx 63`
(126 mm separation). It selects
class 0, counts completed placement sequences, stops at the validated grid capacity,
waits up to `SECOND_WAIT_MS=2000` for the second packet and places the first alone on
timeout. Two packets descend together only when the two cells match the rotated
±tool offsets and share a Z height. Otherwise collect/place a single packet. The
operator's midpoint/descent/release-both/lift sequence is preserved. An odd last
slot collects only one packet. A new run after changing the box
starts a fresh count; stopping midway does not retain a count for resuming a partly
filled box. Empty the box before restarting after an interrupted run.

The builder deliberately leaves `code` empty: regenerate it with the deployed Blockly
version and all its custom definitions in an isolated staging directory, then update
the program hash in the manifest. Never deploy a JSON with empty/stale executable code.
Reject generator warnings and compare a second generation before activation.

The executor cancels at Python script lines; Pick checks between movement/IO calls.
This prevents subsequent commands after cooperative Stop; it cannot interrupt a
motion command already accepted by firmware and does not replace the physical E-stop.
The executor stays busy until the active stack has unwound. Cancellation reports a
stopped status, not an arithmetic error or a completed box. Vacuum placement, including
the separate tray helper, descends before releasing; vacuum pickup retains early suction.

`packing_capacity`, `packing_pair_fits`, `wait_object_in_robot_area` and `script_completion_message` are
reusable toolbox blocks. The completion message is sent through the existing Studio
script status event. No sensor input, automatic conveyor or new-box signal is assumed.
With confirmation disabled, counts represent completed command sequences rather than
independently verified physical packets. Existing angle and measured tool offsets need real
mechanical validation; this patch does not infer them from images or old settings.

Before activation verify source/program hashes and idle runtime, back up affected
source/program and the web build, build the staged web, and apply only manifest files.
Do not enable auto-start or run the robot as part of software verification. Keep the
operator's current program edits if a baseline hash has changed; rebuild/review instead
of overwriting them. The actual program, snapshots and compiled web stay outside Git.

Checks: `python -m unittest discover -s tests -p test_studio_blockly_packing.py -v`;
`NODE_PATH=... node tools/studio_integration/blockly/verify_blocks.cjs` with
TypeScript 5.5.3 and Blockly 11.2.1. Run the actual regenerated program with mock hardware
for paired/single/mixed pickups and odd capacities before deploying.
