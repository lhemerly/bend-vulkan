//! Runtime primitive port for a Bend2-style Vulkan backend: Term word ABI + fixed ring.
//! Upstream: Bend2 v2.0.35, commit 11d483271b46e445b922756d5fd4127a1ea99ae8 (Apache-2.0).
//! Scope: mirrors only the Term layout and the fixed-ring semantics; this is not a Bend
//! backend, does not execute generated segments, and proves no correctness property.
//! Assumptions: get/put are wrapping u32 counters; the lap marker aliases term bit 63
//! (RFC), so only RFC-clear TAG_TSK terms may be queued; errors are sticky and are never
//! retried; the shader relies on barrier + atomic publication only, which demonstrates no
//! Vulkan release/acquire visibility and no scheduler parity with upstream.

/// Upstream task tag for queued work.
pub const TAG_TSK: u64 = 5;
/// Reference-counted flag, term bit 63.
pub const RFC: u64 = 1 << 63;
/// Location field: low 40 bits.
pub const LOC_MASK: u64 = (1 << 40) - 1;
pub const ERR_NONE: u32 = 0;
pub const ERR_RING1: u32 = 1;
pub const ERR_FIX2: u32 = 2;
pub const RING_MAX: u32 = 1024;

/// Fixture ABI 1: flat 30-word buffer shared with the shader (lane 0 only).
pub const W_GET: usize = 0;
pub const W_PUT: usize = 1;
pub const W_ERR: usize = 2;
pub const W_SLOTS: usize = 3; // 4 slots x (low, high) -> 3..10
pub const W_INPUTS: usize = 11; // 4 input terms x (low, high) -> 11..18
pub const W_OUTPUTS: usize = 19; // 4 restored terms -> 19..26
pub const W_FINAL: usize = 27; // final get, put, error -> 27..29
pub const FIXTURE_WORDS: usize = 30;
pub const FIXTURE_LEN: u32 = 4;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct Term(u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TermError {
    Tag,
    Aux,
    Loc,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QueueError {
    Tag,
    Rfc,
}

impl Term {
    /// `term_make = (tag << 56) | (aux << 40) | loc`, validated host-side.
    pub fn make(tag: u64, aux: u64, loc: u64) -> Result<Term, TermError> {
        if tag > 0x7f {
            return Err(TermError::Tag);
        }
        if aux > 0xffff {
            return Err(TermError::Aux);
        }
        if loc > LOC_MASK {
            return Err(TermError::Loc);
        }
        Ok(Term((tag << 56) | (aux << 40) | loc))
    }
    pub fn from_raw(raw: u64) -> Term {
        Term(raw)
    }
    pub fn raw(self) -> u64 {
        self.0
    }
    pub fn tag(self) -> u64 {
        (self.0 >> 56) & 0x7f
    }
    pub fn aux(self) -> u64 {
        (self.0 >> 40) & 0xffff
    }
    pub fn loc(self) -> u64 {
        self.0 & LOC_MASK
    }
    pub fn rfc(self) -> bool {
        self.0 & RFC != 0
    }
    /// RFC setter/clearer; tag, aux and loc are unaffected.
    pub fn with_rfc(self, on: bool) -> Term {
        Term(if on { self.0 | RFC } else { self.0 & !RFC })
    }
    /// Queue precondition: tag must be TAG_TSK and RFC must be clear.
    pub fn queued(self) -> Result<Term, QueueError> {
        if self.tag() != TAG_TSK {
            return Err(QueueError::Tag);
        }
        if self.rfc() {
            return Err(QueueError::Rfc);
        }
        Ok(self)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RingError {
    ShortBuffer,
    BadLen(u32),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PushError {
    /// Sticky ring error code after the failed push.
    pub ring_error: u32,
    /// `put` after being advanced by the reservation.
    pub put_after: u32,
}

/// Capacity is a power of two in `2..=1024`; `len - 1` is the slot mask.
fn check_len(len: u32) -> Result<u32, RingError> {
    if !(2..=RING_MAX).contains(&len) || !len.is_power_of_two() {
        return Err(RingError::BadLen(len));
    }
    Ok(len.trailing_zeros())
}

/// CPU reference for the upstream fixed ring. Slot `i` holds `(low, high)` words; the
/// publication marker is `lap << 31` of the high word, OR-ed over the RFC-clear term.
#[derive(Debug, Clone)]
pub struct Ring {
    lows: Box<[u32]>,
    highs: Box<[u32]>,
    shift: u32,
    get: u32,
    put: u32,
    error: u32,
}

impl Ring {
    pub fn new(len: u32) -> Result<Ring, RingError> {
        Self::new_at(len, 0)
    }
    /// Empty ring whose stale slot markers cannot match an initial reservation.
    pub fn new_at(len: u32, start: u32) -> Result<Ring, RingError> {
        let shift = check_len(len)?;
        let n = len as usize;
        Ok(Ring {
            lows: vec![0; n].into_boxed_slice(),
            highs: (0..n)
                .map(|i| {
                    let pos = start.wrapping_add((i as u32).wrapping_sub(start) & (len - 1));
                    (1 - Self::lap(pos, shift)) << 31
                })
                .collect::<Vec<_>>()
                .into_boxed_slice(),
            shift,
            get: start,
            put: start,
            error: ERR_NONE,
        })
    }
    /// `lap = ~(pos / len) & 1`, with `len` a power of two.
    fn lap(pos: u32, shift: u32) -> u32 {
        (!(pos >> shift)) & 1
    }
    pub fn len(&self) -> u32 {
        1 << self.shift
    }
    pub fn is_empty(&self) -> bool {
        self.get == self.put
    }
    pub fn get(&self) -> u32 {
        self.get
    }
    pub fn put(&self) -> u32 {
        self.put
    }
    pub fn error(&self) -> u32 {
        self.error
    }
    /// Sticky: the first error wins.
    pub fn set_error(&mut self, code: u32) {
        if self.error == ERR_NONE {
            self.error = code;
        }
    }
    pub fn set_cursors(&mut self, get: u32, put: u32) {
        self.get = get;
        self.put = put;
    }
    pub fn set_slot_words(&mut self, i: usize, low: u32, high: u32) {
        self.lows[i] = low;
        self.highs[i] = high;
    }
    pub fn slot_words(&self, i: usize) -> (u32, u32) {
        (self.lows[i], self.highs[i])
    }
    pub fn into_words(self) -> (Box<[u32]>, Box<[u32]>) {
        (self.lows, self.highs)
    }
    /// Reserve with `put`, check the window, then write low and publish high.
    pub fn push(&mut self, t: Term) -> Result<usize, PushError> {
        if self.error != ERR_NONE {
            return Err(PushError {
                ring_error: self.error,
                put_after: self.put,
            });
        }
        if t.queued().is_err() {
            self.set_error(ERR_FIX2);
            return Err(PushError {
                ring_error: self.error,
                put_after: self.put,
            });
        }
        let pos = self.put;
        self.put = self.put.wrapping_add(1);
        if pos.wrapping_sub(self.get) >= self.len() {
            self.set_error(ERR_RING1); // put stays advanced; the slot is not written
            return Err(PushError {
                ring_error: self.error,
                put_after: self.put,
            });
        }
        let raw = t.raw();
        // RFC clear is a queue precondition, so bit 31 belongs to the lap marker.
        let (low, high) = ((raw as u32), ((raw >> 32) & 0x7fff_ffff) as u32);
        let slot = (pos & (self.len() - 1)) as usize;
        self.lows[slot] = low;
        self.highs[slot] = high | (Ring::lap(pos, self.shift) << 31);
        Ok(slot)
    }
    /// Consume only a published slot; `get` advances only then.
    pub fn pop(&mut self) -> Option<Term> {
        if self.error != ERR_NONE || self.get == self.put {
            return None;
        }
        let slot = (self.get & (self.len() - 1)) as usize;
        let hw = self.highs[slot];
        if (hw >> 31) != Ring::lap(self.get, self.shift) {
            return None; // not published yet (or a stale generation)
        }
        let t = Term::from_raw((((hw & 0x7fff_ffff) as u64) << 32) | self.lows[slot] as u64);
        self.get = self.get.wrapping_add(1);
        Some(t)
    }
}

pub fn load_term(words: &[u32], at: usize) -> Term {
    Term::from_raw((u64::from(words[at + 1]) << 32) | u64::from(words[at]))
}

pub fn store_term(words: &mut [u32], at: usize, t: Term) {
    words[at] = t.raw() as u32;
    words[at + 1] = (t.raw() >> 32) as u32;
}

/// Host mirror of the shader fixture: push 4 tasks, drain 4, record restored terms.
/// Input words `11..18` are preserved; the buffer must hold at least 30 words.
pub fn run_fixture(words: &mut [u32]) -> Result<(), RingError> {
    if words.len() < FIXTURE_WORDS {
        return Err(RingError::ShortBuffer);
    }
    let mut ring = Ring::new(FIXTURE_LEN)?;
    for i in 0..FIXTURE_LEN as usize * 2 {
        words[W_SLOTS + i] = 0;
        words[W_OUTPUTS + i] = 0;
    }
    words[W_GET] = 0;
    words[W_PUT] = 0;
    words[W_ERR] = ERR_NONE;
    words[W_FINAL] = 0;
    words[W_FINAL + 1] = 0;
    words[W_FINAL + 2] = 0;
    let valid =
        (0..FIXTURE_LEN as usize).all(|i| load_term(words, W_INPUTS + 2 * i).queued().is_ok());
    if !valid {
        ring.set_error(ERR_FIX2);
    }
    for i in 0..FIXTURE_LEN as usize {
        if valid {
            let _ = ring.push(load_term(words, W_INPUTS + 2 * i));
        }
    }
    for i in 0..FIXTURE_LEN as usize {
        let want = load_term(words, W_INPUTS + 2 * i);
        let got = ring.pop().unwrap_or_default();
        words[W_OUTPUTS + 2 * i] = got.raw() as u32;
        words[W_OUTPUTS + 2 * i + 1] = (got.raw() >> 32) as u32;
        if got != want {
            ring.set_error(ERR_FIX2);
        }
    }
    let (g, p, e) = (ring.get(), ring.put(), ring.error());
    let (lows, highs) = ring.into_words();
    for i in 0..FIXTURE_LEN as usize {
        words[W_SLOTS + 2 * i] = lows[i];
        words[W_SLOTS + 2 * i + 1] = highs[i];
    }
    words[W_GET] = g;
    words[W_PUT] = p;
    words[W_ERR] = e;
    words[W_FINAL] = g;
    words[W_FINAL + 1] = p;
    words[W_FINAL + 2] = e;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn t(aux: u64, loc: u64) -> Term {
        Term::make(TAG_TSK, aux, loc).unwrap()
    }

    #[test]
    fn term_abi_40bit_loc_16bit_aux_and_rfc() {
        let x = Term::make(0x7f, 0xffff, LOC_MASK).unwrap();
        assert_eq!((x.tag(), x.aux(), x.loc()), (0x7f, 0xffff, LOC_MASK));
        let r = x.with_rfc(true);
        assert!(r.rfc() && r.tag() == 0x7f && r.aux() == 0xffff && r.loc() == LOC_MASK);
        assert_eq!(r.with_rfc(false), x);
        assert_eq!(Term::make(0, 0, 1 << 32 | 7).unwrap().loc(), (1 << 32) + 7);
        assert_eq!(Term::make(128, 0, 0), Err(TermError::Tag));
        assert_eq!(Term::make(0, 0x1_0000, 0), Err(TermError::Aux));
        assert_eq!(Term::make(0, 0, 1 << 40), Err(TermError::Loc));
        assert_eq!(t(0, 0).queued(), Ok(t(0, 0)));
        assert_eq!(Term::make(6, 0, 0).unwrap().queued(), Err(QueueError::Tag));
        assert_eq!(t(0, 0).with_rfc(true).queued(), Err(QueueError::Rfc));
    }

    #[test]
    fn fifo_then_lap_rollover() {
        let mut r = Ring::new(4).unwrap();
        for i in 0..4u64 {
            r.push(t(i, i * 10)).unwrap();
        }
        for i in 0..4u64 {
            assert_eq!(r.pop(), Some(t(i, i * 10)));
        }
        assert_eq!(r.pop(), None); // empty: get == put
        for i in 4..8u64 {
            assert_eq!(r.push(t(i, i)), Ok((i & 3) as usize));
        }
        for i in 4..8u64 {
            assert_eq!(r.pop(), Some(t(i, i)));
        }
        // A new lap needs fresh publication: stale lap-1 markers must not be read.
        r.set_cursors(8, 9);
        assert_eq!(r.pop(), None);
        assert_eq!(r.get(), 8);
    }

    #[test]
    fn unpublished_slot_is_not_consumed() {
        let mut r = Ring::new(4).unwrap();
        r.push(t(1, 1)).unwrap();
        r.set_slot_words(0, 7, 0); // low staged, lap marker still opposite
        assert_eq!(r.pop(), None);
        assert_eq!(r.get(), 0);
    }

    #[test]
    fn full_advances_put_and_leaves_sticky_error() {
        let mut r = Ring::new(4).unwrap();
        for i in 0..4u64 {
            r.push(t(i, i)).unwrap();
        }
        let e = r.push(t(9, 9)).unwrap_err();
        assert_eq!((e.ring_error, e.put_after), (ERR_RING1, 5));
        assert_eq!((r.error(), r.put(), r.get()), (ERR_RING1, 5, 0));
        assert_eq!(r.push(t(1, 1)), Err(e)); // no retry claim: still poisoned
        assert_eq!(r.pop(), None);
    }

    #[test]
    fn wrapping_u32_positions() {
        let mut r = Ring::new_at(4, u32::MAX).unwrap();
        assert_eq!(r.push(t(1, 2)), Ok(3));
        assert_eq!(r.put(), 0);
        assert_eq!(r.pop(), Some(t(1, 2)));
        assert_eq!((r.get(), r.put(), r.error()), (0, 0, ERR_NONE));
    }

    #[test]
    fn capacity_is_power_of_two_in_2_to_1024() {
        assert!(Ring::new(1).is_err() && Ring::new(3).is_err() && Ring::new(2048).is_err());
        assert!(Ring::new(2).is_ok() && Ring::new(1024).is_ok());
    }

    fn boundary_inputs() -> [Term; 4] {
        [
            t(0, 0),
            t(0xffff, 7),
            t(0, (1 << 32) + 7),
            t(0xabcd, LOC_MASK),
        ]
    }

    #[test]
    fn fixture_matches_shader_abi() {
        let mut w = [0u32; FIXTURE_WORDS];
        for (i, t) in boundary_inputs().iter().enumerate() {
            store_term(&mut w, W_INPUTS + 2 * i, *t);
        }
        let inputs = w[W_INPUTS..W_INPUTS + 8].to_vec();
        run_fixture(&mut w).unwrap();
        assert_eq!(&w[W_INPUTS..W_INPUTS + 8], inputs.as_slice()); // preserved
        assert_eq!(&w[W_OUTPUTS..W_OUTPUTS + 8], &inputs[..]);
        assert_eq!(
            (w[W_FINAL], w[W_FINAL + 1], w[W_FINAL + 2]),
            (4, 4, ERR_NONE)
        );
        assert_eq!((w[W_GET], w[W_PUT], w[W_ERR]), (4, 4, ERR_NONE));
        for s in 0..4 {
            assert_eq!(w[W_SLOTS + 2 * s + 1] >> 31, 1); // lap(pos 0..3) == 1
        }
    }

    #[test]
    fn fixture_flags_bad_input_and_short_buffer() {
        let mut w = [0u32; FIXTURE_WORDS];
        store_term(&mut w, W_INPUTS, Term::make(9, 0, 1).unwrap()); // not TAG_TSK
        run_fixture(&mut w).unwrap();
        assert_eq!(w[W_FINAL + 2], ERR_FIX2);
        assert_eq!((w[W_FINAL], w[W_FINAL + 1]), (0, 0));
        let mut short = [0u32; 29];
        assert_eq!(run_fixture(&mut short), Err(RingError::ShortBuffer));
    }
}

#[cfg(test)]
mod independent_checks {
    use super::*;
    #[test]
    fn upstream_literal_c_helpers_4096_vectors() {
        assert_eq!(
            include_str!("../evidence/upstream-helper-vectors.txt")
                .lines()
                .count(),
            4096
        );
        for (i, line) in include_str!("../evidence/upstream-helper-vectors.txt")
            .lines()
            .enumerate()
        {
            let x: Vec<_> = line.split_whitespace().collect();
            let raw = u64::from_str_radix(x[0], 16).unwrap();
            let t = Term::from_raw(raw);
            assert_eq!(t.tag(), x[1].parse::<u64>().unwrap());
            assert_eq!(t.aux(), x[2].parse::<u64>().unwrap());
            assert_eq!(t.loc(), x[3].parse::<u64>().unwrap());
            assert_eq!(t.rfc(), x[4] == "1");
            assert_eq!(Ring::lap(i as u32, 2), x[5].parse::<u32>().unwrap());
            assert_eq!(
                Term::make(t.tag(), t.aux(), t.loc())
                    .unwrap()
                    .with_rfc(t.rfc()),
                t
            );
        }
    }
    #[test]
    fn translated_shader_128_fixtures_match_cpu_all_words() {
        assert_eq!(
            include_str!("../evidence/shader-cpu-vectors.txt")
                .lines()
                .count(),
            128
        );
        for line in include_str!("../evidence/shader-cpu-vectors.txt").lines() {
            let expected: Vec<u32> = line
                .split_whitespace()
                .map(|s| u32::from_str_radix(s, 16).unwrap())
                .collect();
            let mut words = [0xdeadbeef; FIXTURE_WORDS];
            words[W_INPUTS..W_INPUTS + 8].copy_from_slice(&expected[W_INPUTS..W_INPUTS + 8]);
            run_fixture(&mut words).unwrap();
            assert_eq!(words.as_slice(), expected.as_slice());
        }
    }
}
