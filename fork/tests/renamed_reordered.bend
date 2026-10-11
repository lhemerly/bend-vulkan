import Base

def tiger(x: U32) -> U32:
  U32.xor(x, 19)

def llama(x: U32) -> U32:
  ((x * 11 : U32) + 31 : U32)

def gather(+x: U32) -> U32:
  p q = llama((x + 2 : U32)) tiger(x)
  (p + q : U32)

def main() -> U32:
  gather!(4294967294)
#|12
