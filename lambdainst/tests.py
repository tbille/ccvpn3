from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.core.management import call_command
from django.core import mail
from django.utils.six import StringIO
from constance import config as site_config
from constance.test import override_config

from .forms import SignupForm
from .models import VPNUser, User, random_gift_code, GiftCode, GiftCodeUser
from payments.models import Payment, Subscription


class UserTestMixin:
    def assertRemaining(self, vpnuser, time):
        """ Check that the vpnuser will expire in time (+/- 5 seconds) """
        exp = vpnuser.expiration or timezone.now()
        seconds = (exp - timezone.now() - time).total_seconds()
        self.assertAlmostEqual(seconds, 0, delta=5)


class UserModelTest(TestCase, UserTestMixin):
    def setUp(self):
        User.objects.create_user('aaa')

    def test_add_time(self):
        u = User.objects.get(username='aaa')
        vu = u.vpnuser
        p = timedelta(days=1)

        self.assertFalse(vu.is_paid)

        vu.expiration = timezone.now()
        vu.add_paid_time(p)
        final = vu.expiration

        self.assertRemaining(vu, p)
        self.assertGreater(final, timezone.now())
        self.assertTrue(vu.is_paid)

    def test_add_time_past(self):
        u = User.objects.get(username='aaa')
        vu = u.vpnuser
        p = timedelta(days=1)

        self.assertFalse(vu.is_paid)

        vu.expiration = timezone.now() - timedelta(days=135)
        vu.add_paid_time(p)
        final = vu.expiration

        self.assertRemaining(vu, p)
        self.assertGreater(final, timezone.now())
        self.assertTrue(vu.is_paid)

    def test_add_time_initial(self):
        u = User.objects.get(username='aaa')
        vu = u.vpnuser
        p = timedelta(days=1)

        self.assertFalse(vu.is_paid)

        vu.add_paid_time(p)
        self.assertTrue(vu.is_paid)

    def test_paid_between_subscr_payments(self):
        u = User.objects.get(username='aaa')
        vu = u.vpnuser
        s = Subscription(user=u, backend_id='paypal', status='new')
        s.save()

        self.assertFalse(vu.is_paid)

        s.status = 'active'
        s.save()

        self.assertTrue(vu.is_paid)

    def test_grant_trial(self):
        p = timedelta(days=1)
        u = User.objects.get(username='aaa')
        vu = u.vpnuser

        with override_config(TRIAL_PERIOD_HOURS=24, TRIAL_PERIOD_MAX=2):
            self.assertEqual(vu.remaining_trial_periods, 2)
            self.assertTrue(vu.can_have_trial)
            vu.give_trial_period()
            self.assertRemaining(vu, p)

            self.assertEqual(vu.remaining_trial_periods, 1)
            self.assertTrue(vu.can_have_trial)
            vu.give_trial_period()
            self.assertRemaining(vu, p * 2)

            self.assertEqual(vu.remaining_trial_periods, 0)
            self.assertFalse(vu.can_have_trial)

    def test_trial_refused(self):
        p = timedelta(days=1)
        u = User.objects.get(username='aaa')
        payment = Payment.objects.create(user=u, status='confirmed', amount=300,
                                         time=timedelta(days=30))
        payment.save()

        vu = u.vpnuser

        with override_config(TRIAL_PERIOD_HOURS=24, TRIAL_PERIOD_MAX=2):
            self.assertEqual(vu.remaining_trial_periods, 2)
            self.assertFalse(vu.can_have_trial)


class UserModelReferrerTest(TestCase, UserTestMixin):
    def setUp(self):
        self.referrer = User.objects.create_user('ref')

        self.without_ref = User.objects.create_user('aaaa')

        self.with_ref = User.objects.create_user('bbbb')
        self.with_ref.vpnuser.referrer = self.referrer

        self.payment = Payment.objects.create(
            user=self.with_ref, status='confirmed', amount=300, time=timedelta(days=30))

    def test_no_ref(self):
        self.without_ref.vpnuser.on_payment_confirmed(self.payment)

    def test_ref(self):
        self.with_ref.vpnuser.on_payment_confirmed(self.payment)
        self.assertTrue(self.with_ref.vpnuser.referrer_used)
        self.assertEqual(self.with_ref.vpnuser.referrer, self.referrer)
        self.assertRemaining(self.referrer.vpnuser, timedelta(days=14))


