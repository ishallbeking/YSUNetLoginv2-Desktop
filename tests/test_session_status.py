import unittest
from unittest.mock import Mock

from ysu_net_login.ruijie_client import RuijieClient


class SessionStatusTests(unittest.TestCase):
    def setUp(self):
        self.client = RuijieClient()
        self.addCleanup(self.client.client.close)
        self.client.redirect_to_portal = Mock(return_value={"sessionId": "real-portal-session"})
        self.client.get_online_user_info = Mock()

    def test_online_status_uses_real_session(self):
        info = {"portalOnlineUserInfo": {"redirectUrl": None, "userName": "test-user"}}
        self.client.get_online_user_info.return_value = info

        self.assertEqual(self.client.check_login_status(), (True, info))
        self.client.get_online_user_info.assert_called_once_with("real-portal-session")

    def test_offline_redirect_is_preserved(self):
        self.client.get_online_user_info.return_value = {
            "portalOnlineUserInfo": {"redirectUrl": "https://auth1.ysu.edu.cn/portal/portal-main"}
        }

        self.assertEqual(
            self.client.check_login_status(),
            (False, "https://auth1.ysu.edu.cn/portal/portal-main"),
        )

    def test_online_login_does_not_repeat_authentication(self):
        self.client.get_online_user_info.return_value = {
            "portalOnlineUserInfo": {"redirectUrl": None, "userName": "test-user"}
        }
        self.client.cas_sso_login = Mock()
        self.client.service_login = Mock()

        self.assertTrue(self.client.login("test-user", "test-password", "中国电信"))
        self.client.cas_sso_login.assert_not_called()
        self.client.service_login.assert_not_called()


if __name__ == "__main__":
    unittest.main()
