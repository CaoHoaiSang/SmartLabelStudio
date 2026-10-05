"""Cross-check the Fleet Phase A2 vectors without requiring the private Fleet checkout."""
import hashlib
import json
import os
from pathlib import Path
import unittest

from smartlabel.hydro_release_candidate import validate_release_candidate


CANDIDATES = (
    "vectors/valid-candidate.json",
    "vectors/candidate-fractional-2.json",
    "vectors/candidate-fractional-6.json",
    "vectors/candidate-operational-unvalidated-v2.json",
)


def vector_root():
    configured = os.environ.get("FLEET_RELEASE_VECTORS")
    if configured:
        root = Path(configured)
        if not root.is_dir():
            raise unittest.SkipTest(f"FLEET_RELEASE_VECTORS does not exist: {root}")
        return root
    bundled = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "fleet-model-releases"
    if bundled.is_dir():
        return bundled
    raise unittest.SkipTest(
        "FLEET_RELEASE_VECTORS is unset and tests/fixtures/fleet-model-releases is absent."
    )


class FleetReleaseVectorTests(unittest.TestCase):
    def test_candidate_vectors_match_artifact_manifest_and_parser(self):
        root = vector_root()
        manifest = json.loads((root / "artifact-manifest.json").read_text(encoding="utf-8"))
        pins = {item["path"]: item["sha256"] for item in manifest["files"]}
        parsed = []
        for relative in CANDIDATES:
            payload = (root / relative).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), pins[relative], relative)
            parsed.append(json.loads(payload.decode("utf-8")))
        self.assertEqual(validate_release_candidate(parsed[0])["schema"], "HydroModelReleaseCandidateV1")
        for candidate in parsed[1:]:
            with self.assertRaises(ValueError):
                validate_release_candidate(candidate)


if __name__ == "__main__":
    unittest.main()
