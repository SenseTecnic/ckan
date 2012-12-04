import json
import email.mime.text

import ckan.model as model
import ckan.lib.email_notifications as email_notifications
import ckan.lib.base
import ckan.lib.mailer
import ckan.tests.pylons_controller
import ckan.tests.mock_mail_server as mock_mail_server

import paste
import pylons.test


def post(app, action, apikey=None, status=200, **kwargs):
    params = json.dumps(kwargs)
    response = app.post('/api/action/{0}'.format(action), params=params,
            extra_environ={'Authorization': str(apikey)}, status=status)
    if status in (200,):
        assert response.json['success'] is True
        return response.json['result']
    else:
        assert response.json['success'] is False
        return response.json['error']


class TestEmailNotifications(mock_mail_server.SmtpServerHarness,
        ckan.tests.pylons_controller.PylonsTestCase):

    @classmethod
    def setup_class(cls):
        mock_mail_server.SmtpServerHarness.setup_class()
        ckan.tests.pylons_controller.PylonsTestCase.setup_class()
        ckan.tests.CreateTestData.create()
        cls.app = paste.fixture.TestApp(pylons.test.pylonsapp)
        joeadmin = model.User.get('joeadmin')
        cls.joeadmin = {'id': joeadmin.id,
                'apikey': joeadmin.apikey,
                }

    @classmethod
    def teardown_class(self):
        mock_mail_server.SmtpServerHarness.teardown_class()
        ckan.tests.pylons_controller.PylonsTestCase.teardown_class()
        model.repo.rebuild_db()

    def mime_encode(self, msg, recipient_name):
        sender_name = ckan.lib.base.g.site_title
        sender_url = ckan.lib.base.g.site_url
        body = ckan.lib.mailer.add_msg_niceties(
                recipient_name, msg, sender_name, sender_url)
        encoded_body = email.mime.text.MIMEText(
                body.encode('utf-8'), 'plain', 'utf-8').get_payload().strip()
        return encoded_body

    def check_email(self, email, address, name, subject, body):
        assert email[1] == 'info@test.ckan.net'
        assert email[2] == [address]
        encoded_subject = 'Subject: =?utf-8?q?{subject}'.format(
                subject=subject.replace(' ', '_'))
        assert encoded_subject in email[3]
        encoded_body = self.mime_encode(body, name)
        assert encoded_body in email[3]
        # TODO: Check that body contains link to dashboard and email prefs.

    def test_01_no_email_notifications_after_registration(self):
        '''A new user who isn't following anything shouldn't get any emails.'''

        # Clear any emails already sent due to CreateTestData.create().
        email_notifications.get_and_send_notifications_for_all_users()
        self.clear_smtp_messages()

        # Register a new user.
        sara = post(self.app, 'user_create', apikey=self.joeadmin['apikey'],
                name='sara', email='sara@sararollins.com', password='sara',
                fullname='Sara Rollins', email_notifications=True)

        # Save the user for later tests to use.
        TestEmailNotifications.sara = sara

        # No notification emails should be sent to anyone at this point.
        email_notifications.get_and_send_notifications_for_all_users()
        assert len(self.get_smtp_messages()) == 0

    def test_02_one_new_activity(self):
        '''A user with one new activity should get one email.'''

        # Make Sara follow something, have to do this to get new activity.
        post(self.app, 'follow_dataset', apikey=self.sara['apikey'],
                id='warandpeace')

        # Make someone else update the dataset Sara's following, this should
        # create a new activity on Sara's dashboard.
        post(self.app, 'package_update', apikey=self.joeadmin['apikey'],
                name='warandpeace', notes='updated')

        # Run the email notifier job, it should send one notification email
        # to Sara.
        email_notifications.get_and_send_notifications_for_all_users()
        assert len(self.get_smtp_messages()) == 1
        email = self.get_smtp_messages()[0]
        self.check_email(email, 'sara@sararollins.com', 'Sara Rollins',
                'You have new activity', 'You have new activity')

        self.clear_smtp_messages()

    def test_03_multiple_new_activities(self):
        '''Test that a user with multiple new activities gets just one email.

        '''
        # Make someone else update the dataset Sara's following three times,
        # this should create three new activities on Sara's dashboard.
        for i in range(1, 4):
            post(self.app, 'package_update', apikey=self.joeadmin['apikey'],
                    name='warandpeace', notes='updated {0} times'.format(i))

        # Run the email notifier job, it should send one notification email
        # to Sara.
        email_notifications.get_and_send_notifications_for_all_users()
        assert len(self.get_smtp_messages()) == 1
        email = self.get_smtp_messages()[0]
        self.check_email(email, 'sara@sararollins.com', 'Sara Rollins',
                'You have new activity', 'You have new activity')

        self.clear_smtp_messages()

    def test_04_no_repeat_email_notifications(self):
        '''Test that a user does not get a second email notification for the
        same new activity.

        '''
        # TODO: Assert that Sara has some new activities and has already had
        # an email about them.
        email_notifications.get_and_send_notifications_for_all_users()
        assert len(self.get_smtp_messages()) == 0

    def test_05_no_email_if_seen_on_dashboard(self):
        '''Test that emails are not sent for activities already seen on dash.

        If a user gets some new activities in her dashboard activity stream,
        then views her dashboard activity stream, then she should not got any
        email notifications about these new activities.

        '''
        # Make someone else update the dataset Sara's following, this should
        # create a new activity on Sara's dashboard.
        post(self.app, 'package_update', apikey=self.joeadmin['apikey'],
                name='warandpeace',
                notes='updated by test_05_no_email_if_seen_on_dashboard')

        # At this point Sara should have a new activity on her dashboard.
        num_new_activities = post(self.app, 'dashboard_new_activities_count',
                apikey=self.sara['apikey'])
        assert num_new_activities > 0, num_new_activities

        # View Sara's dashboard.
        post(self.app, 'dashboard_mark_activities_old',
                apikey=self.sara['apikey'])

        # No email should be sent.
        email_notifications.get_and_send_notifications_for_all_users()
        assert len(self.get_smtp_messages()) == 0

    def test_05_no_email_notifications_when_disabled_site_wide(self):
        '''Users should not get email notifications when the feature is
        disabled site-wide by a sysadmin.'''

    def test_06_enable_email_notifications_sitewide(self):
        '''When a sysadamin enables email notifications site wide, users
        should not get emails for new activities from before email
        notifications were enabled.

        '''


