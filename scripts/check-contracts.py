#!/usr/bin/env python3
"""Studiolo Sync Protocol v3 契约校验器（仅标准库，无第三方依赖）。

用法:
    python3 scripts/check-contracts.py [--contracts-dir DIR] [--notes]

默认契约目录 = 本脚本所在目录的上一级 + ``packages/contracts``。

每条样例按 cases.json 的 kind 校验:

    valid            线格式必须被 normative JSON Schema 接受（= schema 层零违规）
    schema-invalid   必须被契约拒绝：schema 层拒绝，或（MutationBatch 文档）被
                     schema 表达不了的服务端规则 SR-4 / SR-3 / SR-2 拒绝
                     （JSON Schema 无法表达按 entityType 的分派，该映射同样是契约的一部分）
    semantic         （cases.json 里省略 kind，靠 rule 字段识别）
                     先 schema 校验，再执行 SR-1..SR-8 并与 expect 比对

为什么 valid 与 schema-invalid 的判定层次不同：valid 样例冻结的是线格式，负向样例冻结的
是"契约整体会拒绝"。把 data 层校验也加到 valid 上会让
samples/valid/mutations-batch.json 失败 —— 它的 data 里 ``amount`` 是 JSON number、
``occurredAt`` 不是 ISO UTC，违反规范 §1。那是样例自身的缺陷（用 --notes 可以看到），
既不该由本校验器私自放宽，也不该拿它去判 valid 样例失败，故如实输出提示而不隐藏。

两处 semantic 用例在 schema 层就已被拒，因此不能"先过 schema"（已在报告中标注）:
    SR-1  protocol-version-mismatch 的 payload 是 protocolVersion=2 + 空 mutations，schema
          必然拒绝；而规范 §1/§3.2 规定版本闸门在 body 解析之前，故该用例只校验信封。
    SR-4  invalid-fields 要验证的正是"mutation 多了 note 键"，Mutation.additionalProperties
          =false 已表达同一约束；故该用例放行 additionalProperties 违规后再跑规则。
其余 SR-2/3/5/6/7/8 都强制 schema 先通过。

JSON Schema 子集校验器只实现 schema/sync-v3.schema.json 实际使用的关键词；若 schema
新增了未实现的关键词或引用，校验器直接报错，绝不静默放过（见 collect_unknown_keywords）。

退出码: 0 = 全部通过；1 = 有样例失败或契约文件本身有问题。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "packages" / "contracts"

KIND_VALID = "valid"
KIND_SCHEMA_INVALID = "schema-invalid"
KIND_SEMANTIC = "semantic"
KINDS = (KIND_VALID, KIND_SCHEMA_INVALID, KIND_SEMANTIC)

# schema 里允许出现的关键词。多一个就说明本校验器可能漏检，必须显式实现后再放行。
KNOWN_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "title",
        "description",
        "$defs",
        "$ref",
        "type",
        "enum",
        "const",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
        "oneOf",
    }
)

# §3.1 / SR-4：mutation 对象允许出现的键（封闭集合）
MUTATION_FIELDS = (
    "mutationId",
    "entityType",
    "entityId",
    "operation",
    "baseRevision",
    "data",
)

_MISSING = object()


class ContractError(Exception):
    """契约文件本身有问题（不是某条样例校验失败）。"""


# --------------------------------------------------------------------------- #
# JSON 语义工具
# --------------------------------------------------------------------------- #


def _reject_json_constant(name):
    raise ContractError("JSON 中不允许出现 %s" % name)


def load_json(path):
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError("无法读取 %s: %s" % (path, exc))
    try:
        return json.loads(text, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        raise ContractError("%s 不是合法 JSON: %s" % (path, exc))


def is_number(value):
    """JSON number：bool 是 int 子类，必须先排除。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_integer(value):
    """JSON Schema 的 integer：拒绝 True/False；1.0 这类整值浮点按规范算整数。"""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return value.is_integer()
    return False


