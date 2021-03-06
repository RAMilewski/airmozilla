import os
import sys
import shutil
from cStringIO import StringIO

from nose.tools import ok_, eq_
import mock

from django.core.cache import cache
from django.test import TestCase

from airmozilla.main.models import Event, Template, VidlySubmission, Picture
from airmozilla.manage import videoinfo


class _Response(object):
    def __init__(self, content, status_code=200, headers=None):
        self.content = self.text = content
        self.status_code = status_code
        self.headers = headers or {}

    def iter_content(self, chunk_size=1024):
        increment = 0
        while True:
            chunk = self.content[increment: increment + chunk_size]
            increment += chunk_size
            if not chunk:
                break
            yield chunk


class TestVideoinfo(TestCase):
    fixtures = ['airmozilla/manage/tests/main_testdata.json']
    sample_jpg = 'airmozilla/manage/tests/presenting.jpg'
    sample_jpg2 = 'airmozilla/manage/tests/tucker.jpg'

    def tearDown(self):
        cache.clear()
        super(TestVideoinfo, self).tearDown()

    @mock.patch('airmozilla.manage.vidly.logging')
    @mock.patch('airmozilla.manage.vidly.urllib2')
    @mock.patch('requests.head')
    @mock.patch('subprocess.Popen')
    def test_fetch_duration(self, mock_popen, rhead, p_urllib2, p_logging):

        def mocked_urlopen(request):
            return StringIO("""
            <?xml version="1.0"?>
            <Response>
              <Message>OK</Message>
              <MessageCode>7.4</MessageCode>
              <Success>
                <MediaShortLink>xxx999</MediaShortLink>
                <Token>MXCsxINnVtycv6j02ZVIlS4FcWP</Token>
              </Success>
            </Response>
            """)

        p_urllib2.urlopen = mocked_urlopen

        def mocked_head(url, **options):
            return _Response(
                '',
                200
            )

        rhead.side_effect = mocked_head

        ffmpeged_urls = []

        def mocked_popen(command, **kwargs):
            # print (args, kwargs)
            url = command[2]
            ffmpeged_urls.append(url)

            class Inner:
                def communicate(self):

                    out = ''
                    if 'abc123' in url:
                        err = "bla bla"
                    elif 'xyz123' in url:
                        err = """
            Duration: 00:19:17.47, start: 0.000000, bitrate: 1076 kb/s
                        """
                    else:
                        raise NotImplementedError(url)
                    return out, err

            return Inner()

        mock_popen.side_effect = mocked_popen

        event = Event.objects.get(title='Test event')
        template = Template.objects.create(
            name='Vid.ly Something',
            content="{{ tag }}"
        )
        event.template = template
        event.template_environment = {'tag': 'abc123'}
        event.save()
        assert event.duration is None

        videoinfo.fetch_durations()
        event = Event.objects.get(id=event.id)
        assert event.duration is None

        # need to change to a different tag
        # and make sure it has a VidlySubmission
        VidlySubmission.objects.create(
            event=event,
            url='https://s3.com/asomething.mov',
            tag='xyz123',
            hd=True,
        )
        event.template_environment = {'tag': 'xyz123'}
        event.save()
        videoinfo.fetch_durations()
        event = Event.objects.get(id=event.id)
        eq_(event.duration, 1157)

    @mock.patch('airmozilla.manage.vidly.logging')
    @mock.patch('airmozilla.manage.vidly.urllib2')
    @mock.patch('requests.head')
    @mock.patch('subprocess.Popen')
    def test_fetch_duration_token_protected_public_event(
        self, mock_popen, rhead, p_urllib2, p_logging
    ):

        def mocked_urlopen(request):
            return StringIO("""
            <?xml version="1.0"?>
            <Response>
              <Message>OK</Message>
              <MessageCode>7.4</MessageCode>
              <Success>
                <MediaShortLink>xxx999</MediaShortLink>
                <Token>MXCsxINnVtycv6j02ZVIlS4FcWP</Token>
              </Success>
            </Response>
            """)

        p_urllib2.urlopen = mocked_urlopen

        def mocked_head(url, **options):
            return _Response(
                '',
                200
            )

        rhead.side_effect = mocked_head

        ffmpeged_urls = []

        def mocked_popen(command, **kwargs):
            # print (args, kwargs)
            url = command[2]
            ffmpeged_urls.append(url)

            class Inner:
                def communicate(self):
                    assert 'xyz123' in url
                    out = ''
                    err = """
            Duration: 00:19:17.47, start: 0.000000, bitrate: 1076 kb/s
                    """
                    return out, err

            return Inner()

        mock_popen.side_effect = mocked_popen

        event = Event.objects.get(title='Test event')
        template = Template.objects.create(
            name='Vid.ly Something',
            content="{{ tag }}"
        )
        event.template = template
        event.template_environment = {'tag': 'abc123'}
        event.save()
        assert event.privacy == Event.PRIVACY_PUBLIC
        assert event.duration is None

        # need to change to a different tag
        # and make sure it has a VidlySubmission
        VidlySubmission.objects.create(
            event=event,
            url='https://s3.com/asomething.mov',
            tag='xyz123',
            token_protection=True,  # Note!~
            hd=True,
        )
        event.template_environment = {'tag': 'xyz123'}
        event.save()
        videoinfo.fetch_durations()
        event = Event.objects.get(id=event.id)
        eq_(event.duration, 1157)
        url, = ffmpeged_urls
        ok_('&token=' in url)

    @mock.patch('airmozilla.manage.vidly.logging')
    @mock.patch('airmozilla.manage.vidly.urllib2')
    @mock.patch('requests.head')
    def test_fetch_duration_fail_to_fetch(
        self, rhead, p_urllib2, p_logging
    ):

        def mocked_head(url, **options):
            return _Response(
                'Not Found',
                404
            )

        rhead.side_effect = mocked_head

        event = Event.objects.get(title='Test event')
        template = Template.objects.create(
            name='Vid.ly Something',
            content="{{ tag }}"
        )
        event.template = template
        event.template_environment = {'tag': 'abc123'}
        event.save()
        assert event.duration is None

        buffer = StringIO()
        sys.stdout = buffer
        try:
            videoinfo.fetch_durations()
        finally:
            sys.stdout = sys.__stdout__

        event = Event.objects.get(id=event.id)
        eq_(event.duration, None)  # because it failed
        output = buffer.getvalue()
        ok_('404' in output)

    @mock.patch('airmozilla.manage.vidly.logging')
    @mock.patch('airmozilla.manage.vidly.urllib2')
    @mock.patch('requests.head')
    @mock.patch('requests.get')
    @mock.patch('subprocess.Popen')
    def test_fetch_duration_save_locally(
        self, mock_popen, rget, rhead, p_urllib2, p_logging
    ):

        def mocked_urlopen(request):
            return StringIO("""
            <?xml version="1.0"?>
            <Response>
              <Message>OK</Message>
              <MessageCode>7.4</MessageCode>
              <Success>
                <MediaShortLink>xxx999</MediaShortLink>
                <Token>MXCsxINnVtycv6j02ZVIlS4FcWP</Token>
              </Success>
            </Response>
            """)

        p_urllib2.urlopen = mocked_urlopen

        def mocked_head(url, **options):
            if 'file.mpg' in url:
                return _Response(
                    '',
                    200
                )
            return _Response(
                '',
                302,
                headers={
                    'Location': 'https://otherplace.com/file.mpg'
                }
            )

        rhead.side_effect = mocked_head

        def mocked_get(url, **options):
            return _Response(
                '0' * 100000,
                200,
                headers={
                    'Content-Length': 100000
                }
            )

        rget.side_effect = mocked_get

        ffmpeged_urls = []

        def mocked_popen(command, **kwargs):

            url = command[2]
            ffmpeged_urls.append(url)

            class Inner:
                def communicate(self):

                    out = ''
                    if 'abc123' in url:
                        err = "bla bla"
                    elif 'xyz123' in url:
                        err = """
            Duration: 00:19:17.47, start: 0.000000, bitrate: 1076 kb/s
                        """
                    else:
                        raise NotImplementedError(url)
                    return out, err

            return Inner()

        mock_popen.side_effect = mocked_popen

        event = Event.objects.get(title='Test event')
        template = Template.objects.create(
            name='Vid.ly Something',
            content="{{ tag }}"
        )
        event.template = template
        event.template_environment = {'tag': 'abc123'}
        event.save()
        assert event.duration is None

        videoinfo.fetch_durations(save_locally=True)
        event = Event.objects.get(id=event.id)
        assert event.duration is None

        ffmpeged_url, = ffmpeged_urls
        ok_(ffmpeged_url.endswith('abc123.mp4'))

        # need to change to a different tag
        # and make sure it has a VidlySubmission
        VidlySubmission.objects.create(
            event=event,
            url='https://s3.com/asomething.mov',
            tag='xyz123',
            hd=True,
        )
        event.template_environment = {'tag': 'xyz123'}
        event.save()
        videoinfo.fetch_durations(save_locally=True)
        event = Event.objects.get(id=event.id)
        eq_(event.duration, 1157)

        ffmpeged_url, ffmpeged_url2 = ffmpeged_urls
        ok_(ffmpeged_url.endswith('abc123.mp4'))
        ok_(ffmpeged_url2.endswith('xyz123.mp4'))

    @mock.patch('airmozilla.manage.vidly.logging')
    @mock.patch('airmozilla.manage.vidly.urllib2')
    @mock.patch('requests.head')
    @mock.patch('requests.get')
    @mock.patch('subprocess.Popen')
    def test_fetch_duration_save_locally_some(
        self, mock_popen, rget, rhead, p_urllib2, p_logging
    ):
        """This time we're going to have two events to ponder.
        One is public and one is staff only.
        With passing `save_locally_some` it should do
        `ffmpeg -i http://url...` on the public one and
        `wget https://...; ffmpeg -i /local/file.mpg` on the private one.
        """

        def mocked_urlopen(request):
            return StringIO("""
            <?xml version="1.0"?>
            <Response>
              <Message>OK</Message>
              <MessageCode>7.4</MessageCode>
              <Success>
                <MediaShortLink>xxx999</MediaShortLink>
                <Token>MXCsxINnVtycv6j02ZVIlS4FcWP</Token>
              </Success>
            </Response>
            """)

        p_urllib2.urlopen = mocked_urlopen

        def mocked_head(url, **options):
            # print "HEAD URL", url
            if 'file.mp4' in url:
                return _Response(
                    '',
                    200
                )
            return _Response(
                '',
                302,
                headers={
                    'Location': 'https://otherplace.com/file.mp4'
                }
            )

        rhead.side_effect = mocked_head

        def mocked_get(url, **options):
            # print "GET URL", url
            return _Response(
                '0' * 100000,
                200,
                headers={
                    'Content-Length': 100000
                }
            )

        rget.side_effect = mocked_get

        ffmpeged_urls = []

        def mocked_popen(command, **kwargs):

            url = command[2]
            ffmpeged_urls.append(url)

            class Inner:
                def communicate(self):
                    out = ''
                    if 'otherplace.com/file.mp4' in url:
                        err = """
            Duration: 01:05:00.47, start: 0.000000, bitrate: 1076 kb/s
                        """
                    elif 'xyz123' in url:
                        err = """
            Duration: 00:19:17.47, start: 0.000000, bitrate: 1076 kb/s
                        """
                    else:
                        raise NotImplementedError(url)
                    return out, err

            return Inner()

        mock_popen.side_effect = mocked_popen

        event = Event.objects.get(title='Test event')
        template = Template.objects.create(
            name='Vid.ly Something',
            content="{{ tag }}"
        )
        event.template = template
        event.template_environment = {'tag': 'abc123'}
        assert event.privacy == Event.PRIVACY_PUBLIC
        event.save()

        event2 = Event.objects.create(
            slug='slug2',
            title=event.title,
            start_time=event.start_time,
            placeholder_img=event.placeholder_img,
            privacy=Event.PRIVACY_COMPANY,
            template=template,
            template_environment={'tag': 'xyz123'},
        )

        videoinfo.fetch_durations(save_locally_some=True)
        event = Event.objects.get(id=event.id)
        eq_(event.duration, 3900)

        event2 = Event.objects.get(id=event2.id)
        eq_(event2.duration, 1157)

        ffmpeged_urls.sort()
        ffmpeged_url1, ffmpeged_url2 = ffmpeged_urls
        ok_(ffmpeged_url1.endswith('xyz123.mp4'))
        ok_(ffmpeged_url1.startswith('/'))
        ok_(ffmpeged_url2.endswith('file.mp4'))
        ok_(ffmpeged_url2.startswith('http://'))

    @mock.patch('airmozilla.manage.vidly.logging')
    @mock.patch('airmozilla.manage.vidly.urllib2')
    @mock.patch('requests.head')
    @mock.patch('subprocess.Popen')
    def test_fetch_duration_ogg_videos(
        self, mock_popen, rhead, p_urllib2, p_logging
    ):

        def mocked_head(url, **options):
            return _Response(
                '',
                200
            )

        rhead.side_effect = mocked_head

        ffmpeged_urls = []

        def mocked_popen(command, **kwargs):
            url = command[2]
            assert url.endswith('foo.ogg')
            ffmpeged_urls.append(url)

            class Inner:
                def communicate(self):
                    err = """
                    Duration: 00:10:31.52, start: 0.000000, bitrate: 77 kb/s
                    """
                    out = ''
                    return out, err

            return Inner()

        mock_popen.side_effect = mocked_popen

        event = Event.objects.get(title='Test event')
        template = Template.objects.create(
            name='Ogg Video',
            content='<source src="{{ url }}" type="video/ogg" />'
        )
        event.template = template
        event.template_environment = {'url': 'http://videos.m.org/foo.ogg'}
        event.save()
        assert event.duration is None

        videoinfo.fetch_durations()
        event = Event.objects.get(id=event.id)
        eq_(event.duration, 631)

    @mock.patch('airmozilla.manage.vidly.logging')
    @mock.patch('airmozilla.manage.vidly.urllib2')
    @mock.patch('requests.head')
    @mock.patch('subprocess.Popen')
    def test_fetch_screencapture(self, mock_popen, rhead, p_urllib2, p_log):

        assert Picture.objects.all().count() == 0, Picture.objects.all()

        def mocked_urlopen(request):
            return StringIO("""
            <?xml version="1.0"?>
            <Response>
              <Message>OK</Message>
              <MessageCode>7.4</MessageCode>
              <Success>
                <MediaShortLink>xxx999</MediaShortLink>
                <Token>MXCsxINnVtycv6j02ZVIlS4FcWP</Token>
              </Success>
            </Response>
            """)

        p_urllib2.urlopen = mocked_urlopen

        def mocked_head(url, **options):
            return _Response(
                '',
                200
            )

        rhead.side_effect = mocked_head

        ffmpeged_urls = []

        sample_jpg = self.sample_jpg
        sample_jpg2 = self.sample_jpg2

        def mocked_popen(command, **kwargs):
            # print (args, kwargs)
            url = command[2]
            ffmpeged_urls.append(url)
            destination = command[-1]
            assert os.path.isdir(os.path.dirname(destination))

            class Inner:
                def communicate(self):
                    out = err = ''
                    if 'xyz123' in url:
                        # Let's create two jpeg's in that directory
                        shutil.copyfile(sample_jpg, destination % 1)
                        shutil.copyfile(sample_jpg2, destination % 2)
                    else:
                        raise NotImplementedError(url)
                    return out, err

            return Inner()

        mock_popen.side_effect = mocked_popen

        event = Event.objects.get(title='Test event')
        template = Template.objects.create(
            name='Vid.ly Something',
            content="{{ tag }}"
        )
        event.template = template
        event.save()
        assert event.duration is None

        videoinfo.fetch_screencaptures()
        assert not ffmpeged_urls  # because no event has a duration yet
        event.duration = 1157
        event.save()

        # Make sure it has a HD VidlySubmission
        VidlySubmission.objects.create(
            event=event,
            url='https://s3.com/asomething.mov',
            tag='xyz123',
            hd=True,
        )
        event.template_environment = {'tag': 'xyz123'}
        event.save()
        videoinfo.fetch_screencaptures()
        assert ffmpeged_urls
        eq_(Picture.objects.filter(event=event).count(), 2)

        # When viewed, like it's viewed in the picture gallery and gallery
        # select widget, we want the one called "Screencap 1" to appear
        # before the one called "Screencap 2"
        pictures = Picture.objects.all().order_by('event', '-created')
        notes = [x.notes for x in pictures]
        eq_(notes, ["Screencap 1", "Screencap 2"])

        # Try to do it again and it shouldn't run it again
        # because there are pictures in the gallery already.
        assert len(ffmpeged_urls) == 1
        videoinfo.fetch_screencaptures()
        eq_(len(ffmpeged_urls), 1)
        # and still
        eq_(Picture.objects.filter(event=event).count(), 2)
