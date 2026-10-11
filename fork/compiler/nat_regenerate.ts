// Reproduce GLSL bytes from the captured typed plan for generation binding.
import {natShader} from './nat_emitter.ts';
process.stdout.write(natShader(JSON.parse(await Bun.file(process.argv[2]).text())));
