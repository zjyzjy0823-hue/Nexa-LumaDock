#!/usr/bin/env node
/**
 * scripts/check-contracts.mjs
 *
 * Sync Protocol v3 契约校验器（Node.js 独立实现，零依赖，与 check-contracts.py 交叉验证）。
 * 三者（Python / Node / Rust）读取同一份 packages/contracts/cases.json。
 *
 * 用法：
 *   node scripts/check-contracts.mjs [--contracts-dir <dir>] [--explain]
 *
 * 默认契约目录由 import.meta.url 推导：<repo>/packages/contracts，
 * 其中 <repo> = 本文件所在 scripts/ 的上一级。
 *
 * 成功时只输出一行：
 *   CONTRACTS OK cases=32 valid=10 schema-invalid=14 semantic=8
 * 失败时逐条打印明细并以 1 退出。
 *
 * ── 实现范围 ───────────────────────────────────────────────────────────────
 * 1) JSON Schema 子集（见 SUPPORTED_KEYWORDS）。schema 里出现任何未列出的
 *    断言关键词（如 format/anyOf/if）一律硬失败，避免"静默忽略"型漏洞。
 * 2) 三条执行路径：
 *    - valid           必须通过指定 schema
 *    - schema-invalid  必须被契约拒绝：schema 拒绝，或（MutationBatch 文档）
 *                      被服务端 mutation 级规则 SR-4/SR-3/SR-2 拒绝
 *    - semantic        semanticRules 的 SR-x 规则结果必须等于 expect
 *
 * ── 两处 semantic 用例无法"完整通过 schema"的处理 ─────────────────────
 * SR-1：版本闸门（409）在请求体校验之前生效（§1），payload 本身就是
 *       protocolVersion=2 的批次，body 不参与 schema 校验；只断言版本是整数。
 * SR-4：用例要验证的正是 mutation 白名单，payload 特意携带 `note` 额外字段，
 *       schema 的 additionalProperties=false 会先命中。故只豁免这一条约束
 *       （gate='lenient-mutation-fields'），其余 schema 约束仍强制通过。
 * 其余规则（SR-2/3/5/6/7/8）均强制完整通过 schema。
 */

import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const DEFAULT_REPO_ROOT = resolve(SCRIPT_DIR, '..');
const DEFAULT_CONTRACTS_DIR = join(DEFAULT_REPO_ROOT, 'packages', 'contracts');

/* ═══════════════════════════════ 通用工具 ═══════════════════════════════ */

class ContractError extends Error {}

const isPlainObject = (v) => typeof v === 'object' && v !== null && !Array.isArray(v);
const isInteger = (v) => typeof v === 'number' && Number.isInteger(v);
const has = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
const jsonOf = (v) => JSON.stringify(v);
const codePointLength = (s) => [...s].length;
const truncate = (s, max) => (s.length > max ? `${s.slice(0, max)}…` : s);

/** 类型感知的深比较：1 与 true、"3" 与 3 都不相等。 */
function deepEqual(a, b) {
  if (a === b) return true;
  if (typeof a !== typeof b) return false;
  if (typeof a !== 'object' || a === null || b === null) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a)) {
    return a.length === b.length && a.every((item, i) => deepEqual(item, b[i]));
  }
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  return ka.length === kb.length && ka.every((k) => has(b, k) && deepEqual(a[k], b[k]));
}

/** 错误信息里的人类可读值描述（截断长字符串）。 */
function describeValue(v) {
  if (v === null) return 'null';
  if (Array.isArray(v)) return `array(${v.length})`;
  if (typeof v === 'string') {
    const body = v.length > 40 ? `${v.slice(0, 40)}…` : v;
    return `string(${jsonOf(body)})`;
  }
  if (typeof v === 'number') return `number(${v})`;
  if (typeof v === 'boolean') return `boolean(${v})`;
  if (typeof v === 'object') return `object{${Object.keys(v).join(',')}}`;
  return typeof v;
}

/* ═════════════════════ JSON Schema 子集校验器 ═════════════════════ */

// 契约 schema 只允许使用这些关键词（见 schema 文件 description）。
const SUPPORTED_KEYWORDS = new Set([
  '$ref',
  'type',
  'enum',
  'const',
  'required',
  'properties',
  'additionalProperties',
  'items',
  'minItems',
  'maxItems',
  'minimum',
  'maximum',
  'minLength',
  'maxLength',
  'pattern',
  'oneOf',
]);

