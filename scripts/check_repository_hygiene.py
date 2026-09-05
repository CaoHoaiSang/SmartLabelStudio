#!/usr/bin/env python3
"""Block new runtime data, model artifacts, and credentials without rewriting legacy history."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath


FORBIDDEN_DIRECTORIES = {
    "cache",
    "captures",
    "data",
    "dataset",
    "datasets",
    "exports",
    "models",
    "runs",
    "runtime",
    "workspace",
}
FORBIDDEN_SUFFIXES = {
    ".7z", ".bin", ".ckpt", ".engine", ".jpeg", ".jpg", ".onnx", ".p12",
    ".pem", ".pfx", ".plan", ".png", ".pt", ".pth", ".rar", ".rknn",
    ".tflite", ".weights", ".zip",
}
FORBIDDEN_FILENAMES = {".env", "credentials.json", "project.json", "secrets.h"}
SECRET_PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    "credentialed MongoDB URI": re.compile(r"mongodb(?:\+srv)?://[^\s\"']+:[^\s\"']+@"),
}
MAX_TEXT_SCAN_BYTES = 2 * 1024 * 1024


def git_lines(*arguments: str) -> list[str]:
    result = subprocess.run(
        ["git", *arguments], check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def is_example(path: str) -> bool:
    lowered = path.lower()
    return ".example." in lowered or lowered.endswith(".example")


def forbidden_reason(path: str) -> str | None:
    normalized = PurePosixPath(path)
    if is_example(path):
        return None
    if {part.lower() for part in normalized.parts[:-1]} & FORBIDDEN_DIRECTORIES:
        return "runtime/data directory"
    filename = normalized.name.lower()
    if filename in FORBIDDEN_FILENAMES or filename.startswith(".env."):
        return "private runtime configuration"
    if normalized.suffix.lower() in FORBIDDEN_SUFFIXES:
        return "binary dataset/model/archive artifact"
    return None


def scan_secrets(paths: list[str]) -> list[str]:
    findings: list[str] = []
    for relative in paths:
        if is_example(relative):
            continue
        path = Path(relative)
        if not path.is_file() or path.stat().st_size > MAX_TEXT_SCAN_BYTES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{relative}: possible {label}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all", action="store_true")
    mode.add_argument("--base-ref")
    arguments = parser.parse_args()

    if arguments.all:
        policy_paths = git_lines("ls-files")
        secret_paths = policy_paths
    else:
        policy_paths = git_lines("diff", "--name-only", "--diff-filter=A", arguments.base_ref, "HEAD")
        secret_paths = git_lines("diff", "--name-only", "--diff-filter=ACMR", arguments.base_ref, "HEAD")

    findings = [
        f"{path}: {reason}"
        for path in policy_paths
        if (reason := forbidden_reason(path)) is not None
    ]
    findings.extend(scan_secrets(secret_paths))
    if findings:
        print("Repository hygiene check failed:", file=sys.stderr)
        for finding in sorted(set(findings)):
            print(f"  - {finding}", file=sys.stderr)
        print("Legacy files remain untouched; do not add new runtime data to Git.", file=sys.stderr)
        return 1

    print(f"Repository hygiene check passed ({len(policy_paths)} policy paths, {len(secret_paths)} secret-scan paths).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
