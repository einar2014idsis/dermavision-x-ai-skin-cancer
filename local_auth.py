"""Credencial local de administrador; no cifra los datos del proyecto."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

SCHEMA = "dermavision-local-admin-v1"


class LocalAdmin:
    def __init__(self, path):
        self.path = Path(path)

    def exists(self):
        return self.path.exists()

    @staticmethod
    def _digest(password, salt):
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)

    def create(self, username, password):
        username = username.strip()
        if not 1 <= len(username) <= 80 or any(ord(c) < 32 for c in username):
            raise ValueError("Indica un nombre de usuario válido (máximo 80 caracteres).")
        if not 10 <= len(password) <= 256:
            raise ValueError("La contraseña debe tener entre 10 y 256 caracteres.")
        salt = os.urandom(16)
        data = dict(schema=SCHEMA, username=username,
                    salt=base64.b64encode(salt).decode("ascii"),
                    digest=base64.b64encode(self._digest(password, salt)).decode("ascii"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents overwriting an existing account.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            # A partial file remains visible and requires manual recovery; never overwrite it.
            raise

    def verify(self, username, password):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema") != SCHEMA or not isinstance(data.get("username"), str):
                raise ValueError("Formato de cuenta no reconocido.")
            salt = base64.b64decode(data["salt"], validate=True)
            expected = base64.b64decode(data["digest"], validate=True)
            if len(salt) != 16 or len(expected) != 32:
                raise ValueError("Datos de cuenta incompletos.")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError("No se puede leer la cuenta de administrador. No se ha creado otra cuenta.") from exc
        if len(password) > 256:
            return False
        actual = self._digest(password, salt)
        return hmac.compare_digest(data["username"].encode("utf-8"), username.strip().encode("utf-8")) and hmac.compare_digest(expected, actual)
