-- تجهيز الدور والقاعدة لمُنير عبر provision.sh بصلاحيات superuser؛ المتغيرات :db_name :db_user :db_password (idempotent)

\set ON_ERROR_STOP on

-- 1) الدور: يُنشأ إن لم يوجد، وتُزامَن كلمة المرور والصلاحيات في كل تشغيل (CREATEDB لقاعدة الاختبار)
SELECT format('CREATE ROLE %I', :'db_user')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'db_user')
\gexec

SELECT format(
  'ALTER ROLE %I LOGIN PASSWORD %L CREATEDB NOSUPERUSER NOCREATEROLE NOREPLICATION',
  :'db_user', :'db_password')
\gexec

-- 2) قاعدة البيانات: تُنشأ إن لم توجد بترميز UTF8 ومملوكة للمستخدم
SELECT format(
  'CREATE DATABASE %I OWNER %I ENCODING ''UTF8'' TEMPLATE template0',
  :'db_name', :'db_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db_name')
\gexec

-- لا يتصل بالقاعدة إلا من مُنح ذلك صراحةً.
SELECT format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', :'db_name') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'db_name', :'db_user') \gexec

-- 3) داخل القاعدة: ملكية schema public والامتدادات
\connect :"db_name"

-- دور التطبيق يملك schema public؛ ولا ينشئ غيره كائنات فيه.
SELECT format('ALTER SCHEMA public OWNER TO %I', :'db_user') \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- امتدادات البحث النصي تُفعَّل عند الحاجة فقط (تتطلب superuser):
-- CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- CREATE EXTENSION IF NOT EXISTS unaccent;

\echo ''
\echo '[provision.sql] اكتمل:'
\echo '  database =' :db_name
\echo '  owner    =' :db_user
