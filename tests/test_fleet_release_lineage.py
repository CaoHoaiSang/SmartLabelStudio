import json
from pathlib import Path
import unittest
from smartlabel.hydro_release_candidate import validate_release_candidate
from smartlabel.fleet_release_lineage import candidate_digest

class ReleaseLineageContractTests(unittest.TestCase):
    def test_shared_v2_vectors_and_unicode_digest(self):
        vectors=json.loads((Path(__file__).parent/'fixtures/fleet-model-releases-v2/vectors.json').read_text(encoding='utf-8'))
        candidate=validate_release_candidate(vectors['candidate'])
        self.assertEqual(candidate_digest(candidate),vectors['candidateDigest'])
        for row in vectors['invalid']:
            with self.subTest(name=row['name']),self.assertRaises(ValueError):validate_release_candidate(row['candidate'])
