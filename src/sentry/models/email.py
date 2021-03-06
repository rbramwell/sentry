from __future__ import absolute_import

from django.db import models
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from sentry.db.models import Model, sane_repr
from sentry.db.models import CIEmailField


class Email(Model):
    """
    Email represents a unique email. Email settings (unsubscribe state) should be associated here.
    UserEmail represents whether a given user account has access to that email.
    """
    __core__ = True

    email = CIEmailField(_('email address'), unique=True)
    date_added = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = 'sentry'
        db_table = 'sentry_email'

    __repr__ = sane_repr('email')
