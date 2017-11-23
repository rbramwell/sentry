from __future__ import absolute_import

from sentry import options
from sentry.identity import OAuth2Provider

options.register('slack.client-id')
options.register('slack.client-secret')
options.register('slack.verification-token')


class SlackIdentityProvider(OAuth2Provider):
    key = 'slack'
    name = 'Slack'

    oauth_access_token_url = 'https://slack.com/api/oauth.access'
    oauth_authorize_url = 'https://slack.com/oauth/authorize'

    oauth_scopes = tuple(sorted((
        'bot',
        'chat:write:bot',
        'commands',
        'links:read',
        'links:write',
        'team:read',
    )))

    def get_oauth_client_id(self):
        return options.get('slack.client-id')

    def get_oauth_client_secret(self):
        return options.get('slack.client-secret')

    def get_oauth_scopes(self):
        return self.oauth_scopes
