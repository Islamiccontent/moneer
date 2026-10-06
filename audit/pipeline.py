"""خط التدقيق الفوري لترجمة مستند: القواعد المحلية ثم Gemini مجموعةً مجموعة، والكتابة في جداول audit.

منقول من trreview/pipeline.py (ومحوّله في منصة تدقيق) بلا تغيير في المنطق سوى إسقاط مسار
Gemini Batch: كل مجموعة صفوف تُرسل بنداء generateContent واحد وتُكتب نتيجتها فور وصولها،
وتُعاد المجموعة الفاشلة حتى حدّ المحاولات. الصفوف تأتي من جمل ترجمة المستند لا من ملف Excel.

    create_job(document_translation) → run_job(job)      أو      run_audit(document_translation)
"""

import io
import json
import logging
import time

from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from content.models import Phrase

from .models import AuditFinding, AuditGroup, AuditJob, AuditRow
from .services import gemini
from .services.config import load_settings, request_config
from .services.excel_io import compute_stats, write_output
from .services.languages import is_arabic_script
from .services.local_rules import apply_rules
from .services.parsing import normalize_finding, validate_group_result
from .services.prompt import PROMPT_TEMPLATE, PROMPT_VERSION, RESPONSE_SCHEMA, build_prompt
from .services.taxonomy import max_severity, verdict_for

logger = logging.getLogger("audit.pipeline")

RAW_RESPONSE_LIMIT = 200_000
ERROR_LIMIT = 1000


class AuditError(RuntimeError):
    """خطأ مفهوم يُعرض للمستخدم كما هو (بلا traceback)."""


class GeminiClient:
    """غلاف رفيع حول موصل Gemini يحمل المفتاح والنموذج وإعدادات الطلب."""

    def __init__(self, settings):
        if not settings.api_key:
            raise AuditError("GEMINI_API_KEY غير مضبوط. ضعه في .env أو في البيئة.")
        self.api_key = settings.api_key
        self.model = settings.model
        self.thinking_level = settings.thinking_level or None
        self.temperature = settings.temperature
        self.schema = RESPONSE_SCHEMA if settings.use_schema else None
        gemini.set_defaults(settings.http_timeout, settings.http_retries)

    def build_request(self, prompt):
        return gemini.build_request(prompt, self.thinking_level, self.temperature, self.schema)

    def generate(self, request_body):
        return gemini.generate_content(self.api_key, self.model, request_body)

    def list_models(self):
        return gemini.list_models(self.api_key)


def log(message):
    logger.info(message)


# ══════════════════════ 1) إنشاء المهمة ══════════════════════


def build_rows(document_translation, limit=None):
    """صفوف التدقيق من جمل المستند القابلة للترجمة بترتيبها، ونص كل جملة الحالي في الترجمة.

    ``seq`` هو ``id`` العنصر في البرومت (عدد صحيح) ويُحفظ في AuditRow.seq؛ الجملة التي لم
    تُترجم بعد تُدرج بترجمة فارغة فتلتقطها قاعدة FRM-EMP كما في السكربت الأصلي.
    """
    translations = dict(document_translation.phrases.values_list("phrase_id", "translation"))
    phrases = document_translation.document.phrases.filter(translatable=True).order_by(
        "group_id", "group_order"
    )
    rows = []
    for seq, phrase in enumerate(phrases, start=1):
        rows.append(
            {
                "seq": seq,
                "phrase": phrase,
                "source": phrase.text.strip(),
                "target": (translations.get(phrase.pk) or "").strip(),
                "row_type": (
                    AuditRow.RowType.NAQHARA
                    if phrase.text_type == Phrase.TextType.NAQHARA
                    else AuditRow.RowType.TRANSLATION
                ),
            }
        )
        if limit and len(rows) >= limit:
            break
    return rows


