import unittest
from emit_u32_segment import expression,emit,Unsupported
class Tests(unittest.TestCase):
 def test_nested_wrap(self):self.assertEqual(expression('U32_BIN(U32_BIN(_x_0, *, 17ull), +, 5ull)','_x_0'),'((x * 17u) + 5u)')
 def test_rejects(self):
  for s in ['foo(_x_0)','U32_BIN(_x_0, /, 0ull)','4294967296ull','_x_1','1ull;bad','U32_BIN(_x_0,+,1ull) extra']:
   with self.assertRaises(Unsupported):expression(s,'_x_0')
 def test_fail_closed_calls_heap_shape(self):
  for s in ['WL_CASE(FID_TEST) { WL_OPEN r0 = heap_alloc(e,0); WL_RETN(1); }}','']:
   with self.assertRaises(Unsupported):emit(s,'FID_TEST')
if __name__=='__main__':unittest.main()
