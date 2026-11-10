import os
from pathlib import Path
from dataclasses import dataclass
from urllib.parse import urlparse


def _load_dotenv(dotenv_path: Path) -> None:
    """Sederhana parser file .env tanpa dependency eksternal."""
    if not dotenv_path.is_file():
        return
    with open(dotenv_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            # Jangan timpa jika sudah ada di environment
            if key not in os.environ:
                os.environ[key] = val


def normalize_base_url(raw_url: str) -> str:
    """
    Normalisasi base URL agar mendukung berbagai format input user:
    - http://127.0.0.1:1234            -> http://127.0.0.1:1234/v1
    - http://127.0.0.1:1234/v1         -> http://127.0.0.1:1234/v1
    - http://127.0.0.1:1234/v1/chat/completions -> http://127.0.0.1:1234/v1
    - https://ai.sumopod.com/v1        -> https://ai.sumopod.com/v1
    """
    url = raw_url.strip().rstrip("/")
    if not url:
        return ""

    for suffix in ("/chat/completions", "/completions", "/models"):
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")

    parsed = urlparse(url)
    if parsed.path in ("", "/"):
        url = f"{url}/v1"

    return url


@dataclass(frozen=True)
class AIConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 30
    debug: bool = False

    @property
    def is_local(self) -> bool:
        """Cek apakah base_url mengarah ke server lokal (seperti LM Studio/Ollama)."""
        parsed = urlparse(self.base_url)
        host = (parsed.hostname or "").lower()
        return host in ("127.0.0.1", "localhost", "0.0.0.0", "::1")


def load_config(env_file: str = ".env") -> AIConfig:
    """Muat konfigurasi aman dari environment variable atau .env."""
    root_dir = Path(__file__).resolve().parent.parent
    dotenv_file = root_dir / env_file
    _load_dotenv(dotenv_file)

    raw_base_url = os.getenv("AI_API_BASE_URL", "")
    base_url = normalize_base_url(raw_base_url)
    api_key = os.getenv("AI_API_KEY", "").strip()
    model = os.getenv("AI_API_MODEL", "default-model").strip()
    timeout = int(os.getenv("AI_TIMEOUT_SECONDS", "30"))
    debug = os.getenv("AI_DEBUG", "false").lower() in ("true", "1", "yes")

    return AIConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout,
        debug=debug,
    )
