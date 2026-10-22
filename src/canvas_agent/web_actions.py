"""Explicit future app dialogs. Constructing this adapter never opens a desktop window."""

from pathlib import Path


class NativeActions:
    def __init__(self, window):
        self._window = window

    def save_file(self, filename, file_types):
        # Only called after the user explicitly selects an export in the app.
        import webview

        chosen = self._window.create_file_dialog(
            webview.FileDialog.SAVE, save_filename=filename, file_types=file_types
        )
        return Path(chosen[0]) if chosen else None

    def open_files(self, file_types):
        import webview

        chosen = self._window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True, file_types=file_types
        )
        return [Path(item) for item in chosen] if chosen else []

    def open_backup(self):
        import webview

        chosen = self._window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=False, file_types=("Agent backup (*.zip)",)
        )
        return Path(chosen[0]) if chosen else None

    def open_folder(self):
        import webview

        chosen = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return Path(chosen[0]) if chosen else None

    def copy_text(self, text):
        # Executed only after an explicit in-app copy action, on the existing STA window.
        from System import Action
        from System.Windows.Forms import Clipboard

        native = self._window.native
        if native is None or native.IsDisposed:
            raise RuntimeError("window_closed")
        native.Invoke(Action(lambda: Clipboard.SetText(text)))
