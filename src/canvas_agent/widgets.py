"""Small responsive Tk building blocks shared by the five navigation pages."""

import tkinter as tk
from tkinter import ttk


class ScrollPage(ttk.Frame):
    def __init__(self, parent, background):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=background, highlightthickness=0)
        scroll = ttk.Scrollbar(self, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas, padding=(4, 4, 12, 24))
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.resize)
        # Local bindings, never bind_all (would steal wheel events from dialogs).
        self.bind("<Enter>", self.wheel_bind)

    def resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)

    def wheel_bind(self, _event):
        def visit(widget):
            widget.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-int(e.delta / 120), "units"))
            for child in widget.winfo_children():
                visit(child)

        visit(self)


class Card(tk.Canvas):
    def __init__(self, parent, palette, padding=16):
        super().__init__(parent, bg=palette["bg"], highlightthickness=0, height=100)
        self.palette, self.padding = palette, padding
        self.body = ttk.Frame(self, style="Card.TFrame", padding=padding)
        self.window = self.create_window(padding // 2, padding // 2, window=self.body, anchor="nw")
        self.bind("<Configure>", self.resize)
        self.body.bind("<Configure>", self.height_changed)

    def height_changed(self, _event):
        self.configure(height=self.body.winfo_reqheight() + self.padding)

    def resize(self, event):
        self.itemconfigure(self.window, width=max(1, event.width - self.padding))
        self.delete("surface")
        r, x, y = 14, event.width - 1, event.height - 1
        self.create_polygon(
            r,
            0,
            x - r,
            0,
            x,
            0,
            x,
            r,
            x,
            y - r,
            x,
            y,
            x - r,
            y,
            r,
            y,
            0,
            y,
            0,
            y - r,
            0,
            r,
            0,
            0,
            smooth=True,
            fill=self.palette["card"],
            outline=self.palette["border"],
            tags="surface",
        )
        self.tag_lower("surface")


def label(parent, text, style="TLabel", **kwargs):
    widget = ttk.Label(parent, text=text, style=style, justify="left", **kwargs)
    widget.pack(anchor="w", fill="x", pady=(2, 6))
    parent.bind("<Configure>", lambda e: widget.configure(wraplength=max(100, e.width - 28)), add="+")
    return widget


class Flow(ttk.Frame):
    """Wrap action buttons on narrow / high-DPI windows instead of clipping a fixed row."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.buttons = []
        self.bind("<Configure>", self.arrange)

    def add(self, button):
        self.buttons.append(button)
        button.grid(row=len(self.buttons) - 1, column=0, sticky="w", padx=4, pady=6)

    def arrange(self, event):
        x, row, column = 0, 0, 0
        for button in self.buttons:
            width = button.winfo_reqwidth() + 8
            if column and x + width > event.width:
                x, row, column = 0, row + 1, 0
            button.grid(row=row, column=column, sticky="w", padx=4, pady=6)
            x += width
            column += 1
