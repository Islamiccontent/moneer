"""إنشاء content.DocumentTranslation يُدرج مهمة ترجمته بعد commit عبر transaction.on_commit."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from content.models import DocumentTranslation

from .tasks import enqueue_translation


@receiver(post_save, sender=DocumentTranslation, dispatch_uid="translate.enqueue_on_create")
def enqueue_on_create(sender, instance, created, raw=False, **kwargs):
    if created and not raw and instance.status == DocumentTranslation.Status.PENDING:
        enqueue_translation(instance)
