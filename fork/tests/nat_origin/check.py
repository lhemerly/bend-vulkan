"""Small source-emission/model checks. No native build, shader or GPU launch."""
import json
import pathlib
import subprocess
import sys
import copy

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'runtime'))
from nat_oracle import evaluate,validate
from nat_arena import simulate, JOIN_BASE, TASK_BASE, ROOT as SENTINEL, CANARIES


def check(destination):
    destination = pathlib.Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'source emission and Python model only; no native/shader compilation or device execution', 'cases': {}}
    def recorded(inject, events):
        def run(words):
            before=words.copy()
            inject(words)
            if words!=before:
                events.append({'phase':'before transition budget/count checks and record selection',
                  'transitions_before':before[8],'writes':[{'word':i,'before':a,'after':b} for i,(a,b) in enumerate(zip(before,words)) if a!=b],
                  'before':before,'injected':words.copy()})
        return run
    for name, accepted in [('changed_argument', False), ('constant_argument', False), ('identity_forwarding', True), ('recursive_source',True)]:
        output = destination/name
        job = subprocess.run(['bun', 'nat_source_cli.ts', str(ROOT/'tests/nat_origin'/f'{name}.bend'), str(output)], cwd=ROOT, capture_output=True, text=True, timeout=10)
        (destination/f'{name}.stderr').write_text(job.stderr)
        assert (job.returncode == 0) == accepted, (name, job.stderr)
        if not accepted:
            assert 'Nat discriminator is not the proven original task argument' in job.stderr
            assert not output.exists()
            report['cases'][name] = {'rejected_before_output': True, 'reason': 'unproved/transformed Nat discriminator'}
            continue
        plan = json.loads((output/'nat-plan.json').read_text())
        root = plan['roots'][0]
        expected_values = [(0,3),(1,6),(2,12)] if name=='recursive_source' else [(0,11),(1,6),(2,14)]
        values = []
        for argument, expected in expected_values:
            words = simulate(plan, root, argument)
            assert evaluate(plan, root, argument) == words[9] == expected
            assert words[10] == 0 and tuple(words[-4:]) == CANARIES
            values.append({'argument': argument, 'root_result': expected})
        report['cases'][name] = {'accepted_with_original_input_proof': True, 'values': values}
        if name!='recursive_source':
            continue

        for role, field in [('child','id'),('join','join')]:
            malformed=copy.deepcopy(plan)
            task=next(s for s in malformed['segments'] if s['role']=='task')
            fork=task['match']['successor']
            if role=='child':fork['children'][0][field]=True
            else:fork[field]=True
            try:
                validate(malformed)
                raise AssertionError('boolean reference accepted')
            except ValueError:
                report['cases'][f'boolean_{role}_reference']={'rejected':True}

        for name, code in [('unknown_join_fid', 6), ('invalid_root_slot', 4)]:
            before = []
            events=[]

            def inject(words):
                if not before and words[7] and words[JOIN_BASE+3] == 1:
                    words[JOIN_BASE if code == 6 else JOIN_BASE+2] = 65535 if code == 6 else 1
                    before.append(words[JOIN_BASE:JOIN_BASE+8])

            words = simulate(plan, root, 1, fault=recorded(inject,events))
            assert before and words[JOIN_BASE:JOIN_BASE+8] == before[0], name
            assert words[10] == code and words[11] == 1 and words[9] == words[12] == 0
            assert tuple(words[-4:]) == CANARIES
            (destination/f'{name}-buffer.json').write_text(json.dumps(words)+'\n')
            (destination/f'{name}-injection.json').write_text(json.dumps(events)+'\n')
            report['cases'][name] = {'error': code, 'join_unchanged_after_injection': True, 'done': 1, 'result': 0, 'canaries_unchanged': True}

        for label in ('nonroot_leaf_as_root','nonroot_join_as_root','nonroot_pending_join_as_root','combined_unknown_task_root','task_count64','join_count32'):
            snapshot=[]
            events=[]
            def inject(words):
                if snapshot:return
                at=None
                if label in ('task_count64','join_count32'):
                    words[6 if label=='task_count64' else 7]=64 if label=='task_count64' else 32
                    snapshot.append((None,None));return
                if label in ('nonroot_leaf_as_root','combined_unknown_task_root'):
                    for i in range(1,words[6]):
                        pos=TASK_BASE+i*8
                        if words[pos+5]==(1 if label=='combined_unknown_task_root' else 3):
                            at=pos;words[at+2]=SENTINEL;words[at+3]=0
                            if label=='combined_unknown_task_root':words[at]=65535
                            break
                else:
                    for i in range(1,words[7]):
                        pos=JOIN_BASE+i*8
                        eligible=words[pos+6]==11 if label=='nonroot_pending_join_as_root' else words[pos+3]==1
                        if eligible:
                            at=pos;words[at+1]=SENTINEL;words[at+2]=0;break
                if at is not None:snapshot.append((at,words[at:at+8]))
            words=simulate(plan,root,2,fault=recorded(inject,events))
            code=2 if label.endswith(('64','32')) else 4
            assert snapshot and words[10]==code and words[11]==1 and words[9]==words[12]==0,label
            at,record=snapshot[0]
            assert at is None or words[at:at+8]==record,label
            assert tuple(words[-4:])==CANARIES
            (destination/f'{label}-buffer.json').write_text(json.dumps(words)+'\n')
            (destination/f'{label}-injection.json').write_text(json.dumps(events)+'\n')
            report['cases'][label]={'error':code,'faulted_record_unchanged':True,'done':1,'result':0,'canaries_unchanged':True}
    (destination/'RESULT.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    check(sys.argv[1])