def _finding_objects(job, row, findings, start_seq=1):
    return [
        AuditFinding(
            job=job,
            row=row,
            seq=start_seq + offset,
            source=f["source"],
            category_code=f["category_code"][:10],
            category=f["category"][:100],
            type_code=f["type_code"][:20],
            type_name=f["type_name"][:150],
            severity=f["severity"],
            sharia_sensitive=bool(f["sharia_sensitive"]),
            detection=f["detection"],
            confidence=f["confidence"],
            location=f["location"],
            explanation=f["explanation"],
            required_action=f["required_action"],
            suggested_fix=f["suggested_fix"],
            needs_human_review=bool(f["needs_human_review"]),
        )
        for offset, f in enumerate(findings)
    ]


ROW_RESULT_FIELDS = (
    "status",
    "verdict",
    "summary",
    "error_count",
    "max_severity",
    "sharia_sensitive",
    "needs_human_review",
)


def _apply_row_result(row, findings, status, summary):
    """يضبط حكم الصف من ملاحظاته (قاعدية ونموذجية) كما في db.update_row_result."""
    severities = [f["severity"] if isinstance(f, dict) else f.severity for f in findings]
    sharia = [
        f["sharia_sensitive"] if isinstance(f, dict) else f.sharia_sensitive for f in findings
    ]
    review = [
        f["needs_human_review"] if isinstance(f, dict) else f.needs_human_review for f in findings
    ]
    row.status = status
    row.verdict = verdict_for(severities)
    row.summary = summary or ""
    row.error_count = len(findings)
    row.max_severity = max_severity(severities) or ""
    row.sharia_sensitive = any(sharia)
    row.needs_human_review = any(review)


def create_job(
    document_translation,
    settings=None,
    *,
    created_by=None,
    extra_rules="",
    limit=None,
):
    """يبني الصفوف، يطبّق القواعد المحلية، يخزّن الصفوف والملاحظات القطعية، ويقسّم المؤهل منها
    إلى مجموعات. يعيد AuditJob بحالة «بانتظار البدء»."""
    settings = settings or load_settings()
    rows = build_rows(document_translation, limit)
    if not rows:
        raise AuditError("لا توجد جمل قابلة للتدقيق في هذه الترجمة.")
    language = document_translation.target_language
    arabic_script = is_arabic_script(language.iso_code)
    rule_results = apply_rules(rows, arabic_script, settings.short_ratio, settings.long_ratio)

    with transaction.atomic():
        job = AuditJob.objects.create(
            document_translation=document_translation,
            language=language.name,
            arabic_script=arabic_script,
            model=settings.model,
            group_size=settings.group_size,
            prompt_version=PROMPT_VERSION,
            # لقطة البرومت: القالب كاملًا بعناصر فارغة، كي تُعاد صياغة الطلبات منه لاحقًا
            prompt_snapshot=PROMPT_TEMPLATE,
            request_config=request_config(settings),
            extra_rules=extra_rules or "",
            total_rows=len(rows),
            created_by=created_by,
        )
        row_objs = AuditRow.objects.bulk_create(
            [
                AuditRow(
                    job=job,
                    seq=r["seq"],
                    phrase=r["phrase"],
                    source_text=r["source"],
                    target_text=r["target"],
                    row_type=r["row_type"],
                    hints=rr["hints"],
                    status=AuditRow.Status.SKIPPED if rr["skip"] else AuditRow.Status.PENDING,
                    skip_reason=(rr["skip"] or "")[:255],
                )
                for r, rr in zip(rows, rule_results, strict=True)
            ]
        )
        findings, skipped, eligible = [], [], []
        for row, rr in zip(row_objs, rule_results, strict=True):
            normalized = [normalize_finding(f, source="rule") for f in rr["findings"]]
            findings += _finding_objects(job, row, normalized)
            if rr["skip"]:
                _apply_row_result(row, normalized, AuditRow.Status.SKIPPED, rr["skip"])
                skipped.append(row)
            else:
                eligible.append(row)
        AuditFinding.objects.bulk_create(findings)
        AuditRow.objects.bulk_update(skipped, ROW_RESULT_FIELDS)

        size = settings.group_size
        groups = []
        for number, start in enumerate(range(0, len(eligible), size)):
            group = AuditGroup.objects.create(job=job, key=f"j{job.pk}-g{number:05d}")
            AuditRow.objects.filter(pk__in=[r.pk for r in eligible[start : start + size]]).update(
                group=group
            )
            groups.append(group)
        job.eligible_rows = len(eligible)
        job.save(update_fields=["eligible_rows", "updated_at"])

    log(
        f"✔ أُنشئت مهمة التدقيق #{job.pk}: {len(rows)} صفًا، {len(eligible)} مؤهلًا للفحص، "
        f"{len(rows) - len(eligible)} مستبعدًا بقاعدة قطعية، {len(groups)} مجموعة × {size} صفًا."
    )
    return job


