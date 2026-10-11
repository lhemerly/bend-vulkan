"""Independent recursive typed-IR scalar oracle; no arena or device execution.

This is source-stage preparation. The compiler must produce checked Nat IR;
handwritten plans are not a substitute for checked source lowering.
"""
LIMITS = dict(depth=5, tasks=63, joins=31, steps=192, segments=64, expr=64, words=772)
MASK = (1 << 32) - 1


def integer(value, lo, hi):
    return type(value) is int and lo <= value <= hi


def expression(tree, args, budget=None):
    if budget is None:
        budget = [LIMITS['expr']]
    budget[0] -= 1
    if budget[0] < 0 or type(tree) is not list:
        raise ValueError('expression bound/shape')
    if len(tree) == 2 and tree[0] == 'lit' and integer(tree[1], 0, MASK):
        return tree[1]
    if len(tree) == 2 and tree[0] == 'arg' and integer(tree[1], 0, len(args)-1):
        return args[tree[1]]
    if len(tree) == 4 and tree[0] == 'bin' and tree[1] in ('+', '-', '*', '&', '|', '^'):
        left = expression(tree[2], args, budget)
        right = expression(tree[3], args, budget)
        return {'+': lambda: left+right, '-': lambda: left-right,
                '*': lambda: left*right, '&': lambda: left & right,
                '|': lambda: left | right, '^': lambda: left ^ right}[tree[1]]() & MASK
    raise ValueError('unsupported expression')


def validate(plan):
    if plan.get('schema') != 'bend-nat-fork-v1' or plan.get('limits') != LIMITS:
        raise ValueError('Nat ABI/policy mismatch')
    segments = plan.get('segments')
    if type(segments) is not list or not 1 <= len(segments) <= LIMITS['segments']:
        raise ValueError('segment count')
    by = {}
    names = set()
    for segment in segments:
        fid = segment.get('id')
        name = segment.get('fid')
        if not integer(fid, 0, 65535) or fid in by or type(name) is not str or not name or name in names:
            raise ValueError('segment identity')
        by[fid] = segment
        names.add(name)
    for segment in segments:
        if segment.get('result') != 'U32':
            raise ValueError('result type')
        if segment.get('role') == 'join':
            if segment.get('arguments') != ['U32', 'U32']:
                raise ValueError('join types')
            expression(segment['value'], [0, 0])
            continue
        match = segment.get('match', {})
        if segment.get('role') != 'task' or segment.get('argument') != 'Nat' or match.get('kind') != 'Nat':
            raise ValueError('task match/type')
        zero = match.get('zero', {})
        if zero.get('op') != 'result':
            raise ValueError('missing Zero result')
        expression(zero['value'], [])
        succ = match.get('successor', {})
        if succ.get('op') == 'result':
            expression(succ['value'], [])
            continue
        children = succ.get('children', [])
        if succ.get('op') != 'fork' or len(children) != 2 or not integer(succ.get('join'), 0, 65535) or by.get(succ.get('join'), {}).get('role') != 'join':
            raise ValueError('binary fork/join')
        slots = set()
        for child in children:
            slot = child.get('slot')
            if not integer(slot, 0, 1) or slot in slots or not integer(child.get('id'), 0, 65535) or by.get(child.get('id'), {}).get('role') != 'task' or child.get('argument') != {'kind': 'Nat', 'op': 'guarded-predecessor'}:
                raise ValueError('child predecessor/type/slot')
            slots.add(slot)
    roots = plan.get('roots')
    if type(roots) is not list or not roots or any(not integer(r, 0, 65535) for r in roots) or len(set(roots)) != len(roots) or any(by.get(r, {}).get('role') != 'task' for r in roots):
        raise ValueError('root membership')
    return by


def evaluate(plan, root, argument):
    by = validate(plan)
    # Python preserves the complete host integer; no low-word coercion.
    if not integer(argument, 0, (1 << 48)-1):
        raise ValueError('upstream Nat immediate range')
    if argument > LIMITS['depth'] or not integer(root, 0, 65535) or root not in plan['roots']:
        raise ValueError('Nat subset/root')

    def recurse(fid, n):
        match = by[fid]['match']
        branch = match['zero'] if n == 0 else match['successor']
        if branch['op'] == 'result':
            return expression(branch['value'], [])
        values = [None, None]
        for child in branch['children']:
            values[child['slot']] = recurse(child['id'], n-1)
        return expression(by[branch['join']]['value'], values)

    return recurse(root, argument)
