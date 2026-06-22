#!/usr/bin/env node

import { rm } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const root = process.cwd();
const args = new Set(process.argv.slice(2));

const targets = [
  'node_modules',
  '.turbo',
  'apps/web-ele/node_modules',
  'apps/web-ele/dist',
  'internal/node-utils/dist',
];

if (args.has('--del-lock')) {
  targets.push('pnpm-lock.yaml');
}

async function removeTarget(relativePath) {
  const fullPath = path.join(root, relativePath);
  await rm(fullPath, {
    force: true,
    recursive: true,
  });
  console.log(`Removed ${relativePath}`);
}

async function main() {
  for (const target of targets) {
    await removeTarget(target);
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
