"""Apply a prepared pair-upload patch with exact source and payload checksums."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def apply(bundle, backend_root, web_root, backup):
    bundle, backup = Path(bundle).resolve(), Path(backup).resolve()
    roots = {'backend': Path(backend_root).resolve(), 'web': Path(web_root).resolve()}
    pending = []
    for entry in json.loads((bundle / 'manifest.json').read_text())['files']:
        root = roots[entry['profile']]
        target, payload = (root / entry['path']).resolve(), (bundle / entry['payload']).resolve()
        if not target.is_relative_to(root) or not payload.is_relative_to(bundle):
            raise ValueError('Patch path escapes root')
        if sha(payload) != entry['after_sha256']:
            raise ValueError('Patch payload checksum mismatch')
        current = sha(target)
        if current == entry['after_sha256']:
            continue
        if current != entry['before_sha256']:
            raise ValueError(f"Source changed: {entry['path']}; review/rebase before applying")
        saved = backup / entry['profile'] / entry['path']
        if saved.exists() and sha(saved) != entry['before_sha256']:
            raise ValueError('Conflicting backup')
        pending.append((entry, target, payload, saved))
    for entry, target, _, saved in pending:
        if target.exists():
            saved.parent.mkdir(parents=True, exist_ok=True)
            if not saved.exists():
                shutil.copy2(target, saved)
    # Record absent paths too, so rollback can remove only introduced helper files.
    backup.mkdir(parents=True, exist_ok=True)
    (backup / 'manifest.json').write_text((bundle / 'manifest.json').read_text())
    for entry, target, payload, _ in pending:
        if sha(target) != entry['before_sha256']:
            raise ValueError('Source changed during apply')
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_name(target.name + '.ori-upload-tmp')
        shutil.copy2(payload, staged)
        os.replace(staged, target)
    print(f'Applied {len(pending)} Studio upload files; backup: {backup}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('bundle', 'backend-root', 'web-root', 'backup'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    apply(args.bundle, args.backend_root, args.web_root, args.backup)