def json_equal(left, right):
    """JSON 值相等：true 与 1 不相等，1 与 1.0 相等。"""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if is_number(left) and is_number(right):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(
            json_equal(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            json_equal(left[key], right[key]) for key in left
        )
    return left == right


def json_type_name(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def short(value, limit=72):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):  # pragma: no cover - 样例只来自 JSON
        text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --------------------------------------------------------------------------- #
# JSON Schema 子集校验器
# --------------------------------------------------------------------------- #


class Failure(object):
    """单条 schema 违规：路径 + 关键词 + 说明。"""

    __slots__ = ("path", "keyword", "message")

    def __init__(self, path, keyword, message):
        self.path = path or ""
        self.keyword = keyword
        self.message = message

    def __str__(self):
        return "%s [%s] %s" % (self.path or "<root>", self.keyword, self.message)

    def __repr__(self):  # pragma: no cover - 调试用
        return "Failure(%r, %r, %r)" % (self.path, self.keyword, self.message)


class SchemaValidator(object):
    """sync-v3.schema.json 用到的关键词子集，行为对齐 draft 2020-12。"""

    def __init__(self, schema):
        if not isinstance(schema, dict):
            raise ContractError("schema 根节点必须是对象")
        self.schema = schema
        defs = schema.get("$defs", {})
        if not isinstance(defs, dict):
            raise ContractError("$defs 必须是对象")
        self.defs = defs
        self._patterns = {}

    # -- 入口 ------------------------------------------------------------- #

    def validate(self, node, instance, path=""):
        errors = []
        self._check(node, instance, path, errors)
        return errors

    def validate_def(self, name, instance, path=""):
        if name not in self.defs:
            raise ContractError("$defs 里没有 %r" % name)
        return self.validate({"$ref": "#/$defs/" + name}, instance, path)

    # -- 内部 ------------------------------------------------------------- #

    def _resolve(self, ref):
        prefix = "#/$defs/"
        if not isinstance(ref, str) or not ref.startswith(prefix):
            raise ContractError("只支持本地引用 #/$defs/Xxx，遇到 %r" % (ref,))
        name = ref[len(prefix) :]
        if name not in self.defs:
            raise ContractError("$ref 指向不存在的定义 %r" % name)
        return self.defs[name]

    def _match_pattern(self, pattern, value):
        regex = self._patterns.get(pattern)
        if regex is None:
            try:
                # ECMA-262 的 \d\w\s 只匹配 ASCII，用 re.ASCII 对齐
                regex = re.compile(pattern, re.ASCII)
            except re.error as exc:
                raise ContractError("非法 pattern %r: %s" % (pattern, exc))
            self._patterns[pattern] = regex
        match = regex.search(value)
        if match is None:
            return False
        # Python 的 $ 允许匹配结尾换行；以 $ 收尾的 pattern 收紧到整串
        if pattern.endswith("$"):
            return match.end() == len(value)
        return True

    @staticmethod
    def _type_matches(expected, value):
        if isinstance(expected, list):
            return any(SchemaValidator._type_matches(item, value) for item in expected)
        if expected == "object":
            return isinstance(value, dict)
        if expected == "array":
            return isinstance(value, list)
        if expected == "string":
            return isinstance(value, str)
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "null":
            return value is None
        if expected == "integer":
            return is_integer(value)
        if expected == "number":
            return is_number(value)
        raise ContractError("未知 type: %r" % (expected,))

    def _check(self, node, value, path, errors):
        if node is True:
            return
        if node is False:
            errors.append(Failure(path, "false", "该位置不允许任何值"))
            return
        if not isinstance(node, dict):
            raise ContractError("schema 节点必须是对象或布尔值")

        if "$ref" in node:
            self._check(self._resolve(node["$ref"]), value, path, errors)
            rest = {key: item for key, item in node.items() if key != "$ref"}
            if not rest:
                return
            node = rest

        if "type" in node and not self._type_matches(node["type"], value):
            errors.append(
                Failure(
                    path,
                    "type",
                    "期望 %s，实际 %s" % (short(node["type"]), json_type_name(value)),
                )
            )
            return  # 类型不符时其余关键词不再适用

        if "const" in node and not json_equal(value, node["const"]):
            errors.append(
                Failure(
                    path,
                    "const",
                    "期望 %s，实际 %s" % (short(node["const"]), short(value)),
                )
            )

        if "enum" in node and not any(json_equal(value, item) for item in node["enum"]):
            errors.append(
                Failure(
                    path,
                    "enum",
                    "%s 不在 %s 内" % (short(value), short(node["enum"])),
                )
            )

        if is_number(value):
            if "minimum" in node and value < node["minimum"]:
                errors.append(
                    Failure(path, "minimum", "%s < %s" % (value, node["minimum"]))
                )
            if "maximum" in node and value > node["maximum"]:
                errors.append(
                    Failure(path, "maximum", "%s > %s" % (value, node["maximum"]))
                )

        if isinstance(value, str):
            length = len(value)
            if "minLength" in node and length < node["minLength"]:
                errors.append(
                    Failure(
                        path,
                        "minLength",
                        "长度 %d < %d" % (length, node["minLength"]),
                    )
                )
            if "maxLength" in node and length > node["maxLength"]:
                errors.append(
                    Failure(
                        path,
                        "maxLength",
                        "长度 %d > %d" % (length, node["maxLength"]),
                    )
                )
            if "pattern" in node and not self._match_pattern(node["pattern"], value):
                errors.append(
                    Failure(
                        path,
                        "pattern",
                        "%s 不匹配 %s" % (short(value), node["pattern"]),
                    )
                )

        if isinstance(value, list):
            if "minItems" in node and len(value) < node["minItems"]:
                errors.append(
                    Failure(path, "minItems", "%d 项 < %d" % (len(value), node["minItems"]))
                )
            if "maxItems" in node and len(value) > node["maxItems"]:
                errors.append(
                    Failure(path, "maxItems", "%d 项 > %d" % (len(value), node["maxItems"]))
                )
            if "items" in node:
                for index, item in enumerate(value):
                    self._check(node["items"], item, "%s/%d" % (path, index), errors)

        if isinstance(value, dict):
            for key in node.get("required", []):
                if key not in value:
                    errors.append(
                        Failure(path, "required", "缺少必需字段 %r" % key)
                    )
            properties = node.get("properties", {})
            for key, subschema in properties.items():
                if key in value:
                    self._check(subschema, value[key], "%s/%s" % (path, key), errors)
            if node.get("additionalProperties", True) is False:
                for key in value:
                    if key not in properties:
                        errors.append(
                            Failure(
                                "%s/%s" % (path, key),
                                "additionalProperties",
                                "未知字段 %r" % key,
                            )
                        )

        if "oneOf" in node:
            matched = 0
            branch_errors = []
            for index, branch in enumerate(node["oneOf"]):
                branch_result = []
                self._check(branch, value, path, branch_result)
                if branch_result:
                    branch_errors.append((index, branch_result))
                else:
                    matched += 1
            if matched == 0:
                detail = "; ".join(
                    "#%d: %s" % (index, items[0]) for index, items in branch_errors[:4]
                )
                errors.append(
                    Failure(path, "oneOf", "没有任何分支匹配（%s）" % detail)
                )
            elif matched > 1:
                errors.append(
                    Failure(
                        path,
                        "oneOf",
                        "匹配了 %d 个分支，必须恰好 1 个" % matched,
                    )
                )


def collect_unknown_keywords(node, path="$"):
    """遍历 schema 节点，返回本校验器未实现的关键词（含 dict 形式的 additionalProperties）。"""
    found = []
    if not isinstance(node, dict):
        return found
    for key in node:
        if key not in KNOWN_SCHEMA_KEYWORDS:
            found.append((path, key))
    if isinstance(node.get("additionalProperties"), dict):
        found.append((path, "additionalProperties(schema)"))
    for name, subschema in (node.get("$defs") or {}).items():
        found.extend(collect_unknown_keywords(subschema, "%s/$defs/%s" % (path, name)))
    for name, subschema in (node.get("properties") or {}).items():
        found.extend(
            collect_unknown_keywords(subschema, "%s/properties/%s" % (path, name))
        )
    if isinstance(node.get("items"), dict):
        found.extend(collect_unknown_keywords(node["items"], path + "/items"))
    for index, sub in enumerate(node.get("oneOf") or []):
        found.extend(collect_unknown_keywords(sub, "%s/oneOf/%d" % (path, index)))
    return found


# --------------------------------------------------------------------------- #
# 契约（schema + cases.json）
# --------------------------------------------------------------------------- #


class Contract(object):
    def __init__(self, contracts_dir):
        self.dir = Path(contracts_dir)
        if not self.dir.is_dir():
            raise ContractError("契约目录不存在: %s" % self.dir)

        self.cases_doc = load_json(self.dir / "cases.json")
        schema_file = self.cases_doc.get("schemaFile")
        if not schema_file:
            raise ContractError("cases.json 缺少 schemaFile")
        self.schema = load_json(self.dir / schema_file)
        self.validator = SchemaValidator(self.schema)

        unknown = collect_unknown_keywords(self.schema)
        if unknown:
            raise ContractError(
                "schema 使用了校验器未实现的关键词（先实现再放行）: "
                + ", ".join("%s:%s" % item for item in unknown)
            )

        self.entity_data_schemas = self.cases_doc.get("entityDataSchemas") or {}
        for entity_type, def_name in self.entity_data_schemas.items():
            if def_name not in self.validator.defs:
                raise ContractError(
                    "entityDataSchemas[%r] 指向不存在的 $defs/%s"
                    % (entity_type, def_name)
                )

        # cases.json 重复了 schema 的两个封闭枚举；复制品最容易漂移，先对齐
        self._check_enum_parity("entityTypes", "EntityType")
        self._check_enum_parity("rejectionReasons", "RejectionReason")

        # 规则描述表与实际实现必须一一对应
        for rule_id in self.cases_doc.get("semanticRules") or {}:
            if rule_id not in SEMANTIC_RULES:
                raise ContractError(
                    "cases.json 声明了语义规则 %s，但校验器没有实现" % rule_id
                )

        for case in self.cases_doc.get("cases", []):
            name = case.get("name")
            if not name:
                raise ContractError("用例缺少 name 字段: %r" % (case,))
            if not case.get("file"):
                raise ContractError("样例 %r 缺少 file 字段" % name)
            schema_name = case.get("schema")
            kind = case.get("kind")
            if kind in (KIND_VALID, KIND_SCHEMA_INVALID) and not schema_name:
                raise ContractError("样例 %r（%s）缺少 schema 字段" % (name, kind))
            if schema_name and schema_name not in self.validator.defs:
                raise ContractError(
                    "样例 %r 引用不存在的 schema %r" % (name, schema_name)
                )

    def _check_enum_parity(self, key, def_name):
        declared = self.cases_doc.get(key)
        if declared is None:
            return
        enum = (self.validator.defs.get(def_name) or {}).get("enum")
        if enum is None:
            raise ContractError("$defs/%s 缺少 enum" % def_name)
        if list(declared) != list(enum):
            raise ContractError(
                "cases.json.%s 与 $defs/%s.enum 不一致: 仅 cases.json 有 %r，仅 schema 有 %r"
                % (
                    key,
                    def_name,
                    [item for item in declared if item not in enum],
                    [item for item in enum if item not in declared],
                )
            )

    # -- data 层 ---------------------------------------------------------- #

    def data_errors(self, entity_type, data, path):
        def_name = self.entity_data_schemas.get(entity_type)
        if def_name is None:
            return []
        return self.validator.validate_def(def_name, data, path)

    def mutation_data_errors(self, doc):
        """对信封里每个带 data 的 mutation 跑实体 schema（用于负向样例与 --notes）。"""
        errors = []
        if not isinstance(doc, dict):
            return errors
        mutations = doc.get("mutations")
        if not isinstance(mutations, list):
            return errors
        for index, mutation in enumerate(mutations):
            if not isinstance(mutation, dict) or "data" not in mutation:
                continue
            errors.extend(
                self.data_errors(
                    mutation.get("entityType"),
                    mutation["data"],
                    "/mutations/%d/data" % index,
                )
            )
        return errors


# --------------------------------------------------------------------------- #
# 语义规则 SR-1..SR-8
# --------------------------------------------------------------------------- #


def rule_sr1(contract, doc):
    version = doc.get("protocolVersion", _MISSING) if isinstance(doc, dict) else _MISSING
    if version is not _MISSING and is_integer(version) and version == 3:
        return {}, "protocolVersion == 3"
    return (
        {"httpStatus": 409, "detail": "sync_protocol_mismatch"},
        "protocolVersion=%s != 3" % short(version),
    )


def rule_sr2(contract, doc):
    """mutation.data 必须符合 entityType 对应的实体 schema。"""
    if not isinstance(doc, dict):
        return {}, "文档不是对象"
    for index, mutation in enumerate(doc.get("mutations") or []):
        if not isinstance(mutation, dict):
            continue
        if mutation.get("operation") == "delete":
            continue  # delete 携带 data 由 SR-3 负责
        if "data" not in mutation:
            continue
        entity_type = mutation.get("entityType")
        def_name = contract.entity_data_schemas.get(entity_type)
        if def_name is None:
            continue
        errors = contract.validator.validate_def(
            def_name, mutation["data"], "/mutations/%d/data" % index
        )
        if errors:
            return (
                {"status": "rejected", "reason": "invalid_data"},
                "mutations[%d].data 不符合 %s：%s" % (index, def_name, errors[0]),
            )
    return {}, "所有 mutation.data 都符合实体 schema"


def rule_sr3(contract, doc):
    if not isinstance(doc, dict):
        return {}, "文档不是对象"
    for index, mutation in enumerate(doc.get("mutations") or []):
        if (
            isinstance(mutation, dict)
            and mutation.get("operation") == "delete"
            and "data" in mutation
        ):
            return (
                {"status": "rejected", "reason": "invalid_data"},
                "mutations[%d] 是 delete 却携带 data=%s"
                % (index, short(mutation["data"])),
            )
    return {}, "没有 delete 携带 data"


def rule_sr4(contract, doc):
    allowed = set(MUTATION_FIELDS)
    if not isinstance(doc, dict):
        return {}, "文档不是对象"
    for index, mutation in enumerate(doc.get("mutations") or []):
        if not isinstance(mutation, dict):
            continue
        extra = [key for key in mutation if key not in allowed]
        if extra:
            return (
                {"status": "rejected", "reason": "invalid_fields"},
                "mutations[%d] 出现白名单外字段 %s" % (index, extra),
            )
    return {}, "所有 mutation 键都在白名单内"


def rule_sr5(contract, doc):
    if not isinstance(doc, dict):
        return {}, "文档不是对象"
    cursor = doc.get("cursor")
    workspace = doc.get("workspaceRevision")
    if isinstance(cursor, bool) or not isinstance(cursor, int):
        return {}, "cursor 不是整数，交给 schema 阶段"
    if isinstance(workspace, bool) or not isinstance(workspace, int):
        return {}, "workspaceRevision 不是整数，交给 schema 阶段"
    if cursor > workspace:
        return (
            {"httpStatus": 400, "detail": "Invalid sync cursor"},
            "cursor=%s > workspaceRevision=%s" % (cursor, workspace),
        )
    return {}, "cursor=%s 未超过 workspaceRevision=%s" % (short(cursor), short(workspace))


def rule_sr6(contract, doc):
    if not isinstance(doc, dict):
        return {"invalid": False}, "文档不是对象"
    changes = doc.get("changes") or []
    cursor = doc.get("cursor")
    if changes:
        last = changes[-1].get("revision") if isinstance(changes[-1], dict) else None
        if is_integer(cursor) and is_integer(last) and cursor != last:
            return (
                {"invalid": True},
                "cursor=%s 不等于最后一条 revision=%s" % (cursor, last),
            )
    return {"invalid": False}, "cursor 与最后一条 revision 一致（或 changes 为空）"


def rule_sr7(contract, doc):
    if not isinstance(doc, dict):
        return {"invalid": False}, "文档不是对象"
    previous = None
    for index, change in enumerate(doc.get("changes") or []):
        if not isinstance(change, dict):
            continue
        revision = change.get("revision")
        if not is_integer(revision):
            continue
        if previous is not None and revision <= previous:
            return (
                {"invalid": True},
                "changes[%d].revision=%s 未严格大于前一条 %s"
                % (index, revision, previous),
            )
        previous = revision
    return {"invalid": False}, "revision 严格递增"


def rule_sr8(contract, doc):
    if not isinstance(doc, dict):
        return {"invalid": False}, "文档不是对象"
    for index, change in enumerate(doc.get("changes") or []):
        if not isinstance(change, dict):
            continue
        operation = change.get("operation")
        if operation == "delete":
            if "data" not in change or change["data"] is not None:
                return (
                    {"invalid": True},
                    "changes[%d] 是 delete，data 必须是 null，实际 %s"
                    % (
                        index,
                        "缺失" if "data" not in change else short(change["data"]),
                    ),
                )
        elif operation == "upsert":
            if not isinstance(change.get("data"), dict):
                return (
                    {"invalid": True},
                    "changes[%d] 是 upsert，data 必须是对象，实际 %s"
                    % (
                        index,
                        "缺失"
                        if "data" not in change
                        else json_type_name(change["data"]),
                    ),
                )
    return {"invalid": False}, "delete→null / upsert→object 全部成立"


SEMANTIC_RULES = {
    "SR-1": rule_sr1,
    "SR-2": rule_sr2,
    "SR-3": rule_sr3,
    "SR-4": rule_sr4,
    "SR-5": rule_sr5,
    "SR-6": rule_sr6,
    "SR-7": rule_sr7,
    "SR-8": rule_sr8,
}

# 语义用例先做 schema 校验，但规则自身覆盖的字段不能同时算 schema 违规
# （否则规则永远测不到：schema 先把它拒了）。仅 SR-4 需要放行——它的被测量正是
# "mutation 多了一个键"，而 Mutation.additionalProperties=false 会先命中。
# SR-1 不在此表：版本闸门先于 body 校验，单独在 _semantic_schema_errors 里处理。
RULE_SCHEMA_EXEMPTIONS = {
    "SR-4": lambda failure: failure.keyword == "additionalProperties"
    and failure.path.startswith("/mutations/"),
}


def infer_schema_name(doc):
    if not isinstance(doc, dict):
        return None
    if "mutations" in doc:
        return "MutationBatch"
    if "changes" in doc:
        return "ChangesResponse"
    return None


def _semantic_schema_errors(contract, case, doc):
    rule = case.get("rule")
    schema_name = infer_schema_name(doc)
    if schema_name is None:
        return [Failure("", "$case", "无法从样例推断信封类型（既无 mutations 也无 changes）")]

    if rule == "SR-1":
        # 规范 §1/§3.2：protocolVersion != 3 时服务端在解析 body 之前就返回 409，
        # body 根本不参与校验。样例本身可能同时带别的 shape 问题，这里只校验信封。
        if not isinstance(doc, dict) or not is_integer(doc.get("protocolVersion")):
            return [Failure("/protocolVersion", "type", "protocolVersion 必须是整数")]
        if doc["protocolVersion"] != 3:
            return []

    errors = contract.validator.validate_def(schema_name, doc)
    exempt = RULE_SCHEMA_EXEMPTIONS.get(rule)
    if exempt is not None:
        errors = [failure for failure in errors if not exempt(failure)]
    return errors


# --------------------------------------------------------------------------- #
# 样例校验
# --------------------------------------------------------------------------- #


class CaseFailure(object):
    def __init__(self, case, expected, problems):
        self.case = case
        self.expected = expected
        self.problems = problems

    def render(self):
        lines = [
            "FAIL %s [%s]" % (self.case.get("name"), self.case.get("kind")),
            "  file: %s" % self.case.get("file"),
            "  期望: %s" % self.expected,
        ]
        for index, problem in enumerate(self.problems):
            lines.append(("  实际: " if index == 0 else "        · ") + problem)
        return lines


def compare_expect(expect, outcome):
    problems = []
    for key, wanted in expect.items():
        if key not in outcome:
            problems.append("%s 期望 %s，实际未触发" % (key, short(wanted)))
        elif not json_equal(outcome[key], wanted):
            problems.append(
                "%s 期望 %s，实际 %s" % (key, short(wanted), short(outcome[key]))
            )
    return problems


def check_valid(contract, case, doc, notes):
    schema_name = case["schema"]
    errors = contract.validator.validate_def(schema_name, doc)
    if not errors:
        # 线格式通过。data 层不属于 kind=valid 的断言范围，但发现不合规要留痕。
        for failure in contract.mutation_data_errors(doc):
            notes.append(
                "%s: mutation.data 违反 entityDataSchemas（样例缺陷，不影响 valid 判定）: %s"
                % (case.get("name"), failure)
            )
        return []
    problems = ["schema %s 拒绝该文档: %s" % (schema_name, errors[0])]
    problems.extend("  · %s" % item for item in errors[1:3])
    return problems


def check_schema_invalid(contract, case, doc, notes):
    schema_name = case["schema"]
    errors = contract.validator.validate_def(schema_name, doc)
    if errors:
        return []

    # schema 接受该文档时，拒绝只能来自 schema 表达不了的服务端规则：
    # Mutation.data 在本子集里是宽松的 {type:object}，entityType→data 的映射只能由
    # SR-2 承担；delete 携带 data 由 SR-3 承担；mutation 白名单由 SR-4 承担
    # （SR-4 与 Mutation.additionalProperties=false 同义，此处冗余但保持与
    #  scripts/check-contracts.mjs 的判定层次一致）。
    if schema_name == "MutationBatch" and isinstance(doc, dict):
        for rule_id in ("SR-4", "SR-3", "SR-2"):
            outcome, detail = SEMANTIC_RULES[rule_id](contract, doc)
            if outcome:
                if rule_id == "SR-2":
                    # schema 宽松化回归会被 SR-2 掩盖，必须留痕
                    notes.append(
                        "%s: schema 接受该文档，仅靠 %s 拒绝（%s）—— schema 若进一步宽松化，本用例将失效"
                        % (case.get("name"), rule_id, detail)
                    )
                return []

    return [
        "期望被契约拒绝，实际 %s 接受该文档（schema 与 SR-2/SR-3/SR-4 均未拒绝）"
        % schema_name
    ]


def check_semantic(contract, case, doc):
    problems = []
    errors = _semantic_schema_errors(contract, case, doc)
    if errors:
        problems.append(
            "schema 阶段失败（语义用例应先通过 schema）: %s"
            % "; ".join(str(item) for item in errors[:3])
        )

    rule = case.get("rule")
    handler = SEMANTIC_RULES.get(rule)
    if handler is None:
        raise ContractError("样例 %r 使用未知语义规则 %r" % (case.get("name"), rule))

    outcome, note = handler(contract, doc)
    mismatches = compare_expect(case.get("expect") or {}, outcome)
    if mismatches:
        problems.append("%s 结果与 expect 不符: %s（%s）" % (rule, "; ".join(mismatches), note))
    return problems


def expected_label(case, kind):
    if kind == KIND_VALID:
        return "schema %s 接受该文档" % case.get("schema")
    if kind == KIND_SCHEMA_INVALID:
        return "契约拒绝该文档（schema %s 或 SR-2/3/4）" % case.get("schema")
    return "%s 触发 → %s" % (case.get("rule"), short(case.get("expect") or {}))


def case_kind(case):
    """cases.json 里语义样例省略了 kind，用 rule 字段补齐。"""
    kind = case.get("kind")
    if kind:
        return kind
    if case.get("rule"):
        return KIND_SEMANTIC
    raise ContractError("样例 %r 既没有 kind 也没有 rule" % case.get("name"))


def run(contracts_dir, want_notes=False):
    contract = Contract(contracts_dir)
    cases = contract.cases_doc.get("cases") or []
    if not cases:
        raise ContractError("cases.json 没有任何用例")

    counters: dict = dict((kind, 0) for kind in KINDS)
    failures = []
    notes = []

    for case in cases:
        kind = case_kind(case)
        if kind not in counters:
            raise ContractError(
                "样例 %r 的 kind=%r 不受支持" % (case.get("name"), kind)
            )
        counters[kind] += 1
        case = dict(case)
        case["kind"] = kind

        doc = load_json(contract.dir / case["file"])
        if kind == KIND_VALID:
            problems = check_valid(contract, case, doc, notes)
        elif kind == KIND_SCHEMA_INVALID:
            problems = check_schema_invalid(contract, case, doc, notes)
        else:
            problems = check_semantic(contract, case, doc)

        if problems:
            failures.append(CaseFailure(case, expected_label(case, kind), problems))

    if want_notes:
        for note in notes:
            print("NOTE: %s" % note, file=sys.stderr)

    total = len(cases)
    if failures:
        print(
            "CONTRACTS FAIL cases=%d passed=%d failed=%d"
            % (total, total - len(failures), len(failures))
        )
        for failure in failures:
            for line in failure.render():
                print(line)
        return 1

    print(
        "CONTRACTS OK cases=%d valid=%d schema-invalid=%d semantic=%d"
        % (
            total,
            counters[KIND_VALID],
            counters[KIND_SCHEMA_INVALID],
            counters[KIND_SEMANTIC],
        )
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="校验 Studiolo Sync Protocol v3 契约（cases.json + schema + 样例）"
    )
    parser.add_argument(
        "--contracts-dir",
        default=str(DEFAULT_CONTRACTS_DIR),
        help="契约目录（默认 %(default)s）",
    )
    parser.add_argument(
        "--notes",
        action="store_true",
        help="在 stderr 打印样例层面提示（data 层违规、拒绝层次），不影响退出码",
    )
    args = parser.parse_args(argv)

    try:
        return run(args.contracts_dir, want_notes=args.notes)
    except ContractError as exc:
        print("CONTRACTS ERROR %s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
