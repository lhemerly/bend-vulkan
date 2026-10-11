import Base

law leaf:
  for +d: Nat
  U32
def leaf(d):
  match d:
    case 0n:
      3
    case 1n+p:
      7

law choose:
  for +d: Nat
  U32
def choose(d):
  match d:
    case 0n:
      11
    case 1n+p:
      a b = leaf(p) leaf(p)
      U32.add(a,b)

law altered:
  for +d: Nat
  U32
def altered(d):
  choose(1n)

law main:
  U32

def main():
  altered!(0n)
