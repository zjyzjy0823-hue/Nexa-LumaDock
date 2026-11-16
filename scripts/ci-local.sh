#!/usr/bin/env bash
# 本地一键复现 CI：后端全量 pytest + 契约校验三件套（Python / Node / Rust）。
# 用法：bash scripts/ci-local.sh [--contracts-only] [--with-frontend]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONTRACTS_ONLY=0
WITH_FRONTEND=0

usage() {
  cat <<'EOF'
用法: bash scripts/ci-local.sh [选项]

  --contracts-only   只跑契约校验三件套（Python / Node / Rust）
  --with-frontend    额外运行前端构建（npm run build），默认略过
  -h, --help         显示本帮助

后端测试使用仓库根或 backend/ 下已有的 .venv（优先根目录）；都缺失时报错退出，本脚本不创建 venv。
EOF
}

for arg in "$@"; do
  case "$arg" in
    --contracts-only) CONTRACTS_ONLY=1 ;;
    --with-frontend) WITH_FRONTEND=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

step() { printf '\n==> %s\n' "$*"; }

HEAD_SHA="$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
HEAD_BRANCH="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
echo "==> git HEAD: $HEAD_SHA ($HEAD_BRANCH)"
if [[ -d "$ROOT/.git" && -n "$(git -C "$ROOT" status --porcelain 2>/dev/null || true)" ]]; then
  echo "==> 注意: 工作区存在未提交改动，结果可能与 CI 不一致"
fi

if [[ "$CONTRACTS_ONLY" -eq 0 ]]; then
  step "backend: python -m pytest -q"
  # CI 在 backend/ 下运行；本地 venv 可能在仓库根（README 的安装方式），
  # 也可能在 backend/，两处都接受，避免静默跳过整个后端套件。
  PYTEST_PY=""
  for candidate in "$ROOT/.venv/bin/python" "$ROOT/backend/.venv/bin/python"; do
    if [[ -x "$candidate" ]]; then PYTEST_PY="$candidate"; break; fi
  done
  if [[ -n "$PYTEST_PY" ]]; then
    echo "==> 使用 $PYTEST_PY"
    (cd "$ROOT/backend" && "$PYTEST_PY" -m pytest -q)
  else
    echo "skip: 未找到 .venv（仓库根或 backend/），本脚本不创建虚拟环境；请按 README 自建后重跑" >&2
    exit 3
  fi

  if [[ "$WITH_FRONTEND" -eq 1 ]]; then
    step "frontend: npm run build"
    npm run build
    for suite in test:local-time test:automation test:core-sync test:data-bounded-reads; do
      step "frontend: npm run $suite"
      npm run "$suite"
    done
  else
    echo "skip: frontend build（默认略过；加 --with-frontend 运行）"
  fi
fi

step "contracts: python3 scripts/check-contracts.py"
python3 scripts/check-contracts.py

step "contracts: node scripts/check-contracts.mjs"
node scripts/check-contracts.mjs

step "contracts: cargo test --manifest-path packages/contracts/rust/Cargo.toml"
cargo test --manifest-path packages/contracts/rust/Cargo.toml

printf '\n==> 全部检查通过\n'
