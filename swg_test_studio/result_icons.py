"""Small native Tk result icons with a transparent background."""
import tkinter as tk


def icons(master):
    result = {}
    for name, points, color in (
        ("Passed", [(3, 7), (4, 8), (5, 9), (6, 8), (7, 7), (8, 6), (9, 5), (10, 4)], "#17763c"),
        ("Failed", [(i, i) for i in range(3, 11)] + [(i, 13 - i) for i in range(3, 11)], "#b42318"),
    ):
        icon = tk.PhotoImage(master=master, width=14, height=14)
        for x, y in points:
            icon.put(color, to=(x, y, x + 2, y + 2))
        result[name] = icon
    points = ((6, 1), (9, 2), (11, 6), (9, 9), (6, 11), (2, 9), (1, 6), (2, 2))
    result["Running"] = []
    for index in range(len(points)):
        icon = tk.PhotoImage(master=master, width=14, height=14)
        for offset in range(4):
            x, y = points[(index - offset) % len(points)]
            icon.put(("#2465a6", "#518ac0", "#8bb1d3", "#c1d4e7")[offset], to=(x, y, x + 2, y + 2))
        result["Running"].append(icon)
    return result
