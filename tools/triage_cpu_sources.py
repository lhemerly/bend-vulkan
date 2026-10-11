"""Read sources only: no Bend loading, compiling, imports, or execution."""
import collections
import hashlib
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / 'bend-vulkan-feasibility/source'
LEDGER = ROOT / 'evidence/cpu-compatibility-ledger-v9/LEDGER.json'
OUT = ROOT / 'evidence/cpu-safety-triage-v1'
OUT.mkdir(exist_ok=True)
sha = lambda b: hashlib.sha256(b).hexdigest()

# Individually read, finite computations / captured stdout; no custom import.
reviewed = {'tests/io/' + n + '.bend' for n in (
    'bind_let_shape bool_bridge confluence_sharing do_let_lines driver_name_clash '
    'float_printing_000 float_printing_001 hello_end_to_end hello_print '
    'intrinsic_user_name main_alias_io main_forged_io print_write pure_main_exit '
    'readback_chain readback_sugars request_dead_fall text_formatting').split()}
reviewed.add('tests/run/literal_sugar.bend')

def classify(symbol):
    if symbol.startswith(('TCP.', 'UDP.', 'TLS.')) or symbol in ('HTTP.fetch', 'HTTP.exchange'):
        return 'network'
    if symbol.startswith(('Window.', 'GFX.', 'Gfx.')) or symbol in ('App.run', 'App.play', 'App.loop'):
        return 'GUI'
    if symbol.startswith('Audio.'):
        return 'audio'
    if symbol.startswith('File.'):
        return 'filesystem'
    if symbol.startswith('Process.'):
        return 'subprocess'
    if symbol in ('IO.get_env', 'IO.args'):
        return 'environment-or-argv'
    if symbol.startswith(('Chan.', 'Thread.', 'Fiber.')) or symbol in ('IO.fork', 'IO.join', 'IO.spawn', 'IO.sleep', 'IO.now', 'IO.within', 'IO.thread_count', 'IO.random_u32'):
        return 'scheduling-time-randomness'
    if symbol in ('IO.print', 'IO.write'):
        return 'captured-stdout'
    if symbol in ('IO.print_err', 'IO.die'):
        return 'stderr-or-nonzero-contract'
    if symbol.startswith('HTTP.'):
        return 'HTTP-pure-surface-or-type'
    return 'IO-construction-or-other-symbol'

def inspect(rel, seen):
    if rel in seen:
        return
    p = SOURCE / rel
    if not p.resolve().is_relative_to(SOURCE.resolve()) or not p.is_file():
        return
    data = p.read_bytes()
    text = data.decode()
    entry = {'path': rel, 'sha256': sha(data), 'imports': [], 'symbol_evidence': []}
    seen[rel] = entry
    for line_no, line in enumerate(text.splitlines(), 1):
        # Code references only; diagnostic/comment words are not effects.
        code = re.sub(r'"(?:\\.|[^"\\])*"', '""', line).split('#', 1)[0]
        for m in re.finditer(r'\b(?:IO|File|TCP|Tcp|UDP|Udp|TLS|Http|HTTP|GFX|Gfx|Audio|Window|App|Process|Chan|Thread|Fiber)\.[A-Za-z_][\w.]*', code):
            sym = m.group().rstrip('.')
            entry['symbol_evidence'].append({'line': line_no, 'symbol': sym, 'category': classify(sym), 'source_line': line.strip()})
        if p.suffix in ('.c', '.js'):
            for category, pattern in {
                'network': r'\b(?:socket|connect|accept|listen|bind|send|recv|sendto|recvfrom|getaddrinfo|fetch)\s*\(',
                'filesystem': r'\b(?:fopen|open|mkfifo|unlink|rename|mkdir|readFileSync|writeFileSync|createReadStream)\s*\(',
                'subprocess': r'\b(?:system|popen|execve|execl|spawn|execSync)\s*\(',
                'environment-or-argv': r'\bgetenv\s*\(|\bprocess\.(?:env|argv)\b',
                'GUI': r'\bSDL_(?:CreateWindow|Init|PollEvent)\s*\(',
                'audio': r'\b(?:snd_pcm_open|SDL_OpenAudioDevice)\s*\(',
            }.items():
                for m in re.finditer(pattern, code):
                    entry['symbol_evidence'].append({'line':line_no,'symbol':m.group(),'category':category,'source_line':line.strip(),'note':'foreign-source operation presence, not proven reachability'})
        m = re.match(r'^\s*import\s+(.+?)\s*$', line.split('#', 1)[0])
        if not m:
            continue
        spec = m.group(1).strip()
        imp = {'line': line_no, 'spelling': spec}
        entry['imports'].append(imp)
        if spec == 'Base':
            imp['kind'] = 'pinned-Base-not-whole-prelude-effect-propagation'
            continue
        target = spec.split(' as ')[0].strip('"')
        imp['kind'] = 'foreign-source' if target.endswith(('.c', '.js')) else 'module-source'
        if not target.startswith('.'):
            imp['resolution'] = 'not-read-absolute-or-unrecognized-path'
            continue
        q = (p.parent / target).resolve()
        if not q.is_relative_to(SOURCE.resolve()) or not q.is_file():
            imp['resolution'] = 'missing-or-outside-pinned-source'
            continue
        imp['resolved_path'] = str(q.relative_to(SOURCE.resolve()))
        imp['resolution'] = 'local-source-read-only'
        inspect(imp['resolved_path'], seen)