// 纯注释 / 容器关键词：不影响校验，直接忽略。
const ANNOTATION_KEYWORDS = new Set(['$schema', '$id', '$comment', 'title', 'description', '$defs', 'definitions']);

const PATTERN_CACHE = new Map();

function compilePattern(pattern, path) {
  let re = PATTERN_CACHE.get(pattern);
  if (!re) {
    try {
      re = new RegExp(pattern, 'u');
    } catch (err) {
      throw new ContractError(`${path}: pattern 无法编译 (${pattern}): ${err.message}`);
    }
    PATTERN_CACHE.set(pattern, re);
  }
  return re;
}

/** 只支持 local $ref：#/$defs/Xxx */
function resolveRef(ref, root, path) {
  const m = /^#\/\$defs\/([A-Za-z0-9_.-]+)$/.exec(ref);
  if (!m) throw new ContractError(`${path}: 只支持 "#/$defs/Xxx" 形式的 $ref，实际为 ${jsonOf(ref)}`);
  const name = m[1];
  const defs = isPlainObject(root) ? root.$defs : undefined;
  if (!isPlainObject(defs) || !has(defs, name)) {
    throw new ContractError(`${path}: $ref 指向不存在的定义 ${jsonOf(ref)}`);
  }
  return defs[name];
}

function assertKeywordsSupported(schema, path) {
  for (const key of Object.keys(schema)) {
    if (!SUPPORTED_KEYWORDS.has(key) && !ANNOTATION_KEYWORDS.has(key)) {
      throw new ContractError(`${path}: 不支持的 schema 关键词 ${jsonOf(key)}（校验器只实现冻结子集）`);
    }
  }
}

function matchesType(type, v) {
  switch (type) {
    case 'object':
      // 必须拒绝数组与 null
      return typeof v === 'object' && v !== null && !Array.isArray(v);
    case 'array':
      return Array.isArray(v);
    case 'string':
      return typeof v === 'string';
    case 'integer':
      // 必须拒绝布尔（typeof true === 'boolean'）与小数
      return typeof v === 'number' && Number.isInteger(v);
    case 'number':
      return typeof v === 'number' && Number.isFinite(v);
    case 'boolean':
      return typeof v === 'boolean';
    case 'null':
      return v === null;
    default:
      throw new ContractError(`不支持的 type ${jsonOf(type)}`);
  }
}

/**
 * 递归校验。返回 true/false，错误累积进 errors（形如 `$.mutations[0].baseRevision: ...`）。
 * $ref 与其它关键词互斥使用（契约内均独占），命中 $ref 时直接委托。
 */
