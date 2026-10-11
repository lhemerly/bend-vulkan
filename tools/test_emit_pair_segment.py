import unittest
from pathlib import Path
from emit_pair_segment import parse,cpu_source
from emit_u32_segment import Unsupported
SOURCE=(Path(__file__).resolve().parents[1]/'evidence/pair-preparation/generated.c').read_text()
class PairAdapterTests(unittest.TestCase):
 def test_actual_parallel_tasks_and_join(self):
  p=parse(SOURCE)
  self.assertEqual(p['fids'],{'FID_AFFINE':0,'FID_PAIR':1,'FID_PAIR_J2':4})
  self.assertEqual(p['arg_glsl'],['x','(x + 1u)'])
  self.assertEqual(p['affine_glsl'],'((x * 17u) + 5u)')
  self.assertEqual(p['join_glsl'],'(a + b)')
  self.assertIn(p['affine_raw'],cpu_source(p));self.assertIn(p['join_raw'],cpu_source(p))
 def test_unsupported_shape_mutants(self):
  mutants=[SOURCE.replace('WL_IDX, 2);','WL_IDX, 3);',1),
   SOURCE.replace('term_tsk(FID_PAIR_J2, _t_0), 1, 0','term_tsk(FID_PAIR_J2, _t_0), 0, 0',1),
   SOURCE.replace('u64 _t_2 = task_node(e, FID_AFFINE','u64 _t_2 = task_node(e, FID_PAIR',1),
   SOURCE.replace('e.mem[_t_2 + 0] = U32_BIN(_x_0, +, 1ull);','e.mem[_t_2 + 0] = unknown(_x_0);',1),
   SOURCE.replace('r0 = U32_BIN(_a_2, +, _b_1);','r0 = U32_BIN(_a_2, /, _b_1);',1),
   SOURCE.replace('#define FID_PAIR_J2 4','#define FID_PAIR_J2 0',1),
   SOURCE.replace('u32 _b_1 = r1;','u32 _b_1 = r0;',1),
   SOURCE.replace('return term_tsk(FID_PAIR_J2, _t_0);','side_effect(); return term_tsk(FID_PAIR_J2, _t_0);',1),
   SOURCE.replace('r0 = U32_BIN(U32_BIN(_x_0, *, 17ull), +, 5ull);','r0 = unknown(_x_0);',1),
   SOURCE+'\nWL_CASE(FID_PAIR) { }',
   # Drift inside paths this adapter never emits must still be rejected.
   SOURCE.replace('WL_JMP(FID_PAIR_J2);','WL_JMP(FID_MAIN);',1),
   SOURCE.replace('STK(1) = FID_PAIR_K3;','STK(1) = FID_MAIN;',1),
   SOURCE.replace('STK(1) = FID_PAIR_K2;','STK(1) = FID_MAIN;',1),
   SOURCE.replace('u64 _t_4 = task_node(e, FID_AFFINE, WL_CONT, WL_IDX, 0);','u64 _t_4 = task_node(e, FID_AFFINE, WL_CONT, WL_IDX, 3);',1),
   SOURCE.replace('u64 _t_5 = task_node(e, FID_PAIR_J2, WL_CONT, WL_IDX, 0);','u64 _t_5 = task_node(e, FID_PAIR_J2, WL_CONT, WL_IDX, 2);',1),
   SOURCE.replace('e.mem[_t_5 + 1] = _b_0;','e.mem[_t_5 + 1] = 7u;',1),
   SOURCE.replace('WL_POPN(2);','WL_POPN(3);',1),
   SOURCE.replace('u32 _a_1 = STK(1);','u32 _a_1 = STK(2);',1),
   SOURCE.replace('r0 = _x_0;\n    WL_JMP(FID_AFFINE);','r0 = _x_0;\n    r1 = 9u;\n    WL_JMP(FID_AFFINE);',1),
   SOURCE.replace('if (!DEVICE && !seq && fid_nofk(FID_AFFINE)) {\n      u64 _t_3','if (!DEVICE && seq && fid_nofk(FID_AFFINE)) {\n      u64 _t_3',1),
   SOURCE.replace('u32 _x_1 = STK(-1);','u32 _x_1 = STK(-2);',1),
   SOURCE.replace('u32 _b_0 = r0;\n    WL_OPEN\n    if (!DEVICE','u32 _b_0 = r1;\n    WL_OPEN\n    if (!DEVICE',1)]
  for i,s in enumerate(mutants):
   with self.subTest(mutant=i),self.assertRaises(Unsupported):parse(s)
if __name__=='__main__':unittest.main()
