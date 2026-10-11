import Base

def calculate(x: U32) -> U32:
  ((x * 7 : U32) + 13 : U32)

def main() -> U32:
  calculate!(42)
#|307
