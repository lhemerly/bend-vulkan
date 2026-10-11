import {f32Shader} from './f32_shader';
console.log(f32Shader(JSON.parse(await Bun.file(process.argv[2]).text())).trimEnd());