ledger = json.loads(LEDGER.read_text())
rows = []
for row in ledger['files']:
    if row['status'] != 'pending-safety-review':
        continue
    closure = {}
    inspect(row['path'], closure)
    assert closure[row['path']]['sha256'] == row['sha256']
    own = closure[row['path']]
    symbols = [e for s in closure.values() for e in s['symbol_evidence']]
    categories = sorted({e['category'] for e in symbols})
    imports = [i for s in closure.values() for i in s['imports']]
    nonbase = [i for i in imports if i['kind'] != 'pinned-Base-not-whole-prelude-effect-propagation']
    source_text = (SOURCE / row['path']).read_text()
    probe_import_ok = all(l.strip() == 'import Base' for l in source_text.splitlines() if re.match(r'^\s*import\b', l))
    checker_only = probe_import_ok and row['expected_negative'] and row['expected_output'].startswith('SOME PROOFS FAIL')
    if row['path'] == 'bend2/base.bend':
        decision = 'prelude-definition-inventory-not-execution-case'
    elif checker_only:
        decision = 'candidate-checker-only-no-runtime'
    elif row['path'] in reviewed:
        assert probe_import_ok and not row['expected_negative']
        decision = 'candidate-finite-computation-captured-stdout'
    elif any(c in categories for c in ('network','GUI','audio','filesystem','subprocess','environment-or-argv')):
        decision = 'environment-or-manual-effect-review'
    elif nonbase or not probe_import_ok:
        decision = 'import-or-foreign-closure-probe-support-review'
    elif row['expected_negative'] or re.search(r'^#\|exit [1-9]',source_text,re.M) or 'stderr-or-nonzero-contract' in categories:
        decision = 'runtime-stream-exit-contract-review'
    else:
        decision = 'manual-cost-scheduling-or-pure-helper-review'
    rows.append({'path': row['path'], 'sha256': row['sha256'], 'original_risk': row['risk'],
                 'decision': decision, 'effect_reference_categories': categories,
                 'expected_negative': row['expected_negative'],
                 'main_marker_per_upstream_gate': row['main_marker_per_upstream_gate'],
                 'candidate_compiled_lanes_per_upstream_gate': row['candidate_compiled_lanes_per_upstream_gate'],
                 'current_harness_admitted': False, 'source_closure': list(closure.values())})