function validateNode(schema, value, root, path, errors) {
  if (schema === true) return true;
  if (schema === false) {
    errors.push(`${path}: false schema 不允许任何值`);
    return false;
  }
  if (!isPlainObject(schema)) {
    throw new ContractError(`${path}: schema 节点必须是对象，实际为 ${describeValue(schema)}`);
  }
  assertKeywordsSupported(schema, path);
  const startErrors = errors.length; // 只对本节点子树负责，避免调用方已有错误影响返回值

  if (has(schema, '$ref')) {
    return validateNode(resolveRef(schema.$ref, root, path), value, root, path, errors);
  }

  let ok = true;
  const fail = (msg) => {
    ok = false;
    errors.push(`${path}: ${msg}`);
  };

  if (has(schema, 'type')) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!types.some((t) => matchesType(t, value))) {
      // 类型不符时其它关键词无意义，直接短路，保持报错可读
      errors.push(`${path}: 期望 type=${types.join('|')}，实际 ${describeValue(value)}`);
      return false;
    }
  }

  if (has(schema, 'enum')) {
    if (!Array.isArray(schema.enum)) throw new ContractError(`${path}: enum 必须是数组`);
    if (!schema.enum.some((candidate) => deepEqual(candidate, value))) {
      fail(`值不在 enum 内，实际 ${describeValue(value)}`);
    }
  }

  if (has(schema, 'const')) {
    if (!deepEqual(schema.const, value)) {
      fail(`期望 const=${jsonOf(schema.const)}，实际 ${describeValue(value)}`);
    }
  }

  if (has(schema, 'required')) {
    if (!Array.isArray(schema.required)) throw new ContractError(`${path}: required 必须是数组`);
    if (isPlainObject(value)) {
      for (const key of schema.required) {
        if (!has(value, key)) fail(`缺少必填字段 ${jsonOf(key)}`);
      }
    }
  }

  if (has(schema, 'properties')) {
    if (!isPlainObject(schema.properties)) throw new ContractError(`${path}: properties 必须是对象`);
    if (isPlainObject(value)) {
      for (const [key, subSchema] of Object.entries(schema.properties)) {
        if (has(value, key)) {
          // 子节点的错误单独收集后回填，避免兄弟节点/兄弟分支互相污染
          const childErrors = [];
          if (!validateNode(subSchema, value[key], root, `${path}.${key}`, childErrors)) ok = false;
          errors.push(...childErrors);
        }
      }
    }
  }

  if (has(schema, 'additionalProperties')) {
    const ap = schema.additionalProperties;
    if (typeof ap !== 'boolean') {
      throw new ContractError(`${path}: 只支持 additionalProperties 为布尔值`);
    }
    if (!ap && isPlainObject(value)) {
      const allowed = new Set(Object.keys(schema.properties ?? {}));
      for (const key of Object.keys(value)) {
        if (!allowed.has(key)) fail(`未知字段 ${jsonOf(key)}（additionalProperties=false）`);
      }
    }
  }

  if (has(schema, 'items')) {
    if (Array.isArray(schema.items)) {
      throw new ContractError(`${path}: 不支持 tuple 形式（items 为数组）`);
    }
    if (Array.isArray(value)) {
      for (let i = 0; i < value.length; i += 1) {
        const childErrors = [];
        if (!validateNode(schema.items, value[i], root, `${path}[${i}]`, childErrors)) ok = false;
        errors.push(...childErrors);
      }
    }
  }

  if (has(schema, 'minItems')) {
    if (Array.isArray(value) && value.length < schema.minItems) {
      fail(`数组长度 ${value.length} < minItems ${schema.minItems}`);
    }
  }
  if (has(schema, 'maxItems')) {
    if (Array.isArray(value) && value.length > schema.maxItems) {
      fail(`数组长度 ${value.length} > maxItems ${schema.maxItems}`);
    }
  }

  if (has(schema, 'minimum')) {
    if (typeof value === 'number' && value < schema.minimum) {
      fail(`${value} < minimum ${schema.minimum}`);
    }
  }
  if (has(schema, 'maximum')) {
    if (typeof value === 'number' && value > schema.maximum) {
      fail(`${value} > maximum ${schema.maximum}`);
    }
  }

  if (has(schema, 'minLength')) {
    if (typeof value === 'string' && codePointLength(value) < schema.minLength) {
      fail(`字符串长度 ${codePointLength(value)} < minLength ${schema.minLength}`);
    }
  }
  if (has(schema, 'maxLength')) {
    if (typeof value === 'string' && codePointLength(value) > schema.maxLength) {
      fail(`字符串长度 ${codePointLength(value)} > maxLength ${schema.maxLength}`);
    }
  }

  if (has(schema, 'pattern')) {
    if (typeof value === 'string') {
      const re = compilePattern(schema.pattern, path);
      if (!re.test(value)) fail(`不匹配 pattern ${jsonOf(schema.pattern)}`);
    }
  }

  if (has(schema, 'oneOf')) {
    if (!Array.isArray(schema.oneOf) || schema.oneOf.length === 0) {
      throw new ContractError(`${path}: oneOf 必须是非空数组`);
    }
    const matched = [];
    const branchErrors = [];
    schema.oneOf.forEach((branch, index) => {
      const errors = [];
      if (validateNode(branch, value, root, path, errors)) matched.push(index);
      branchErrors.push(errors);
    });
    // 必须恰好一个分支通过
    if (matched.length !== 1) {
      if (matched.length === 0) {
        // 0 分支命中时把各分支的首条错误带出来，否则嵌套 oneOf 的报错无法定位
        const heads = branchErrors.map((errors, index) => {
          const head = (errors[0] ?? '无错误').replace(`${path}: `, '');
          return `[${index}] ${head}`;
        });
        fail(
          `oneOf 无分支通过（共 ${schema.oneOf.length} 个分支）: ${truncate(heads.join(' | '), 320)}`,
        );
      } else {
        fail(`oneOf 有 ${matched.length} 个分支同时通过（索引 ${matched.join(',')}），必须恰好 1 个`);
      }
    }
  }

  return ok && errors.length === startErrors;
}