class GCModelTest(TestCase):
    def test_generator(self):
        c = random_gift_code()
        self.assertEqual(len(c), 10)
        self.assertNotEqual(c, random_gift_code())


class SignupViewTest(TestCase):
    def test_form(self):
        response = self.client.get('/account/signup')
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context['form'], SignupForm)

    def test_post(self):
        response = self.client.post('/account/signup', {
            'username': 'test_un', 'password': 'test_pw', 'password2': 'test_pw'})
        self.assertRedirects(response, '/account/')

        user = User.objects.get(username='test_un')
        self.assertTrue(user.check_password('test_pw'))

    def test_post_error(self):
        response = self.client.post('/account/signup', {
            'username': 'test_un', 'password': 'test_pw', 'password2': 'qsdf'})
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context['form'], SignupForm)
        self.assertFormError(response, 'form', 'password',
                             'Passwords are not the same')

    def test_post_referrer(self):
        ref = User.objects.create_user('referrer')

        response = self.client.post('/account/signup?ref=%d' % ref.id, {
            'username': 'test_un', 'password': 'test_pw', 'password2': 'test_pw'})
        self.assertRedirects(response, '/account/')

        user = User.objects.get(username='test_un')
        self.assertTrue(user.check_password('test_pw'))
        self.assertEqual(user.vpnuser.referrer, ref)


class AccountViewsTest(TestCase, UserTestMixin):
    def setUp(self):
        User.objects.create_user('test', None, 'testpw')
        self.client.login(username='test', password='testpw')

    def test_account(self):
        response = self.client.get('/account/')
        self.assertEqual(response.status_code, 200)

    def test_trial_get(self):
        response = self.client.get('/account/trial')
        self.assertRedirects(response, '/account/')

    def test_trial(self):
        p = timedelta(days=1)
        with self.settings(RECAPTCHA_API='TEST'):
            with override_config(TRIAL_PERIOD_HOURS=24, TRIAL_PERIOD_MAX=2):
                good_data = {'g-recaptcha-response': 'TEST-TOKEN'}

                response = self.client.post('/account/trial', good_data)
                self.assertRedirects(response, '/account/')

                user = User.objects.get(username='test')
                self.assertRemaining(user.vpnuser, p)

    def test_trial_fail(self):
        p = timedelta(days=1)
        with self.settings(RECAPTCHA_API='TEST'):
            with override_config(TRIAL_PERIOD_HOURS=24, TRIAL_PERIOD_MAX=2):
                bad_data = {'g-recaptcha-response': 'TOTALLY-NOT-TEST-TOKEN'}

                response = self.client.post('/account/trial', bad_data)
                self.assertRedirects(response, '/account/')

                user = User.objects.get(username='test')
                self.assertRemaining(user.vpnuser, timedelta())

    def test_settings_form(self):
        response = self.client.get('/account/settings')
        self.assertEqual(response.status_code, 200)

    def test_settings_post(self):
        response = self.client.post('/account/settings', {
            'password': 'new_test_pw', 'password2': 'new_test_pw',
            'email': 'new_email@example.com'})
        self.assertEqual(response.status_code, 200)

        user = User.objects.get(username='test')
        self.assertTrue(user.check_password('new_test_pw'))
        self.assertEqual(user.email, 'new_email@example.com')

    def test_settings_post_fail(self):
        response = self.client.post('/account/settings', {
            'password': 'new_test_pw', 'password2': 'new_test_pw_qsdfg',
            'email': 'new_email@example.com'})
        self.assertEqual(response.status_code, 200)

        user = User.objects.get(username='test')
        self.assertFalse(user.check_password('new_test_pw'))
        self.assertEqual(user.email, 'new_email@example.com')

    def test_giftcode_use_single(self):
        gc = GiftCode.objects.create(time=timedelta(days=42), single_use=True)

        response = self.client.post('/account/gift_code', {'code': gc.code})
        self.assertRedirects(response, '/account/')

        user = User.objects.get(username='test')
        self.assertRemaining(user.vpnuser, timedelta(days=42))

        response = self.client.post('/account/gift_code', {'code': gc.code})
        self.assertRedirects(response, '/account/')

        user = User.objects.get(username='test')
        self.assertRemaining(user.vpnuser, timedelta(days=42))  # same expiration

    def test_giftcode_use_free_only(self):
        gc = GiftCode.objects.create(time=timedelta(days=42), free_only=True)

        response = self.client.post('/account/gift_code', {'code': gc.code})
        self.assertRedirects(response, '/account/')

        user = User.objects.get(username='test')
        self.assertRemaining(user.vpnuser, timedelta(days=42))

    def test_giftcode_use_free_only_fail(self):
        gc = GiftCode.objects.create(time=timedelta(days=42), free_only=True)
        user = User.objects.get(username='test')
        user.vpnuser.add_paid_time(timedelta(days=1))
        user.vpnuser.save()

        response = self.client.post('/account/gift_code', {'code': gc.code})
        self.assertRedirects(response, '/account/')

        user = User.objects.get(username='test')
        self.assertRemaining(user.vpnuser, timedelta(days=1))

    def test_giftcode_create_gcu(self):
        gc = GiftCode.objects.create(time=timedelta(days=42))

        response = self.client.post('/account/gift_code', {'code': gc.code})
        self.assertRedirects(response, '/account/')

        user = User.objects.get(username='test')
        gcu = GiftCodeUser.objects.get(user=user, code=gc)

        self.assertRemaining(user.vpnuser, timedelta(days=42))
        self.assertIn(gcu, user.giftcodeuser_set.all())


