import unittest, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime'))
from voice_settings import read_settings
SRC=(ROOT/'src/SMAVoiceCapture.cs').read_text()
BLOCK=SRC.split('private void PollFixedToolkitBox(float now)',1)[1].split('#endif',1)[0]
class FixedToolkitTests(unittest.TestCase):
    def test_exact_observed_layout_not_options(self):
        for token in ('ObjectPath(c) != "/InterviewChatBar"','"InterviewChatBar-container"','InspectChild(row,0)','InspectChild(row,1)','!= 3','IdentityForName(label)','VerifiedBarkIdentity(identity,label)'):
            self.assertIn(token,BLOCK)
        self.assertNotIn('InspectChild(row,2)',BLOCK)
        self.assertNotIn('GreetHerUITK',BLOCK)
    def test_box_queue_and_stability(self):
        for token in ('normalReady : normalFallback','FindBoxLine(name,original,spoken,now,false)','Export("UITKBox",identity.Id,name,spoken,ready,identity.Alias,true,line)','fixedReported = true','SameBoxText(original,fixedLastSource)'):
            self.assertIn(token,BLOCK)
        self.assertIn('if (!ready && !Enabled("TextPoll")) return;',BLOCK)
    def test_backend_guard_and_scene_reset(self):
        self.assertIn('#if SMA_IL2CPP\n            PollFixedToolkitBox(now);\n#endif',SRC)
        self.assertIn('fixedDocument = null; nextFixedScan = 0; fixedNotices.Clear(); ResetFixedBox();',SRC)
    def test_translation_exact_match(self):
        b=SRC.split('private bool FixedTranslation(',1)[1].split('private void PollFixedToolkitBox',1)[0]
        self.assertIn('fixedNotices.TryGetValue(native.Pointer,out notice)',b)
        self.assertIn('(current == before || current == after)',b)
        self.assertIn('return false;',b)
    def test_config_default_and_optout(self):
        self.assertTrue(read_settings()['ENABLE_CMA_FIXED_BOX'])
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'cfg.txt'; f.write_text('ENABLE_CMA_FIXED_BOX=false\n')
            self.assertFalse(read_settings(f)['ENABLE_CMA_FIXED_BOX'])
    def test_visibility_and_diagnostics(self):
        self.assertIn('!FixedNodeShown(nameNode) || !FixedNodeShown(bodyNode)',BLOCK)
        self.assertIn('SMA UITK_BOX_STATE',SRC)
        self.assertIn('SMA SESSION_UITK_BOX_END',SRC)
if __name__=='__main__': unittest.main()