/** 构造按 $defs 名称校验的入口。 */
function makeValidator(rootSchema) {
  if (!isPlainObject(rootSchema?.$defs)) {
    throw new ContractError('schema 缺少 $defs 对象');
  }
  const validateSchema = (schema, value) => {
    const errors = [];
    const valid = validateNode(schema, value, rootSchema, '$', errors);
    return { valid, errors };
  };
  return {
    validateDef(defName, value) {
      if (!has(rootSchema.$defs, defName)) {
        throw new ContractError(`schema 中不存在 $defs/${defName}`);
      }
      return validateSchema(rootSchema.$defs[defName], value);
    },
    validateSchema,
  };
}

/**
 * SR-4 专用信封：MutationBatch 去掉 Mutation 上的 additionalProperties:false，
 * 其余约束原样保留。这样"mutation 多了键"不会被 schema 先拒，
 * 但类型/必填/枚举/pattern 等仍然强制通过。
 */
function buildLenientBatchSchema(rootSchema) {
  const defs = rootSchema.$defs ?? {};
  const mutation = defs.Mutation;
  const batch = defs.MutationBatch;
  const mutations = batch?.properties?.mutations;
  if (!isPlainObject(mutation) || !isPlainObject(batch) || !isPlainObject(mutations)) return null;
  return {
    ...batch,
    properties: {
      ...batch.properties,
      mutations: { ...mutations, items: { ...mutation, additionalProperties: true } },
    },
  };
}

/* ═══════════════════════════ 语义规则 SR-1..SR-8 ═══════════════════════════ */

const MUTATION_ALLOWED_FIELDS = new Set([
  'mutationId',
  'entityType',
  'entityId',
  'operation',
  'baseRevision',
  'data',
]);

const rejected = (reason) => ({ status: 'rejected', reason });
const CONTRACT_BREAK = () => ({ invalid: true });

function requireMutationBatch(doc, ruleId) {
  if (!isPlainObject(doc) || !Array.isArray(doc.mutations)) {
    throw new ContractError(`${ruleId}: 需要 { protocolVersion, mutations[] } 形式的 MutationBatch`);
  }
  return doc.mutations.filter(isPlainObject);
}

function requireChanges(doc, ruleId) {
  if (!isPlainObject(doc) || !Array.isArray(doc.changes)) {
    throw new ContractError(`${ruleId}: 需要 { protocolVersion, changes[], cursor, workspaceRevision }`);
  }
  return doc.changes;
}

/**
 * 每条规则返回 null（未触发）或"协议规定的可观察结果"对象，
 * 由调用方与 cases.json 的 expect 做深比较。
 */
