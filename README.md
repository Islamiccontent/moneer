# مُنير (moneer)

منصة لإنشاء وترجمة المحتوى الإسلامي بدعم الذكاء الاصطناعي: رفع المحتوى، تقطيعه وتصنيفه، مطابقة الآيات والأحاديث والمصطلحات مع المصادر المعتمدة وذاكرة الترجمة، ثم المراجعة البشرية والاعتماد والتصدير. **الآلة تقترح والمُراجع يعتمد.** الصفحة الرئيسية (`index.html`) تعرض الفكرة كاملة.

هذا المستودع في **المرحلة الأولى (التأسيس)**: مشروع Django على PostgreSQL مع نموذج المستخدم المخصّص والبيانات المرجعية، والصفحة الرئيسية كما هي على `/`.

## المتطلبات

| المكوّن | الإصدار |
|---|---|
| Python | 3.12 أو أحدث (`.python-version` = 3.12) |
| Django | **6.1.1 حصراً** (`requirements.txt`) |
| PostgreSQL | **17** (المعتمد؛ Django 6.1 يدعم 15 فأعلى) في كل البيئات. لا SQLite |
| محرّك القاعدة | `psycopg[binary]` 3 |
| الجودة | `ruff` |

## التشغيل المحلي خطوة بخطوة

```bash
# 1) الاستنساخ
git clone https://github.com/Islamiccontent/moneer.git
cd moneer

# 2) بيئة افتراضية بـ Python 3.12 وتثبيت الاعتماديات (بإصدارات دقيقة)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 3) ملف البيئة
cp .env.example .env
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
#    ضع الناتج في SECRET_KEY داخل .env، واضبط DB_PASSWORD و DB_PORT
#    (DB_PORT = منفذ عنقود PostgreSQL 17 لديك؛ الافتراضي في المثال 5434)
#    ولتشغيل الترجمة: GEMINI_API_KEY و OPENAI_API_KEY
#    وللتصدير اختيارياً SPIRE_DOC_KEY

# 4) تجهيز قاعدة البيانات (idempotent؛ يسأل عن أي قيمة ناقصة في .env ويعرض حفظها)
./scripts/db/provision.sh
#    خادم بعيد: PROVISION_PSQL="psql -h HOST -U postgres" ./scripts/db/provision.sh

# 5) الجداول والبيانات الأولية
python manage.py migrate
#    (اختياري) القائمة الكاملة للغات من ICADB؛ idempotent ويمكن إعادته في أي وقت
python manage.py import_languages
#    (اختياري) بيانات القرآن المعتمدة لتطبيق الترجمة، بالترتيب؛ ملفات xlsx المصدر
#    في imports/quran-kb/ (غير متتبَّع)
python manage.py import_quran_ayat
python manage.py import_quran_keys
python manage.py import_quran_translations
#    (اختياري) تنسيق تصدير افتراضي لكل لغة
python manage.py ensure_default_formats

# 6) المشرف الأول (بالبريد الإلكتروني)
python manage.py createsuperuser

# 7) التشغيل
python manage.py runserver
```

ثم:

- الصفحة الرئيسية: <http://127.0.0.1:8000/>
- لوحة الإدارة (بالعربية وRTL): <http://127.0.0.1:8000/admin/>
- قائمة الملفات (مرحلة كل ملف وكل لغة فيه ونسبة تقدّمها): <http://127.0.0.1:8000/translate/documents/>

لا يُفرض تسجيل الدخول على أي صفحة؛ الدخول مطلوب للوحة admin فقط.

الترجمة تعمل في الخلفية: إضافة لغة هدف لمستند من admin تُطلق ترجمته، والكنس الدوري `python manage.py translate_pending` من cron يستأنف ما لم يكتمل. في الإنتاج يُضبط `TASKS_BACKEND=django_tasks_db.DatabaseBackend` ويعمل العامل `python manage.py db_worker` خدمةً مستقلة.

التصدير آني بلا تخزين: روابط DOCX وPDF في admin «ترجمات المستندات» (المسار `/export/<id>/docx/`)، أو `python manage.py export_translation <id> --output ملف.docx`.

## الفحوصات قبل الدمج

تعمل آلياً في CI على PostgreSQL 17 (`.github/workflows/ci.yml`)، وتُشغَّل محلياً هكذا:

```bash
ruff check . && ruff format --check .
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py test
```

## النشر على الخادم (الترجمة في الخلفية)

على خادم Linux بـ systemd وPostgreSQL 17، بمستخدم خدمة مثل `moneer` ومسار مثل `/home/moneer`؛ عدّلهما في الملفات حيث يرِدان.

