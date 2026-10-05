#!/usr/bin/env bash
# تجهيز قاعدة PostgreSQL لمُنير من .env (idempotent)؛ ENV_FILE وPROVISION_PSQL اختياريان لملف أو خادم آخر.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_ROOT/.env}"
SQL_FILE="$SCRIPT_DIR/provision.sql"

log() { printf '\e[1;34m[provision]\e[0m %s\n' "$*"; }
warn() { printf '\e[1;33m[provision] تنبيه:\e[0m %s\n' "$*" >&2; }
die() { printf '\e[1;31m[provision] خطأ:\e[0m %s\n' "$*" >&2; exit 1; }

[[ -f "$SQL_FILE" ]] || die "ملف SQL غير موجود: $SQL_FILE"

# هل يوجد terminal تفاعلي للسؤال؟ (بفتح /dev/tty فعلياً)
have_tty() { ( : < /dev/tty ) 2> /dev/null; }

# قراءة متغير من .env مع تجاهل التعليقات والأسطر الفارغة وإزالة علامات الاقتباس
env_get() {
  local key="$1" line
  [[ -f "$ENV_FILE" ]] || return 1
  line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$ENV_FILE" | tail -n 1)" || return 1
  line="${line#*=}"
  line="${line%$'\r'}"
  line="${line#\"}"; line="${line%\"}"
  line="${line#\'}"; line="${line%\'}"
  [[ -n "$line" ]] || return 1
  printf '%s' "$line"
}

# resolve VAR "السؤال" [افتراضي] [secret]: من .env وإلا يسأل المستخدم ويسجّله في MISSING؛ السر يُطلب مرتين
MISSING=()
resolve() {
  local key="$1" prompt="$2" default="${3:-}" secret="${4:-}" value="" confirm=""

  if value="$(env_get "$key")"; then
    printf -v "$key" '%s' "$value"
    return 0
  fi

  have_tty || die "المتغير $key غير موجود في $ENV_FILE ولا يوجد terminal تفاعلي للسؤال عنه. أضفه إلى .env ثم أعد التشغيل."

  if [[ -n "$secret" ]]; then
    while true; do
      read -r -s -p "$prompt: " value < /dev/tty;            printf '\n' > /dev/tty
      read -r -s -p "تأكيد $prompt: " confirm < /dev/tty;    printf '\n' > /dev/tty
      if [[ -z "$value" ]]; then
        printf '%s\n' "القيمة مطلوبة." > /dev/tty
      elif [[ "$value" != "$confirm" ]]; then
        printf '%s\n' "القيمتان غير متطابقتين، حاول مرة أخرى." > /dev/tty
      else
        break
      fi
    done
  else
    read -r -p "$prompt${default:+ [$default]}: " value < /dev/tty
    value="${value:-$default}"
    [[ -n "$value" ]] || die "قيمة $key مطلوبة."
  fi

  printf -v "$key" '%s' "$value"
  MISSING+=("$key")
}

# 1) جمع الإعدادات
if [[ -f "$ENV_FILE" ]]; then
  log "قراءة الإعدادات من $ENV_FILE"
else
  warn "ملف .env غير موجود في $ENV_FILE — سيُسأل عن كل القيم."
fi

resolve DB_NAME     "اسم قاعدة البيانات"            "moneer_db"
resolve DB_USER     "اسم مستخدم قاعدة البيانات"     "moneer_user"
resolve DB_PASSWORD "كلمة مرور المستخدم $DB_USER"   ""        secret
resolve DB_HOST     "المضيف"                        "localhost"
resolve DB_PORT     "المنفذ"                        "5432"

# أمر psql الإداري: محلياً عبر المستخدم postgres على منفذ العنقود، ولخادم بعيد يُمرَّر PROVISION_PSQL كاملاً
PROVISION_PSQL="${PROVISION_PSQL:-sudo -u postgres psql -p $DB_PORT}"

# 2) عرض حفظ القيم المُدخلة في .env
if (( ${#MISSING[@]} > 0 )); then
  printf '\n' > /dev/tty
  read -r -p "حفظ القيم المُدخلة (${MISSING[*]}) في $ENV_FILE؟ [y/N]: " answer < /dev/tty
  if [[ "${answer,,}" == "y" ]]; then
    if [[ ! -f "$ENV_FILE" ]]; then
      touch "$ENV_FILE"
      chmod 600 "$ENV_FILE"
    fi
    for key in "${MISSING[@]}"; do
      printf '%s=%s\n' "$key" "${!key}" >> "$ENV_FILE"
    done
    chmod 600 "$ENV_FILE"
    log "تم الحفظ في $ENV_FILE (صلاحيات 600)"
  else
    log "لم تُحفظ القيم؛ ستُسأل عنها عند التشغيل القادم."
  fi
fi

# 3) تنفيذ SQL بصلاحيات superuser عبر stdin (-X يتجاهل .psqlrc، و-d postgres قاعدة بداية مضمونة)
log "تجهيز قاعدة البيانات '$DB_NAME' للمستخدم '$DB_USER' (المنفذ $DB_PORT)"
# shellcheck disable=SC2086
$PROVISION_PSQL \
  -X -d postgres \
  -v ON_ERROR_STOP=1 \
  -v db_name="$DB_NAME" \
  -v db_user="$DB_USER" \
  -v db_password="$DB_PASSWORD" \
  < "$SQL_FILE"

# 4) التحقق من الاتصال بالطريقة التي يستخدمها Django (TCP وكلمة مرور)
if command -v psql > /dev/null 2>&1; then
  if PGPASSWORD="$DB_PASSWORD" psql -X -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
       -tAc 'SELECT 1' > /dev/null 2>&1; then
    log "تم التحقق: الاتصال بـ $DB_NAME عبر $DB_HOST:$DB_PORT ناجح."
  else
    warn "تعذّر الاتصال بكلمة المرور عبر $DB_HOST:$DB_PORT. راجع pg_hba.conf (يجب أن يسمح بـ scram-sha-256 أو md5 للاتصالات من هذا المضيف) ثم أعد تشغيل PostgreSQL."
  fi
else
  warn "الأمر psql غير متوفر للمستخدم الحالي؛ تخطّي خطوة التحقق."
fi

log "اكتمل التجهيز. الاتصال: postgresql://$DB_USER:<password>@$DB_HOST:$DB_PORT/$DB_NAME"
