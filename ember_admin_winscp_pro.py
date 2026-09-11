import os
from pathlib import Path

from ember_admin_winscp import EmberAdmin as _WinSCPApp

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = None
    TkinterDnD = None


class EmberAdmin(_WinSCPApp):
    """WinSCP-like interaction layer with safer Windows drag/drop."""

    def _install_sftp_enhancements(self):
        super()._install_sftp_enhancements()

        self.local_tree.configure(selectmode="extended")
        self.remote_tree.configure(selectmode="extended")
        self._selection_anchor = {"local": None, "remote": None}

        self._install_selection_bindings(self.local_tree, "local")
        self._install_selection_bindings(self.remote_tree, "remote")

        self.local_tree.bind(
            "<ButtonPress-1>",
            lambda e: self._file_drag_press("local", self.local_tree, e),
        )
        self.remote_tree.bind(
            "<ButtonPress-1>",
            lambda e: self._file_drag_press("remote", self.remote_tree, e),
        )
        self.local_tree.bind("<B1-Motion>", self._drag_motion, add="+")
        self.remote_tree.bind("<B1-Motion>", self._drag_motion, add="+")

        # The previous layer used bind_all(<ButtonRelease-1>). Remove that global
        # Tcl/Tk callback and scope drag completion to the two file panes only.
        try:
            self.unbind_all("<ButtonRelease-1>")
        except Exception:
            pass
        self.local_tree.bind("<ButtonRelease-1>", self._safe_finish_drag, add="+")
        self.remote_tree.bind("<ButtonRelease-1>", self._safe_finish_drag, add="+")

        # Explorer -> SFTP now uses TkDND instead of windnd. windnd's native
        # Windows message hook could terminate the process without a Python
        # exception/log after a successful drop.
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
        tree.bind("<Control-a>", lambda e, t=tree: self._tree_select_all(t))
        tree.bind("<Control-A>", lambda e, t=tree: self._tree_select_all(t))

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
        # Dedicated Ctrl/Shift bindings manage modified clicks.
        if event.state & 0x0005:
            return None

        row = tree.identify_row(event.y)
        selected = tree.selection()

        # Initialise drag state directly. This avoids depending on another class
        # binding while keeping a multi-selection intact.
        self._sftp_drag_source = side if row else None
        self._sftp_drag_active = False
        self._sftp_drag_start = (event.x_root, event.y_root)

        if row:
            self._selection_anchor[side] = row

        if row and row in selected and len(selected) > 1:
            tree.focus(row)
            return "break"
        return None

    def _safe_finish_drag(self, event):
        source = getattr(self, "_sftp_drag_source", None)
        active = bool(getattr(self, "_sftp_drag_active", False))
        self._sftp_drag_source = None
        self._sftp_drag_active = False

        if not source or not active:
            return "break"

        target = event.widget
        if source == "local" and self._widget_is_or_inside(target, self.remote_tree):
            self.after(75, self.upload_selected)
        elif source == "remote" and self._widget_is_or_inside(target, self.local_tree):
            self.after(75, self.download_selected)
        return "break"

    # ---------- Windows Explorer -> SFTP pane via TkDND ----------
    def _install_windows_explorer_drop(self):
        if TkinterDnD is None or DND_FILES is None:
            self.transfer_status.configure(
                text=(
                    "Explorer drag/drop unavailable: install tkinterdnd2"
                    if self.language.get() == "EN"
                    else "Glisser-déposer Explorateur indisponible : installe tkinterdnd2"
                )
            )
            return

        try:
            # Load the tkdnd Tcl extension into the already existing CTk root.
            # tkinterdnd2 patches tkinter.BaseWidget with drop_target_register
            # and dnd_bind, so the existing ttk.Treeview can be used directly.
            TkinterDnD._require(self)
            self.remote_tree.drop_target_register(DND_FILES)
            self.remote_tree.dnd_bind("<<Drop>>", self._windows_files_dropped)
        except Exception as exc:
            self.transfer_status.configure(text=f"Windows DnD error: {exc}")

    def _windows_files_dropped(self, event):
        try:
            raw_items = self.tk.splitlist(event.data)
        except Exception:
            raw_items = [event.data]

        paths = []
        for raw in raw_items:
            try:
                p = Path(str(raw).strip().strip("{}"))
            except Exception:
                continue
            if p.exists():
                paths.append(p)

        if paths:
            # Let the TkDND callback return before any UI/SFTP work begins.
            self.after(100, lambda p=paths: self._upload_external_paths(p))
        return "copy"

    def _upload_external_paths(self, items):
        if not self.need():
            return

        remote_dir = self.path.get().strip() or "/"
        conflicts = self._collect_upload_conflicts(items, remote_dir)
        if not self._confirm_overwrite(conflicts):
            return

        import posixpath
        import threading

        def worker():
            try:
                total = len(items)
                for i, item in enumerate(items, 1):
                    self.q.put(("transfer", f"Upload {i}/{total} : {item.name}"))
                    self._upload_path(item, posixpath.join(remote_dir, item.name))
                self.q.put(("transfer", f"Upload complete ({total} item(s))"))
                self.q.put(("refresh_remote", None))
            except Exception as exc:
                self.q.put(("transfer", f"Error: {exc}"))

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    EmberAdmin().mainloop()
