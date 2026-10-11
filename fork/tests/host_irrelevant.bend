import Base

def offload(x: U32) -> U32:
  (x + 29 : U32)

def host(x: Nat) -> Nat:
  match x:
    case 0n:
      1n
    case 1n+p:
      Nat.add(p, 2n)

def main() -> U32:
  (offload!(U32.from_nat(host(2n))) + 1 : U32)
#|33
