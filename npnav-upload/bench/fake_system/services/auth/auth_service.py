"""Auth service: hands out a limited pool of connections."""
from services.common import load_config


class AuthService:
    def __init__(self):
        cfg = load_config()["auth"]
        self.pool_size = cfg["AUTH_POOL_SIZE"]
        self.timeout_s = cfg["AUTH_TIMEOUT_S"]

    def connect(self, n: int) -> list[str]:
        """Open n connections at once. Too few in the pool -> timeout."""
        if n > self.pool_size:
            raise TimeoutError(f"auth pool exhausted after {self.timeout_s}s")
        return [f"conn-{i}" for i in range(n)]
