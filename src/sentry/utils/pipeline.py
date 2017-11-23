from __future__ import absolute_import, print_function

import logging

from sentry.models import Organization
from sentry.utils.session_store import RedisSessionStore
from sentry.utils.hashlib import md5_text


class PipelineProvider(object):
    """
    A class implementing the PipelineProvider interface provides the pipeline
    views that the ProviderPipeline will traverse through.
    """

    def get_pipeline(self):
        """
        Returns a list of instantiated views which implement the PipelineView
        class. Each view will be dispatched in order.
        >>> return [OAuthInitView(), OAuthCallbackView()]
        """
        raise NotImplementedError


class PipelineView(object):
    """
    A class implementing the PipelineView may be used in a PipleineProviders
    get_pipeline list.
    """

    def dispatch(self, request, pipeline):
        """
        Called on request, the active pipeline is passed in which can and
        should be used to bind data and traverse the pipeline.
        """
        raise NotImplementedError


class ProviderPipeline(object):
    """
    ProviderPipeline provides a mechanism to guide the user through a request
    'pipeline', where each view may be copleted by calling the ``next_step``
    pipeline method to traverse through the pipe.

    The provider pipeline works with a Provider object which provides the
    pipeline views and is made available to the views through the passed in
    pipeline.

    :provider_manager: A class property that must be specified to allow for
                       lookup of a provider implmentation object given it's
                       key.
    """
    pipeline_name = None
    provider_manager = None

    @classmethod
    def get_for_request(cls, request):
        state = RedisSessionStore(request, cls.pipeline_name)
        if not state.is_valid():
            return None

        organization_id = state.org_id
        if not organization_id:
            return None

        organization = Organization.objects.get(id=state.org_id)
        provider_key = state.provider_key

        return cls(request, organization, provider_key)

    def __init__(self, request, organization, provider_key=None):
        self.request = request
        self.organization = organization
        self.state = RedisSessionStore(request, self.pipeline_name)
        self.provider = self.provider_manager.get(provider_key)

        # we serialize the pipeline to be [PipelineView().get_ident(), ...] which
        # allows us to determine if the pipeline has changed during the auth
        # flow or if the user is somehow circumventing a chunk of it
        pipe_ids = ['{}.{}'.format(type(v).__module__, type(v).__name__) for v in self.pipeline]
        self.signature = md5_text(*pipe_ids).hexdigest()

    def pipeline_is_valid(self):
        return self.state.is_valid() and self.state.signature == self.signature

    def init_pipeline(self):
        self.state.regenerate({
            'uid': self.request.user.id if self.request.user.is_authenticated() else None,
            'provider_key': self.provider.key,
            'org_id': self.organization.id,
            'step_index': 0,
            'signature': self.signature,
            'data': {},
        })

    def clear_session(self):
        self.state.clear()

    def current_step(self):
        """
        Render the current step.
        """
        step_index = self.state.step_index

        if step_index == len(self.pipeline):
            return self.finish_pipeline()

        return self.pipeline[step_index].dispatch(
            request=self.request,
            helper=self,
        )

    def next_step(self):
        """
        Render the next step.
        """
        self.state.step_index += 1
        return self.current_step()

    def finish_pipeline(self):
        """
        Called when the pipeline complets the final step.
        """
        raise NotImplementedError

    def bind_state(self, key, value):
        data = self.state.data
        data[key] = value

        self.state.data = data

    def fetch_state(self, key=None):
        return self.state.data if key is None else self.state.data.get(key)
