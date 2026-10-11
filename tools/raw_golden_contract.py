"""Lossless source-golden contracts; diagnostics/history remain frozen.

No Bend loader, subprocess, execution, safety-admission or ledger mutation.
"""
import hashlib,json,re
from pathlib import Path

POLICY='pinned-successful-runtime-payloads-plus-one-LF-v1'
def sha_bytes(b):return hashlib.sha256(b).hexdigest()
def digest(x):return sha_bytes(json.dumps(x,sort_keys=True,separators=(',',':')).encode())
def require(ok,msg):
 if not ok:raise ValueError(msg)
def markers(source):
 require(isinstance(source,bytes),'source must be exact bytes')
 lines=[{'line':i,'payload_hex':l[2:].hex()} for i,l in enumerate(source.split(b'\n'),1) if l.startswith(b'#|')]
 return {'has_marker':bool(lines),'marker_count':len(lines),'payload_lines':lines,
         'joined_payload_hex':b'\n'.join(bytes.fromhex(l['payload_hex']) for l in lines).hex()}
def kind(row,raw):
 if not raw['has_marker']:return 'missing-golden-contract'
 # Classify using the FROZEN diagnostic field, never raw leading-LF text.
 if row['expected_output'].startswith('SOME PROOFS FAIL'):return 'checker-negative-contract'
 if not row['main_marker_per_upstream_gate']:return 'check-verdict-contract'
 if any(bytes.fromhex(l['payload_hex']).startswith(b'exit ') and bytes.fromhex(l['payload_hex'])!=b'exit 0' for l in raw['payload_lines']):return 'runtime-negative-contract-review'
 return 'positive-runtime-contract-candidate'
def source_record(row,source):
 require(sha_bytes(source)==row['sha256'],'source/hash drift')
 raw=markers(source);group=kind(row,raw)
 stdout=None
 if group=='positive-runtime-contract-candidate':
  # This declared, reviewed corpus policy applies only to marker-bearing
  # successful runtime. It is NOT part of the lossless marker extractor.
  stdout=bytes.fromhex(raw['joined_payload_hex'])+b'\n'
 return {'path':row['path'],'source_sha256':row['sha256'],'raw':raw,'contract_group':group,
  'frozen_expected_output':row['expected_output'],'frozen_expected_output_sha256':sha_bytes(row['expected_output'].encode()),
  'successful_runtime':None if stdout is None else {'policy':POLICY,'stdout_hex':stdout.hex(),'stdout_sha256':sha_bytes(stdout),'stderr_hex':'','exit':0},
  'safety_admission_granted':False,'historical_status_hint':row['status']}

class FrozenBundle:
 def __init__(self,sidecar_bytes,freeze,parser_bytes,inventory_bytes,baseline_bytes):
  require(sha_bytes(sidecar_bytes)==freeze['sidecar_sha256'],'sidecar mutation')
  require(sha_bytes(parser_bytes)==freeze['parser_policy_sha256'],'parser/policy mutation')
  require(sha_bytes(inventory_bytes)==freeze['inventory_sha256'],'inventory mutation')
  require(sha_bytes(baseline_bytes)==freeze['baseline_ledger_sha256'],'historical ledger mutation')
  self.data=json.loads(sidecar_bytes);self.freeze=dict(freeze);self.records={r['path']:r for r in self.data['records']}
  require(len(self.records)==len(self.data['records']),'duplicate source record')
  self._canonical=digest(self.data);self._freeze_canonical=digest(freeze)
  self._baseline_bytes=baseline_bytes
  self._rows={r['path']:r for r in json.loads(baseline_bytes)['files']}
 def _entry(self,row,source):
  require(digest(self.data)==self._canonical and digest(self.freeze)==self._freeze_canonical,'in-memory contract mutation')
  require(row==self._rows.get(row['path']),'row no longer matches frozen history/selection')
  entry=self.records.get(row['path']);require(entry is not None,'unbound path')
  require(entry==source_record(row,source),'source/raw-golden/diagnostic drift')
  return entry
 def context(self,row,source):
  e=self._entry(row,source)
  require(e['successful_runtime'] is not None,'not a successful-runtime oracle')
  return {'sidecar_sha256':self.freeze['sidecar_sha256'],'parser_policy_sha256':self.freeze['parser_policy_sha256'],
   'inventory_sha256':self.freeze['inventory_sha256'],'baseline_ledger_sha256':self.freeze['baseline_ledger_sha256'],
   'review_archive_sha256':self.freeze['review_archive_sha256'],'path':row['path'],'source_sha256':e['source_sha256'],
   'successful_runtime_contract':e['successful_runtime'],'diagnostic_field_unchanged_sha256':e['frozen_expected_output_sha256']}
 def bind_fresh_basis(self,basis,row,source):
  require('raw_golden_binding' not in basis,'do not retrofit an already-bound receipt basis')
  result=dict(basis);result['raw_golden_binding']=self.context(row,source);return result
 def exact_fresh_runtime(self,receipt,row,source,stdout,stderr):
  context=self.context(row,source)
  require(receipt.get('basis',{}).get('raw_golden_binding')==context,'old/stale receipt cannot become fresh under new oracle')
  require(receipt.get('receipt_sha256')==digest({k:v for k,v in receipt.items() if k!='receipt_sha256'}),'receipt integrity changed')
  require(sha_bytes(stdout)==receipt.get('stdout_sha256') and sha_bytes(stderr)==receipt.get('stderr_sha256'),'captured output bytes changed')
  c=context['successful_runtime_contract']
  return receipt.get('timeout') is False and receipt.get('exit')==0 and stdout==bytes.fromhex(c['stdout_hex']) and stderr==b''
 def observe_historical(self,row,source,stdout,stderr,exit_code,timed_out):
  e=self._entry(row,source);c=e['successful_runtime']
  return {'original_status_preserved':row['status'],'fresh_execution':False,'status_promoted':False,
   'raw_contract_match':c is not None and not timed_out and exit_code==0 and stdout==bytes.fromhex(c['stdout_hex']) and stderr==b''}
