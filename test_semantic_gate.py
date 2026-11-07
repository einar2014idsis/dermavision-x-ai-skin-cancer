import unittest
import numpy as np
from semantic_gate import decide, combine_decisions


class SemanticDecisionsTests(unittest.TestCase):
    def test_clear_lesion_accepted(self):
        self.assertEqual(decide([0.35, 0.25, 0.20], 0.02, -0.025).state, "accepted")

    def test_object_rejected(self):
        self.assertEqual(decide([0.1, 0.15, 0.35], 0.02, -0.025).state, "rejected")

    def test_skin_without_clear_lesion_is_uncertain(self):
        self.assertEqual(decide([0.2, 0.35, 0.15], 0.02, -0.025).state, "uncertain")

    def test_close_votes_abstain(self):
        for scores in ([0.25, 0.24, 0.23], [0.24, 0.24, 0.25]):
            self.assertEqual(decide(scores, 0.02, -0.025).state, "uncertain")

    def test_invalid_response_cannot_pass(self):
        for scores in ([np.nan, 0.2, 0.3], [0.2], [0.3, 0.2, np.inf]):
            with self.assertRaises(ValueError):
                decide(scores, 0.02, -0.025)

    def test_reference_rejection_cannot_be_overridden(self):
        positive = decide([0.35, 0.2, 0.15], 0.02, -0.025)
        self.assertEqual(combine_decisions(positive, False).state, "uncertain")
        self.assertEqual(combine_decisions(positive, True).state, "accepted")


if __name__ == "__main__":
    unittest.main()
