"""Incremental quality configuration and original-component reuse contracts."""
import unittest
from dlssnr import deploy,upstream
class Quality042(unittest.TestCase):
 def test_pins_and_default(self):
  self.assertEqual(upstream.VERSION,'0.4.3')
  self.assertIn(b'Quality=fast\n',upstream.DEFAULT_CONFIG)
 def test_missing_quality_added_without_resetting_visuals(self):
  for newline in ('\n','\r\n'):
   data=newline.join(('[DlssNrOnAmd]','Style=2','ToneLift=.3','QueuePriority=0','Profile=0','')).encode()
   out=deploy._ini(data,0,update=True)
   for val in ('Style=2','ToneLift=.3','QueuePriority=0','Profile=0','Quality=fast'):
    self.assertIn((val+newline).encode(),out)
   self.assertEqual(out,deploy._ini(out,0,update=True))
 def test_user_quality_preserved(self):
  for value in ('fast','reference','Reference'):
   data=f'[DlssNrOnAmd]\nQuality={value}\nStyle=1\n'.encode()
   out=deploy._ini(data,0,update=True)
   self.assertIn(f'Quality={value}\n'.encode(),out)
   self.assertEqual(out.lower().count(b'quality='),1)
 def test_quality_is_scoped_to_mod_section(self):
  out=deploy._ini(b'[Other]\nQuality=reference\n[DlssNrOnAmd]\nStyle=0\n',0,update=True)
  self.assertIn(b'[Other]\nQuality=reference\n',out)
  self.assertIn(b'Quality=fast\n',out)
if __name__=='__main__':unittest.main()
