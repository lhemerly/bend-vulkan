import Base

def offload(x: U32) -> U32:
  (x + 7 : U32)

def main() -> U32:
  a b = offload!(1) offload!(2)
  (a + b : U32)
#|17