class CACrtViewTest(TestCase):
    def test_ca_crt(self):
        with self.settings(OPENVPN_CA='test ca'):
            response = self.client.get('/ca.crt')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'application/x-x509-ca-cert')
            self.assertEqual(response.content, b'test ca')


def email_text(body):
    return body.replace('\n', ' ') \
               .replace('\xa0', ' ')  # nbsp


class ExpireNotifyTest(TestCase):
    def setUp(self):
        pass

    def test_notify_first(self):
        out = StringIO()
        u = User.objects.create_user('test_username', 'test@example.com', 'testpw')
        u.vpnuser.add_paid_time(timedelta(days=2))
        u.vpnuser.save()

        call_command('expire_notify', stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['test@example.com'])
        self.assertIn('expire in 1 day', email_text(mail.outbox[0].body))

        u = User.objects.get(username='test_username')
        self.assertAlmostEqual(u.vpnuser.last_expiry_notice, timezone.now(),
                               delta=timedelta(minutes=1))

    def test_notify_second(self):
        out = StringIO()
        u = User.objects.create_user('test_username', 'test@example.com', 'testpw')
        u.vpnuser.last_expiry_notice = timezone.now() - timedelta(days=2)
        u.vpnuser.add_paid_time(timedelta(days=1))
        u.vpnuser.save()

        call_command('expire_notify', stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['test@example.com'])
        self.assertIn('expire in 23 hours, 59 minutes', email_text(mail.outbox[0].body))

        u = User.objects.get(username='test_username')
        self.assertAlmostEqual(u.vpnuser.last_expiry_notice, timezone.now(),
                               delta=timedelta(minutes=1))

    def test_notify_subscription(self):
        out = StringIO()
        u = User.objects.create_user('test_username', 'test@example.com', 'testpw')
        u.vpnuser.add_paid_time(timedelta(days=2))
        u.vpnuser.save()

        s = Subscription(user=u, backend_id='paypal', status='active')
        s.save()

        call_command('expire_notify', stdout=out)
        self.assertEqual(len(mail.outbox), 0)

        u = User.objects.get(username='test_username')
        # FIXME:
        # self.assertNotAlmostEqual(u.vpnuser.last_expiry_notice, timezone.now(),
        #                           delta=timedelta(minutes=1))

    def test_notify_subscription_new(self):
        out = StringIO()
        u = User.objects.create_user('test_username', 'test@example.com', 'testpw')
        u.vpnuser.add_paid_time(timedelta(days=2))
        u.vpnuser.last_expiry_notice = timezone.now() - timedelta(days=5)
        u.vpnuser.save()

        s = Subscription(user=u, backend_id='paypal', status='new')
        s.save()

        call_command('expire_notify', stdout=out)
        self.assertEqual(len(mail.outbox), 1)

        u = User.objects.get(username='test_username')
        # FIXME:
        # self.assertNotAlmostEqual(u.vpnuser.last_expiry_notice, timezone.now(),
        #                           delta=timedelta(minutes=1))


