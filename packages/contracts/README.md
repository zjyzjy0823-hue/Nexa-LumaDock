# packages/contracts

Sync Protocol v3 的**唯一权威定义**。三端（桌面 / Android / Core）都以这里的形状为准；实现与这里不一致，改的是实现。

| 路径 | 内容 |
| --- | --- |
| [`sync-protocol-v3.md`](sync-protocol-v3.md) | 规范正文（含幂等、分页、冲突、删除、快照恢复、兼容矩阵与已知缺口） |
| [`schema/sync-v3.schema.json`](schema/sync-v3.schema.json) | 机器可读 JSON Schema（normative） |
| [`samples/valid/`](samples/valid/) | 必须被接受的样例 |
| [`samples/invalid/`](samples/invalid/) | 必须被信封（schema）拒绝的样例 |
| [`samples/semantic/`](samples/semantic/) | 信封合法但语义违规的样例（SR-1…SR-8） |
| [`cases.json`](cases.json) | 用例清单 + 语义规则 + 枚举，三种校验器共用 |
| `rust/` | Rust 侧严格 serde 类型（`studiolo-contracts` crate）与契约测试 |

## 校验

```bash
python3 scripts/check-contracts.py           # 纯标准库
node    scripts/check-contracts.mjs          # 零依赖
cargo test --manifest-path packages/contracts/rust/Cargo.toml
bash scripts/ci-local.sh --contracts-only    # 三件套一次跑完
```

三者读同一份 `cases.json`：成功时都输出同一行
`CONTRACTS OK cases=35 valid=13 schema-invalid=13 semantic=9`。任何一方失败即视为契约被破坏，CI 会拒绝合并。

## 两处容易搞混的层次

1. **`Mutation.data` / `Change.data` 在信封层是不透明对象**（`{"type":"object"}`）。实体字段的校验属于 **SR-2**（服务层），由 `parse_entity_data` / 实体 schema 完成 —— 所以"amount 是数字"这类样例在 `samples/semantic/`，不在 `samples/invalid/`。
2. **版本闸门先于 body 校验**：`protocolVersion != 3` 直接 409，不会先报字段错误（SR-1）。

## 修订规则

修改契约必须同时改 `sync-protocol-v3.md` + `schema/` + `samples/` + `cases.json`，并让三种校验器全绿。只改文档或只改 schema 视为未完成。