counts = dict(collections.Counter(r['decision'] for r in rows))
result = {'schema': 'bend-cpu-source-safety-triage-v1', 'ledger_sha256': sha(LEDGER.read_bytes()),
          'triage_script_sha256': sha(pathlib.Path(__file__).read_bytes()), 'reviewed_records': len(rows),
          'executions': 0, 'GPU_dispatches': 0, 'ledger_or_safety_rules_modified': False,
          'counts': counts, 'remaining_ledger_counts': ledger['summary']['statuses'],
          'limitations': ['References are source evidence, not proven main reachability. Imported foreign sources remain manual review regardless of symbols.',
                          'Current strict harness asserts no risk at line 67; all 249 retain risk and remain blocked. Candidates require a reviewed, freshly bound admission manifest; no rule/ledger edits made.',
                          'Checker-only candidates have Base-only imports and checker-failure goldens; existing negative branch cannot enter runtime even if check unexpectedly succeeds.',
                          'Import parser/closure inventory is conservative textual review, not Bend semantic evaluation. Absolute/missing/unknown import spellings were never opened.',
                          'Library v6 contains the full 521-case checkpoint before this separate source triage.'],
          'records': rows}
(OUT/'TRIAGE.json').write_text(json.dumps(result, indent=2)+'\n')
for label in counts:
    (OUT/(label+'.json')).write_text(json.dumps([r for r in rows if r['decision']==label],indent=2)+'\n')
lines = ['# CPU source safety triage — no cases executed', '',
         'All 249 safety-review records retain their original ledger status. This is a source review, not runtime correctness evidence.', '',
         'The frozen strict runner asserts `not row["risk"]` before checkup. Therefore even the source-safe candidates below are **not admitted by the current checkpoint**. A future reviewed admission manifest must preserve source hashes and bind the revised policy before execution. The Base-only probe remains unchanged.', '',
         '| Decision | Records |', '|---|---:|']
lines += [f'| {k} | {v} |' for k,v in counts.items()]
lines += ['', '## Candidate computation / captured stdout', '',
          'These sources were individually read. They contain finite local computation with Base print/write only (or pure values). Base print/write C/JS definitions were inspected: they emit captured stdout, not files or messages. Bounds and printer eligibility remain runtime obligations. IO interpreter uses the generated JS driver, not an independent numeric engine.', '']
lines += [f'- `{r["path"]}`' for r in rows if r['decision']=='candidate-finite-computation-captured-stdout']
lines += ['', '## Candidate checker-only', '',
          'These 11 Base-only records expect `SOME PROOFS FAIL`. Their permitted obligation would be checkup and normalized diagnostics only. Network/GUI names in some invalid bodies do not authorize their runtime. Existing strict negative branch compares check exit/diagnostics and continues before interpreter/native work.', '']
lines += [f'- `{r["path"]}`' for r in rows if r['decision']=='candidate-checker-only-no-runtime']
lines += ['', '## Kept for explicit review', '',
          'Every record has source hashes, import edges, line-numbered code references and a decision in TRIAGE.json and the per-decision lists. Network includes loopback TCP/UDP as well as external hosts; local sockets still require a reserved network fixture. GUI/audio are held even for invalid-handle/rate-zero tests. Files need disposable scratch paths and cleanup; env/argv need a fixed allowlisted environment; subprocess cases need executable/argv approval. No ambient environment or credentials were read.', '',
          'Foreign C/JS and non-Base imports remain held: even a harmless-looking module cannot pass the current Base-only probe. Missing/absolute/hub-spelled imports need loader-path review; do not invent fixtures or fetch them. Pure LAWS/PROOF dependencies importing application modules are not themselves evidence that the app main is safe to execute.', '',
          'Runtime-negative/stdout-stderr contracts require explicit lane obligations: the current successful runtime contract demands empty stderr and exit zero. `print_utf8_law` writes stderr; `text_utf8` exits 7. Neither is a success under that contract. `confluence_threads` documents a slow interpreter (4096 leaves); `stack_fault_trap` deliberately drives 300M levels. Keep both outside the ordinary bounded batch. Channels/fibers/timers/randomness need reviewed scheduling/cost semantics, not merely a namespace exemption.', '',
          'Cumulative checkpoint stays 521 accounted, 910 pending, 249 safety-review. Five new printer-ineligible C/JS cases remain unpassed (seven cumulative). CPU_PAUSE remains present; no GPU or heavy job was started.']
(OUT/'REVIEW.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'reviewed_records':len(rows),'counts':counts,'executions':0},indent=2))