```bash
# 1) الكود والاعتماديات
git clone https://github.com/Islamiccontent/moneer.git /home/moneer
cd /home/moneer && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2) .env على الخادم (غير متتبَّع): انسخ .env.example واملأ SECRET_KEY وDEBUG=False وALLOWED_HOSTS
#    وDB_* ومفاتيح النماذج GEMINI_API_KEY وOPENAI_API_KEY، واجعل المهام تعمل بعامل مستقل:
#    TASKS_BACKEND=django_tasks_db.DatabaseBackend
cp .env.example .env && nano .env

# 3) القاعدة والبيانات المرجعية (ملفات xlsx لترجمات القرآن في imports/quran-kb/ أولاً)
.venv/bin/python manage.py migrate
.venv/bin/python manage.py import_languages
.venv/bin/python manage.py import_quran_ayat
.venv/bin/python manage.py import_quran_keys
.venv/bin/python manage.py import_quran_translations
.venv/bin/python manage.py ensure_default_formats

# 4) عامل المهام: خدمة systemd من الملف الجاهز deploy/systemd/moneer-translate-worker.service
sudo cp deploy/systemd/moneer-translate-worker.service /etc/systemd/system/
sudo nano /etc/systemd/system/moneer-translate-worker.service   # User/Group وWorkingDirectory وExecStart
sudo systemctl daemon-reload
sudo systemctl enable --now moneer-translate-worker
systemctl status moneer-translate-worker                        # active (running)
journalctl -u moneer-translate-worker -f                        # سجل العامل الحي

# 5) الكنس الدوري: ملف cron الجاهز deploy/cron/moneer-translate-pending كل عشر دقائق
sudo mkdir -p /var/log/moneer && sudo chown root:www-data /var/log/moneer
sudo cp deploy/cron/moneer-translate-pending /etc/cron.d/moneer-translate-pending
sudo nano /etc/cron.d/moneer-translate-pending                 # المستخدم والمسار
sudo chmod 644 /etc/cron.d/moneer-translate-pending

# 6) التحقق: أضف لغة هدف لمستند من admin؛ يظهر صف في «Tasks Database Backend» خلال ثوانٍ،
#    ثم تتحول ترجمة المستند إلى «قيد المراجعة» بعد أن ينهيها العامل. أو شغّل الكنس يدوياً:
.venv/bin/python manage.py translate_pending
```

- **بعد كل تحديث للكود** أعد تشغيل العامل لأنه يحمّل الكود عند بدئه: `sudo systemctl restart moneer-translate-worker`.
- دورياً: `.venv/bin/python manage.py prune_db_task_results` لحذف نتائج المهام القديمة من الجدول.
- بلا `TASKS_BACKEND` يبقى الافتراضي الفوري: تعمل الترجمة داخل طلب admin نفسه وقد تتجاوز مهلة خادم الويب، فلا يصلح إلا للتطوير.

## التطبيقات

| التطبيق | المسؤولية |
|---|---|
| `core` | البيانات المرجعية المشتركة: `Language` (رمز ISO، الاسم بالعربية والإنجليزية، الاتجاه) مع اللغات الأولية عبر data migration، والقائمة الكاملة عبر `manage.py import_languages` من ICADB |
| `content` | المحتوى العربي بعد التقطيع والتصنيف: المستندات والعبارات وتحليلها والمعجم الموحّد، وترجمة كل مستند إلى لغات هدف جملةً جملة؛ أمر `manage.py import_glossary` |
| `translate` | الترجمة في الخلفية على `django.tasks`: الآيات من الترجمة المعتمدة لموسوعة القرآن الكريم بعد مطابقتها بالرسمين واستخلاصها بـ gpt-5-nano، وبقية النصوص بـ Gemini على طريقة ترجمان؛ يكتب في `content.PhraseTranslation`. الأوامر: `import_quran_ayat`، `import_quran_keys`، `import_quran_translations`، `translate_pending` |
| `export` | تصدير ترجمة المستند إلى DOCX وPDF بـ Spire.Doc بمنطق لوحة تنسيق الكتب، وتنسيق افتراضي لكل لغة (`ExportFormat`)؛ تصدير آني بلا تخزين من روابط admin أو `/export/<id>/docx/`. الأوامر: `ensure_default_formats`، `export_translation` |
| `users` | نموذج المستخدم المخصّص: البريد الإلكتروني معرّف الدخول، `full_name`، `preferred_language`؛ admin مخصّص |
| `pages` | الصفحات العامة: تخدم `index.html` على `/` وصفحات `pages/html` كما هي مع ملفات الجذر (الأيقونات، `site.webmanifest`، `og.jpg`)، وأصولها المشتركة (الخطوط والصور والأنماط ومشغّل القوالب) من `pages/assets` على `/assets/` بلا `collectstatic`؛ وقائمة الملفات `/translate/documents/` التي تقرأ `/api/translate/documents/` وتعرض مرحلة كل ملف وكل لغة ونسبة التقدّم، وخطوطها وشعارها في `pages/static/pages/` |

## هيكل المستودع

```
manage.py            moneer/        إعدادات المشروع (settings, urls, wsgi, asgi)
core/  users/  pages/               التطبيقات
index.html + الأيقونات + site.webmanifest + og.jpg   الصفحة الرئيسية
templates/  static/                 قوالب وملفات ثابتة مشتركة
scripts/db/                         provision.sh + provision.sql
.github/workflows/ci.yml            فحوصات CI
```

## الرخصة

انظر [`LICENSE`](LICENSE).
