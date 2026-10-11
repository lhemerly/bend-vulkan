"""Generate a bounded single-workgroup SPSC shader from the reviewed helper source."""
from pathlib import Path
import json,hashlib,struct
root=Path(__file__).resolve().parents[1]
s=(root/'shaders/ring_fixture.comp').read_text();s=s[:s.index('\nvoid main()')].replace('layout(local_size_x = 1)','layout(local_size_x = 128)').replace('#version 450','#version 450\n#extension GL_KHR_shader_subgroup_basic : require')
s=s[:s.index('// Runtime primitive')] + '// Bounded single-workgroup publication/reuse litmus; not a general runtime.\n' + s[s.index('layout(local_size_x'): ]
s+='''
// One producer/consumer, uniform workgroup execution phases. NO Buffer barrier semantics.
void phase() { controlBarrier(gl_ScopeWorkgroup, gl_ScopeWorkgroup,
    gl_StorageSemanticsShared, gl_SemanticsAcquireRelease); }
uint payloadLow(uint i) { return (i * 1664525u) ^ 0x9e3779b9u; }
uint payloadHigh(uint i) { return (5u << 24) | ((i & 65535u) << 8) | (i & 255u); }
void main() {
    // These decisions are uniform within each workgroup. One WG owns this buffer.
    if (any(notEqual(gl_WorkGroupID,uvec3(0u)))) return;
    if (w.length()<44 || w[31]!=4096u || gl_NumSubgroups<2u) return;
    uint start=w[30], iterations=w[31];
    bool producer=gl_SubgroupID==0u && gl_SubgroupInvocationID==0u;
    bool consumer=gl_SubgroupID==1u && gl_SubgroupInvocationID==0u;
    if(producer) {
        for(uint j=0u;j<30u;j++) w[j]=0u;
        for(uint j=32u;j<44u;j++) w[j]=0u;
        storeRelease(W_GET,start);storeRelease(W_PUT,start);
        for(uint slot=0u;slot<4u;slot++) {
            uint pos=start+((slot-start)&3u);
            storeRelease(W_SLOTS+2u*slot+1u,(1u-lapOf(pos))<<31);
        }
        w[40]=gl_SubgroupSize;w[41]=gl_NumSubgroups;w[42]=gl_SubgroupID;
        storeRelease(W_ERR,0u); // release all initialization before helpers read error acquire.
    }
    phase();
    for(uint i=0u;i<iterations;i++) {
        if(producer && !ringPush(payloadHigh(i),payloadLow(i))) {
            atomicAdd(w[32],1u,gl_ScopeDevice,gl_StorageSemanticsNone,gl_SemanticsRelaxed);
        }
        phase();
        if(consumer) {
            uint hi,lo;
            w[43]=gl_SubgroupID;
            bool ok=ringPop(hi,lo);
            if(!ok || hi!=payloadHigh(i) || lo!=payloadLow(i)) {
                atomicAdd(w[32],1u,gl_ScopeDevice,gl_StorageSemanticsNone,gl_SemanticsRelaxed);
                firstError(ERR_FIX2);
            } else {
                atomicAdd(w[36],1u,gl_ScopeDevice,gl_StorageSemanticsNone,gl_SemanticsRelaxed);
                w[38]=lo;w[39]=hi;
            }
        }
        phase(); // consumer get release precedes producer's next get acquire.
    }
    if(producer) {
        storeRelease(33u,loadAcquire(W_GET));storeRelease(34u,loadAcquire(W_PUT));
        storeRelease(35u,loadAcquire(W_ERR));
        uint slot=(start+iterations-1u)&3u;storeRelease(37u,loadAcquire(W_SLOTS+2u*slot+1u));
    }
}
'''
(root/'shaders/publication_litmus.comp').write_text(s)
starts=[0,1,3,4,0xfffffff8,0xfffffffc,0xfffffffe,0xffffffff]
p=root/'evidence/litmus-fixtures';p.mkdir(exist_ok=True)
for start in starts:
 initial=[0xdeadbeef]*44;initial[30]=start;initial[31]=4096
 expected=[0]*40;expected[0]=expected[1]=(start+4096)&0xffffffff
 for slot in range(4):
  i=4095-(((start+4095)&3)-slot)%4;pos=(start+i)&0xffffffff
  expected[3+2*slot]=((i*1664525)&0xffffffff)^0x9e3779b9
  expected[4+2*slot]=(5<<24)|((i&65535)<<8)|(i&255)|(((~(pos>>2))&1)<<31)
 expected[30]=start;expected[31]=4096;expected[33]=expected[34]=expected[0];expected[36]=4096
 expected[37]=expected[4+2*((start+4095)&3)];expected[38]=((4095*1664525)&0xffffffff)^0x9e3779b9;expected[39]=(5<<24)|((4095&65535)<<8)|(4095&255)
 for name,values in [('input',initial),('expected',expected)]:
  (p/f'{start:08x}-{name}.bin').write_bytes(struct.pack('<'+'I'*len(values),*values))
(p/'manifest.json').write_text(json.dumps({'starts':starts,'pairs_per_case':4096,'logical_words':44,'exact_oracle_words':40,'dynamic_subgroup_words':[40,41,42,43],'workgroups':[1,1,1],'local_size':[128,1,1],'gpu_dispatches':0,'scope':'strictly alternating singleWG-SPSC occupancy<=1; publication/reuse/wrap only; distinct subgroup leaders, Shared-only phase barriers; Buffer payload depends high release/acquire','shader_sha256':hashlib.sha256(s.encode()).hexdigest()},indent=2)+'\n')
print('Built bounded single-WG SPSC design and8 fixtures with exact40-word oracle and4 subgroup metadata words. NoGPU dispatch.')
