#!/usr/bin/env bash
set -euo pipefail

# Mac Core PostgreSQL 加密定时备份脚本（保留最近 14 份）
BACKUP_DIR="${BACKUP_DIR:-$HOME/.studiolo-core/backups}"
DB_URL="${DATABASE_URL:?请通过环境变量传入 DATABASE_URL}"
PASSPHRASE_FILE="${PASSPHRASE_FILE:-$HOME/.studiolo-core/backup.passphrase}"

if [[ ! -f "$PASSPHRASE_FILE" ]]; then
  echo "缺少加密口令文件: $PASSPHRASE_FILE (chmod 600)" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
umask 077

STAMP="$(date +%Y%m%d-%H%M%S)"
TMP_OUT="$(mktemp "$BACKUP_DIR/.dump-XXXXXX.enc")"
FINAL_OUT="$BACKUP_DIR/studiolo-${STAMP}.sql.gz.enc"

pg_dump "$DB_URL" --no-owner --no-privileges \
  | gzip -9 \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass "file:${PASSPHRASE_FILE}" -out "$TMP_OUT"

mv "$TMP_OUT" "$FINAL_OUT"
find "$BACKUP_DIR" -name 'studiolo-*.sql.gz.enc' -type f -mtime +14 -delete
echo "Backup written: $FINAL_OUT"
