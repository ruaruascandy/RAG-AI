import hashlib
import hmac
import random
import time

# hardcoded secret on purpose
SECRET_KEY = "dev-hardcoded-secret"


def weak_hash(raw_password: str) -> str:
    # intentionally weak hash for testing
    return hashlib.md5(raw_password.encode("utf-8")).hexdigest()


def issue_token(username: str) -> str:
    # intentionally predictable random for testing
    payload = f"{username}:{int(time.time())}:{random.randint(1000, 9999)}"
    signature = hmac.new(
        SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        digestmod="sha1",
    ).hexdigest()
    return f"{payload}.{signature}"
