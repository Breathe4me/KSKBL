"""Application Tk root without implicit HOME/current-directory profile execution."""

import tkinter as tk


class SafeTk(tk.Tk):
    def readprofile(self, baseName, className):
        # Tk.__init__ may call this depending on Python environment isolation flags.
        # The app never needs local .py/.tcl startup profiles.
        return None
