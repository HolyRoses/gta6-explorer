"""Interactive terminal browser (curses).

Two panes: archives on the left, details for the selected archive on the right.
Everything is read-only except the explicit ``e`` action, which carves media
carriers into ``./gta6x-extracted``.
"""

from __future__ import annotations

import curses
import os
import sys
import textwrap

from . import media, rpf

KEYS = (
    "  up/down  move      s  scan media      e  extract media\n"
    "  h        headers   r  reload          q  quit"
)


class App:
    def __init__(self, root: str, screen):
        self.root = os.path.abspath(root)
        self.screen = screen
        self.archives: list[str] = []
        self.cursor = 0
        self.top = 0
        self.status = ""
        self.cache: dict[str, list[media.Hit]] = {}
        self.load()

    # -- data -------------------------------------------------------------
    def load(self):
        self.archives = []
        for dirpath, _dirs, files in os.walk(self.root):
            depth = dirpath[len(self.root):].count(os.sep)
            if depth >= 3:
                _dirs[:] = []
            for name in files:
                if name.lower().endswith(".rpf"):
                    self.archives.append(os.path.join(dirpath, name))
        self.archives.sort(key=lambda p: -os.path.getsize(p))
        self.cache.clear()
        self.status = f"{len(self.archives)} archive(s) under {self.root}"

    @property
    def selected(self) -> str | None:
        if not self.archives:
            return None
        return self.archives[min(self.cursor, len(self.archives) - 1)]

    def hits_for(self, path: str, limit_mib: int = 256) -> list[media.Hit]:
        if path not in self.cache:
            self.status = f"scanning {os.path.basename(path)}…"
            self.draw()
            self.cache[path] = list(media.scan_file(path, limit=limit_mib * 1024 * 1024))
        return self.cache[path]

    # -- drawing ----------------------------------------------------------
    def draw(self):
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        left_w = max(34, min(52, width // 3))

        title = " gta6x — GTA VI package explorer "
        self._put(0, 0, title.ljust(width - 1), curses.A_REVERSE)

        visible = height - 4
        if self.cursor < self.top:
            self.top = self.cursor
        if self.cursor >= self.top + visible:
            self.top = self.cursor - visible + 1

        for index in range(self.top, min(len(self.archives), self.top + visible)):
            path = self.archives[index]
            label = f"{os.path.basename(path)[:left_w - 12]:<{left_w - 12}}"
            try:
                size = os.path.getsize(path)
                label += f"{size / 1024 ** 3:7.2f} GiB"
            except OSError:
                label += "     ? GiB"
            attr = curses.A_REVERSE if index == self.cursor else curses.A_NORMAL
            self._put(1 + index - self.top, 0, label[: left_w - 1].ljust(left_w - 1), attr)

        self._put(1, left_w, "│")
        details = self.details()
        for i, line in enumerate(details[: visible]):
            self._put(1 + i, left_w + 2, line[: width - left_w - 3])

        self._put(height - 2, 0, self.status[: width - 1], curses.A_DIM)
        self._put(height - 1, 0, KEYS.splitlines()[0][: width - 1], curses.A_DIM)
        self.screen.refresh()

    def _put(self, y: int, x: int, text: str, attr: int = curses.A_NORMAL):
        try:
            self.screen.addstr(y, x, text, attr)
        except curses.error:
            pass  # bottom-right corner writes are allowed to fail

    def details(self) -> list[str]:
        path = self.selected
        if not path:
            return ["no .rpf archives found under this root"]
        width = max(30, self.screen.getmaxyx()[1] - self.screen.getmaxyx()[1] // 3 - 4)
        lines = [os.path.basename(path), "=" * min(width, len(os.path.basename(path))), ""]
        try:
            header = rpf.read_header(path)
            lines += ["RPF9 header", textwrap.indent(rpf.format_header(header), "  "), ""]
            lines.append(f"  constant 0x40 block : {'yes' if rpf.has_constant_block(path) else 'NO'}")
            lines.append(f"  TOC plausibility    : {rpf.toc_word_plausibility(path)['fraction']:.2%}")
            lines.append(f"  TOC entropy         : {rpf.entropy_at(path, rpf.TOC_OFFSET, 4096):.2f} bits/byte")
            lines.append(f"  likely encrypted    : {'yes' if rpf.looks_encrypted(path) else 'no'}")
        except (OSError, ValueError) as exc:
            lines.append(f"header error: {exc}")
        hits = self.cache.get(path)
        if hits is not None:
            lines += ["", f"plaintext carriers: {len(hits)}"]
            for hit in hits[:12]:
                lines.append("  " + media.describe_hit(hit))
            if len(hits) > 12:
                lines.append(f"  … {len(hits) - 12} more")
        else:
            lines += ["", "press 's' to scan this archive for plaintext media"]
        return lines

    # -- actions ----------------------------------------------------------
    def loop(self):
        curses.curs_set(0)
        while True:
            self.draw()
            key = self.screen.getch()
            if key in (ord("q"), 27):
                return
            if key in (curses.KEY_DOWN, ord("j")):
                if self.archives:
                    self.cursor = min(self.cursor + 1, len(self.archives) - 1)
            elif key in (curses.KEY_UP, ord("k")):
                self.cursor = max(self.cursor - 1, 0)
            elif key in (ord("s"), ord("r")):
                if key == ord("r"):
                    self.load()
                if self.selected:
                    hits = self.hits_for(self.selected)
                    self.status = f"{len(hits)} carrier(s) in {os.path.basename(self.selected)}"
            elif key == ord("h"):
                self.status = "header view is always shown in the right pane"
            elif key == ord("e"):
                self.extract()

    def extract(self):
        path = self.selected
        if not path:
            return
        hits = self.hits_for(path)
        if not hits:
            self.status = "nothing to extract in this archive"
            return
        out = os.path.join(os.getcwd(), "gta6x-extracted")
        self.status = f"writing {len(hits)} file(s) to {out}…"
        self.draw()
        written = media.extract_hits(hits, out, source_root=self.root)
        self.status = f"extracted {len(written)} file(s) to {out}"


def run(root: str = ".") -> int:
    if not sys.stdout.isatty():
        print("tui needs an interactive terminal; use the other subcommands instead",
              file=sys.stderr)
        return 1
    try:
        curses.wrapper(lambda screen: App(root, screen).loop())
    except KeyboardInterrupt:
        pass
    except curses.error as exc:
        print(f"tui unavailable: {exc}", file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------- #
# Catalog browser (SQLite) -- `gta6x tui --db gta6.db`
# --------------------------------------------------------------------------- #

class CatalogApp:
    """Three-pane browser: archives -> assets -> details."""

    def __init__(self, db_path: str, screen):
        from . import catalog as catalog_mod
        self.db_path = db_path
        self.store = catalog_mod.Store(db_path)
        self.screen = screen
        self.counts = self.store.counts()
        self.groups = self.counts["by_archive"]
        self.gi = 0                # archive index
        self.ai = 0                # asset index within archive
        self.page = 0
        self.status = f"{self.counts['total']['assets'] or 0:,} assets"

    def assets(self) -> list[dict]:
        if not self.groups:
            return []
        archive = self.groups[min(self.gi, len(self.groups) - 1)]["archive"]
        return self.store.fetch(limit=500, offset=self.page * 500, archive=archive)

    def draw(self):
        from . import catalog as catalog_mod
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        left = max(28, min(40, w // 4))
        self._put(0, 0, f" gta6x catalog — {self.db_path} ".ljust(w - 1), curses.A_REVERSE)

        visible = h - 3
        for i, g in enumerate(self.groups[:visible]):
            label = f"{g['archive'][:left - 10]:<{left - 10}}{g['count']:>8,}"
            attr = curses.A_REVERSE if i == self.gi else curses.A_NORMAL
            self._put(1 + i, 0, label[:left - 1], attr)

        rows = self.assets()
        self.ai = min(self.ai, max(0, len(rows) - 1))
        mid = left + 1
        for i, a in enumerate(rows[:visible]):
            label = (f"{a['kind'][:12]:<13}{a['size']:>10,}  "
                     f"0x{a['offset']:09x}  {'ok' if a['verified'] else '??'}")
            attr = curses.A_REVERSE if i == self.ai else curses.A_NORMAL
            self._put(1 + i, mid, label[: w - mid - 2], attr)

        if rows:
            a = rows[self.ai]
            info = [
                "asset",
                f"  archive   {a['archive']}",
                f"  offset    0x{a['offset']:09x}",
                f"  kind      {a['kind']}",
                f"  packed    {a['compressed']:,} B",
                f"  inflated  {a['size']:,} B",
                f"  ratio     {a['size'] / max(1, a['compressed']):.1f}x",
                f"  verified  {'yes' if a['verified'] else 'NO'}",
                f"  sha256    {a['sha256'][:32]}",
            ]
            if a.get("xml_root"):
                info.append(f"  xml root  {a['xml_root']}")
            for i, line in enumerate(info[: max(0, visible - 0)]):
                self._put(1 + i, mid, " " * (w - mid - 2))
                self._put(1 + i, mid, line[: w - mid - 2], curses.A_DIM)

        self._put(h - 2, 0, self.status[: w - 1], curses.A_DIM)
        self._put(h - 1, 0, "↑/↓ archives   a/z assets   pgup/pgdn page   e extract   "
                            "r reload   q quit"[: w - 1], curses.A_DIM)
        self.screen.refresh()

    def _put(self, y, x, text, attr=curses.A_NORMAL):
        try:
            self.screen.addstr(y, x, text, attr)
        except curses.error:
            pass

    def loop(self):
        curses.curs_set(0)
        while True:
            self.draw()
            key = self.screen.getch()
            if key in (ord("q"), 27):
                break
            if key == curses.KEY_UP:
                self.gi = max(0, self.gi - 1); self.ai = 0; self.page = 0
            elif key == curses.KEY_DOWN:
                self.gi = min(len(self.groups) - 1, self.gi + 1); self.ai = 0; self.page = 0
            elif key == ord("a"):
                self.ai = min(self.ai + 1, max(0, len(self.assets()) - 1))
            elif key == ord("z"):
                self.ai = max(0, self.ai - 1)
            elif key == curses.KEY_NPAGE:
                self.page += 1; self.ai = 0
            elif key == curses.KEY_PPAGE:
                self.page = max(0, self.page - 1); self.ai = 0
            elif key == ord("r"):
                self.counts = self.store.counts(); self.groups = self.counts["by_archive"]
                self.status = f"{self.counts['total']['assets'] or 0:,} assets"
            elif key == ord("e"):
                self.extract()

    def extract(self):
        import os, zlib
        rows = self.assets()
        if not rows:
            return
        a = rows[self.ai]
        root = os.environ.get("GTA6_ROOT", ".")
        path = None
        for dirpath, _d, files in os.walk(root):
            if a["archive"] in files:
                path = os.path.join(dirpath, a["archive"]); break
        if not path:
            self.status = "set GTA6_ROOT to the package directory to extract"
            return
        with open(path, "rb") as fh:
            fh.seek(a["offset"])
            chunk = fh.read(a["compressed"])
        try:
            blob = zlib.decompress(chunk)
        except zlib.error:
            self.status = "inflate failed"
            return
        suffix = {"xml": ".xml", "text": ".txt", "psin-page": ".psin"}.get(a["kind"], ".bin")
        out = os.path.join("gta6x-extracted", f"{a['archive'].split('.')[0]}_{a['offset']:09x}{suffix}")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as fh:
            fh.write(blob)
        self.status = f"wrote {out} ({len(blob):,} B)"


def run_catalog(db_path: str) -> int:
    if not sys.stdout.isatty():
        print("tui needs an interactive terminal", file=sys.stderr)
        return 1
    try:
        curses.wrapper(lambda screen: CatalogApp(db_path, screen).loop())
    except KeyboardInterrupt:
        pass
    except curses.error as exc:
        print(f"tui unavailable: {exc}", file=sys.stderr)
        return 1
    return 0
