from __future__ import absolute_import

import mock
import uuid
from time import time

from sentry import quotas, tsdb
from sentry.event_manager import EventManager, HashDiscarded
from sentry.plugins import Plugin2
from sentry.signals import event_discarded, event_saved
from sentry.tasks.store import preprocess_event, process_event, save_event
from sentry.testutils import PluginTestCase
from sentry.testutils.asserts import assert_mock_called_once_with_partial
from sentry.utils.dates import to_datetime


class BasicPreprocessorPlugin(Plugin2):
    def get_event_preprocessors(self, data):
        def remove_extra(data):
            del data['extra']
            return data

        def put_on_hold(data):
            data['unprocessed'] = True
            return data

        if data.get('platform') == 'mattlang':
            return [remove_extra, lambda x: None]

        if data.get('platform') == 'noop':
            return [lambda data: data]

        if data.get('platform') == 'holdmeclose':
            return [put_on_hold]

        return []

    def is_enabled(self, project=None):
        return True


class StoreTasksTest(PluginTestCase):
    plugin = BasicPreprocessorPlugin

    @mock.patch('sentry.tasks.store.save_event')
    @mock.patch('sentry.tasks.store.process_event')
    def test_move_to_process_event(self, mock_process_event, mock_save_event):
        project = self.create_project()

        data = {
            'project': project.id,
            'platform': 'mattlang',
            'message': 'test',
            'extra': {
                'foo': 'bar'
            },
        }

        preprocess_event(data=data)

        assert mock_process_event.delay.call_count == 1
        assert mock_save_event.delay.call_count == 0

    @mock.patch('sentry.tasks.store.save_event')
    @mock.patch('sentry.tasks.store.process_event')
    def test_move_to_save_event(self, mock_process_event, mock_save_event):
        project = self.create_project()

        data = {
            'project': project.id,
            'platform': 'NOTMATTLANG',
            'message': 'test',
            'extra': {
                'foo': 'bar'
            },
        }

        preprocess_event(data=data)

        assert mock_process_event.delay.call_count == 0
        assert mock_save_event.delay.call_count == 1

    @mock.patch('sentry.tasks.store.save_event')
    @mock.patch('sentry.tasks.store.default_cache')
    def test_process_event_mutate_and_save(self, mock_default_cache, mock_save_event):
        project = self.create_project()

        data = {
            'project': project.id,
            'platform': 'mattlang',
            'message': 'test',
            'extra': {
                'foo': 'bar'
            },
        }

        mock_default_cache.get.return_value = data

        process_event(cache_key='e:1', start_time=1)

        # The event mutated, so make sure we save it back
        mock_default_cache.set.assert_called_once_with(
            'e:1',
            {
                'project': project.id,
                'platform': 'mattlang',
                'message': 'test',
            },
            3600,
        )

        mock_save_event.delay.assert_called_once_with(
            cache_key='e:1', data=None, start_time=1, event_id=None,
        )

    @mock.patch('sentry.tasks.store.save_event')
    @mock.patch('sentry.tasks.store.default_cache')
    def test_process_event_no_mutate_and_save(self, mock_default_cache, mock_save_event):
        project = self.create_project()

        data = {
            'project': project.id,
            'platform': 'noop',
            'message': 'test',
            'extra': {
                'foo': 'bar'
            },
        }

        mock_default_cache.get.return_value = data

        process_event(cache_key='e:1', start_time=1)

        # The event did not mutate, so we shouldn't reset it in cache
        mock_default_cache.set.call_count == 0

        mock_save_event.delay.assert_called_once_with(
            cache_key='e:1', data=None, start_time=1, event_id=None,
        )

    @mock.patch('sentry.tasks.store.save_event')
    @mock.patch('sentry.tasks.store.default_cache')
    def test_process_event_unprocessed(self, mock_default_cache, mock_save_event):
        project = self.create_project()

        data = {
            'project': project.id,
            'platform': 'holdmeclose',
            'message': 'test',
            'extra': {
                'foo': 'bar'
            },
        }

        mock_default_cache.get.return_value = data

        process_event(cache_key='e:1', start_time=1)

        mock_default_cache.set.assert_called_once_with(
            'e:1', {
                'project': project.id,
                'platform': 'holdmeclose',
                'message': 'test',
                'extra': {
                    'foo': 'bar'
                },
                'unprocessed': True,
            }, 3600
        )

        mock_save_event.delay.assert_called_once_with(
            cache_key='e:1', data=None, start_time=1, event_id=None,
        )

    def test_event_saved_signal(self):
        project = self.create_project()

        mock_event_saved = mock.Mock()

        event_saved.connect(mock_event_saved)

        data = {
            'project': project.id,
            'platform': 'NOTMATTLANG',
            'message': 'test',
            'event_id': uuid.uuid4().hex,
            'extra': {
                'foo': 'bar'
            },
        }

        now = time()
        mock_save = mock.Mock()
        with mock.patch.object(EventManager, 'save', mock_save):
            save_event(data=data, start_time=now)
            assert_mock_called_once_with_partial(
                mock_event_saved,
                project_id=project.id,
                organization_id=project.organization_id,
                sender=EventManager,
                signal=event_saved,
            )

    @mock.patch.object(tsdb, 'incr')
    @mock.patch.object(quotas, 'refund')
    def test_hash_discarded_raised(self, mock_refund, mock_incr):
        project = self.create_project()

        data = {
            'project': project.id,
            'platform': 'NOTMATTLANG',
            'message': 'test',
            'event_id': uuid.uuid4().hex,
            'extra': {
                'foo': 'bar'
            },
        }

        now = time()
        mock_save = mock.Mock()
        mock_save.side_effect = HashDiscarded

        # make sure signals are properly triggered
        mock_event_saved = mock.Mock()
        event_saved.connect(mock_event_saved)
        mock_event_discarded = mock.Mock()
        event_discarded.connect(mock_event_discarded)

        with mock.patch.object(EventManager, 'save', mock_save):
            save_event(data=data, start_time=now)
            mock_incr.assert_called_with(
                tsdb.models.project_total_received_discarded,
                project.id,
                timestamp=to_datetime(now),
            )
            assert not mock_event_saved.called

            assert_mock_called_once_with_partial(
                mock_event_discarded,
                project_id=project.id,
                organization_id=project.organization_id,
                sender=EventManager,
                signal=event_discarded,
            )
