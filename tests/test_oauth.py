import json
import os
import time
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from requests import Response
from spotipy.oauth2 import SpotifyOauthError

from spotpris2 import __main__ as spotpris2_main


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache_path = f"{self.temp_dir.name}/spotify-token"

        self.dirs_patch = patch.object(
            spotpris2_main,
            "dirs",
            SimpleNamespace(user_cache_dir=self.cache_path),
        )
        self.config_patch = patch.object(
            spotpris2_main,
            "get_config",
            return_value={"client_id": "test-client", "client_secret": "test-secret"},
        )
        self.auth_response_patch = patch.object(
            spotpris2_main.SpotifyOAuth,
            "get_auth_response",
            return_value="test-authorization-code",
        )
        self.post_patch = patch("spotipy.oauth2.requests.Session.post")

        self.dirs_patch.start()
        self.config_patch.start()
        self.auth_response = self.auth_response_patch.start()
        self.post = self.post_patch.start()
        self.addCleanup(self.dirs_patch.stop)
        self.addCleanup(self.config_patch.stop)
        self.addCleanup(self.auth_response_patch.stop)
        self.addCleanup(self.post_patch.stop)

    def test_valid_cached_token_skips_authorization(self):
        cached_token = self._token(expires_at=int(time.time()) + 3600)
        self._write_cache(cached_token)

        oauth = spotpris2_main.authenticate()

        self.assertEqual(spotpris2_main.redirect_uri, oauth.redirect_uri)
        self.auth_response.assert_not_called()
        self.post.assert_not_called()
        self.assertEqual(cached_token, self._read_cache())

    def test_expired_access_token_is_refreshed_and_rotated_token_is_saved(self):
        self._write_cache(self._token(expires_at=int(time.time()) - 60))
        refreshed_token = self._token(
            access_token="refreshed-access-token",
            refresh_token="rotated-refresh-token",
        )
        self.post.return_value = self._response(200, refreshed_token)

        spotpris2_main.authenticate()

        self.auth_response.assert_not_called()
        request_data = self.post.call_args.kwargs["data"]
        self.assertEqual("refresh_token", request_data["grant_type"])
        self.assertEqual("cached-refresh-token", request_data["refresh_token"])
        self.assertEqual("rotated-refresh-token", self._read_cache()["refresh_token"])

    def test_invalid_grant_removes_stale_cache_and_reauthorizes(self):
        self._write_cache(self._token(expires_at=int(time.time()) - 60))
        new_token = self._token(
            access_token="reauthorized-access-token",
            refresh_token="reauthorized-refresh-token",
        )
        self.post.side_effect = [
            self._response(
                400,
                {"error": "invalid_grant", "error_description": "Refresh token revoked"},
            ),
            self._response(200, new_token),
        ]

        def fresh_authorization_code():
            self.assertFalse(os.path.exists(self.cache_path))
            return "test-authorization-code"

        self.auth_response.side_effect = fresh_authorization_code

        with patch("builtins.print") as print_mock:
            spotpris2_main.authenticate()

        print_mock.assert_called_once_with(
            "Spotify authorization has expired or was revoked. "
            "Starting a new authorization flow."
        )
        self.auth_response.assert_called_once_with()
        self.assertEqual("reauthorized-access-token", self._read_cache()["access_token"])
        self.assertEqual("reauthorized-refresh-token", self._read_cache()["refresh_token"])

    def test_runtime_invalid_grant_reauthorizes_existing_oauth_manager(self):
        self._write_cache(self._token(expires_at=int(time.time()) + 3600))
        oauth = spotpris2_main.authenticate()

        self.auth_response.assert_not_called()
        self.post.assert_not_called()

        self._write_cache(self._token(expires_at=int(time.time()) - 60))
        new_token = self._token(
            access_token="reauthorized-access-token",
            refresh_token="reauthorized-refresh-token",
        )
        self.post.side_effect = [
            self._response(
                400,
                {"error": "invalid_grant", "error_description": "Refresh token revoked"},
            ),
            self._response(200, new_token),
        ]

        def fresh_authorization_code():
            self.assertFalse(os.path.exists(self.cache_path))
            return "test-authorization-code"

        self.auth_response.side_effect = fresh_authorization_code

        with patch("builtins.print") as print_mock:
            access_token = oauth.get_access_token(as_dict=False)

        self.assertEqual("reauthorized-access-token", access_token)
        print_mock.assert_called_once_with(
            "Spotify authorization has expired or was revoked. "
            "Starting a new authorization flow."
        )
        self.auth_response.assert_called_once_with()
        self.assertEqual(
            ["refresh_token", "authorization_code"],
            [call.kwargs["data"]["grant_type"] for call in self.post.call_args_list],
        )
        self.assertEqual("reauthorized-access-token", self._read_cache()["access_token"])
        self.assertEqual("reauthorized-refresh-token", self._read_cache()["refresh_token"])

        self.assertEqual("reauthorized-access-token", oauth.get_access_token(as_dict=False))
        self.assertEqual(2, self.post.call_count)
        self.auth_response.assert_called_once_with()

    def test_unrelated_oauth_error_is_raised_and_cache_is_preserved(self):
        cached_token = self._token(expires_at=int(time.time()) - 60)
        self._write_cache(cached_token)
        self.post.return_value = self._response(
            400,
            {"error": "invalid_client", "error_description": "Client authentication failed"},
        )

        with self.assertRaises(SpotifyOauthError) as raised:
            spotpris2_main.authenticate()

        self.assertEqual("invalid_client", raised.exception.error)
        self.auth_response.assert_not_called()
        self.assertEqual(cached_token, self._read_cache())

    def test_new_authorization_token_is_persisted(self):
        new_token = self._token(
            access_token="new-access-token",
            refresh_token="new-refresh-token",
        )
        self.post.return_value = self._response(200, new_token)

        spotpris2_main.authenticate()

        self.auth_response.assert_called_once_with()
        request_data = self.post.call_args.kwargs["data"]
        self.assertEqual("authorization_code", request_data["grant_type"])
        self.assertEqual("test-authorization-code", request_data["code"])
        self.assertEqual("new-access-token", self._read_cache()["access_token"])
        self.assertEqual("new-refresh-token", self._read_cache()["refresh_token"])

    def _token(
        self,
        access_token="cached-access-token",
        refresh_token="cached-refresh-token",
        expires_at=None,
    ):
        if expires_at is None:
            expires_at = int(time.time()) + 3600
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "expires_in": 3600,
            "scope": "user-modify-playback-state user-read-playback-state "
                     "user-read-currently-playing",
            "token_type": "Bearer",
        }

    def _write_cache(self, token_info):
        with open(self.cache_path, "w") as cache_file:
            json.dump(token_info, cache_file)

    def _read_cache(self):
        with open(self.cache_path) as cache_file:
            return json.load(cache_file)

    @staticmethod
    def _response(status_code, payload):
        response = Response()
        response.status_code = status_code
        response.url = "https://accounts.spotify.com/api/token"
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(payload).encode("utf-8")
        return response


if __name__ == "__main__":
    unittest.main()
