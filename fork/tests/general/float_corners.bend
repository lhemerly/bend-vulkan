import Base

def bit(b: Bool) -> U32:
  match b:
    case False{}:
      0
    case True{}:
      1

def corners(+x: F32, +y: F32) -> U32:
  a = bit(U32.is_eq(F32.bits(F32.add(F32.mul(x, x), y)), 0))
  b = bit(F32.is_eq(F32.mod(F32.neg(5.5), 2.0), F32.neg(1.5)))
  c = bit(U32.is_eq(F32.bits(F32.mod(F32.neg(4.0), 2.0)), 2147483648))
  d = bit(F32.is_eq(F32.pow(F32.neg(2.0), 3.0), F32.neg(8.0)))
  e = bit(F32.is_eq(F32.pow(1.0, F32.div(0.0, 0.0)), 1.0))
  f = bit(F32.is_eq(F32.pow(F32.neg(1.0), F32.div(1.0, 0.0)), 1.0))
  U32.add(U32.add(U32.add(a, b), U32.add(c, d)), U32.add(e, f))

def main() -> U32:
  corners!(1.00000011920928955078125, F32.neg(1.0000002384185791015625))
#|6
