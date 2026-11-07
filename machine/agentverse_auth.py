"""Use a deployment-only Codespaces secret without changing the normal CLI login."""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time


def access_token():
    token = (os.environ.get("AGENTVERSE_API_KEY") or os.environ.get("AGENTVERSE_API_TOKEN") or "").strip()
    if token:
        if token.startswith("Bearer ") or any(character.isspace() for character in token):
            raise ValueError("Agentverse deployment secret must contain the raw personal token, not a Bearer header")
        return token
    path = Path.home() / ".config/avctl/auth.json"
    try:
        saved = json.loads(path.read_text())
        if saved.get("expires_in", 0) <= time.time():
            raise ValueError("Agentverse login expired; configure AGENTVERSE_API_KEY in Codespaces secrets or renew avctl login")
        return saved["access_token"]
    except (OSError, KeyError, json.JSONDecodeError):
        raise ValueError("No Agentverse deployment credential; configure AGENTVERSE_API_KEY in Codespaces secrets or avctl login") from None


@contextmanager
def cli_environment():
    environment = dict(os.environ)
    if not (environment.get("AGENTVERSE_API_KEY") or environment.get("AGENTVERSE_API_TOKEN") or "").strip():
        yield environment
        return
    token = access_token()
    expires = int(time.time()) + 3600
    try:
        claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "===").decode())
        expiry = claims.get("exp")
        if isinstance(expiry, int) and not isinstance(expiry, bool):
            expires = expiry
    except (ValueError, IndexError, UnicodeError, AttributeError):
        pass
    if expires <= time.time():
        raise ValueError("Agentverse deployment token has expired; replace the secret in Codespaces")
    with TemporaryDirectory(prefix="tooloffer-avctl-auth-") as directory:
        home = Path(directory)
        credentials = home / ".config/avctl"
        credentials.mkdir(parents=True, mode=0o700)
        path = credentials / "auth.json"
        with open(path, "x", opener=lambda filename, flags: os.open(filename, flags, 0o600)) as stream:
            json.dump({"access_token": token, "expires_in": expires, "scope": ""}, stream)
        environment["HOME"] = str(home)
        environment.pop("AGENTVERSE_API_KEY", None)
        environment.pop("AGENTVERSE_API_TOKEN", None)
        yield environment