# ══════════════════════ 2) بناء طلب مجموعة ══════════════════════


def _group_rows(group):
    return list(group.rows.order_by("seq"))


def build_group_prompt(job, group):
    items = [
        {
            "id": r.seq,
            "source": r.source_text,
            "target": r.target_text,
            "row_type": r.row_type,
            "hints": r.hints or [],
        }
        for r in _group_rows(group)
    ]
    return build_prompt(
        items,
        job.language,
        bool(job.arabic_script),
        extra_rules=job.extra_rules,
        template=job.prompt_snapshot,
    )


# ══════════════════════ 3) كتابة نتائج مجموعة ══════════════════════


def _write_group_results(job, group, parsed):
    """parsed: {seq: {summary, errors}} — يكتب الملاحظات ويحدّث حكم كل صف."""
    for row in _group_rows(group):
        result = parsed[row.seq]
        # ملاحظات النموذج تُستبدل، وملاحظات القواعد تبقى ويُكمل الترقيم بعدها
        row.findings.exclude(source=AuditFinding.Source.RULE).delete()
        start = row.findings.aggregate(last=Max("seq"))["last"] or 0
        AuditFinding.objects.bulk_create(_finding_objects(job, row, result["errors"], start + 1))
        all_findings = list(row.findings.order_by("seq"))
        _apply_row_result(row, all_findings, AuditRow.Status.DONE, result["summary"])
        row.save(update_fields=[*ROW_RESULT_FIELDS])


def _handle_group_response(job, settings, group, item):
    """يحلّل رد مجموعة ويكتب نتائجه أو يعلّم فشلها/إعادتها."""
    try:
        text = gemini.response_text(item)
        parsed = validate_group_result(text, [r.seq for r in _group_rows(group)])
    except Exception as exc:
        _mark_group_failure(settings, group, str(exc))
        return False
    p_tok, o_tok = gemini.usage_tokens(item)
    with transaction.atomic():
        _write_group_results(job, group, parsed)
        group.status = AuditGroup.Status.DONE
        group.completed_at = timezone.now()
        group.last_error = ""
        group.raw_response = text[:RAW_RESPONSE_LIMIT]
        group.save(update_fields=["status", "completed_at", "last_error", "raw_response"])
        AuditJob.objects.filter(pk=job.pk).update(
            prompt_tokens=F("prompt_tokens") + p_tok, output_tokens=F("output_tokens") + o_tok
        )
    return True


def _mark_group_failure(settings, group, error):
    """إعادة معلّقة إن بقيت محاولات، وإلا فشل نهائي مع تعليم صفوفها."""
    retry = group.attempts < settings.max_attempts
    with transaction.atomic():
        group.status = AuditGroup.Status.PENDING if retry else AuditGroup.Status.FAILED
        group.last_error = str(error)[:ERROR_LIMIT]
        group.save(update_fields=["status", "last_error"])
        if not retry:
            group.rows.filter(status=AuditRow.Status.PENDING).update(status=AuditRow.Status.FAILED)
    log(
        f"  ⚠ المجموعة {group.key}: {str(error)[:160]} → "
        f"{'ستُعاد' if retry else 'فشلت نهائيًا'} (محاولة {group.attempts}/{settings.max_attempts})"
    )


