#!/usr/bin/env node

import process from 'node:process';
import path from 'node:path';
import { readFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';

import { cac } from 'cac';

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

function runCommand(command, args, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      stdio: 'inherit',
    });

    child.on('error', reject);
    child.on('exit', (code) => {
      resolve(code ?? 1);
    });
  });
}

async function runAndExit(command, args, cwd) {
  const exitCode = await runCommand(command, args, cwd);
  process.exit(exitCode);
}

async function main() {
  const workspaceRoot = await findWorkspaceRoot(process.cwd());
  const cli = cac('vsh');

  cli
    .command('lint')
    .option('--format', 'Run formatter only')
    .option('--fix', 'Run oxlint with --fix')
    .allowUnknownOptions()
    .action(async (options) => {
      const passthroughArgs = cli.args.slice(1);
      if (options.format) {
        await runAndExit('pnpm', ['exec', 'oxfmt', '.', ...passthroughArgs], workspaceRoot);
      }

      const oxlintArgs = ['exec', 'oxlint'];
      if (options.fix) {
        oxlintArgs.push('--fix');
      }
      oxlintArgs.push('.', ...passthroughArgs);
      await runAndExit('pnpm', oxlintArgs, workspaceRoot);
    });

  cli
    .command('check-circular')
    .allowUnknownOptions()
    .action(async () => {
      const passthroughArgs = cli.args.slice(1);
      await runAndExit(
        'pnpm',
        ['exec', 'circular-dependency-scanner', ...passthroughArgs],
        workspaceRoot,
      );
    });

  cli
    .command('check-dep')
    .allowUnknownOptions()
    .action(async () => {
      const passthroughArgs = cli.args.slice(1);
      await runAndExit('pnpm', ['exec', 'knip', ...passthroughArgs], workspaceRoot);
    });

  cli
    .command('publint')
    .allowUnknownOptions()
    .action(async () => {
      const passthroughArgs = cli.args.slice(1);
      await runAndExit('pnpm', ['exec', 'publint', ...passthroughArgs], workspaceRoot);
    });

  cli
    .command('code-workspace')
    .action(() => {
      console.log('code-workspace command is currently a no-op in this trimmed workspace.');
    });

  cli.help();
  cli.parse();
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
