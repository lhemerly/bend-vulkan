import Base

def affine(x: U32) -> U32:
  ((x * 17 : U32) + 5 : U32)

def main() -> U32:
  affine(12345)
