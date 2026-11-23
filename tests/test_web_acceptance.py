"""Deterministic Web acceptance gate tests; no simulated production acceptance."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import web_acceptance as wa


class WebAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.r = wa.new_register("orbit-web")

    def filled(self):
        for key in wa.REQUIREMENTS:
            self.r = wa.record(self.r, key, reference="https://example.org/evidence/" + key,
                               reviewer="QA Owner", passed=True)
        return self.r

    def test_mobile_locked_by_default(self):
        result = wa.evaluate(self.r)
        self.assertFalse(result["mobile_unlocked"])
        self.assertFalse(result["complete"])
        self.assertEqual(len(result["missing"]), len(wa.REQUIREMENTS))

    def test_all_evidence_without_signoff_is_not_accepted(self):
        result = wa.evaluate(self.filled())
        self.assertTrue(result["complete"])
        self.assertFalse(result["accepted"])
        self.assertFalse(result["mobile_unlocked"])

    def test_explicit_human_signoff_unlocks_mobile(self):
        r = wa.signoff(self.filled(), owner="Product Owner",
                       confirmation="ACCEPT WEB orbit-web")
        self.assertTrue(wa.evaluate(r)["accepted"])
        self.assertTrue(wa.evaluate(r)["mobile_unlocked"])

    def test_wrong_confirmation_fails_closed(self):
        with self.assertRaises(PermissionError):
            wa.signoff(self.filled(), owner="Product Owner", confirmation="YES")

    def test_partial_evidence_blocks_signoff(self):
        self.r = wa.record(self.r, wa.REQUIREMENTS[0],
                           reference="https://example.org/evidence/first",
                           reviewer="QA Owner", passed=True)
        with self.assertRaises(PermissionError):
            wa.signoff(self.r, owner="Product Owner",
                       confirmation="ACCEPT WEB orbit-web")

    def test_failed_gate_blocks_signoff(self):
        self.filled()
        self.r = wa.record(self.r, wa.REQUIREMENTS[2],
                           reference="https://example.org/evidence/failure",
                           reviewer="QA Owner", passed=False)
        self.assertIn(wa.REQUIREMENTS[2], wa.evaluate(self.r)["failed"])
        with self.assertRaises(PermissionError):
            wa.signoff(self.r, owner="Product Owner",
                       confirmation="ACCEPT WEB orbit-web")

    def test_change_after_signoff_invalidates_acceptance(self):
        signed = wa.signoff(self.filled(), owner="Product Owner",
                            confirmation="ACCEPT WEB orbit-web")
        updated = wa.record(signed, wa.REQUIREMENTS[0],
                            reference="https://example.org/evidence/new",
                            reviewer="QA Owner", passed=True)
        self.assertFalse(wa.evaluate(updated)["accepted"])

    def test_tampered_evidence_digest_fails_closed(self):
        signed = wa.signoff(self.filled(), owner="Product Owner",
                            confirmation="ACCEPT WEB orbit-web")
        signed["evidence"][wa.REQUIREMENTS[0]]["reference"] = "https://example.org/tampered"
        self.assertFalse(wa.evaluate(signed)["accepted"])

    def test_invalid_evidence_ref_rejected(self):
        with self.assertRaises(ValueError):
            wa.record(self.r, wa.REQUIREMENTS[0], reference="ok",
                      reviewer="QA Owner", passed=True)

    def test_invalid_actor_rejected(self):
        with self.assertRaises(ValueError):
            wa.record(self.r, wa.REQUIREMENTS[0],
                      reference="https://example.org/evidence",
                      reviewer="", passed=True)

    def test_boolean_type_enforced(self):
        with self.assertRaises(ValueError):
            wa.record(self.r, wa.REQUIREMENTS[0],
                      reference="https://example.org/evidence",
                      reviewer="QA Owner", passed=1)

    def test_unknown_gate_rejected(self):
        with self.assertRaises(ValueError):
            wa.record(self.r, "mobile_release",
                      reference="https://example.org/evidence",
                      reviewer="QA Owner", passed=True)

    def test_invalid_project_id_rejected(self):
        with self.assertRaises(ValueError):
            wa.new_register("../outside")

    def test_unknown_evidence_key_rejected(self):
        self.r["evidence"]["forged"] = {}
        with self.assertRaises(ValueError):
            wa.evaluate(self.r)


if __name__ == "__main__":
    unittest.main()