const SEMANTIC_RULES = {
  'SR-1': {
    summary: 'protocolVersion != 3 ⇒ HTTP 409, detail = sync_protocol_mismatch',
    // 版本闸门在请求体校验之前（§1）：body 根本不参与 schema 校验
    gate: 'none',
    check(doc) {
      if (!isPlainObject(doc)) throw new ContractError('SR-1: 需要 JSON 对象');
      if (!isInteger(doc.protocolVersion)) {
        throw new ContractError('SR-1: protocolVersion 必须是整数');
      }
      if (doc.protocolVersion === 3) return null;
      return { httpStatus: 409, detail: 'sync_protocol_mismatch' };
    },
  },

  'SR-2': {
    summary: 'mutation.data 必须符合其 entityType 对应的实体 schema ⇒ 否则 rejected/invalid_data',
    gate: 'full',
    check(doc, ctx) {
      for (const mutation of requireMutationBatch(doc, 'SR-2')) {
        // delete 不得携带 data，由 SR-3 负责，这里不重复判定
        if (mutation.operation === 'delete') continue;
        const schemaName = ctx.entityDataSchemas[mutation.entityType];
        // 未知 entityType 不属于 SR-2 的范围（对应 unknown_entity_type）
        if (!schemaName) continue;
        if (!has(mutation, 'data')) return rejected('invalid_data');
        if (!ctx.validateDef(schemaName, mutation.data).valid) return rejected('invalid_data');
      }
      return null;
    },
  },

  'SR-3': {
    summary: 'operation=delete 时不得携带 data ⇒ 否则 rejected/invalid_data',
    gate: 'full',
    check(doc) {
      for (const mutation of requireMutationBatch(doc, 'SR-3')) {
        // "出现即 invalid_data"：即使 data 为 null 也算携带
        if (mutation.operation === 'delete' && has(mutation, 'data')) return rejected('invalid_data');
      }
      return null;
    },
  },

  'SR-4': {
    summary: 'mutation 对象键必须 ⊆ 白名单 ⇒ 否则 rejected/invalid_fields',
    // 该规则验证的正是白名单本身，payload 特意带额外字段，schema 的
    // additionalProperties=false 会先命中。故只放行这一条约束，
    // 其余 schema 约束（类型/必填/枚举/pattern…）仍必须通过。
    gate: 'lenient-mutation-fields',
    check(doc) {
      for (const mutation of requireMutationBatch(doc, 'SR-4')) {
        for (const key of Object.keys(mutation)) {
          if (!MUTATION_ALLOWED_FIELDS.has(key)) return rejected('invalid_fields');
        }
      }
      return null;
    },
  },

  'SR-5': {
    summary: 'changes.cursor 必须 ≤ workspaceRevision ⇒ 否则 HTTP 400 Invalid sync cursor',
    gate: 'full',
    check(doc) {
      requireChanges(doc, 'SR-5');
      if (!isInteger(doc.cursor) || !isInteger(doc.workspaceRevision)) {
        throw new ContractError('SR-5: cursor / workspaceRevision 必须是整数');
      }
      return doc.cursor > doc.workspaceRevision
        ? { httpStatus: 400, detail: 'Invalid sync cursor' }
        : null;
    },
  },

  'SR-6': {
    summary: 'changes 非空时 cursor 必须等于最后一条 change 的 revision ⇒ 否则契约破坏',
    gate: 'full',
    check(doc) {
      const changes = requireChanges(doc, 'SR-6');
      if (changes.length === 0) return null; // 空页回显请求值，不适用
      const last = changes[changes.length - 1];
      return doc.cursor === last.revision ? null : CONTRACT_BREAK();
    },
  },

  'SR-7': {
    summary: 'changes 的 revision 必须严格递增 ⇒ 否则契约破坏',
    gate: 'full',
    check(doc) {
      const changes = requireChanges(doc, 'SR-7');
      for (let i = 1; i < changes.length; i += 1) {
        if (!(changes[i].revision > changes[i - 1].revision)) return CONTRACT_BREAK();
      }
      return null;
    },
  },

  'SR-8': {
    summary: 'delete 的 change 必须 data=null；upsert 必须 data 为对象 ⇒ 否则契约破坏',
    gate: 'full',
    check(doc) {
      for (const change of requireChanges(doc, 'SR-8')) {
        if (change.operation === 'delete') {
          if (change.data !== null) return CONTRACT_BREAK();
        } else if (change.operation === 'upsert') {
          if (!isPlainObject(change.data)) return CONTRACT_BREAK();
        }
      }
      return null;
    },
  },
};

/* ═══════════════════════════ 用例执行 ═══════════════════════════ */

function inferTopLevelSchema(doc) {
  if (isPlainObject(doc) && has(doc, 'mutations')) return 'MutationBatch';
  if (isPlainObject(doc) && has(doc, 'changes')) return 'ChangesResponse';
  return null;
}

function evaluateValidCase(caseDef, doc, ctx) {
  const { valid, errors } = ctx.validateDef(caseDef.schema, doc);
  if (valid) return { pass: true, layer: 'schema' };
  return {
    pass: false,
    details: [`期望通过 $defs/${caseDef.schema}，实际被拒：`, ...errors.map((e) => `  - ${e}`)],
  };
}

