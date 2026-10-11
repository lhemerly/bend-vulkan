import Base

def affine(x: U32) -> U32:
  ((x * 17 : U32) + 5 : U32)

def pair(+x: U32) -> U32:
  a b = affine(x) affine((x + 1 : U32))
  (a + b : U32)

def main() -> U32:
  pair!(12345)
