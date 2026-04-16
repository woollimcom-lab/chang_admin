#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

function ensure(condition, message) {
  if (!condition) throw new Error(message);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, ''));
}

function writeJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(value, null, 2));
}

function isObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value);
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function parseArgs(argv) {
  const args = argv.slice(2);
  const positional = [];
  let reportPath = '';

  for (let index = 0; index < args.length; index += 1) {
    const current = args[index];
    if (current === '--report') {
      reportPath = args[index + 1] || '';
      index += 1;
      continue;
    }
    positional.push(current);
  }

  return {
    requestPath: positional[0],
    outputPath: positional[1],
    reportPath
  };
}

function humanizeFeatureId(featureId) {
  return String(featureId || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function normalizeFeatureRequest(item, index) {
  if (typeof item === 'string' && item.trim()) {
    return { id: item.trim(), inlineOverride: {} };
  }

  if (isObject(item) && typeof item.id === 'string' && item.id.trim()) {
    const inlineOverride = clone(item);
    delete inlineOverride.id;
    return { id: item.id.trim(), inlineOverride };
  }

  throw new Error(`request.features[${index}] must be a string feature id or an object with an id field`);
}

function mergeObjects(base, override) {
  return Object.assign({}, base || {}, override || {});
}

function mergeArrayField(feature, override, fieldName) {
  if (Object.prototype.hasOwnProperty.call(override, fieldName)) {
    return clone(override[fieldName] || []);
  }
  return clone(feature[fieldName] || []);
}

function resolveScalar(feature, override, fieldName, fallback = undefined) {
  if (Object.prototype.hasOwnProperty.call(override, fieldName)) {
    return override[fieldName];
  }
  if (Object.prototype.hasOwnProperty.call(feature, fieldName)) {
    return feature[fieldName];
  }
  return fallback;
}

function buildInstruction(feature, override, targetFiles, goal) {
  const explicit = resolveScalar(feature, override, 'instruction', '');
  if (typeof explicit === 'string' && explicit.trim()) {
    return explicit.trim();
  }

  const fileText = Array.isArray(targetFiles) && targetFiles.length > 0
    ? `Update only ${targetFiles.join(', ')}.`
    : 'Keep changes tightly scoped.';
  const goalText = typeof goal === 'string' && goal.trim()
    ? ` ${goal.trim()}`
    : '';
  return `${fileText}${goalText}`.trim();
}

function buildVerification(feature, override, presets, request, featureId) {
  const requestVerification = isObject(request.verification) ? request.verification : {};
  const featureVerification = isObject(feature.verification) ? feature.verification : {};
  const overrideVerification = isObject(override.verification) ? override.verification : {};
  const presetName = resolveScalar(feature, override, 'verification_preset', 'none');
  const preset = presets[presetName] || presets.none || { steps: [] };

  const mergedVerification = mergeObjects(
    mergeObjects(
      mergeObjects(preset, featureVerification),
      requestVerification
    ),
    overrideVerification
  );

  const urlRaw = mergedVerification.url || request.url || request.defaultUrl || '';
  const url = typeof urlRaw === 'string' ? urlRaw.trim() : '';
  ensure(url, `verification url is required for feature: ${featureId}`);
  const useAuth = Object.prototype.hasOwnProperty.call(mergedVerification, 'useAuth')
    ? !!mergedVerification.useAuth
    : request.useAuth !== false;
  const forbidDialogs = Object.prototype.hasOwnProperty.call(mergedVerification, 'forbidDialogs')
    ? !!mergedVerification.forbidDialogs
    : !!preset.forbidDialogs;

  let steps = preset.steps || [];
  if (Array.isArray(featureVerification.steps)) steps = featureVerification.steps;
  if (Array.isArray(requestVerification.steps)) steps = requestVerification.steps;
  if (Array.isArray(overrideVerification.steps)) steps = overrideVerification.steps;

  const verification = clone(mergedVerification);
  verification.url = url;
  verification.useAuth = useAuth;
  verification.forbidDialogs = forbidDialogs;
  verification.steps = clone(steps);
  return verification;
}

function buildTask(featureId, feature, inlineOverride, featureOverrides, presets, request, index) {
  const namedOverride = isObject(featureOverrides[featureId]) ? featureOverrides[featureId] : {};
  const override = mergeObjects(namedOverride, inlineOverride);

  const targetFiles = mergeArrayField(feature, override, 'target_files');
  const goal = resolveScalar(feature, override, 'goal', '');
  const verification = buildVerification(feature, override, presets, request, featureId);
  const task = {
    task_id: resolveScalar(feature, override, 'task_id', `${featureId}-${String(index + 1).padStart(3, '0')}`),
    priority: resolveScalar(feature, override, 'priority', request.priority || 'high'),
    name: resolveScalar(feature, override, 'name', humanizeFeatureId(featureId)),
    goal,
    instruction: buildInstruction(feature, override, targetFiles, goal),
    target_files: targetFiles,
    reuse_symbols: mergeArrayField(feature, override, 'reuse_symbols'),
    do_not_touch: mergeArrayField(feature, override, 'do_not_touch'),
    acceptance: mergeArrayField(feature, override, 'acceptance'),
    verification,
    rollback_plan: resolveScalar(
      feature,
      override,
      'rollback_plan',
      'restore workspace snapshot and restore uploaded target files if reviewer or verification fails'
    ),
    promotion_rule: resolveScalar(
      feature,
      override,
      'promotion_rule',
      'promote only after the same pattern passes again on a similar task'
    )
  };

  const maxChangedFiles = resolveScalar(feature, override, 'maxChangedFiles', undefined);
  if (Number.isInteger(maxChangedFiles) && maxChangedFiles > 0) {
    task.maxChangedFiles = maxChangedFiles;
  }

  const batch = resolveScalar(feature, override, 'batch', '');
  if (typeof batch === 'string' && batch.trim()) {
    task.batch = batch.trim();
  }

  const dependsOn = resolveScalar(feature, override, 'depends_on', []);
  if (Array.isArray(dependsOn) && dependsOn.length > 0) {
    task.depends_on = clone(dependsOn);
  }

  return task;
}

function buildReport(request, outputPath, tasks) {
  const byFile = new Map();
  const byBatch = new Map();
  const warnings = [];

  tasks.forEach((task) => {
    const batchName = (task.batch || 'default').trim() || 'default';
    const batchTasks = byBatch.get(batchName) || [];
    batchTasks.push(task.task_id);
    byBatch.set(batchName, batchTasks);

    task.target_files.forEach((file) => {
      const refs = byFile.get(file) || [];
      refs.push(task.task_id);
      byFile.set(file, refs);
    });

    if (!task.instruction || !task.instruction.trim()) {
      warnings.push(`${task.task_id}: missing instruction`);
    }
    if (!task.verification.url && Array.isArray(task.verification.steps) && task.verification.steps.length > 0) {
      warnings.push(`${task.task_id}: verification has steps but empty url`);
    }
  });

  const hotspotFiles = Array.from(byFile.entries())
    .map(([file, taskIds]) => ({ file, count: taskIds.length, task_ids: taskIds }))
    .filter((entry) => entry.count > 1)
    .sort((left, right) => right.count - left.count || left.file.localeCompare(right.file));

  if (hotspotFiles.length > 0) {
    warnings.push(`hotspot files detected: ${hotspotFiles.length}`);
  }

  return {
    request_id: request.request_id || '',
    goal: request.goal || '',
    generated_queue: path.resolve(outputPath),
    feature_count: Array.isArray(request.features) ? request.features.length : 0,
    task_count: tasks.length,
    batches: Array.from(byBatch.entries()).map(([name, taskIds]) => ({
      name,
      task_count: taskIds.length,
      task_ids: taskIds
    })),
    hotspot_files: hotspotFiles,
    tasks: tasks.map((task) => ({
      task_id: task.task_id,
      name: task.name || '',
      priority: task.priority || '',
      batch: task.batch || 'default',
      target_files: task.target_files
    })),
    warnings
  };
}

function main() {
  const { requestPath, outputPath, reportPath } = parseArgs(process.argv);
  ensure(requestPath, 'usage: node scripts/compile_request_to_tasks.js <request.json> <output.json> [--report <report.json>]');
  ensure(outputPath, 'output path is required');

  const root = path.resolve(__dirname, '..');
  const request = readJson(path.resolve(requestPath));
  const patterns = readJson(path.join(root, 'brain', 'REQUEST_PATTERNS.json'));
  const presetsRoot = readJson(path.join(root, 'brain', 'VERIFICATION_PRESETS.json'));
  const presets = presetsRoot.presets || {};

  const defaults = Object.assign({
    model: 'gpt-5.4-mini',
    modelReasoningEffort: 'medium',
    maxAttempts: 2,
    maxChangedFiles: 2,
    allowNewFiles: false,
    requirePlanJson: true
  }, request.defaults || {});

  const rawRequestedFeatures = Array.isArray(request.features) ? request.features : [];
  ensure(rawRequestedFeatures.length > 0, 'request.features must contain at least one feature id');

  const featureOverrides = isObject(request.feature_overrides) ? request.feature_overrides : {};
  const requestedFeatures = rawRequestedFeatures.map(normalizeFeatureRequest);

  const tasks = requestedFeatures.map((featureRequest, index) => {
    const feature = patterns.features[featureRequest.id];
    ensure(feature, `unknown feature id: ${featureRequest.id}`);
    return buildTask(
      featureRequest.id,
      feature,
      featureRequest.inlineOverride,
      featureOverrides,
      presets,
      request,
      index
    );
  });

  const result = { defaults, tasks };
  const resolvedOutputPath = path.resolve(outputPath);
  writeJson(resolvedOutputPath, result);

  if (reportPath) {
    const report = buildReport(request, resolvedOutputPath, tasks);
    writeJson(path.resolve(reportPath), report);
  }

  console.log(resolvedOutputPath);
}

main();
