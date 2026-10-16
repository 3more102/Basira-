import json
import unittest
from datetime import datetime
from unittest.mock import patch

import server


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode()


class TokenIssuerTests(unittest.TestCase):
    def test_uses_one_time_token_and_locks_model(self):
        captured = {}

        def fake_opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse({"name": "ephemeral-test-token", "expireTime": "2030-01-01T00:00:00Z"})

        result = server.mint_ephemeral_token("test-secret", opener=fake_opener)
        payload = json.loads(captured["request"].data)
        self.assertEqual(captured["request"].get_header("X-goog-api-key"), "test-secret")
        self.assertEqual(captured["timeout"], 15)
        self.assertEqual(result["token"], "ephemeral-test-token")
        self.assertEqual(payload["uses"], 1)
        self.assertEqual(payload["liveConnectConstraints"]["model"], server.LIVE_MODEL)
        self.assertEqual(payload["liveConnectConstraints"]["config"]["responseModalities"], ["AUDIO"])
        self.assertEqual(payload["liveConnectConstraints"]["config"]["sessionResumption"], {})
        expiry = datetime.fromisoformat(payload["expireTime"].replace("Z", "+00:00"))
        start_expiry = datetime.fromisoformat(payload["newSessionExpireTime"].replace("Z", "+00:00"))
        self.assertGreater(expiry, start_expiry)

    def test_rejects_invalid_token_response(self):
        with self.assertRaisesRegex(RuntimeError, "invalid token response"):
            server.mint_ephemeral_token("test-secret", opener=lambda *_a, **_k: FakeResponse({}))


if __name__ == "__main__":
    unittest.main()