function evaluateSchemaInvalidCase(caseDef, doc, ctx) {
  if (!ctx.validateDef(caseDef.schema, doc).valid) return { pass: true, layer: 'schema' };

  // schema 接受该文档时，拒绝只能来自 schema 表达不了的层次：
  // Mutation.data 在本子集中是宽松的 ({type:object})，entityType→data 的映射
  // 只能由服务端规则承担（SR-2）；delete 携带 data 同为运行时规则（SR-3）。
  // 注意：这意味着 schema 的"宽松化"回归可能被 SR-2 掩盖，见 --explain 的 layer 列。
  if (isPlainObject(doc) && Array.isArray(doc.mutations)) {
    for (const ruleId of ['SR-4', 'SR-3', 'SR-2']) {
      const outcome = SEMANTIC_RULES[ruleId].check(doc, ctx);
      if (outcome) return { pass: true, layer: ruleId, outcome };
    }
  }
  return {
    pass: false,
    details: [
      `$defs/${caseDef.schema} 接受了该文档，且 SR-2/3/4 均未拒绝它`,
      '（schema 对该文档不产生任何约束失败）',
    ],
  };
}

function runSemanticCase(caseDef, doc, ctx) {
  const rule = SEMANTIC_RULES[caseDef.rule];
  if (!rule) return { pass: false, details: [`cases.json 引用了未实现的规则 ${jsonOf(caseDef.rule)}`] };

  const gate = rule.gate ?? 'full';
  if (gate !== 'none') {
    const schemaName = inferTopLevelSchema(doc);
    if (!schemaName) {
      return { pass: false, details: [`无法从样例推断顶层 schema（${caseDef.rule} 要求先过 schema）`] };
    }
    // SR-4 只豁免 Mutation.additionalProperties，其余约束照常执行
    const useLenient =
      gate === 'lenient-mutation-fields' && schemaName === 'MutationBatch' && ctx.lenientBatchSchema;
    const result = useLenient
      ? ctx.validateSchema(ctx.lenientBatchSchema, doc)
      : ctx.validateDef(schemaName, doc);
    if (!result.valid) {
      const label = useLenient ? '$defs/MutationBatch（豁免 Mutation 白名单）' : `$defs/${schemaName}`;
      return {
        pass: false,
        details: [
          `${caseDef.rule} 前置条件：${label} 必须通过，实际被拒：`,
          ...result.errors.map((e) => `  - ${e}`),
        ],
      };
    }
  }

  let outcome;
  try {
    outcome = rule.check(doc, ctx);
  } catch (err) {
    if (err instanceof ContractError) return { pass: false, details: [err.message] };
    throw err;
  }

  const actual = outcome ?? null;
  if (!deepEqual(actual, caseDef.expect)) {
    return {
      pass: false,
      details: [
        `${caseDef.rule} 结果与 expect 不一致`,
        `  实际: ${jsonOf(actual)}`,
        `  期望: ${jsonOf(caseDef.expect)}`,
        `  规则: ${rule.summary}`,
      ],
    };
  }
  return { pass: true, layer: caseDef.rule, outcome: actual };
}

const CASE_EVALUATORS = {
  valid: evaluateValidCase,
  'schema-invalid': evaluateSchemaInvalidCase,
  semantic: runSemanticCase,
};

/**
 * cases.json 的 24 条 valid / schema-invalid 用例显式带 kind，
 * 8 条 semantic 用例只带 rule + expect（无 kind）。按形状判定 kind，
 * 避免把缺字段的语义用例误判成 schema 用例。
 */
function effectiveKind(caseDef) {
  if (isPlainObject(caseDef) && typeof caseDef.kind === 'string') return caseDef.kind;
  if (isPlainObject(caseDef) && (typeof caseDef.rule === 'string' || isPlainObject(caseDef.expect))) {
    return 'semantic';
  }
  return undefined;
}

/* ═══════════════════════════ 契约自身一致性 ═══════════════════════════ */

/**
 * cases.json 与 schema 必须互相自洽：实体枚举、拒绝原因、实体数据 schema 映射、
 * 用例 schema 名、文件存在性。任何一条不符都视为契约破坏（而不是校验器缺陷）。
 */
