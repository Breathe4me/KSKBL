"""One layout, two persisted colour palettes; no extra UI dependency."""

from tkinter import ttk

THEMES = {
    "sage": {
        "bg": "#F7F8F5",
        "sidebar": "#EEF2ED",
        "card": "#FFFFFF",
        "primary": "#354B45",
        "accent": "#8EAA9B",
        "border": "#DEE5DE",
    },
    "pink": {
        "bg": "#FFF1F5",
        "sidebar": "#FFF6F8",
        "card": "#FFFFFF",
        "primary": "#A64D70",
        "accent": "#E6A2B6",
        "border": "#F0D9E2",
    },
}


def apply(root, name):
    p = THEMES[name] | {"reminder": "#D6A36A", "warning": "#C77972", "text": "#273834", "muted": "#64736D"}
    root.configure(bg=p["bg"])
    style = ttk.Style(root)
    style.theme_use("clam")
    for key, bg in (("", p["bg"]), ("Card.", p["card"]), ("Side.", p["sidebar"])):
        style.configure(key + "TFrame", background=bg)
        style.configure(key + "TLabel", background=bg, foreground=p["text"], font=("Segoe UI", 10))
    style.configure(
        "Title.TLabel", background=p["bg"], foreground=p["primary"], font=("Segoe UI", 24, "bold")
    )
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"], font=("Segoe UI", 10))
    style.configure(
        "CardTitle.TLabel", background=p["card"], foreground=p["primary"], font=("Segoe UI", 12, "bold")
    )
    style.configure(
        "Count.TLabel", background=p["card"], foreground=p["primary"], font=("Segoe UI", 26, "bold")
    )
    style.configure(
        "TButton",
        font=("Segoe UI", 10),
        padding=(12, 9),
        background=p["card"],
        foreground=p["primary"],
        borderwidth=0,
    )
    style.map("TButton", background=[("active", p["border"]), ("disabled", p["bg"])])
    style.configure("Accent.TButton", background=p["primary"], foreground="white")
    style.map("Accent.TButton", background=[("active", p["primary"])])
    style.configure("Nav.TButton", background=p["sidebar"], anchor="w", padding=(14, 14))
    style.configure("Selected.Nav.TButton", background=p["border"], anchor="w", padding=(14, 14))
    style.configure("TCheckbutton", background=p["bg"], foreground=p["text"], font=("Segoe UI", 10))
    style.configure("Treeview", font=("Segoe UI", 10), rowheight=32, fieldbackground=p["card"])
    return p
