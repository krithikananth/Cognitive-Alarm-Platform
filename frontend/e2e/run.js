#!/usr/bin/env node
/**
 * Playwright launcher.
 *
 * Browsers are kept next to the frontend instead of the OS cache directory,
 * and Playwright only reads that location from PLAYWRIGHT_BROWSERS_PATH when
 * its registry module is first loaded. Setting it here and re-launching the
 * real CLI in a child process is the only way to make `npm run test:e2e`
 * work without every caller exporting the variable by hand.
 */
const path = require('path');
const { spawnSync } = require('child_process');

const FRONTEND_DIR = path.resolve(__dirname, '..');

const env = { ...process.env };
if (!env.PLAYWRIGHT_BROWSERS_PATH) {
    env.PLAYWRIGHT_BROWSERS_PATH = path.join(FRONTEND_DIR, '.playwright-browsers');
}

const SUBCOMMANDS = new Set(['test', 'install', 'install-deps', 'show-report', 'codegen']);
const args = process.argv.slice(2);
const forwarded = SUBCOMMANDS.has(args[0]) ? args : ['test', ...args];

let cli;
try {
    cli = require.resolve('@playwright/test/cli');
} catch {
    cli = require.resolve('playwright/cli');
}

const result = spawnSync(process.execPath, [cli, ...forwarded], {
    stdio: 'inherit',
    cwd: FRONTEND_DIR,
    env,
});

process.exit(result.status === null ? 1 : result.status);
