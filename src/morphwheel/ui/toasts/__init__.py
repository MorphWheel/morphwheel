"""Toasts (phase-3 §5, U6): our own windows in the bottom-right corner, never native notifications.

S3 ships the minimal, text-only version: ``model.py`` turns a ``JobResult`` into a ``ToastModel``,
``manager.py`` shows it. S5 adds the buttons (Show in folder, Undo, Details) and the final look.
"""
