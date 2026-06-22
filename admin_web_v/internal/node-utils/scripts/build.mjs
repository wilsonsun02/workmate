#!/usr/bin/env node

import process from 'node:process';
import { spawn } from 'node:child_process';

const child = spawn('pnpm', ['exec', 'tsdown'], {
  cwd: process.cwd(),
  stdio: 'inherit',
  shell: process.platform === 'win32',
});

child.on('error', (error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});

child.on('exit', (code) => {
  process.exit(code ?? 1);
});
