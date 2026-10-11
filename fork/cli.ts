// Local experimental fork CLI. CPU reference transport is never reported as Vulkan.
import * as fs from "node:fs";
import * as path from "node:path";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import * as Bend from "../evidence/upstream/bend.ts";
import * as Capture from "./compiler/capture.ts";
import { referenceDispatch, shader, type Plan } from "./compiler/emitter.ts";

async function main(): Promise<void> {
const [source, output] = process.argv.slice(2);
if (!source || !output) throw Error("usage: bun fork/cli.ts INPUT.bend OUTPUT_DIRECTORY");
const file = path.resolve(source), out = path.resolve(output);
if (fs.existsSync(out)) throw Error("output directory must be new");
if (fs.readFileSync(file,"utf8").split("\n").filter(s=>/^\s*import\b/.test(s)).some(s=>s.trim()!=="import Base"))
  throw Error("fork version contract permits local Base-only roots");
const book=Bend.book_nil(); await Bend.book_load(book,file,"",new Map()); Bend.book_valid(book);
if(book.hols) throw Error("unchecked holes");
const plan:Plan=JSON.parse(Capture.vulkan_book(book));
const c=Capture.compile_book(book);
const declaration="OUTLINE Term corpus_eval(u64* H, Term t) {";
const boundary="    if (io_gpu && fid_bangs((u32)term_aux(t))) {";
const pending="    if ((u32)H[tl + 1] != 0) {";
const selection='  const char* why = gpu != 0 && BANGS != 0 ? gpu_probe() : "";';
if(c.split(declaration).length!==2 || c.split(boundary).length!==2 || c.split(pending).length!==2 || c.split(selection).length!==2)
  throw Error("pinned host bridge version mismatch");
const bridge=fs.readFileSync(new URL("./runtime/reference_bridge.c",import.meta.url),"utf8");
// Pending host joins enter the CPU scheduler before individual bang tasks surface.
// Reject that unsupported routing mode before it can bypass the chosen transport.
const routing=`    const char* transport = getenv("BEND_FORK_TRANSPORT");
    if (transport && !*transport) transport = NULL;
    if (transport && (u32)H[tl + 1] != 0) {
      err_fail("fork: selected transport does not support pending host parallel joins; CPU fallback refused");
    }
`;
const transport=fs.readFileSync(new URL("./runtime/transport.c",import.meta.url),"utf8");
const controller=path.resolve(path.dirname(new URL(import.meta.url).pathname),"runtime/controller.py");
const precedence=`  const char* fork_mode = getenv("BEND_FORK_TRANSPORT");
  if (fork_mode && *fork_mode) {
    if (strcmp(fork_mode, "cpu-reference") && strcmp(fork_mode, "vulkan"))
      err_fail("fork: unknown transport");
    if (!strcmp(fork_mode, "vulkan") && gpu == 0)
      err_fail("fork: --gpu off vetoes Vulkan transport");
    if (!strcmp(fork_mode, "cpu-reference") && gpu == 1)
      err_fail("fork: --gpu on conflicts with CPU-reference transport");
    gpu = 0; /* Host corpus remains CPU-owned; selected fork transport owns dispatch. */
  }
`;
const planText=JSON.stringify(plan,null,2)+"\n", shaderText=shader(plan);
fs.mkdirSync(out);
fs.writeFileSync(path.join(out,"plan.json"),planText);
fs.writeFileSync(path.join(out,"program.comp"),shaderText);
execFileSync("glslangValidator",["-V","--target-env","vulkan1.2",path.join(out,"program.comp"),"-o",path.join(out,"program.spv")]);
execFileSync("spirv-val",["--target-env","vulkan1.2",path.join(out,"program.spv")]);
const hash=(bytes: string|Buffer) => createHash("sha256").update(bytes).digest("hex");
const caller={schema:"bend-fork-vulkan-transport-v1",plan_schema:plan.schema,
  plan_sha256:hash(planText),shader_source_sha256:hash(shaderText),shader_sha256:hash(fs.readFileSync(path.join(out,"program.spv")))};
const binding=`#define FORK_CONTROLLER ${JSON.stringify(controller)}\n`
  +`#define FORK_CALLER_SCHEMA ${JSON.stringify(caller.schema)}\n`
  +`#define FORK_PLAN_SCHEMA ${JSON.stringify(caller.plan_schema)}\n`
  +`#define FORK_PLAN_SHA256 ${JSON.stringify(caller.plan_sha256)}\n`
  +`#define FORK_SHADER_SOURCE_SHA256 ${JSON.stringify(caller.shader_source_sha256)}\n`
  +`#define FORK_SHADER_SHA256 ${JSON.stringify(caller.shader_sha256)}\n`;
const patched=c.replace(declaration,binding+transport+referenceDispatch(plan)+declaration)
  .replace(pending,routing+pending).replace(boundary,bridge+"\n"+boundary)
  .replace(selection,precedence+selection);
fs.writeFileSync(path.join(out,"caller-identity.json"),JSON.stringify(caller,null,2)+"\n");
fs.writeFileSync(path.join(out,"program.c"),patched);
fs.writeFileSync(path.join(out,"default.c"),c);
fs.writeFileSync(path.join(out,"CONTRACT.txt"),"Experimental local fork v1; pinned Bend 11d483271b46e445b922756d5fd4127a1ea99ae8. BEND_FORK_TRANSPORT=cpu-reference tests host task delivery. Prepared Vulkan transport has admission disabled; --gpu off vetoes it; no CPU fallback is reported as GPU. Generated shader requires new review/hardware gate.\n");

}
main().catch(error => {
  console.error(error?.$ === "Err" ? Bend.err_show(error) : String(error));
  process.exitCode = 1;
});
