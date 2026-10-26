import Base

def apply(f: U32 -> U32, x: U32) -> U32:
  f(x)

def main() -> U32:
  apply!(x => U32.add(x, 7), 35)
#|42
