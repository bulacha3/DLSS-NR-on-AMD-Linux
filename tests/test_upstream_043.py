"""0.4.3 default migration is scoped, additive and preserves the user's key."""
import unittest
from dlssnr import deploy,upstream
class Overlay043(unittest.TestCase):
 def test_version_and_new_default(self):
  self.assertEqual(upstream.VERSION,'0.4.3')
  self.assertIn(b'OverlayKey=End\n',upstream.DEFAULT_CONFIG)
 def test_existing_key_is_preserved(self):
  for value in ('End','F11','Home','Insert'):
   with self.subTest(key=value):
    data=f'[DlssNrOnAmd]\nOverlayKey={value}\nQuality=reference\nStyle=2\n'.encode()
    out=deploy._ini(data,0,update=True)
    self.assertIn(f'OverlayKey={value}\n'.encode(),out)
    self.assertIn(b'Quality=reference\n',out)
    self.assertIn(b'Style=2\n',out)
    self.assertEqual(out,deploy._ini(out,0,update=True))
 def test_missing_key_added_both_newlines(self):
  for nl in ('\n','\r\n'):
   data=('[DlssNrOnAmd]'+nl+'Quality=fast'+nl+'Style=1'+nl).encode()
   out=deploy._ini(data,0,update=True)
   self.assertIn(('OverlayKey=End'+nl).encode(),out)
   self.assertEqual(out.lower().count(b'overlaykey='),1)
 def test_other_section_not_used(self):
  out=deploy._ini(b'[Other]\nOverlayKey=Home\n[DlssNrOnAmd]\nQuality=reference\n',0,update=True)
  self.assertIn(b'[Other]\nOverlayKey=Home\n',out)
  self.assertIn(b'OverlayKey=End\n',out)
 def test_existing_duplicate_visual_keys_are_not_silently_rewritten(self):
  # Existing policy rejects duplicate synchronization keys but preserves visual keys.
  out=deploy._ini(b'[DlssNrOnAmd]\nOverlayKey=Home\noverlaykey=End\n',0,update=True)
  self.assertIn(b'OverlayKey=Home\noverlaykey=End\n',out)
  self.assertEqual(out.lower().count(b'overlaykey='),2)
if __name__=='__main__':unittest.main()
