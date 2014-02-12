"""
sentry_webhooks.plugin
~~~~~~~~~~~~~~~~~~~~~~

:copyright: (c) 2012 by the Sentry Team, see AUTHORS for more details.
:license: BSD, see LICENSE for more details.
"""
import json

import logging
import ipaddr
import sentry_webhooks
import socket
import urllib2

from django.conf import settings
from django import forms
from django.utils.translation import ugettext_lazy as _
from urlparse import urlparse

from sentry.plugins import Plugin
from sentry.utils.safe import safe_execute


DISALLOWED_IPS = map(
    ipaddr.IPNetwork,
    getattr(settings, 'SENTRY_WEBHOOK_DISALLOWED_IPS', (
        '10.0.0.0/8',
        '172.16.0.0/12',
        '192.168.0.0/16',
    )),
)


def is_valid_url(url):
    parsed = urlparse(url)
    ip_network = ipaddr.IPNetwork(socket.gethostbyname(parsed.hostname))
    for addr in DISALLOWED_IPS:
        if ip_network in addr:
            return False
    return True


class NoRedirection(urllib2.HTTPErrorProcessor):
    def http_response(self, request, response):
        return response

    https_response = http_response


class WebHooksOptionsForm(forms.Form):
    urls = forms.CharField(
        label=_('Callback URLs'),
        widget=forms.Textarea(attrs={
            'class': 'span6', 'placeholder': 'https://getsentry.com/callback/url'}),
        help_text=_('Enter callback URLs to POST new events to (one per line).'))

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

    def clean_url(self):
        value = self.cleaned_data.get('url')
        if not is_valid_url(value):
                raise forms.ValidationError('Invalid hostname')
        return value


class WebHooksPlugin(Plugin):
    author = 'Sentry Team'
    author_url = 'https://github.com/getsentry/sentry'
    version = sentry_webhooks.VERSION
    description = "Integrates web hooks."
    resource_links = [
        ('Bug Tracker', 'https://github.com/getsentry/sentry-webhooks/issues'),
        ('Source', 'https://github.com/getsentry/sentry-webhooks'),
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
        return bool(self.get_option('urls', project))

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

    def get_group_data(self, group, event):
        data = {
            'id': str(group.id),
            'checksum': group.checksum,
            'project': group.project.slug,
            'project_name': group.project.name,
            'logger': group.logger,
            'level': group.get_level_display(),
            'culprit': group.culprit,
            'message': event.message,
            'url': group.get_absolute_url(),
        }
        data['event'] = dict(event.data or {})
        return data

    def get_webhook_urls(self, project):
        return filter(bool, self.get_option('urls', project).strip().splitlines())

    def send_webhook(self, url, data):
        self.logger.debug('Sending webhook')
        req = urllib2.Request(url, data)
        req.add_header('User-Agent', 'sentry-webhooks/%s' % self.version)
        req.add_header('Content-Type', 'application/json')
        opener = urllib2.build_opener(NoRedirection)
        resp = opener.open(req, timeout=self.timeout)
        return resp

    def post_process(self, group, event, is_new, is_sample, **kwargs):
        self.logger.debug('in post_process')
        if not is_new:
            self.logger.debug('this is not new bailing out!')
            return

        if not self.is_configured(group.project):
            self.logger.debug('Plugin is not configured returning')
            return

        data = json.dumps(self.get_slack_payload(group, event))
        for url in self.get_webhook_urls(group.project):
            if not is_valid_url(url):
                self.logger.error('URL is not valid: %s', url)
                continue

            safe_execute(self.send_webhook, url, data)
