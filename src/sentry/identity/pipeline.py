from __future__ import absolute_import, print_function

from sentry.utils.pipeline import ProviderPipeline
from sentry.identity import default_manager


class IdentityProviderPipeline(ProviderPipeline):
    pipeline_name = 'identity_provider'
    provider_manager = default_manager
