import os
import posixpath
import stat
import subprocess
import tempfile
from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox

from ember_admin import EmberAdmin as _CurrentApp


class EmberAdmin(_CurrentApp):
    """Adds Explorer-like navigation and more reliable SFTP drag/drop."""

    def _install_sftp_enhancements(self):
        self.local_tree.configure(selectmode="extended")
        self.remote_tree.configure(selectmode="extended")

        self._sftp_drag_source = None
        self._sftp_drag_active = False
        self._sftp_drag_start = (0, 0)
        self._files_auto_refresh_busy = False
        self._local_signature = None
        self._remote_signature = None

        self._local_history = [str(Path(self.local_path.get()).expanduser())]
        self._local_history_index = 0
        self._remote_history = [self.path.get().strip() or "/"]
        self._remote_history_index = 0
        self._history_navigation = False

        self.local_tree.bind("<Double-Button-1>", self.local_open)
        self.remote_tree.bind("<Double-Button-1>", self.remote_open)

        self.local_tree.bind(
            "<ButtonPress-1>", lambda e: self._remember_drag("local", e), add="+"
        )
        self.remote_tree.bind(
            "<ButtonPress-1>", lambda e: self._remember_drag("remote", e), add="+"
        )
        self.local_tree.bind("<B1-Motion>", self._drag_motion, add="+")
        self.remote_tree.bind("<B1-Motion>", self._drag_motion, add="+")
        self.bind_all("<ButtonRelease-1>", self._finish_drag, add="+")

        self._install_file_navigation_buttons()

        local_entry = self._find_local_path_entry()
        if local_entry is not None:
            local_entry.bind("<Return>", lambda _e: self._navigate_local_address())
        self.path.bind("<Return>", lambda _e: self._navigate_remote_address())

        self.local_tree.bind("<Alt-Left>", lambda _e: self.local_back())
        self.remote_tree.bind("<Alt-Left>", lambda _e: self.remote_back())
        self.local_tree.bind("<Alt-Right>", lambda _e: self.local_forward())
        self.remote_tree.bind("<Alt-Right>", lambda _e: self.remote_forward())

        self._update_file_signatures()
        self.after(1800, self._files_auto_refresh_tick)

    def _find_local_path_entry(self):
        root = self.pages.get("Fichiers")
        if root is None:
            return None
        wanted = str(self.local_path)
        stack = [root]
        while stack:
            widget = stack.pop()
            try:
                stack.extend(widget.winfo_children())
            except Exception:
                pass
            try:
                if isinstance(widget, ctk.CTkEntry) and str(widget.cget("textvariable")) == wanted:
                    return widget
            except Exception:
                pass
        return None

    def _install_file_navigation_buttons(self):
        local_entry = self._find_local_path_entry()
        if local_entry is not None:
            frame = local_entry.master
            ctk.CTkButton(frame, text="←", width=34, command=self.local_back).pack(
                side="left", padx=(0, 4), before=local_entry
            )
            ctk.CTkButton(frame, text="→", width=34, command=self.local_forward).pack(
                side="left", padx=(0, 4), before=local_entry
            )

        frame = self.path.master
        ctk.CTkButton(frame, text="←", width=34, command=self.remote_back).pack(
            side="left", padx=(0, 4), before=self.path
        )
        ctk.CTkButton(frame, text="→", width=34, command=self.remote_forward).pack(
            side="left", padx=(0, 4), before=self.path
        )

    def _push_local_history(self, path):
        if self._history_navigation:
            return
        path = str(Path(path).expanduser())
        current = self._local_history[self._local_history_index]
        if path == current:
            return
        del self._local_history[self._local_history_index + 1 :]
        self._local_history.append(path)
        self._local_history_index = len(self._local_history) - 1

    def _push_remote_history(self, path):
        if self._history_navigation:
            return
        path = posixpath.normpath(path or "/")
        current = self._remote_history[self._remote_history_index]
        if path == current:
            return
        del self._remote_history[self._remote_history_index + 1 :]
        self._remote_history.append(path)
        self._remote_history_index = len(self._remote_history) - 1

    def local_back(self):
        if self._local_history_index <= 0:
            return "break"
        self._local_history_index -= 1
        self._history_navigation = True
        try:
            self.local_path.set(self._local_history[self._local_history_index])
            self.list_local()
        finally:
            self._history_navigation = False
        return "break"

    def local_forward(self):
        if self._local_history_index >= len(self._local_history) - 1:
            return "break"
        self._local_history_index += 1
        self._history_navigation = True
        try:
            self.local_path.set(self._local_history[self._local_history_index])
            self.list_local()
        finally:
            self._history_navigation = False
        return "break"

    def remote_back(self):
        if self._remote_history_index <= 0:
            return "break"
        self._remote_history_index -= 1
        self._history_navigation = True
        try:
            p = self._remote_history[self._remote_history_index]
            self.path.delete(0, "end")
            self.path.insert(0, p)
            self.list_remote()
        finally:
            self._history_navigation = False
        return "break"

    def remote_forward(self):
        if self._remote_history_index >= len(self._remote_history) - 1:
            return "break"
        self._remote_history_index += 1
        self._history_navigation = True
        try:
            p = self._remote_history[self._remote_history_index]
            self.path.delete(0, "end")
            self.path.insert(0, p)
            self.list_remote()
        finally:
            self._history_navigation = False
        return "break"

    def _navigate_local_address(self):
        p = str(Path(self.local_path.get()).expanduser())
        self._push_local_history(p)
        self.list_local()
        return "break"

    def _navigate_remote_address(self):
        p = posixpath.normpath(self.path.get().strip() or "/")
        self.path.delete(0, "end")
        self.path.insert(0, p)
        self._push_remote_history(p)
        self.list_remote()
        return "break"

    def local_parent(self):
        p = Path(self.local_path.get()).expanduser()
        parent = p.parent
        if parent == p:
            return
        self.local_path.set(str(parent))
        self._push_local_history(str(parent))
        self.list_local()

    def parent(self):
        p = posixpath.dirname(self.path.get().rstrip("/")) or "/"
        self.path.delete(0, "end")
        self.path.insert(0, p)
        self._push_remote_history(p)
        self.list_remote()

    def local_open(self, event=None):
        sel = self.local_tree.selection()
        if not sel:
            return
        item = self.local_entries.get(sel[0])
        if not item:
            return
        if item.is_dir():
            self.local_path.set(str(item))
            self._push_local_history(str(item))
            self.list_local()
        else:
            try:
                self._windows_open_with(item)
            except Exception as exc:
                messagebox.showerror("Open file", str(exc))

    def remote_open(self, event=None):
        sel = self.remote_tree.selection()
        if not sel:
            return
        e = self.remote_entries.get(sel[0])
        if not e:
            return
        remote = posixpath.join(self.path.get().strip() or "/", e.filename)
        if stat.S_ISDIR(e.st_mode):
            self.path.delete(0, "end")
            self.path.insert(0, remote)
            self._push_remote_history(remote)
            self.list_remote()
            return

        preview_dir = Path(tempfile.gettempdir()) / "AzerothErasControl" / "preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        local = preview_dir / e.filename
        try:
            self.sftp.get(remote, str(local))
            self._windows_open_with(local)
        except Exception as exc:
            messagebox.showerror("Open file", str(exc))

    def _windows_open_with(self, path):
        path = str(Path(path))
        if os.name == "nt":
            try:
                os.startfile(path)
                return
            except OSError:
                subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", path])
                return
        subprocess.Popen(["xdg-open", path])

    def _remember_drag(self, side, event):
        self._sftp_drag_source = side
        self._sftp_drag_active = False
        self._sftp_drag_start = (event.x_root, event.y_root)

    def _drag_motion(self, event):
        if not self._sftp_drag_source:
            return
        x0, y0 = self._sftp_drag_start
        if abs(event.x_root - x0) + abs(event.y_root - y0) >= 8:
            self._sftp_drag_active = True

    @staticmethod
    def _widget_is_or_inside(widget, ancestor):
        while widget is not None:
            if widget is ancestor:
                return True
            try:
                widget = widget.master
            except Exception:
                return False
        return False

    def _finish_drag(self, event):
        source = self._sftp_drag_source
        active = self._sftp_drag_active
        self._sftp_drag_source = None
        self._sftp_drag_active = False
        if not source or not active:
            return
        try:
            target = self.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return
        if source == "local" and self._widget_is_or_inside(target, self.remote_tree):
            self.upload_selected()
        elif source == "remote" and self._widget_is_or_inside(target, self.local_tree):
            self.download_selected()

    def _get_local_signature(self):
        try:
            base = Path(self.local_path.get()).expanduser()
            return tuple(
                sorted(
                    (
                        p.name,
                        p.is_dir(),
                        0 if p.is_dir() else p.stat().st_size,
                        p.stat().st_mtime_ns,
                    )
                    for p in base.iterdir()
                )
            )
        except Exception:
            return None

    def _get_remote_signature(self):
        if not self.sftp:
            return None
        try:
            base = self.path.get().strip() or "/"
            return tuple(
                sorted(
                    (e.filename, e.st_mode, e.st_size, int(e.st_mtime or 0))
                    for e in self.sftp.listdir_attr(base)
                )
            )
        except Exception:
            return None

    def _update_file_signatures(self):
        self._local_signature = self._get_local_signature()
        self._remote_signature = self._get_remote_signature() if self.sftp else None

    def list_local(self):
        super().list_local()
        if hasattr(self, "_local_signature"):
            self._local_signature = self._get_local_signature()

    def list_remote(self):
        super().list_remote()
        if hasattr(self, "_remote_signature") and self.sftp:
            self._remote_signature = self._get_remote_signature()

    def _files_auto_refresh_tick(self):
        try:
            if self.current_page == "Fichiers" and not self._files_auto_refresh_busy:
                self._files_auto_refresh_busy = True

                local_sig = self._get_local_signature()
                if local_sig is not None and local_sig != self._local_signature:
                    super().list_local()
                    self._local_signature = local_sig

                if self.sftp:
                    remote_sig = self._get_remote_signature()
                    if remote_sig is not None and remote_sig != self._remote_signature:
                        super().list_remote()
                        self._remote_signature = remote_sig
        finally:
            self._files_auto_refresh_busy = False
            self.after(1800, self._files_auto_refresh_tick)


if __name__ == "__main__":
    EmberAdmin().mainloop()
