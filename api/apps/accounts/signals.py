from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile, User, UserPreferences


@receiver(post_save, sender=User)
def ensure_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)
        UserPreferences.objects.get_or_create(user=instance)
