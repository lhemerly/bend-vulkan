"""Bounded event simulation for complete Nat buffers, separate from recursion.

Source preparation only: no native worker, shader dispatch or host integration.
The scalar oracle in nat_oracle uses recursion; this model uses record states.
"""
from nat_oracle import LIMITS, MASK, expression, integer, validate

ROOT = MASK
TASK_BASE = 16
JOIN_BASE = TASK_BASE + 63*8
CANARIES = (0xA17ECAFE, 0x5A5AA5A5, 0xDEADBEEF, 0xC001D00D)
READY, EXPANDED, PENDING, DELIVERED = 1, 2, 3, 4
WAITING, JOIN_PENDING, JOIN_DELIVERED = 4, 8, 12


class ArenaError(Exception):
    def __init__(self, code):
        self.code = code


def simulate(plan, root, argument, order=0, *, task_cap=63, join_cap=31, step_cap=192, fault=None):
    """Return all 772 words, including terminal errors and unchanged canaries.

    Lowered capacities are CPU fault probes; none may increase fixed policy.
    Optional fault(buffer) is a CPU-model-only test hook before each transition;
    it never changes plan provenance or enables a native/device dispatch.
    Preflight failures raise before creating a buffer. Runtime failures publish
    error/DONE at the common endpoint and never publish a successful result.
    """
    by = validate(plan)
    if not integer(argument, 0, (1 << 48)-1):
        raise ValueError('upstream Nat immediate range')
    if argument > LIMITS['depth'] or not integer(root, 0, 65535) or root not in plan['roots']:
        raise ValueError('Nat subset/root')
    if not integer(order, 0, 1) or not integer(task_cap, 1, 63) or not integer(join_cap, 0, 31) or not integer(step_cap, 0, 192):
        raise ValueError('arena policy')
    w = [0]*LIMITS['words']
    w[:16] = [1, root, argument, task_cap, join_cap, step_cap, 1, 0, 0, 0, 0, 0, 0, order, 0, 0]
    w[-4:] = CANARIES
    w[TASK_BASE:TASK_BASE+8] = [root, argument, ROOT, 0, 0, READY, 0, 0]
    result = None
    root_join = None

    def finish(value):
        nonlocal result
        if result is not None:
            raise ArenaError(5)
        result = value

    def deliver(parent, slot, value):
        if parent == ROOT:
            # Root leaves finish in EVALUATE; root joins finish on their
            # second slot. No queued DELIVER may target the root sentinel.
            raise ArenaError(4)
        if not integer(parent, 0, w[7]-1) or slot not in (0, 1):
            raise ArenaError(4)
        at = JOIN_BASE + parent*8
        state = w[at+6]
        valid = state & 3
        if state & ~3 != WAITING or valid & (1 << slot) or w[at+3] != 2-valid.bit_count():
            raise ArenaError(5)
        joined = None
        if w[at+3] == 1:
            join = by.get(w[at])
            if join is None or join['role'] != 'join':
                raise ArenaError(6)
            args = [w[at+4], w[at+5]]
            args[slot] = value
            joined = expression(join['value'], args)
            if (w[at+1] == ROOT or parent == root_join) and (parent != root_join or w[at+1] != ROOT or w[at+2] != 0 or result is not None):
                raise ArenaError(4)
        # Match the shader's fail-stop contract: final delivery resolves the
        # join and root ownership before any slot/count/state mutation.
        valid |= 1 << slot
        w[at+4+slot] = value
        w[at+3] -= 1
        w[at+6] = WAITING | valid
        if w[at+3] == 0:
            w[at+7] = joined
            if w[at+1] == ROOT:
                w[at+6] = JOIN_DELIVERED | valid
                finish(joined)
            else:
                w[at+6] = JOIN_PENDING | valid

    def choose():
        # Prioritize durable pending values. Child order changes execution
        # order alone; each child's stored slot determines join arguments.
        for i in range(w[7]):
            at = JOIN_BASE+i*8
            if w[at+6] == JOIN_PENDING | 3:
                return 'join', at
        for i in range(w[6]):
            at = TASK_BASE+i*8
            if w[at+5] == PENDING:
                return 'pending', at
        indices = range(w[6]) if order == 0 else range(w[6]-1, -1, -1)
        for i in indices:
            at = TASK_BASE+i*8
            if w[at+5] == READY:
                return 'evaluate', at
        raise ArenaError(5)

    try:
        while result is None:
            if fault is not None:
                fault(w)
            if w[8] >= step_cap:
                raise ArenaError(3)
            if not integer(w[6], 0, task_cap) or not integer(w[7], 0, join_cap):
                raise ArenaError(2)
            kind, at = choose()
            w[8] += 1
            if kind == 'join':
                deliver(w[at+1], w[at+2], w[at+7])
                w[at+6] = JOIN_DELIVERED | 3
                continue
            if kind == 'pending':
                deliver(w[at+2], w[at+3], w[at+6])
                w[at+5] = DELIVERED
                continue
            n = w[at+1]
            if n > 5 or w[at+4] > 5 or n+w[at+4] != argument:
                raise ArenaError(5)
            if (at == TASK_BASE or w[at+2] == ROOT) and (at != TASK_BASE or w[at+2] != ROOT or w[at+3] != 0):
                raise ArenaError(4)
            task = by.get(w[at])
            if task is None or task['role'] != 'task':
                raise ArenaError(6)
            branch = task['match']['zero'] if n == 0 else task['match']['successor']
            if branch['op'] == 'result':
                w[at+6] = expression(branch['value'], [])
                if w[at+2] == ROOT:
                    if w[at+3] != 0:
                        raise ArenaError(4)
                    finish(w[at+6])
                    w[at+5] = DELIVERED
                else:
                    w[at+5] = PENDING
                continue
            if n == 0 or w[6]+2 > task_cap or w[7]+1 > join_cap:
                raise ArenaError(2)
            # Check all capacities before allocating any descriptor.
            j = w[7]
            ja = JOIN_BASE+j*8
            w[ja:ja+8] = [branch['join'], w[at+2], w[at+3], 2, 0, 0, WAITING, 0]
            for child in sorted(branch['children'], key=lambda c: c['slot']):
                ca = TASK_BASE+w[6]*8
                w[ca:ca+8] = [child['id'], n-1, j, child['slot'], w[at+4]+1, READY, 0, 0]
                w[6] += 1
            w[7] += 1
            if at == TASK_BASE:
                root_join = j
            w[at+5] = EXPANDED
    except ArenaError as error:
        w[10] = error.code
    # Mirrors the future common device publication path, without claiming
    # memory-ordering evidence: no successful value is exposed on error.
    w[9] = 0 if w[10] else result
    w[11] = 1
    w[12] = 0 if w[10] else w[9]
    return w
