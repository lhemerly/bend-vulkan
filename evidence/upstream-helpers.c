#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
typedef uint64_t u64;typedef uint64_t Term;typedef uint32_t u32;
#define INLINE static inline
#define LOC_MASK ((1ull<<40)-1)
#define RFC_BIT (1ull<<63)
#define RING_LEN 4u
#define term_make(tag, aux, loc) \
  (((u64)(tag) << 56) | ((u64)(aux) << 40) | (u64)(loc))

#define term_ctr(cid, loc) term_make(TAG_CTR, cid, loc)
#define term_pak(cid, loc) term_make(TAG_PAK, cid, loc)
#define term_clo(fid, loc) term_make(TAG_CLO, fid, loc)
#define term_buf(cls, loc) term_make(TAG_BUF, cls, loc)
#define term_tsk(fid, loc) term_make(TAG_TSK, fid, loc)


INLINE u64 term_tag(Term t) {
  return (t >> 56) & 0x7f;
}
INLINE bool term_rfc(Term t) {
  return (t & RFC_BIT) != 0;
}
INLINE u64 term_aux(Term t) {
  return (t >> 40) & 0xFFFF;
}
INLINE u64 term_loc(Term t) {
  return t & LOC_MASK;
}
INLINE u32 ring_lap(u32 pos) {
  return ~(u32)(pos / RING_LEN) & 1;
}
int main(void){u64 state=17;for(u32 i=0;i<4096;i++){state=state*6364136223846793005ULL+1;u64 tag=(state>>56)&127,aux=(state>>40)&65535,loc=state&LOC_MASK;u64 t=term_make(tag,aux,loc);if(i&1)t|=RFC_BIT;printf("%016llx %llu %llu %llu %u %u\n",(unsigned long long)t,(unsigned long long)term_tag(t),(unsigned long long)term_aux(t),(unsigned long long)term_loc(t),term_rfc(t),ring_lap(i));}return 0;}
