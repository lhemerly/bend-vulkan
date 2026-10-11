import Base

def left(x: U32) -> U32:
  (x * 3 : U32)

def right(x: U32) -> U32:
  (x + 7 : U32)

def offload(+x: U32) -> U32:
  a b = left(x) right(x)
  (a + b : U32)

def main() -> IO(Unit):
  do IO<Unit>:
    first: U32 = offload!(2)
    Unit <- IO.print(U32.show((first + 100 : U32)))
    second: U32 = offload!(5)
    IO.print(U32.show((second + 20 : U32)))
#|115
#|47