function checkContractConsistency(casesDoc, schemaRoot, loadCaseFile) {
  const problems = [];
  const defs = schemaRoot.$defs ?? {};
  const defEnum = (name) => defs[name]?.enum;

  const entityEnum = defEnum('EntityType');
  if (!Array.isArray(entityEnum)) {
    problems.push('schema 缺少 $defs/EntityType.enum');
  } else if (!deepEqual(casesDoc.entityTypes, entityEnum)) {
    problems.push('cases.json entityTypes 与 $defs/EntityType.enum 不一致');
  }

  const reasonEnum = defEnum('RejectionReason');
  if (!Array.isArray(reasonEnum)) {
    problems.push('schema 缺少 $defs/RejectionReason.enum');
  } else if (!deepEqual(casesDoc.rejectionReasons, reasonEnum)) {
    problems.push('cases.json rejectionReasons 与 $defs/RejectionReason.enum 不一致');
  }

  const mapping = casesDoc.entityDataSchemas ?? {};
  if (!isPlainObject(mapping)) {
    problems.push('cases.json entityDataSchemas 必须是对象');
  } else {
    if (Array.isArray(entityEnum)) {
      for (const entityType of entityEnum) {
        if (!has(mapping, entityType)) problems.push(`entityDataSchemas 缺少实体 ${entityType}`);
      }
      for (const key of Object.keys(mapping)) {
        if (!entityEnum.includes(key)) {
          problems.push(`entityDataSchemas 含未知实体 ${key}`);
        }
      }
    }
    for (const [entityType, defName] of Object.entries(mapping)) {
      if (!has(defs, defName)) {
        problems.push(`entityDataSchemas["${entityType}"] 指向不存在的 $defs/${defName}`);
      }
    }
  }

  if (!Array.isArray(casesDoc.cases) || casesDoc.cases.length === 0) {
    problems.push('cases.json cases 必须是非空数组');
    return problems;
  }

  const seen = new Set();
  for (const caseDef of casesDoc.cases) {
    const label = caseDef?.name ?? '(未命名)';
    if (seen.has(label)) problems.push(`用例名重复: ${label}`);
    seen.add(label);
    const kind = effectiveKind(caseDef);
    if (!CASE_EVALUATORS[kind]) {
      problems.push(`${label}: 未知 kind ${jsonOf(caseDef?.kind)}`);
    }
    if (kind === 'semantic') {
      if (!SEMANTIC_RULES[caseDef.rule]) problems.push(`${label}: 未实现的规则 ${jsonOf(caseDef?.rule)}`);
      if (!isPlainObject(caseDef.expect)) problems.push(`${label}: 缺少 expect`);
    } else if (!has(defs, caseDef?.schema)) {
      problems.push(`${label}: 引用了不存在的 $defs/${caseDef?.schema}`);
    }
    if (typeof caseDef?.file !== 'string') {
      problems.push(`${label}: 缺少 file`);
      continue;
    }
    try {
      loadCaseFile(caseDef.file); // 读取失败会抛 ContractError
    } catch (err) {
      problems.push(`${label}: 无法读取 ${caseDef.file}（${err.message}）`);
    }
  }

  const batchVersion = defs.MutationBatch?.properties?.protocolVersion?.const;
  if (batchVersion !== casesDoc.contractVersion) {
    problems.push(
      `cases.json contractVersion=${jsonOf(casesDoc.contractVersion)} 与 MutationBatch.protocolVersion.const=${jsonOf(batchVersion)} 不一致`,
    );
  }

  return problems;
}

/* ═══════════════════════════ main ═══════════════════════════ */

function parseArgs(argv) {
  const opts = { contractsDir: DEFAULT_CONTRACTS_DIR, explain: false, help: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--help' || arg === '-h') {
      opts.help = true;
    } else if (arg === '--explain') {
      opts.explain = true;
    } else if (arg === '--contracts-dir') {
      const value = argv[i + 1];
      if (!value) throw new ContractError('--contracts-dir 需要一个目录参数');
      opts.contractsDir = resolve(process.cwd(), value);
      i += 1;
    } else if (arg.startsWith('--contracts-dir=')) {
      opts.contractsDir = resolve(process.cwd(), arg.slice('--contracts-dir='.length));
    } else {
      throw new ContractError(`未知参数 ${jsonOf(arg)}（--help 查看用法）`);
    }
  }
  return opts;
}

