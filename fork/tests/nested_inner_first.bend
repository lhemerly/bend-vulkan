import Base

def leaf(x: U32) -> U32:
  (x + 1 : U32)

def inner(+x: U32) -> U32:
  a b = leaf(x) leaf(x)
  (a + b : U32)

def outer(+x: U32) -> U32:
  a b = inner(x) leaf(x)
  (a + b : U32)

def main() -> U32:
  (inner!(1) + outer!(2) : U32)
#|13
