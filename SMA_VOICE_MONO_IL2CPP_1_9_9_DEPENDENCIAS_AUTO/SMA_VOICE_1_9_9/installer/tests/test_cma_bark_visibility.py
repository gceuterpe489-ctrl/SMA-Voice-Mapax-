import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class CmaBarkVisibilityTests(unittest.TestCase):
    def setUp(self): self.s=(ROOT/'src/SMAVoiceCapture.cs').read_text()
    def test_recent_evidence_requires_exact_active_text(self):
        self.assertIn('!c.gameObject.activeInHierarchy',self.s)
        self.assertIn('!behaviour.isActiveAndEnabled',self.s)
        self.assertIn('write.Text == current',self.s)
        self.assertIn('current == CleanPoll(notice.Original) || current == CleanPoll(notice.Translation)',self.s)
        self.assertIn('(now - notice.Changed).TotalSeconds <= 4',self.s)
    def test_repeated_notifications_do_not_renew_evidence(self):
        self.assertIn('prev.Text == text) return',self.s)
        self.assertIn('else { prev.Received = item.Received; }',self.s)
    def test_visibility_fallback_preserves_authorization(self):
        self.assertIn('if (!visible && barkEvidence) text = current;',self.s)
        self.assertIn('if (bark) authorized = enableCmaBark && VerifiedBarkIdentity(identity, name);',self.s)
        self.assertIn('instance.FemaleBarkPath(path)',self.s)
    def test_duplicate_wrappers_and_diagnostics(self):
        self.assertIn('!visitedTextIds.Add(target.GetInstanceID())',self.s)
        self.assertIn('SMA BARK_OBSERVE',self.s)
        self.assertIn('SMA SESSION_BARK_END',self.s)
