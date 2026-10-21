import { build } from 'esbuild';
await build({entryPoints:['frontend/storefront.jsx'],bundle:true,minify:true,format:'iife',target:['es2020'],outfile:'static/storefront.js',legalComments:'external',define:{'process.env.NODE_ENV':'"production"'},jsx:'automatic'});
