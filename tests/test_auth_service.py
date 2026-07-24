import tempfile
import unittest
from pathlib import Path

from tme3bot.domain.models import Actor, DomainError
from tme3bot.infrastructure.auth import BotAuthService, SqliteAuthRepository


class AuthServiceTests(unittest.TestCase):
    def make_service(self, path: Path) -> BotAuthService:
        def actor(user_id: int) -> Actor:
            if user_id != 42:
                raise DomainError("UNAUTHORIZED_ACTOR", "denied", status_code=403)
            return Actor(42, "default")

        return BotAuthService(
            SqliteAuthRepository(path),
            actor,
            "x" * 48,
            "my_bot",
            access_minutes=15,
            refresh_days=30,
            challenge_minutes=5,
        )

    def test_bot_approval_issues_and_rotates_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = self.make_service(Path(temp_dir) / "auth.db")
            challenge = service.create_challenge()
            code = challenge["verification_uri"].split("login_", 1)[1]

            self.assertIsNone(
                service.exchange_challenge(
                    challenge["challenge_id"], challenge["poll_token"]
                )
            )
            service.approve(code, 42)
            pair = service.exchange_challenge(
                challenge["challenge_id"], challenge["poll_token"]
            )
            claims = service.decode_access(pair.access_token)
            self.assertEqual(claims["telegram_user_id"], 42)
            rotated = service.refresh(pair.refresh_token)
            self.assertNotEqual(rotated.refresh_token, pair.refresh_token)
            with self.assertRaises(DomainError):
                service.refresh(pair.refresh_token)

    def test_new_login_revokes_previous_web_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = self.make_service(Path(temp_dir) / "auth.db")

            def login():
                challenge = service.create_challenge()
                code = challenge["verification_uri"].split("login_", 1)[1]
                service.approve(code, 42)
                return service.exchange_challenge(
                    challenge["challenge_id"], challenge["poll_token"]
                )

            first = login()
            second = login()
            with self.assertRaises(DomainError):
                service.refresh(first.refresh_token)
            with self.assertRaises(DomainError) as revoked:
                service.decode_access(first.access_token)
            self.assertEqual(revoked.exception.code, "SESSION_REVOKED")
            self.assertEqual(
                service.decode_access(second.access_token)["telegram_user_id"],
                42,
            )
            self.assertIsNotNone(service.refresh(second.refresh_token))

    def test_service_exchange_still_validates_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = self.make_service(Path(temp_dir) / "auth.db")
            with self.assertRaises(DomainError):
                service.service_exchange(99)


if __name__ == "__main__":
    unittest.main()
