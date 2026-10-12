"""Generate the transport fixture from the audited prepatch Radxa hook."""
import argparse
from pathlib import Path
from tools.studio_integration.upload.prepare_patch import hook_patch

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    source = root / 'tests/fixtures/studio_upload/useSocket.ts'
    Path(args.output).write_text(hook_patch(source.read_text()), encoding='utf-8')
