"""Cancela tareas de Tkinter antes de destruir sus ventanas."""

import tkinter as tk


def cancel_window_tasks(window):
    """Retira solo callbacks registrados por esta ventana y sus descendientes."""
    owners = {}
    pending = [window]
    while pending:
        widget = pending.pop()
        for command in getattr(widget, "_tclCommands", None) or ():
            owners[command] = widget
        pending.extend(widget.winfo_children())
    for identifier in window.tk.splitlist(window.tk.call("after", "info")):
        try:
            script, _ = window.tk.call("after", "info", identifier)
            command = window.tk.splitlist(script)[0]
            owner = owners.get(command)
            if owner is not None:
                owner.after_cancel(identifier)
        except (tk.TclError, IndexError):
            continue
