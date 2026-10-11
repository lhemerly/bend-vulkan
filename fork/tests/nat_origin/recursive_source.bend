import Base

law branch:
  for +d: Nat
  U32

def branch(d):
  match d:
    case 0n:
      3
    case 1n+p:
      a b = branch(p) branch(p)
      U32.add(a,b)

law main:
  U32

def main():
  branch!(2n)
