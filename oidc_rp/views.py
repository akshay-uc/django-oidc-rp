"""
    OpenID Connect relying party (RP) views
    =======================================

    This modules defines views allowing to start the authorization and authentication process in
    order to authenticate a specific user. The most important views are: the "login" allowing to
    authenticate the users using the OP and get an authorizartion code, the callback view allowing
    to retrieve a valid token for the considered user and the logout view.

"""

from django.contrib import auth
from django.core.exceptions import SuspiciousOperation
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.utils.crypto import get_random_string
from django.utils.http import urlencode
from django.views.generic import View

from .conf import settings as oidc_rp_settings


class OIDCAuthRequestView(View):
    """ Allows to start the authorization flow in order to authenticate the end-user.

    This view acts as the main endpoint to trigger the authentication process involving the OIDC
    provider (OP). It prepares an authentication request that will be sent to the authorization
    server in order to authenticate the end-user.

    """

    http_method_names = ['get', ]

    def get(self, request):
        """ Processes GET requests. """
        # Defines common parameters used to bootstrap the authentication request.
        state = get_random_string(oidc_rp_settings.STATE_LENGTH)
        authentication_request_params = {
            'scope': oidc_rp_settings.SCOPES,
            'response_type': 'code',
            'client_id': oidc_rp_settings.CLIENT_ID,
            'redirect_uri': request.build_absolute_uri(reverse('oidc_auth_callback')),
            'state': state,
        }

        # Nonces should be used! In that case the generated nonce is stored both in the
        # authentication request parameters and in the user's session.
        if oidc_rp_settings.USE_NONCE:
            nonce = get_random_string(oidc_rp_settings.NONCE_LENGTH)
            authentication_request_params.update({'nonce': nonce, })
            request.session['oidc_auth_nonce'] = nonce

        # The generated state value must be stored in the user's session for further use.
        request.session['oidc_auth_state'] = state

        # Redirects the user to authorization endpoint.
        query = urlencode(authentication_request_params)
        redirect_url = '{url}?{query}'.format(
            url=oidc_rp_settings.PROVIDER_AUTHORIZATION_ENDPOINT, query=query)
        return HttpResponseRedirect(redirect_url)


class OIDCAuthCallbackView(View):
    """ Allows to complete the authentication process.

    This view acts as the main endpoint to complete the authentication process involving the OIDC
    provider (OP). It checks the request sent by the OIDC provider in order to determine whether the
    considered was successfully authentified or not and authenticates the user at the current
    application level if applicable.

    """

    http_method_names = ['get', ]

    def get(self, request):
        """ Processes GET requests. """
        callback_params = request.GET

        # Retrieve the state value that was previously generated. No state means that we cannot
        # authenticate the user (so a failure should be returned).
        state = request.session.get('oidc_auth_state', None)

        # Retrieve the nonce that was previously generated and remove it from the current session.
        # If no nonce is available (while the USE_NONCE setting is set to True) this means that the
        # authentication cannot be performed and so we have redirect the user to a failure URL.
        nonce = request.session.pop('oidc_auth_nonce', None)

        # NOTE: a redirect to the failure page should be return if some required GET parameters are
        # missing or if no state can be retrieved from the current session.

        if ((nonce and oidc_rp_settings.USE_NONCE) or not oidc_rp_settings.USE_NONCE) and \
                ('code' in callback_params and 'state' in callback_params) and state:
            # Ensures that the passed state values is the same as the one that was previously
            # generated when forging the authorization request. This is necessary to mitigate
            # Cross-Site Request Forgery (CSRF, XSRF).
            if callback_params['state'] != state:
                raise SuspiciousOperation('Invalid OpenID Connect callback state value')

            # Authenticates the end-user.
            user = auth.authenticate(nonce=nonce, request=request)
            if user and user.is_active:
                auth.login(self.request, user)
                return HttpResponseRedirect(oidc_rp_settings.AUTHENTICATION_REDIRECT_URI)

        return HttpResponseRedirect(oidc_rp_settings.AUTHENTICATION_FAILURE_REDIRECT_URI)


class OIDCEndSessionView(View):
    """ Allows to end the session of any user authenticated using OpenID Connect.

    This view acts as the main endpoint to end the session of an end-user that was authenticated
    using the OIDC provider (OP). It calls the "end-session" endpoint provided by the provider if
    applicable.

    """
