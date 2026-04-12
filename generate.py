#!/usr/bin/env python3
"""
gh-text: rewrite this repo's git history so the GitHub contribution wall
spells out whatever is in the 'text' file.

Usage:
  python3 generate.py            # full run (rewrites history + force-pushes)
  python3 generate.py --dry-run  # preview only, no git changes
"""
import datetime
import os
import subprocess
import sys

# ---------------------------------------------------------------------------
# 5 × 5 pixel font  ('.' = dark, '#' = lit)
# ---------------------------------------------------------------------------
FONT: dict[str, list[str]] = {
    " ": [".....", ".....", ".....", ".....", "....."],
    "A": [".###.", "#...#", "#####", "#...#", "#...#"],
    "B": ["####.", "#...#", "####.", "#...#", "####."],
    "C": [".###.", "#....", "#....", "#....", ".###."],
    "D": ["####.", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "####.", "#....", "#####"],
    "F": ["#####", "#....", "####.", "#....", "#...."],
    "G": [".###.", "#....", "#.###", "#...#", ".####"],
    "H": ["#...#", "#...#", "#####", "#...#", "#...#"],
    "I": ["#####", "..#..", "..#..", "..#..", "#####"],
    "J": ["..###", "....#", "....#", "#...#", ".###."],
    "K": ["#...#", "#..#.", "###..", "#..#.", "#...#"],
    "L": ["#....", "#....", "#....", "#....", "#####"],
    "M": ["#...#", "##.##", "#.#.#", "#...#", "#...#"],
    "N": ["#...#", "##..#", "#.#.#", "#..##", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "####.", "#....", "#...."],
    "Q": [".###.", "#...#", "#...#", "#..##", ".####"],
    "R": ["####.", "#...#", "####.", "#.#..", "#..##"],
    "S": [".####", "#....", ".###.", "....#", "####."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#.."],
    "U": ["#...#", "#...#", "#...#", "#...#", ".###."],
    "V": ["#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "W": ["#...#", "#...#", "#.#.#", "##.##", "#...#"],
    "X": ["#...#", ".#.#.", "..#..", ".#.#.", "#...#"],
    "Y": ["#...#", ".#.#.", "..#..", "..#..", "..#.."],
    "Z": ["#####", "...#.", "..#..", ".#...", "#####"],
    "0": [".###.", "#..##", "#.#.#", "##..#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "..##.", ".#...", "#####"],
    "3": [".###.", "....#", ".###.", "....#", ".###."],
    "4": ["#...#", "#...#", "#####", "....#", "....#"],
    "5": ["#####", "#....", "####.", "....#", "####."],
    "6": [".###.", "#....", "####.", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", "..#.."],
    "8": [".###.", "#...#", ".###.", "#...#", ".###."],
    "9": [".###.", "#...#", ".####", "....#", ".###."],
    "!": ["..#..", "..#..", "..#..", ".....", "..#.."],
    "?": [".###.", "#...#", "..##.", ".....", "..#.."],
    ".": [".....", ".....", ".....", ".....", "..#.."],
    ",": [".....", ".....", ".....", "..#..", ".#..."],
    "-": [".....", ".....", "#####", ".....", "....."],
    "'": ["..#..", "..#..", ".....", ".....", "....."],
    ":": [".....", "..#..", ".....", "..#..", "....."],
}

COLS      = 53  # GitHub contribution wall width (52 full weeks + 1 partial current week)
SAFE_COLS = 52  # columns available for text (col 52 = current partial week, reserved as buffer)
ROWS      = 7   # rows: Sunday=0 … Saturday=6
FONT_H    = 5   # glyph height in pixels
FONT_W    = 5   # glyph width in pixels
INTENSITY = 20  # commits per lit cell — dominates ambient activity (level 4 = darkest green)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render(text: str) -> list[list[bool]]:
    """Convert text → ROWS × COLS boolean grid (True = lit)."""
    text = text.strip().upper()

    pixel_cols: list[list[bool]] = []
    for i, ch in enumerate(text):
        glyph = FONT.get(ch)
        if glyph is None:
            print(f"[warn] unsupported char {ch!r} – skipped", file=sys.stderr)
            continue
        for cx in range(FONT_W):
            pixel_cols.append([glyph[ry][cx] == "#" for ry in range(FONT_H)])
        if i < len(text) - 1:
            pixel_cols.append([False] * FONT_H)  # 1-col gap between glyphs

    w = len(pixel_cols)
    if w > SAFE_COLS:
        print(f"[warn] text needs {w} cols but safe grid is {SAFE_COLS} wide – truncating", file=sys.stderr)
        pixel_cols = pixel_cols[:SAFE_COLS]
        w = SAFE_COLS

    left = (SAFE_COLS - w) // 2  # center within the 52 safe columns
    top  = (ROWS - FONT_H) // 2  # vertical centering offset (= 1 row)

    grid: list[list[bool]] = [[False] * COLS for _ in range(ROWS)]
    for ci, col_data in enumerate(pixel_cols):
        c = left + ci
        if c >= SAFE_COLS:  # never place lit pixels in the reserved current-week column
            break
        for ri, lit in enumerate(col_data):
            if lit:
                grid[top + ri][c] = True

    return grid


def preview(grid: list[list[bool]]) -> None:
    on, off = "██", "░░"
    print("┌" + "──" * COLS + "┐")
    for row in grid:
        print("│" + "".join(on if c else off for c in row) + "│")
    print("└" + "──" * COLS + "┘")


# ---------------------------------------------------------------------------
# Date mapping
# ---------------------------------------------------------------------------

def dates_from_grid(grid: list[list[bool]]) -> list[datetime.date]:
    """
    Map lit grid cells to calendar dates.

    GitHub layout:
      column  0 = the week starting 52 weeks ago (its Sunday)
      column 52 = the current (partial) week
      row    0  = Sunday, row 6 = Saturday
    """
    today = datetime.date.today()

    # Python weekday: Mon=0 … Sun=6  →  GitHub row: Sun=0 … Sat=6
    gh_row_today = (today.weekday() + 1) % 7
    sunday_now   = today - datetime.timedelta(days=gh_row_today)
    sunday_col0  = sunday_now - datetime.timedelta(weeks=COLS - 1)

    lit: list[datetime.date] = []
    for col in range(COLS):
        for row in range(ROWS):
            if grid[row][col]:
                d = sunday_col0 + datetime.timedelta(weeks=col, days=row)
                if d <= today:   # never commit to the future
                    lit.append(d)
    return sorted(lit)


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

def run(*args: str, extra_env: dict[str, str] | None = None) -> None:
    env = {**os.environ, **(extra_env or {})}
    subprocess.run(["git", *args], check=True, env=env)


def rewrite_history(dates: list[datetime.date]) -> None:
    # Orphan branch: clean slate, no parent
    run("checkout", "--orphan", "_fresh")
    run("add", "-A")
    run("commit", "-m", "chore: setup")

    # INTENSITY empty commits per lit cell, spread across the day for uniqueness
    for d in dates:
        for i in range(INTENSITY):
            ts = d.strftime(f"%Y-%m-%dT12:{i:02d}:00")
            run("commit", "--allow-empty", "-m", ".",
                extra_env={"GIT_AUTHOR_DATE": ts, "GIT_COMMITTER_DATE": ts})

    # Overwrite main with the freshly built history
    run("push", "--force", "origin", "HEAD:main")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    dry_run = "--dry-run" in sys.argv

    import random
    with open("text") as f:
        lines = [l.strip() for l in f if l.strip()]
    text = random.choice(lines)

    print(f"Text  : {text!r}")
    grid  = render(text)
    dates = dates_from_grid(grid)

    preview(grid)
    print(f"Cells : {len(dates)}")

    if dry_run:
        print("Dry-run – no git changes.")
        return

    rewrite_history(dates)
    print("Done.")


if __name__ == "__main__":
    main()