const USAGE = `用法: node scripts/check-contracts.mjs [选项]

  --contracts-dir <dir>  契约目录，默认 <repo>/packages/contracts
  --explain              额外打印每条用例的执行明细（默认成功只输出一行）
  -h, --help             显示本帮助`;

function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
  } catch (err) {
    console.error(`check-contracts: ${err.message}`);
    console.error(USAGE);
    process.exit(2);
  }

  if (opts.help) {
    console.log(USAGE);
    process.exit(0);
  }

  const contractsDir = opts.contractsDir;
  const readJson = (relPath) => {
    const absPath = resolve(contractsDir, relPath);
    let text;
    try {
      text = readFileSync(absPath, 'utf8');
    } catch (err) {
      throw new ContractError(`无法读取 ${absPath}: ${err.message}`);
    }
    try {
      return JSON.parse(text);
    } catch (err) {
      throw new ContractError(`${absPath} 不是合法 JSON: ${err.message}`);
    }
  };

  let schemaRoot;
  let casesDoc;
  try {
    casesDoc = readJson('cases.json');
    schemaRoot = readJson(casesDoc.schemaFile ?? 'schema/sync-v3.schema.json');
  } catch (err) {
    console.error(`CONTRACTS FAILED ${err.message}`);
    process.exit(1);
  }

  const problems = [];
  const fileCache = new Map();
  const loadCaseFile = (relPath) => {
    if (!fileCache.has(relPath)) fileCache.set(relPath, readJson(relPath));
    return fileCache.get(relPath);
  };

  try {
    problems.push(...checkContractConsistency(casesDoc, schemaRoot, loadCaseFile));
  } catch (err) {
    problems.push(`契约一致性检查异常: ${err.message}`);
  }

  const validator = makeValidator(schemaRoot);
  const ctx = {
    validateDef: validator.validateDef,
    validateSchema: validator.validateSchema,
    lenientBatchSchema: buildLenientBatchSchema(schemaRoot),
    entityDataSchemas: casesDoc.entityDataSchemas ?? {},
  };

  const results = [];
  for (const caseDef of casesDoc.cases ?? []) {
    const result = { caseDef, pass: false, details: [] };
    try {
      const doc = loadCaseFile(caseDef.file);
      const kind = effectiveKind(caseDef);
      const evaluate = CASE_EVALUATORS[kind];
      if (!evaluate) throw new ContractError(`未知 kind ${jsonOf(caseDef.kind)}`);
      Object.assign(result, evaluate(caseDef, doc, ctx));
    } catch (err) {
      if (!(err instanceof ContractError)) throw err;
      result.pass = false;
      result.details = [err.message];
    }
    results.push(result);
  }

  const failedCases = results.filter((r) => !r.pass);
  const byKind = {};
  for (const result of results) {
    if (!result.pass) continue; // 只统计真正通过的用例
    const kind = effectiveKind(result.caseDef);
    byKind[kind] = (byKind[kind] ?? 0) + 1;
  }

  if (opts.explain) {
    for (const result of results) {
      const status = result.pass ? 'ok  ' : 'FAIL';
      const layer = result.layer ? ` layer=${result.layer}` : '';
      console.log(`${status} ${result.caseDef.name} [${effectiveKind(result.caseDef)}]${layer}`);
    }
    console.log('');
  }

  if (problems.length > 0 || failedCases.length > 0) {
    for (const problem of problems) console.error(`FAIL  contract  ${problem}`);
    for (const result of failedCases) {
      console.error(
        `FAIL  ${result.caseDef.name}  [${effectiveKind(result.caseDef)}]  ${result.caseDef.file}`,
      );
      for (const line of result.details) console.error(`      ${line}`);
    }
    const totalCases = casesDoc.cases?.length ?? 0;
    console.error(
      `CONTRACTS FAILED cases=${totalCases} passed=${results.length - failedCases.length} failed=${failedCases.length}${
        problems.length ? ` contract-problems=${problems.length}` : ''
      }`,
    );
    process.exit(1);
  }

  const total = Object.values(byKind).reduce((sum, n) => sum + n, 0);
  process.stdout.write(
    `CONTRACTS OK cases=${total} valid=${byKind.valid ?? 0} ` +
      `schema-invalid=${byKind['schema-invalid'] ?? 0} semantic=${byKind.semantic ?? 0}\n`,
  );
}

main();
