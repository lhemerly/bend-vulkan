import Base

def first(x: U32) -> U32:
  ((x * 3 : U32) + 2 : U32)

def second(x: U32) -> U32:
  U32.xor(x, 7)

def combine(+x: U32) -> U32:
  a b = first(x) second((x + 5 : U32))
  (a + b : U32)

def main() -> U32:
  combine!(4294967295)
#|2
