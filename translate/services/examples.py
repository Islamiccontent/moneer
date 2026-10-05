"""جلب أمثلة الترجمة من القاعدة المركزية (ICADB) لتغذية prompt الترجمة؛ أي فشل يعيد قائمة فارغة."""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

from classify.services.reviewer import UA

logger = logging.getLogger("translate.examples")

EXAMPLES_K = 5
TIMEOUT = 60


def relevant_examples(iso_code, query, k=EXAMPLES_K):
    """قائمة ``{"source_text", "target_text"}`` من القاعدة المركزية للغة الهدف، أو فارغة."""
    base = settings.CENTRAL_DB_URL.rstrip("/")
    url = (
        f"{base}/books/api/books/relevant-examples/{urllib.parse.quote(iso_code)}/?"
        + urllib.parse.urlencode({"query": query, "k": k})
    )
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning("تعذّر جلب الأمثلة من القاعدة المركزية (%s): %s", iso_code, exc)
        return []
    examples = []
    for item in payload.get("examples") or []:
        source, target = item.get("source_text"), item.get("target_text")
        if source and target:
            examples.append({"source_text": source, "target_text": target})
    return examples


def examples_block(examples, source_lang, target_lang):
    """كتلة الأمثلة بالصيغة التي يتوقعها prompt الترجمة."""
    return "".join(
        f'**{source_lang}:** "{ex["source_text"]}"\n'
        f'**{target_lang} Translation:** "{ex["target_text"]}"\n\n'
        for ex in examples
    )
