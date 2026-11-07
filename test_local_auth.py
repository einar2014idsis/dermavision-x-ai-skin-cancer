import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
from local_auth import LocalAdmin
from login_ui import require_login


class LocalAuthTests(unittest.TestCase):
    def test_creation_verification_and_no_plaintext_or_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "admin.json"
            account = LocalAdmin(path)
            account.create("admin", "mi contraseña segura")
            original = path.read_bytes()
            self.assertNotIn("mi contraseña segura".encode(), original)
            self.assertTrue(account.verify("admin", "mi contraseña segura"))
            self.assertFalse(account.verify("admin", "contraseña incorrecta"))
            self.assertFalse(account.verify("otra", "mi contraseña segura"))
            with self.assertRaises(FileExistsError):
                account.create("otro", "otra contraseña segura")
            self.assertEqual(path.read_bytes(), original)

    def test_corrupt_account_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "admin.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "No se puede leer"):
                LocalAdmin(path).verify("admin", "clave")
            self.assertEqual(path.read_text(), "{}")

    def test_login_dialog_create_and_wrong_then_correct(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "admin.json"
            root = tk.Tk()
            root.withdraw()
            def submit(fields):
                dialog = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
                entries = [w for frame in dialog.winfo_children() for w in frame.winfo_children() if w.winfo_class() == "TEntry"]
                for entry, value in zip(entries, fields):
                    entry.delete(0, "end")
                    entry.insert(0, value)
                button = next(w for frame in dialog.winfo_children() for w in frame.winfo_children() if w.winfo_class() == "TButton")
                button.invoke()
            try:
                root.after(100, lambda: submit(["admin", "clave segura 123", "clave segura 123"]))
                self.assertTrue(require_login(root, path))
                root.after(100, lambda: submit(["admin", "incorrecta"]))
                root.after(250, lambda: submit(["admin", "clave segura 123"]))
                self.assertTrue(require_login(root, path))
            finally:
                root.destroy()

    def test_cancel_does_not_create_account(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "admin.json"
            root = tk.Tk()
            root.withdraw()
            root.after(100, lambda: next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel)).destroy())
            try:
                self.assertFalse(require_login(root, path))
                self.assertFalse(path.exists())
            finally:
                root.destroy()

    def test_logout_closes_session_and_waits_for_busy_work(self):
        from interfaz import App
        root = tk.Tk()
        root.withdraw()
        app = App(root, autoload_model=False, authenticated=True)
        app.busy = True
        app.logout()
        self.assertFalse(app.logout_requested)
        self.assertFalse(app.closed)
        app.busy = False
        app.logout()
        self.assertTrue(app.logout_requested)
        self.assertTrue(app.closed)
