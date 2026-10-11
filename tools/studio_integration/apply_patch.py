"""Apply the reviewed Studio ORI patch to an exact compatible source checkout."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil


def apply(root, backup):
    bundle = Path(__file__).resolve().parent
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    root, backup = Path(root).resolve(), Path(backup).resolve()
    pending = []
    for entry in manifest["files"]:
        target = (root / entry["path"]).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Patch path escapes root")
        current = hashlib.sha256(target.read_bytes()).hexdigest()
        if current == entry["after_sha256"]:
            continue
        if current != entry["before_sha256"]:
            raise ValueError(f"Source changed: {entry['path']}. Review/rebase the patch before applying.")
        payload = bundle / entry["payload"]
        if hashlib.sha256(payload.read_bytes()).hexdigest() != entry["after_sha256"]:
            raise ValueError("Patch payload checksum mismatch")
        pending.append((entry, target, payload))
    # Validate every file before modifying any. Backups are immutable and outside the payload.
    for entry, target, _ in pending:
        saved = backup / entry["path"]
        saved.parent.mkdir(parents=True, exist_ok=True)
        if saved.exists() and hashlib.sha256(saved.read_bytes()).hexdigest() != entry["before_sha256"]:
            raise ValueError(f"Conflicting backup: {saved}")
        if not saved.exists():
            shutil.copy2(target, saved)
    for entry, target, payload in pending:
        if hashlib.sha256(target.read_bytes()).hexdigest() != entry["before_sha256"]:
            raise ValueError(f"Source changed during apply: {target}")
        staged = target.with_name(target.name + ".ori-tmp")
        shutil.copyfile(payload, staged)
        os.replace(staged, target)
    print(f"Applied {len(pending)} Studio files; backup: {backup}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--backup", required=True)
    args = parser.parse_args()
    apply(args.root, args.backup)
