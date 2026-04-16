#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

function ensure(condition, message) {
  if (!condition) throw new Error(message);
}

function readText(filePath) {
  return fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, '');
}

function readJson(filePath) {
  return JSON.parse(readText(filePath));
}

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const next = argv[i + 1];
    out[key] = next && !next.startsWith('--') ? next : true;
    if (out[key] !== true) i += 1;
  }
  return out;
}

function normalizeRel(value) {
  return String(value || '').replace(/[\\/]+/g, path.sep).replace(/^\.([\\/])/, '');
}

function shouldIgnoreChangedFile(relPath) {
  const normalized = normalizeRel(relPath);
  return /(^|[\\/])(backup|output|node_modules|__pycache__|\.git|\.venv|venv)([\\/]|$)/i.test(normalized)
    || /\.pyc$/i.test(normalized);
}

function readLines(filePath) {
  if (!filePath || !fs.existsSync(filePath)) return [];
  return readText(filePath).split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
}

function gatherFilesRecursive(rootDir) {
  const out = [];
  if (!fs.existsSync(rootDir)) return out;
  const stack = [rootDir];
  while (stack.length) {
    const current = stack.pop();
    const entries = fs.readdirSync(current, { withFileTypes: true });
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) stack.push(full);
      else out.push(full);
    }
  }
  return out;
}

function loadTask(taskFile, taskId) {
  const raw = readJson(taskFile);
  if (Array.isArray(raw.tasks)) {
    if (taskId) {
      const found = raw.tasks.find((t) => String(t.task_id || '') === String(taskId));
      ensure(found, `task_id not found: ${taskId}`);
      return found;
    }
    ensure(raw.tasks.length === 1, 'task file contains multiple tasks; pass --task-id');
    return raw.tasks[0];
  }
  return raw;
}

function countChangedLines(beforeText, afterText) {
  const before = beforeText.split(/\r?\n/);
  const after = afterText.split(/\r?\n/);
  let changed = 0;
  const max = Math.max(before.length, after.length);
  for (let i = 0; i < max; i += 1) {
    if ((before[i] || '') !== (after[i] || '')) changed += 1;
  }
  return changed;
}

function getChangedFiles(projectRoot, beforeDir, changedFilesPath) {
  if (changedFilesPath) {
    return readLines(path.resolve(changedFilesPath)).map(normalizeRel).filter((rel) => !shouldIgnoreChangedFile(rel));
  }

  return gatherFilesRecursive(projectRoot)
    .map((full) => path.relative(projectRoot, full))
    .filter((rel) => !shouldIgnoreChangedFile(rel))
    .filter((rel) => {
      const beforeFile = path.join(beforeDir, rel);
      if (!fs.existsSync(beforeFile)) return true;
      return readText(full) !== readText(beforeFile);
    })
    .map(normalizeRel);
}

function main() {
  const args = parseArgs(process.argv);
  ensure(args['project-root'], '--project-root is required');
  ensure(args['task-file'], '--task-file is required');
  ensure(args['before-dir'], '--before-dir is required');

  const projectRoot = path.resolve(args['project-root']);
  const beforeDir = path.resolve(args['before-dir']);
  const task = loadTask(path.resolve(args['task-file']), args['task-id']);
  const changedFiles = getChangedFiles(projectRoot, beforeDir, args['changed-files']);

  const targetFiles = new Set(
    (task.target_files || task.paths || [])
      .map(normalizeRel)
      .filter(Boolean)
  );
  const normalizedChanged = changedFiles.map(normalizeRel).filter(Boolean);
  const outside = normalizedChanged.filter((rel) => !targetFiles.has(rel));
  ensure(outside.length === 0, `non-target files changed: ${outside.join(', ')}`);

  const report = {
    task_id: task.task_id || task.name || '',
    checked_files: [],
    warnings: []
  };

  for (const rel of normalizedChanged) {
    const currentPath = path.join(projectRoot, rel);
    const beforePath = path.join(beforeDir, rel);
    const currentText = fs.existsSync(currentPath) ? readText(currentPath) : '';
    const beforeText = fs.existsSync(beforePath) ? readText(beforePath) : '';
    const changedLines = countChangedLines(beforeText, currentText);
    if (changedLines > 200) {
      report.warnings.push(`${rel}: large diff (${changedLines} changed lines)`);
    }
    report.checked_files.push({ file: rel, changedLines });
  }

  const reuseSymbols = task.reuse_symbols || task.reuseSymbols || [];
  const symbolMisses = [];
  for (const symbol of reuseSymbols) {
    const found = normalizedChanged.some((rel) => {
      const currentPath = path.join(projectRoot, rel);
      if (!fs.existsSync(currentPath)) return false;
      return readText(currentPath).includes(symbol);
    });
    if (!found) symbolMisses.push(symbol);
  }
  if (symbolMisses.length > 0) {
    report.warnings.push(`reuse symbols not found in changed targets: ${symbolMisses.join(', ')}`);
  }

  const doNotTouch = task.do_not_touch || task.doNotTouch || [];
  const protectKoreanUi = doNotTouch.some((item) => /korean ui strings/i.test(String(item)));
  if (protectKoreanUi) {
    const hangulPattern = /[\u3131-\u318E\uAC00-\uD7A3]/;
    const suspiciousPattern = /[\uFFFD]|誘|寃|紐|吏|媛/;
    for (const rel of normalizedChanged) {
      const currentPath = path.join(projectRoot, rel);
      const beforePath = path.join(beforeDir, rel);
      if (!fs.existsSync(currentPath) || !fs.existsSync(beforePath)) continue;
      const beforeText = readText(beforePath);
      const afterText = readText(currentPath);
      if (hangulPattern.test(beforeText) && suspiciousPattern.test(afterText)) {
        throw new Error(`possible Korean runtime corruption detected in ${rel}`);
      }
    }
  }

  const templateTargets = normalizedChanged.filter((rel) => /\.(html?|jinja2)$/i.test(rel));
  if (templateTargets.length > 0) {
    const checker = path.join(projectRoot, 'scripts', 'verify_template_inline_scripts.py');
    if (fs.existsSync(checker)) {
      const verify = spawnSync('python', [checker, '--baseline-root', beforeDir, ...templateTargets.map((rel) => path.join(projectRoot, rel))], {
        cwd: projectRoot,
        encoding: 'utf8',
        errors: 'replace'
      });
      if ((verify.status || 0) !== 0) {
        throw new Error(`template inline script verification failed:\n${(verify.stderr || verify.stdout || '').trim()}`);
      }
    }
  }

  console.log(JSON.stringify(report, null, 2));
}

main();
