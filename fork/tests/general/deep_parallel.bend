# General scheduler: 4096 leaves across multiple workgroups, beyond depth five.
import Base

def tree(+n: Nat) -> U32:
  match n:
    case 0n:
      3
    case 1n+p:
      a b = tree(p) tree(p)
      U32.add(a, b)

def main() -> U32:
  tree!(12n)
#|12288
