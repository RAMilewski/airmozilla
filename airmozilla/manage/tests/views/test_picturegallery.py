import json

from nose.tools import eq_, ok_

from django.core.files import File
from django.conf import settings

from funfactory.urlresolvers import reverse

from airmozilla.main.models import Event, Picture
from .base import ManageTestCase


class TestPictureGallery(ManageTestCase):

    main_image = 'airmozilla/manage/tests/firefox.png'
    other_image = 'airmozilla/manage/tests/other_logo.png'

    def test_load_gallery(self):
        url = reverse('manage:picturegallery')
        response = self.client.get(url)
        eq_(response.status_code, 200)

    def test_load_gallery_with_event(self):
        url = reverse('manage:picturegallery')
        event = Event.objects.get(title='Test event')
        response = self.client.get(url, {'event': event.id})
        eq_(response.status_code, 200)
        ok_(event.title in response.content)
        # the link to the upload should carry the event ID
        url = reverse('manage:picture_add') + '?event=%d' % event.id
        ok_(url in response.content)

    def test_picturegallery_data(self):
        url = reverse('manage:picturegallery_data')
        response = self.client.get(url)
        eq_(response.status_code, 200)
        eq_(response['Content-Type'], 'application/json')

        # it's no fun until you add some pictures
        with open(self.main_image) as fp:
            picture = Picture.objects.create(
                file=File(fp),
                notes="Some notes"
            )
            picture2 = Picture.objects.create(
                file=File(fp),
                notes=""
            )
        response = self.client.get(url)
        eq_(response.status_code, 200)
        struct = json.loads(response.content)
        ok_(struct['urls'])
        p1, p2 = struct['pictures']
        # because it's sorted by 'created'
        ok_(p1['width'])
        ok_(p1['height'])
        ok_(p1['size'])
        eq_(p1['events'], [])
        eq_(p2['events'], [])
        assert p1['id'] == picture2.id
        assert p2['id'] == picture.id
        eq_(p2['notes'], 'Some notes')

        # the view is cached but it should be invalidated if you change
        # any picture
        picture.notes = 'Other notes'
        picture.save()
        response = self.client.get(url)
        eq_(response.status_code, 200)
        struct = json.loads(response.content)
        eq_(struct['pictures'][1]['notes'], 'Other notes')
        eq_(struct['stats']['total_pictures'], 2)
        eq_(struct['stats']['event_pictures'], 0)

    def test_picturegallery_data_event_filtering(self):
        url = reverse('manage:picturegallery_data')
        event = Event.objects.get(title='Test event')
        with open(self.main_image) as fp:
            Picture.objects.create(
                file=File(fp),
                notes="Some notes"
            )
            Picture.objects.create(
                file=File(fp),
                notes="Other notes",
                event=event
            )
        response = self.client.get(url)
        eq_(response.status_code, 200)
        struct = json.loads(response.content)
        eq_(len(struct['pictures']), 1)
        p, = struct['pictures']
        eq_(p['notes'], 'Some notes')

        response = self.client.get(url, {'event': event.id})
        eq_(response.status_code, 200)
        struct = json.loads(response.content)
        eq_(len(struct['pictures']), 2)

        eq_(struct['stats']['total_pictures'], 2)
        eq_(struct['stats']['event_pictures'], 1)

    def test_picture_edit(self):
        with open(self.main_image) as fp:
            picture = Picture.objects.create(
                file=File(fp),
                notes="Some notes"
            )

        url = reverse('manage:picture_edit', args=(picture.id,))
        response = self.client.get(url)
        eq_(response.status_code, 200)
        ok_('Some notes' in response.content)

        with open(self.other_image) as fp:
            response = self.client.post(url, {
                'file': fp,
                'notes': 'Other notes'
            })
            eq_(response.status_code, 302)

        picture = Picture.objects.get(id=picture.id)
        eq_(picture.notes, 'Other notes')

    def test_picture_delete(self):
        with open(self.main_image) as fp:
            picture = Picture.objects.create(
                file=File(fp),
                notes="Some notes"
            )

        url = reverse('manage:picture_delete', args=(picture.id,))
        response = self.client.post(url)
        eq_(response.status_code, 200)
        struct = json.loads(response.content)
        eq_(struct, True)

    def test_picture_delete_blocked(self):
        with open(self.main_image) as fp:
            picture = Picture.objects.create(
                file=File(fp),
                notes="Some notes"
            )
        event = Event.objects.get(title='Test event')
        event.placeholder_img = None
        event.picture = picture
        event.save()

        url = reverse('manage:picture_delete', args=(picture.id,))
        response = self.client.post(url)
        eq_(response.status_code, 400)

    def test_picture_delete_updates_cache(self):
        with open(self.main_image) as fp:
            picture = Picture.objects.create(
                file=File(fp),
                notes="Some notes"
            )

        response = self.client.get(reverse('manage:picturegallery'))
        assert response.status_code == 200

        url = reverse('manage:picture_delete', args=(picture.id,))
        response = self.client.post(url)
        assert response.status_code == 200

        response2 = self.client.get(reverse('manage:picturegallery'))
        assert response2.status_code == 200

        ok_(response.content != response2.content)

    def test_picture_add(self):
        url = reverse('manage:picture_add')
        response = self.client.get(url)
        eq_(response.status_code, 200)

        with open(self.other_image) as fp:
            response = self.client.post(url, {
                'file': fp
            })

        picture, = Picture.objects.all()
        assert picture.width
        assert picture.height
        assert picture.size
        eq_(picture.modified_user, self.user)

    def test_redirect_picture_thumbnail(self):
        with open(self.main_image) as fp:
            picture = Picture.objects.create(
                file=File(fp),
                notes="Some notes"
            )

        url = reverse('manage:redirect_picture_thumbnail', args=(picture.id,))
        response = self.client.get(url)
        eq_(response.status_code, 302)
        ok_(settings.MEDIA_URL in response['Location'])

    def test_picture_event_associate(self):
        with open(self.main_image) as fp:
            picture = Picture.objects.create(file=File(fp))

        url = reverse('manage:picture_event_associate', args=(picture.id,))
        response = self.client.post(url)
        eq_(response.status_code, 400)
        response = self.client.post(url, {'event': 9999})
        eq_(response.status_code, 404)

        event = Event.objects.get(title='Test event')
        response = self.client.post(url, {'event': event.id})
        eq_(response.status_code, 200)
        struct = json.loads(response.content)
        eq_(struct, True)
