import time
import requests

from requests_oauthlib import OAuth2Session
from oauthlib.oauth2 import BackendApplicationClient
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ClientCredentialsOAuth2Session(requests.Session):

    def __init__(
        self,
        token_url,
        client_id,
        client_secret,
        refresh_before_expiry_seconds=60,
        **kwargs
    ):
        super(ClientCredentialsOAuth2Session, self).__init__(**kwargs)

        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_before_expiry_seconds = refresh_before_expiry_seconds

        self._oauth2_session = OAuth2Session(
            client=BackendApplicationClient(client_id=client_id)
        )

        self.retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )

        self.adapter = HTTPAdapter(max_retries=self.retry_strategy)

        self._oauth2_session.mount("https://", self.adapter)

        self._oauth2_session.fetch_token(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret
        )

    def request(self, method, url, headers=None, **kwargs):

        if (
            self._oauth2_session.token["expires_at"] - time.time()
            < self.refresh_before_expiry_seconds
        ):
            self._oauth2_session.fetch_token(
                token_url=self.token_url,
                client_id=self.client_id,
                client_secret=self.client_secret
            )

        headers = {} if not headers else headers

        headers["Authorization"] = (
            f"Bearer {self._oauth2_session.token['access_token']}"
        )

        return super(
            ClientCredentialsOAuth2Session,
            self
        ).request(
            method,
            url,
            headers=headers,
            **kwargs
        )


def get_access_token():
    """
    Returns a fresh OAuth access token.
    """

    requests_oauth = ClientCredentialsOAuth2Session(
        token_url="https://c-auth-qa4.copart.com/employee/oauth/token",
        client_id="CLIENT_ID",
        client_secret="CLIENT_SECRET"
    )

    return requests_oauth._oauth2_session.token["access_token"]


if __name__ == "__main__":

    access_token = get_access_token()

    print("\nACCESS TOKEN:\n")
    print(access_token)