def group_status_counts(job):
    return {
        status: job.groups.filter(status=status).count()
        for status in AuditGroup.Status.values
        if job.groups.filter(status=status).exists()
    }


def row_status_counts(job):
    return {
        status: job.rows.filter(status=status).count()
        for status in AuditRow.Status.values
        if job.rows.filter(status=status).exists()
    }


def refresh_job_status(job):
    """يستنتج حالة المهمة من حالات مجموعاتها."""
    counts = group_status_counts(job)
    total = sum(counts.values())
    done, failed = counts.get(AuditGroup.Status.DONE, 0), counts.get(AuditGroup.Status.FAILED, 0)
    if total == 0 or done == total:
        status = AuditJob.Status.DONE
    elif done + failed == total:
        status = AuditJob.Status.PARTIAL if done else AuditJob.Status.FAILED
    else:
        status = AuditJob.Status.RUNNING
    job.status = status
    job.save(update_fields=["status", "updated_at"])
    return status


# ══════════════════════ 4) التنفيذ الفوري ══════════════════════


def run_sync(job, settings, client):
    """ينفّذ المجموعات المعلّقة بنداءات generateContent مباشرة، ويعيد المُعادة في الدورة نفسها."""
    pending = list(job.groups.filter(status=AuditGroup.Status.PENDING).order_by("id"))
    total = len(pending)
    for index, group in enumerate(pending, start=1):
        group.attempts += 1
        group.started_at = timezone.now()
        group.save(update_fields=["attempts", "started_at"])
        n_rows = group.rows.count()
        log(
            f"⏳ [{index}/{total}] إرسال {group.key} ({n_rows} صفًا) إلى {client.model} — "
            "النداء الفوري يستغرق عادةً 30–120 ث مع التفكير العالي."
        )
        started = time.time()
        try:
            item = client.generate(client.build_request(build_group_prompt(job, group)))
        except Exception as exc:
            _mark_group_failure(settings, group, str(exc))
            continue
        if _handle_group_response(job, settings, group, item):
            p_tok, o_tok = gemini.usage_tokens(item)
            log(
                f"✔ {group.key}: تمّ في {time.time() - started:.0f} ث "
                f"(توكن إدخال {p_tok} / إخراج {o_tok})"
            )
    # المجموعات التي عادت معلّقة بعد خطأ تُعاد في الدورة نفسها حتى تنفد المحاولات
    if job.groups.filter(status=AuditGroup.Status.PENDING).exists():
        return run_sync(job, settings, client)
    return refresh_job_status(job)


# ══════════════════════ 5) الإحصائيات والتصدير ══════════════════════


def export_rows(job):
    """(job, rows, findings) بقواميس بأعمدة review.db نفسها لتغذية compute_stats وwrite_output."""
    job_dict = {
        "id": job.pk,
        "input_file": f"{job.document_translation.document.title} — {job.language}",
        "language": job.language,
        "model": job.model,
        "prompt_version": job.prompt_version,
        "created_at": job.created_at.isoformat(),
        "prompt_tokens": job.prompt_tokens,
        "output_tokens": job.output_tokens,
        "columns_json": json.dumps(
            {
                "headers": ["النص العربي", "الترجمة", "معرّف الجملة"],
                "source_col": "النص العربي",
                "target_col": "الترجمة",
            },
            ensure_ascii=False,
        ),
    }
    rows = [
        {
            "id": r.pk,
            "excel_row": r.seq,
            "source_text": r.source_text,
            "target_text": r.target_text,
            "extra_json": json.dumps({"معرّف الجملة": r.phrase_id}, ensure_ascii=False),
            "status": r.status,
            "skip_reason": r.skip_reason,
            "verdict": r.verdict,
            "summary": r.summary,
            "error_count": r.error_count,
            "max_severity": r.max_severity,
            "needs_human_review": r.needs_human_review,
        }
        for r in job.rows.order_by("seq")
    ]
    findings = [
        {
            "row_id": f.row_id,
            "excel_row": f.row.seq,
            "source_text": f.row.source_text,
            "target_text": f.row.target_text,
            "seq": f.seq,
            "source": f.source,
            "category_code": f.category_code,
            "category": f.category,
            "type_code": f.type_code,
            "type_name": f.type_name,
            "severity": f.severity,
            "sharia_sensitive": f.sharia_sensitive,
            "detection": f.detection,
            "confidence": f.confidence,
            "location": f.location,
            "explanation": f.explanation,
            "required_action": f.required_action,
            "suggested_fix": f.suggested_fix,
            "needs_human_review": f.needs_human_review,
        }
        for f in job.findings.select_related("row").order_by("row__seq", "seq")
    ]
    return job_dict, rows, findings


