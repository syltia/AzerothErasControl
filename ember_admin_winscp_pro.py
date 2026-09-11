import os
from pathlib import Path

from tkinter import messagebox

from ember_admin_winscp import EmberAdmin as _WinSCPApp

try:
    import windnd
except Exception:
    windnd = None


class EmberAdmin(_WinSCPApp):
    """Final WinSCP-like interaction layer for the SFTP file manager."""

    def _install_sftp_enhancements(self):
        super()._install_sftp_enhancements()

        # Force real extended selection on both panes.
        self.local_tree.configure(selectmode="extended")
        self.remote_tree.configure(selectmode="extended")
        self._selection_anchor = {"local": None, "remote": None}

        self._install_selection_bindings(self.local_tree, "local")
        self._install_selection_bindings(self.remote_tree, "remote")

        # Preserve a multi-selection when a drag starts on an already selected row.
        self.local_tree.bind(
            "<ButtonPress-1>",
            lambda e: self._file_drag_press("local", self.local_tree, e),
        )
        self.remote_tree.bind(
            "<ButtonPress-1>",
            lambda e: self._file_drag_press("remote", self.remote_tree, e),
        )

        # Re-install motion bindings because ButtonPress above replaces only that sequence.
        self.local_tree.bind("<B1-Motion>", self._drag_motion, add="+")
        self.remote_tree.bind("<B1-Motion>", self._drag_motion, add="+")

        # Native Windows Explorer -> remote pane drag and drop.
        if os.name == "nt":
            self.after(350, self._install_windows_explorer_drop)

    # ---------- Explicit Windows-style multi selection ----------
    def _install_selection_bindings(self, tree, side):
        tree.bind(
            "<Control-Button-1>",
            lambda e, t=tree, s=side: self._tree_ctrl_click(t, s, e),
        )
        tree.bind(
            "<Shift-Button-1>",
            lambda e, t=tree, s=side: self._tree_shift_click(t, s, e),
        )
        tree.bind(
            "<Control-a>",
            lambda e, t=tree: self._tree_select_all(t),
        )
        tree.bind(
            "<Control-A>",
            lambda e, t=tree: self._tree_select_all(t),
        )

    def _tree_ctrl_click(self, tree, side, event):
        row = tree.identify_row(event.y)
        if not row:
            return "break"
        selected = set(tree.selection())
        if row in selected:
            tree.selection_remove(row)
        else:
            tree.selection_add(row)
        tree.focus(row)
        self._selection_anchor[side] = row
        return "break"

    def _tree_shift_click(self, tree, side, event):
        row = tree.identify_row(event.y)
        if not row:
            return "break"
        children = list(tree.get_children(""))
        if row not in children:
            return "break"

        anchor = self._selection_anchor.get(side)
        if anchor not in children:
            current = tree.focus()
            anchor = current if current in children else row

        a = children.index(anchor)
        b = children.index(row)
        lo, hi = sorted((a, b))
        tree.selection_set(children[lo : hi + 1])
        tree.focus(row)
        self._selection_anchor[side] = anchor
        return "break"

    def _tree_select_all(self, tree):
        children = tree.get_children("")
        if children:
            tree.selection_set(children)
        return "break"

    def _file_drag_press(self, side, tree, event):
        # Ctrl/Shift are handled by the dedicated bindings above.
        if event.state & 0x0005:
            return None

        row = tree.identify_row(event.y)
        selected = tree.selection()

        # Record drag state before ttk's class binding changes the selection.
        self._remember_drag(side, event)

        if row:
            self._selection_anchor[side] = row

        # Important: dragging one of several selected rows must NOT collapse the
        # selection to a single row before the drag starts.
        if row and row in selected and len(selected) > 1:
            tree.focus(row)
            return "break"
        return None

    # ---------- Windows Explorer -> SFTP pane ----------
    def _install_windows_explorer_drop(self):
        if windnd is None:
            self.transfer_status.configure(
                text=(
                    "Explorer drag/drop unavailable: install windnd"
                    if self.language.get() == "EN"
                    else "Glisser-déposer Explorateur indisponible : installe windnd"
                )
            )
            return

        try:
            # Hook the actual remote Treeview so dropping files directly onto the
            # server pane uploads them to the currently displayed remote folder.
            windnd.hook_dropfiles(self.remote_tree, func=self._windows_files_dropped)
        except Exception as exc:
            self.transfer_status.configure(text=f"Windows DnD error: {exc}")

    def _windows_files_dropped(self, filenames):
        paths = []
        for raw in filenames:
            try:
                p = Path(os.fsdecode(raw))
            except Exception:
                continue
            if p.exists():
                paths.append(p)

        if not paths:
            return

        # windnd callback can come from a Windows message callback; marshal the
        # actual UI/SFTP operation back onto Tk's event loop.
        self.after(0, lambda p=paths: self._upload_external_paths(p))

    def _upload_external_paths(self, items):
        if not self.need():
            return
        remote_dir = self.path.get().strip() or "/"
        conflicts = self._collect_upload_conflicts(items, remote_dir)
        if not self._confirm_overwrite(conflicts):
            return

        import threading

        def worker():
            try:
                total = len(items)
                for i, item in enumerate(items, 1):
                    self.q.put(("transfer", f"Upload {i}/{total} : {item.name}"))
                    self._upload_path(item, __import__("posixpath").join(remote_dir, item.name))
                self.q.put(("transfer", f"Upload complete ({total} item(s))"))
                self.q.put(("refresh_remote", None))
            except Exception as exc:
                self.q.put(("transfer", f"Error: {exc}"))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    EmberAdmin().mainloop()
