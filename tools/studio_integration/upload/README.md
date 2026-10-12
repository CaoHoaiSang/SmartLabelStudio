# Studio ORI model delivery

This extends the existing RKNN upload control. Choose the `.rknn` and its exported
`.json`; ORI requires JSON. The backend checks the binary SHA256, class order,
RK3588/640 input, five outputs, heading/normalization and export verification
before saving. After success, **Use this ORI model** selects model/type/classes in
the Settings draft. The operator saves Settings through the existing flow.
It does not enable Vision AI or start a robot program.

Legacy DET/SEG/ORI artifacts without sidecars remain loadable. Legacy clients
still auto-finalize chunk uploads. New clients send `paired-v1`, wait for all ACKs,
then finalize with JSON; receiving the last chunk cannot save an incomplete pair.
Upload responses/progress are scoped to the unique upload ID. A legacy replacement
removes stale JSON; storage failures restore both prior files. Upload/save continue
to reject a running system, including a start between receiving and saving.

## Prepare and apply against actual source

The Python transformer only edits known upload anchors and fails on unrecognized
source. It preserves unrelated modifications, including Template Matching. Input
checkouts are read only. Output includes full reviewable payloads and a manifest
pinning exact original/replacement checksums. Never commit generated device source,
models, credentials, runtime data or backups to this repository.

```sh
python prepare_patch.py --backend-root /home/radxa/deltax_pp_sw \
  --web-root /home/radxa/deltax_pp_web --output /tmp/studio-upload-reviewed
python apply_patch.py --bundle /tmp/studio-upload-reviewed \
  --backend-root /home/radxa/deltax_pp_sw --web-root /home/radxa/deltax_pp_web \
  --backup /home/radxa/studio-backups/unique-upload-backup
```

Before activating, the **operator** stops the production program in Studio and
confirms it is safe to restart. The **assistant** checks source hashes, backs up,
applies the decoder/AIX patch from the parent directory with `--layout radxa`,
applies this upload patch, builds the web, and restarts only the necessary services.
Do not restart a running production program as part of a model compatibility test.
The Radxa layout discovers the unique installed YOLORKNN under the backend venv;
editing only the installer library does not update the installed library.

Use a fresh backup directory. For rollback while stopped, restore each saved file
to its profile/root; remove `rknn_model_upload.py` only if `before_sha256` in the
backup manifest is null and its current hash still matches the generated payload.
Restore/rebuild the previous web version before restarting. Model/config/data
directories are not patched or rolled back by these tools.

## Verification

- `python -m unittest discover -s tests -p test_studio_model_upload.py -v`
  checks real prepatch Radxa upload methods, paired/legacy finalization, invalid
  metadata, stopped guards, failed-save rollback, concurrent writers and checksums.
- `python -m tools.studio_integration.upload.verify_fixture --output /tmp/hook.ts`
  and `node tools/studio_integration/upload/verify_transport.cjs /tmp/hook.ts`
  check actual generated hook behavior with TypeScript 5.5.3, retry/duplicate ACK,
  foreign responses/progress, finalization failure/timeout and cleanup.
- Run `tsc --noEmit --incremental false` on an isolated copy of the actual device
  web source/dependencies. Compare baseline and patched diagnostics.
- NPU inference and real object/robot acceptance are separate. Export verification
  metadata is not a signature or a promise of recognition accuracy.

Fixtures contain only upload methods extracted from Radxa at
192.168.100.135 on 2026-10-12. Full-source checksums and hardware test evidence
stay in the owner's local audit, outside Git.
