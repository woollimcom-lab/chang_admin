#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

function fail(message) {
  throw new Error(message);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, ''));
}

function isObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value);
}

function hasOwn(value, key) {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function ensureArrayOfStrings(value, fieldName, { minItems = 0 } = {}) {
  if (!Array.isArray(value)) fail(`${fieldName} must be an array`);
  if (value.length < minItems) fail(`${fieldName} must contain at least ${minItems} item(s)`);
  value.forEach((item, index) => {
    if (typeof item !== 'string') fail(`${fieldName}[${index}] must be a string`);
  });
}

function ensureOptionalBoolean(value, fieldName) {
  if (typeof value !== 'boolean') fail(`${fieldName} must be a boolean`);
}

function ensureOptionalString(value, fieldName) {
  if (typeof value !== 'string') fail(`${fieldName} must be a string`);
}

function ensureOptionalInteger(value, fieldName, { minimum = 0 } = {}) {
  if (!Number.isInteger(value) || value < minimum) {
    fail(`${fieldName} must be an integer >= ${minimum}`);
  }
}

function validateSchemaValue(value, schema, fieldName) {
  if (!isObject(schema)) return;

  const schemaType = schema.type;
  if (schemaType === 'object') {
    if (!isObject(value)) fail(`${fieldName} must be an object`);

    const properties = isObject(schema.properties) ? schema.properties : {};
    if (Array.isArray(schema.required)) {
      schema.required.forEach((requiredKey) => {
        if (!hasOwn(value, requiredKey)) {
          fail(`${fieldName}.${requiredKey} is required by schema`);
        }
      });
    }

    if (schema.additionalProperties === false) {
      Object.keys(value).forEach((key) => {
        if (!hasOwn(properties, key)) {
          fail(`${fieldName}.${key} is not allowed by schema`);
        }
      });
    }

    Object.entries(properties).forEach(([key, childSchema]) => {
      if (hasOwn(value, key)) {
        validateSchemaValue(value[key], childSchema, `${fieldName}.${key}`);
      }
    });
    return;
  }

  if (schemaType === 'array') {
    if (!Array.isArray(value)) fail(`${fieldName} must be an array`);
    if (typeof schema.minItems === 'number' && value.length < schema.minItems) {
      fail(`${fieldName} must contain at least ${schema.minItems} item(s)`);
    }
    if (isObject(schema.items)) {
      value.forEach((item, index) => validateSchemaValue(item, schema.items, `${fieldName}[${index}]`));
    }
    return;
  }

  if (schemaType === 'string') {
    if (typeof value !== 'string') fail(`${fieldName} must be a string`);
    if (Array.isArray(schema.enum) && !schema.enum.includes(value)) {
      fail(`${fieldName} must be one of: ${schema.enum.join(', ')}`);
    }
    return;
  }

  if (schemaType === 'integer') {
    if (!Number.isInteger(value)) fail(`${fieldName} must be an integer`);
    if (typeof schema.minimum === 'number' && value < schema.minimum) {
      fail(`${fieldName} must be >= ${schema.minimum}`);
    }
    return;
  }

  if (schemaType === 'boolean') {
    if (typeof value !== 'boolean') fail(`${fieldName} must be a boolean`);
  }
}

function validateVerificationStep(step, fieldName) {
  if (!isObject(step)) fail(`${fieldName} must be an object`);

  const supportedActions = new Set([
    'goto',
    'waitFor',
    'click',
    'fill',
    'press',
    'select',
    'expectVisible',
    'expectHidden',
    'expectText',
    'expectUrlIncludes',
    'evaluate',
    'screenshot'
  ]);

  if (typeof step.action !== 'string' || !supportedActions.has(step.action)) {
    fail(`${fieldName}.action must be one of: ${Array.from(supportedActions).join(', ')}`);
  }

  ['selector', 'url', 'key', 'text', 'path', 'waitUntil', 'state', 'expression'].forEach((propertyName) => {
    if (hasOwn(step, propertyName)) ensureOptionalString(step[propertyName], `${fieldName}.${propertyName}`);
  });
  if (hasOwn(step, 'timeout')) ensureOptionalInteger(step.timeout, `${fieldName}.timeout`, { minimum: 0 });
  if (hasOwn(step, 'fullPage')) ensureOptionalBoolean(step.fullPage, `${fieldName}.fullPage`);

  if (['click', 'fill', 'press', 'select', 'expectVisible', 'expectHidden', 'expectText'].includes(step.action)) {
    if (typeof step.selector !== 'string' || !step.selector.trim()) {
      fail(`${fieldName}.selector is required for action: ${step.action}`);
    }
  }
  if (step.action === 'expectText' || step.action === 'expectUrlIncludes') {
    if (typeof step.text !== 'string') fail(`${fieldName}.text is required for action: ${step.action}`);
  }
  if (step.action === 'evaluate' && typeof step.expression !== 'string') {
    fail(`${fieldName}.expression is required for action: evaluate`);
  }
}

function validateDefaults(defaults) {
  if (!isObject(defaults)) fail('defaults must be an object');
  if (typeof defaults.model !== 'string' || !defaults.model.trim()) fail('defaults.model is required');
  if (!Number.isInteger(defaults.maxAttempts) || defaults.maxAttempts < 1) fail('defaults.maxAttempts must be an integer >= 1');
  if (typeof defaults.allowNewFiles !== 'boolean') fail('defaults.allowNewFiles must be a boolean');
  if (typeof defaults.requirePlanJson !== 'boolean') fail('defaults.requirePlanJson must be a boolean');
  if (Object.prototype.hasOwnProperty.call(defaults, 'maxChangedFiles')) {
    if (!Number.isInteger(defaults.maxChangedFiles) || defaults.maxChangedFiles < 1) {
      fail('defaults.maxChangedFiles must be an integer >= 1');
    }
  }
  if (Object.prototype.hasOwnProperty.call(defaults, 'modelReasoningEffort') && typeof defaults.modelReasoningEffort !== 'string') {
    fail('defaults.modelReasoningEffort must be a string');
  }
}

function validateVerification(verification, fieldName) {
  if (!isObject(verification)) fail(`${fieldName} must be an object`);
  if (typeof verification.url !== 'string' || !verification.url.trim()) {
    fail(`${fieldName}.url must be a non-empty string`);
  }
  if (typeof verification.useAuth !== 'boolean') fail(`${fieldName}.useAuth must be a boolean`);
  if (typeof verification.forbidDialogs !== 'boolean') fail(`${fieldName}.forbidDialogs must be a boolean`);
  if (!Array.isArray(verification.steps)) fail(`${fieldName}.steps must be an array`);
  if (hasOwn(verification, 'forbidPageErrors')) ensureOptionalBoolean(verification.forbidPageErrors, `${fieldName}.forbidPageErrors`);
  if (hasOwn(verification, 'forbidConsoleErrors')) ensureOptionalBoolean(verification.forbidConsoleErrors, `${fieldName}.forbidConsoleErrors`);
  if (hasOwn(verification, 'autoDismissDialogs')) ensureOptionalBoolean(verification.autoDismissDialogs, `${fieldName}.autoDismissDialogs`);
  if (hasOwn(verification, 'headless')) ensureOptionalBoolean(verification.headless, `${fieldName}.headless`);
  if (hasOwn(verification, 'channel')) ensureOptionalString(verification.channel, `${fieldName}.channel`);
  if (hasOwn(verification, 'initialWaitUntil')) ensureOptionalString(verification.initialWaitUntil, `${fieldName}.initialWaitUntil`);
  if (hasOwn(verification, 'initialTimeout')) ensureOptionalInteger(verification.initialTimeout, `${fieldName}.initialTimeout`, { minimum: 1 });
  if (hasOwn(verification, 'requiredTexts')) ensureArrayOfStrings(verification.requiredTexts, `${fieldName}.requiredTexts`);
  if (hasOwn(verification, 'forbiddenTexts')) ensureArrayOfStrings(verification.forbiddenTexts, `${fieldName}.forbiddenTexts`);
  verification.steps.forEach((step, index) => validateVerificationStep(step, `${fieldName}.steps[${index}]`));
}

function getDependsOn(task, index) {
  if (!Object.prototype.hasOwnProperty.call(task, 'depends_on') || task.depends_on == null) {
    return [];
  }

  ensureArrayOfStrings(task.depends_on, `tasks[${index}].depends_on`);
  return task.depends_on.map((item, depIndex) => {
    if (!item.trim()) fail(`tasks[${index}].depends_on[${depIndex}] must be a non-empty string`);
    return item.trim();
  });
}

function validateTask(task, index) {
  if (!isObject(task)) fail(`tasks[${index}] must be an object`);

  const requiredStrings = ['task_id', 'goal', 'rollback_plan', 'promotion_rule'];
  for (const field of requiredStrings) {
    if (typeof task[field] !== 'string' || !task[field].trim()) {
      fail(`tasks[${index}].${field} is required`);
    }
  }

  ensureArrayOfStrings(task.target_files, `tasks[${index}].target_files`, { minItems: 1 });
  ensureArrayOfStrings(task.reuse_symbols, `tasks[${index}].reuse_symbols`);
  ensureArrayOfStrings(task.do_not_touch, `tasks[${index}].do_not_touch`);
  ensureArrayOfStrings(task.acceptance, `tasks[${index}].acceptance`, { minItems: 1 });
  validateVerification(task.verification, `tasks[${index}].verification`);

  if (Object.prototype.hasOwnProperty.call(task, 'priority')) {
    const allowed = new Set(['critical', 'high', 'medium', 'low']);
    if (typeof task.priority !== 'string' || !allowed.has(task.priority)) {
      fail(`tasks[${index}].priority must be one of: critical, high, medium, low`);
    }
  }

  getDependsOn(task, index);
}

function validateTaskDependencies(tasks) {
  const taskIds = new Set();
  const order = [];
  const dependencyMap = new Map();
  const dependentsMap = new Map();
  const incomingCounts = new Map();

  tasks.forEach((task, index) => {
    const taskId = String(task.task_id || '').trim();
    if (taskIds.has(taskId)) fail(`duplicate task_id: ${taskId}`);
    taskIds.add(taskId);
    order.push(taskId);
    dependentsMap.set(taskId, []);
    incomingCounts.set(taskId, 0);
  });

  tasks.forEach((task, index) => {
    const taskId = String(task.task_id || '').trim();
    const dependsOn = getDependsOn(task, index);
    const seen = new Set();

    dependsOn.forEach((dependencyId, depIndex) => {
      if (dependencyId === taskId) {
        fail(`tasks[${index}].depends_on[${depIndex}] cannot reference its own task_id`);
      }
      if (!taskIds.has(dependencyId)) {
        fail(`tasks[${index}].depends_on[${depIndex}] references unknown task_id: ${dependencyId}`);
      }
      if (seen.has(dependencyId)) {
        fail(`tasks[${index}].depends_on[${depIndex}] duplicates dependency: ${dependencyId}`);
      }

      seen.add(dependencyId);
      incomingCounts.set(taskId, (incomingCounts.get(taskId) || 0) + 1);
      dependentsMap.get(dependencyId).push(taskId);
    });

    dependencyMap.set(taskId, dependsOn);
  });

  const ready = order.filter((taskId) => (incomingCounts.get(taskId) || 0) === 0);
  let resolvedCount = 0;

  while (ready.length > 0) {
    const taskId = ready.shift();
    resolvedCount += 1;

    (dependentsMap.get(taskId) || []).forEach((dependentId) => {
      const nextCount = (incomingCounts.get(dependentId) || 0) - 1;
      incomingCounts.set(dependentId, nextCount);
      if (nextCount === 0) {
        ready.push(dependentId);
      }
    });
  }

  if (resolvedCount !== tasks.length) {
    const unresolved = order.filter((taskId) => (incomingCounts.get(taskId) || 0) > 0);
    fail(`depends_on cycle detected: ${unresolved.join(', ')}`);
  }
}

function main() {
  const taskFile = process.argv[2];
  const schemaFile = process.argv[3];
  if (!taskFile) fail('usage: node scripts/validate_task_queue.js <task-file> [schema-file]');

  const resolvedTaskFile = path.resolve(taskFile);
  if (!fs.existsSync(resolvedTaskFile)) fail(`task file not found: ${resolvedTaskFile}`);
  let schema = null;
  if (schemaFile) {
    const resolvedSchemaFile = path.resolve(schemaFile);
    if (!fs.existsSync(resolvedSchemaFile)) fail(`schema file not found: ${resolvedSchemaFile}`);
    schema = readJson(resolvedSchemaFile);
    if (!isObject(schema)) fail('schema file must be a JSON object');
  }

  const queue = readJson(resolvedTaskFile);
  if (!isObject(queue)) fail('task file root must be an object');
  if (schema) validateSchemaValue(queue, schema, 'root');
  if (!Object.prototype.hasOwnProperty.call(queue, 'defaults')) fail('defaults is required');
  if (!Object.prototype.hasOwnProperty.call(queue, 'tasks')) fail('tasks is required');
  validateDefaults(queue.defaults);
  if (!Array.isArray(queue.tasks) || queue.tasks.length === 0) {
    fail('tasks must be a non-empty array');
  }
  queue.tasks.forEach((task, index) => validateTask(task, index));
  validateTaskDependencies(queue.tasks);

  console.log(JSON.stringify({
    ok: true,
    taskFile: resolvedTaskFile,
    tasks: queue.tasks.length
  }, null, 2));
}

main();
