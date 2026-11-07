"""Acceso local antes de abrir las ventanas y el historial."""
import tkinter as tk
from tkinter import ttk
from local_auth import LocalAdmin


def require_login(root, credential_path):
    account = LocalAdmin(credential_path)
    setup = not account.exists()
    result = {"authenticated": False, "failures": 0}
    dialog = tk.Toplevel(root)
    dialog.title("DermaVision-X · Administrador")
    dialog.geometry("540x390")
    dialog.minsize(470, 370)
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
    outer = ttk.Frame(dialog, padding=24)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="Crear administrador" if setup else "Acceso de administrador", font=("Segoe UI", 16, "bold")).pack(anchor="w", pady=(0, 8))
    ttk.Label(outer, text=("Primera ejecución: crea una cuenta local. Guarda tu contraseña en un lugar seguro."
                          if setup else "Ingresa tus datos para abrir DermaVision-X."), wraplength=460).pack(anchor="w", pady=(0, 12))
    ttk.Label(outer, text="Usuario").pack(anchor="w")
    user = ttk.Entry(outer)
    user.pack(fill="x", pady=(2, 8))
    ttk.Label(outer, text="Contraseña" + (" (mínimo 10 caracteres)" if setup else "")).pack(anchor="w")
    password = ttk.Entry(outer, show="•")
    password.pack(fill="x", pady=(2, 8))
    confirmation = None
    if setup:
        ttk.Label(outer, text="Confirmar contraseña").pack(anchor="w")
        confirmation = ttk.Entry(outer, show="•")
        confirmation.pack(fill="x", pady=(2, 8))
    message = ttk.Label(outer, text="", foreground="#a33b35", wraplength=450)
    message.pack(anchor="w")
    def submit(event=None):
        if str(button.cget("state")) == "disabled":
            return
        try:
            if setup:
                if password.get() != confirmation.get():
                    raise ValueError("Las contraseñas no coinciden.")
                account.create(user.get(), password.get())
            elif not account.verify(user.get(), password.get()):
                result["failures"] += 1
                message.configure(text="Usuario o contraseña incorrectos.")
                password.delete(0, "end")
                if result["failures"] >= 5:
                    button.configure(state="disabled")
                    message.configure(text="Demasiados intentos. Espera 30 segundos.")
                    dialog.after(30000, lambda: button.configure(state="normal"))
                    result["failures"] = 0
                return
            result["authenticated"] = True
            dialog.destroy()
        except (ValueError, OSError) as exc:
            message.configure(text=str(exc))
    button = ttk.Button(outer, text="Crear cuenta y entrar" if setup else "Entrar", command=submit)
    button.pack(anchor="e", pady=8)
    dialog.bind("<Return>", submit)
    user.focus_set()
    dialog.grab_set()
    root.wait_window(dialog)
    return result["authenticated"]