# It's just easier to separate these tests into their own test class.
class TestEmailNotificationsUserPreference(mock_mail_server.SmtpServerHarness,
        ckan.tests.pylons_controller.PylonsTestCase):
    '''Tests for the email notifications (on/off) user preference.'''

    @classmethod
    def setup_class(cls):
        mock_mail_server.SmtpServerHarness.setup_class()
        ckan.tests.pylons_controller.PylonsTestCase.setup_class()
        ckan.tests.CreateTestData.create()
        cls.app = paste.fixture.TestApp(pylons.test.pylonsapp)
        joeadmin = model.User.get('joeadmin')
        cls.joeadmin = {'id': joeadmin.id,
                'apikey': joeadmin.apikey,
                }

    @classmethod
    def teardown_class(self):
        mock_mail_server.SmtpServerHarness.teardown_class()
        ckan.tests.pylons_controller.PylonsTestCase.teardown_class()
        model.repo.rebuild_db()

    def test_00_email_notifications_disabled_by_default(self):
        '''Email notifications should be disabled for new users.'''

        # Register a new user.
        sara = post(self.app, 'user_create', apikey=self.joeadmin['apikey'],
                name='sara', email='sara@sararollins.com', password='sara',
                fullname='Sara Rollins')

        # Save the user for later tests to use.
        TestEmailNotificationsUserPreference.sara = sara

        # Email notifications should be disabled for the new user.
        assert sara['email_notifications'] is False
        assert post(self.app, 'user_show', apikey=self.sara['apikey'],
                id='sara')['email_notifications'] is False

    def test_01_no_email_notifications_when_disabled(self):
        '''Users with email notifications turned off should not get emails.'''

        # First make Sara follow something so she gets some new activity in
        # her dashboard activity stream.
        post(self.app, 'follow_dataset', apikey=self.sara['apikey'],
                id='warandpeace')

        # Now make someone else update the dataset so Sara gets a new activity.
        post(self.app, 'package_update', apikey=self.joeadmin['apikey'],
                id='warandpeace', notes='updated')

        # Test that Sara has a new activity, just to make sure.
        assert post(self.app, 'dashboard_new_activities_count',
                apikey=self.sara['apikey']) > 0

        # No email notifications should be sent to Sara.
        email_notifications.get_and_send_notifications_for_all_users()
        assert len(self.get_smtp_messages()) == 0

    def test_02_enable_email_notifications(self):
        '''Users should be able to turn email notifications on.'''

        # Mark all Sara's new activities as old, just to get a fresh start.
        post(self.app, 'dashboard_mark_activities_old',
                apikey=self.sara['apikey'])
        assert post(self.app, 'dashboard_new_activities_count',
                apikey=self.sara['apikey']) == 0

        # Update the followed dataset a few times so Sara gets a few new
        # activities.
        for i in range(1, 4):
            post(self.app, 'package_update', apikey=self.joeadmin['apikey'],
                    id='warandpeace', notes='updated {0} times'.format(i))

        # Now Sara should have new activities.
        assert post(self.app, 'dashboard_new_activities_count',
                apikey=self.sara['apikey']) == 3

        # Run the email notifier job.
        email_notifications.get_and_send_notifications_for_all_users()
        assert len(self.get_smtp_messages()) == 0

        # Enable email notifications for Sara.
        self.sara['email_notifications'] = True
        post(self.app, 'user_update', **self.sara)

        email_notifications.get_and_send_notifications_for_all_users()
        assert len(self.get_smtp_messages()) == 0, ("After a user enables "
            "email notifications she should _not_ get emails about activities "
            "that happened before she enabled them, even if those activities "
            "are still marked as 'new' on her dashboard.")

        # Update the package to generate another new activity.
        post(self.app, 'package_update', apikey=self.joeadmin['apikey'],
                id='warandpeace', notes='updated yet again')

        # Check that Sara has a new activity.
        assert post(self.app, 'dashboard_new_activities_count',
                apikey=self.sara['apikey']) == 4

        # Run the email notifier job, this time Sara should get one email.
        email_notifications.get_and_send_notifications_for_all_users()
        assert len(self.get_smtp_messages()) == 1
        self.clear_smtp_messages()

    def test_03_disable_email_notifications(self):
        '''Users should be able to turn email notifications off.'''

        self.sara['email_notifications'] = False
        post(self.app, 'user_update', **self.sara)

        post(self.app, 'package_update', apikey=self.joeadmin['apikey'],
                id='warandpeace', notes='updated yet again')

        assert post(self.app, 'dashboard_new_activities_count',
                apikey=self.sara['apikey']) > 0

        email_notifications.get_and_send_notifications_for_all_users()
        assert len(self.get_smtp_messages()) == 0