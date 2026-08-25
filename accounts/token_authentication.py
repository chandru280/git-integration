# -*- coding: utf-8 -*-

# Django modules
# from django.utils.six import text_type
text_type = str
# from django.utils.translation import ugettext_lazy as _
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.shortcuts import get_object_or_404

# rest_framework modules
from rest_framework import HTTP_HEADER_ENCODING
from rest_framework import exceptions

# local modules
# from library.models import TokenGenerate
# from .models import TokenGenerate  
from rest_framework import generics
# from .forms import LoginForm
# from accounts.forms import MySignupForm as SignUpForm

                        
def get_authorization_header(request):
    """
    Return request's 'Key:' header, as a bytestring.

    Hide some test client ickyness where the header can be unicode.
    """

    if request.query_params.get('Key', None):
        auth = request.query_params['Key']

    else:
        auth = request.META.get('HTTP_KEY', b'')

    # print(auth)
    if isinstance(auth, text_type):
        # Work around django test client oddness
        auth = auth.encode(HTTP_HEADER_ENCODING)
    return auth


class TokenAuthentication():
    """
        Simple token based authentication.
        Key:401f7ac837da42b97f613d789819ff93537bee6a
    """

    # keyword = 'Token'
    model = None

    def get_model(self):
        if self.model is not None:
            return self.model

        from rest_framework.authtoken.models import Token

        return Token

    """
    A custom token model may be used, but must have the following properties.
    * key -- The string identifying the token
    * user -- The user to which the token belongs
    """

    def authenticate(self, request):
        auth = get_authorization_header(request)
        # print("auth",auth)

        try:
            token = auth.decode()

        except UnicodeError:
            msg = _('Invalid token header. Token string should not contain invalid characters.')
            raise exceptions.AuthenticationFailed(msg)

        return self.authenticate_credentials(token)

    def authenticate_credentials(self, key):
        model = self.get_model()
        try:

            token = model.objects.select_related('user').get(key=key)

            # get_obj = get_object_or_404(TokenGenerate ,token_id=token.key,user=token.user)
            # if get_obj.expiry_at >= timezone.now():
            #     pass
            # else:
            #     raise exceptions.AuthenticationFailed(_("Your API Key is Expired, So Renewal Your Account. Contact at 'www.zealbots.com'"))

        except model.DoesNotExist:
            raise exceptions.AuthenticationFailed(_('Invalid token or you are not allow to access'))

        if not token.user.is_active:
            raise exceptions.AuthenticationFailed(_('User inactive or deleted.'))

        return (token.user, token)

    def authenticate_header(self, request):
        return self.keyword


