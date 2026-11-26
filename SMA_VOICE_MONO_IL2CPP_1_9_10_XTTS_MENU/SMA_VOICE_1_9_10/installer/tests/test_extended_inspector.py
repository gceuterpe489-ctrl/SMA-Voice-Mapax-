import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'src/SMAVoiceCapture.cs').read_text()
class ExtendedInspectorTests(unittest.TestCase):
    def test_request_only_and_legacy_completion_marker(self):
        block=SOURCE.split('private void InspectRequested()',1)[1].split('private static object InspectRead',1)[0]
        self.assertLess(block.index('if (!File.Exists(request)) return;'),block.index('InspectToolkit(result);'))
        self.assertLess(block.index('InspectToolkit(result);'),block.index('result.AppendLine("Total="'))
    def test_toolkit_reflection_and_bounds(self):
        block=SOURCE.split('private static void InspectToolkit(',1)[1].split('private static Component AsComponent',1)[0]
        for token in ('UnityEngine.UIElements.UIDocument','UnityEngine.UIElements.VisualElement','UnityEngine.UIElements.TextElement','rootVisualElement','childCount','worldBound','UITK_TOTAL','depth > 64','nodes >= 10000','InspectFingerprint(value)'):
            self.assertIn(token,block)
        self.assertNotIn('Append(value)',block)
        self.assertNotIn('Export(',block)
    def test_textmesh_no_queue(self):
        block=SOURCE.split('private static void InspectExtraTextMesh',1)[1].split('private static void InspectToolkit(',1)[0]
        self.assertIn('UnityEngine.TextMesh',block)
        self.assertIn('TEXTMESH_TOTAL',block)
        self.assertNotIn('Export(',block)
        self.assertNotIn('Append(value)',block)
    def test_backend_specific_cast(self):
        block=SOURCE.split('private static object InspectCast',1)[1].split('private static object InspectChild',1)[0]
        self.assertIn('#if SMA_IL2CPP',block)
        self.assertIn('nativeCast.MakeGenericMethod(type)',block)
        self.assertIn('type.IsInstanceOfType(obj)',block)
if __name__=='__main__': unittest.main()
