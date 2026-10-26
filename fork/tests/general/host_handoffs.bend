import Base

def step(x: U32) -> U32:
  U32.add(x, 1)

def main() -> IO(Unit):
  do IO<Unit>:
    Unit <- IO.print(U32.show(step!(40)))
    IO.print(U32.show(step!(41)))
#|41
#|42
