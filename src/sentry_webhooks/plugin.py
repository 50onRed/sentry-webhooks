"""
sentry_webhooks.plugin
~~~~~~~~~~~~~~~~~~~~~~

:copyright: (c) 2012 by the Sentry Team, see AUTHORS for more details.
:license: BSD, see LICENSE for more details.
"""
import json
import requests
import logging
from . import VERSION
from django.conf import settings
from django import forms
from django.utils.translation import ugettext_lazy as _

from sentry.plugins import Plugin
from sentry.utils.safe import safe_execute


class WebHooksOptionsForm(forms.Form):
    urls = forms.CharField(
        label=_('Callback URLs'),
        widget=forms.Textarea(attrs={
            'class': 'span6',
            'placeholder': 'https://getsentry.com/callback/url'}),
        help_text=_(
            'Enter callback URLs to POST new events to (one per line).'))

    channel = forms.CharField(
        label=_('Channels'),
        widget=forms.TextInput(attrs={
            'class': 'span6', 'placeholder': '#general'}),
        help_text=_('Enter the channel to send the event.'))

    username = forms.CharField(
        label=_('Username'),
        widget=forms.TextInput(attrs={
            'class': 'span6', 'placeholder': 'webhookbot'}),
        help_text=_('Enter the username to send the message from.'))

    def clean_channel(self):
        value = self.cleaned_data.get('channel')
        if not value.startswith('#'):
            raise forms.ValidationError('Invalid Channel name')
        return value


class WebHooksPlugin(Plugin):
    author = '50onRed'
    author_url = 'https://50onred.com'
    version = VERSION
    description = "Integrates Slack"
    resource_links = [
        ('Bug Tracker', 'https://github.com/50onRed/sentry-webhooks/issues'),
        ('Source', 'https://github.com/50onRed/sentry-webhooks'),
    ]

    slug = 'webhooks'
    title = _('WebHooks')
    conf_title = title
    conf_key = 'webhooks'
    project_conf_form = WebHooksOptionsForm
    timeout = getattr(settings, 'SENTRY_WEBHOOK_TIMEOUT', 3)
    logger = logging.getLogger('sentry.plugins.webhooks')

    def is_configured(self, project, **kwargs):
        self.logger.debug('Web hooks configured')
        return all([self.get_option('urls', project),
                    self.get_option('channel', project),
                    self.get_option('username', project)])

    def get_slack_payload(self, group, event):
        self.logger.debug('creating slack payload')
        payload = {
            'text': 'New Sentry Issue',
            'channel': self.get_option('channel', group.project),
            'username': self.get_option('username', group.project),
            'icon_emoji': ':ghost:',
            'attachments': [
                {
                    'fallback': 'Your code is bad and you should feel bad',
                    'text': 'A new error has been reported',
                    'color': 'danger',
                    'fields': [
                        {
                            'title': group.project.name,
                            'value': event.message
                        },
                        {
                            'title': 'url',
                            'value': group.get_absolute_url()

                        }
                    ]

                }
            ]
        }
        return payload

    def get_webhook_urls(self, project):
        return filter(bool,
                      self.get_option('urls', project).strip().splitlines())

    def send_webhook(self, url, data):
        self.logger.debug('Sending webhook')
        headers = {
            'User-Agent': 'sentry-webhooks/{}'.format(self.version),
            'Content-Type': 'application/json'
        }
        resp = requests.post(url, data=data, headers=headers)
        return resp

    def post_process(self, group, event, is_new, is_sample, **kwargs):
        self.logger.debug('in post_process')
        # if not is_new:
        #     self.logger.debug('this is not new bailing out!')
        #     return

        if not self.is_configured(group.project):
            self.logger.debug('Plugin is not configured returning')
            return

        data = json.dumps(self.get_slack_payload(group, event))
        for url in self.get_webhook_urls(group.project):
            safe_execute(self.send_webhook, url, data)