def json_stats(stats):
    """إحصائيات compute_stats بشكل قابل للتسلسل JSON لحفظها في AuditJob.stats."""

    def triple(items):
        return [{"label": a, "count": b, "pct": c} for a, b, c in items]

    return {
        "general": {str(k): v for k, v in stats["general"]},
        "verdicts": triple(stats["verdicts"]),
        "by_severity": triple(stats["by_severity"]),
        "by_category": triple(stats["by_category"]),
        "by_detection": triple(stats["by_detection"]),
        "by_source": triple(stats["by_source"]),
        "by_type": [
            {"code": code, "name": name, "count": n, "pct": p}
            for code, name, n, p in stats["by_type"]
        ],
    }


def finalize(job):
    """يحسب الإحصائيات والتقدّم وعدد الملاحظات ورسالة الخطأ المجمّعة ويختم المهمة."""
    job.refresh_from_db()
    job_dict, rows, findings = export_rows(job)
    job.stats = json_stats(compute_stats(job_dict, rows, findings))
    job.progress = {"groups": group_status_counts(job), "rows": row_status_counts(job)}
    job.finding_count = len(findings)
    errors = [
        g.last_error for g in job.groups.filter(status=AuditGroup.Status.FAILED) if g.last_error
    ]
    job.error_message = "؛ ".join(dict.fromkeys(e[:300] for e in errors))[:2000]
    job.finished_at = timezone.now()
    job.save(
        update_fields=[
            "stats",
            "progress",
            "finding_count",
            "error_message",
            "finished_at",
            "updated_at",
        ]
    )
    log(f"✔ انتهت مهمة التدقيق #{job.pk} بحالة {job.status} ({len(findings)} ملاحظة)")
    return job


def export_xlsx(job):
    """ملف Excel للنتائج بأوراقه الأربع في الذاكرة (بلا تخزين)."""
    buffer = io.BytesIO()
    write_output(buffer, *export_rows(job))
    return buffer.getvalue()


# ══════════════════════ 6) نقاط الدخول ══════════════════════


def run_job(job, settings=None, client=None):
    """ينفّذ مهمة مُنشأة: Gemini فورياً ثم الإحصائيات؛ أي خطأ غير متوقع يُسجَّل على المهمة ويُرفع."""
    settings = settings or load_settings()
    job.status = AuditJob.Status.RUNNING
    job.save(update_fields=["status", "updated_at"])
    try:
        client = client or GeminiClient(settings)
        run_sync(job, settings, client)
        finalize(job)
    except Exception as exc:
        job.status = AuditJob.Status.FAILED
        job.error_message = f"{type(exc).__name__}: {exc}"[:2000]
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        raise
    return job


def run_audit(
    document_translation,
    *,
    created_by=None,
    extra_rules="",
    limit=None,
    settings=None,
    client=None,
):
    """الأداة كاملة في نداء واحد: إنشاء المهمة ثم تنفيذها فورياً. يعيد AuditJob بحالتها النهائية."""
    settings = settings or load_settings()
    client = client or GeminiClient(settings)  # بلا مفتاح يُرفع AuditError قبل إنشاء أي شيء
    job = create_job(
        document_translation,
        settings,
        created_by=created_by,
        extra_rules=extra_rules,
        limit=limit,
    )
    return run_job(job, settings, client)
