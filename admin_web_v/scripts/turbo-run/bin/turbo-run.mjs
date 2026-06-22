#!/usr/bin/env node

import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { spawn } from 'node:child_process';

import { cancel, isCancel, select } from '@clack/prompts';

async function findWorkspaceRoot(startDir) {
  let currentDir = startDir;

  while (true) {
    try {
      await readFile(path.join(currentDir, 'pnpm-workspace.yaml'), 'utf8');
      return currentDir;
    } catch {}

    const parentDir = path.dirname(currentDir);
    if (parentDir === currentDir) {
      throw new Error('Cannot locate pnpm-workspace.yaml from current directory.');
    }
    currentDir = parentDir;
  }
}

async function collectPackages(dir, results = []) {
  const entries = await readdir(dir, { withFileTypes: true });

  for (const entry of entries) {
    if (!entry.isDirectory()) {
      continue;
    }
    if (entry.name === 'node_modules' || entry.name === '.git' || entry.name === 'dist') {
      continue;
    }

    const entryPath = path.join(dir, entry.name);
    const packageJsonPath = path.join(entryPath, 'package.json');

    try {
      const packageJson = JSON.parse(await readFile(packageJsonPath, 'utf8'));
      results.push({
        dir: entryPath,
        name: packageJson.name,
        scripts: packageJson.scripts || {},
      });
    } catch {}

    await collectPackages(entryPath, results);
  }

  return results;
}

function runCommand(command, args, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      stdio: 'inherit',
    });

    child.on('error', reject);
    child.on('exit', (code) => {
      process.exitCode = code ?? 1;
      resolve(code ?? 1);
    });
  });
}

async function main() {
  const command = process.argv[2];
  if (!command) {
    console.error('Please provide a script name, e.g. turbo-run dev');
    process.exit(1);
  }

  const workspaceRoot = await findWorkspaceRoot(process.cwd());
  const packages = await collectPackages(workspaceRoot);
  const selectablePackages = packages.filter((pkg) => pkg?.name && pkg?.scripts?.[command]);

  if (selectablePackages.length === 0) {
    console.error(`No workspace package contains script "${command}".`);
    process.exit(1);
  }

  let targetPackageName = selectablePackages[0].name;
  if (selectablePackages.length > 1) {
    const selected = await select({
      message: `Select the package for "${command}":`,
      options: selectablePackages.map((pkg) => ({
        label: pkg.name,
        value: pkg.name,
      })),
    });

    if (isCancel(selected)) {
      cancel('Cancelled');
      process.exit(0);
    }

    targetPackageName = selected;
  }

  const exitCode = await runCommand(
    'pnpm',
    [`--filter=${targetPackageName}`, 'run', command],
    workspaceRoot,
  );

  process.exit(exitCode);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
