import hashlib
import os
import posixpath
import shutil
import stat
import tempfile
import time
from pathlib import Path
import tkinter as tk

import customtkinter as ctk
from tkinter import messagebox

from ember_admin_files import EmberAdmin as _FilesApp


class EmberAdmin(_FilesApp):
    """WinSCP-inspired SFTP quality-of-life layer."""

    def _install_sftp_enhancements(self):
        super()._install_sftp_enhancements()

        self._remote_edit_sessions = {}

        # Keyboard shortcuts similar to a classic file manager.
        for tree in (self.local_tree, self.remote_tree):
            tree.bind("<F5>", self._file_refresh_shortcut, add="+")

        self.local_tree.bind("<F2>", lambda _e: self.local_rename_selected(), add="+")
        self.remote_tree.bind("<F2>", lambda _e: self.remote_rename_selected(), add="+")
        self.local_tree.bind("<Delete>", lambda _e: self.local_delete_selected(), add="+")
        self.remote_tree.bind("<Delete>", lambda _e: self.remote_delete_selected(), add="+")

        # Replace the old right-click behavior with real file-manager menus.
        self.local_tree.bind("<Button-3>", self.local_context_menu)
        self.remote_tree.bind("<Button-3>", self.remote_context_menu)

    # ---------- Selection / context helpers ----------
    def _select_row_under_pointer(self, tree, event):
        row = tree.identify_row(event.y)
        if row and row not in tree.selection():
            tree.selection_set(row)
            tree.focus(row)
        return row

    def local_context_menu(self, event):
        self._select_row_under_pointer(self.local_tree, event)
        lang = self.language.get()
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Open" if lang == "EN" else "Ouvrir", command=self.local_open)
        menu.add_command(label="Upload" if lang == "EN" else "Envoyer", command=self.upload_selected)
        menu.add_separator()
        menu.add_command(label="Rename (F2)" if lang == "EN" else "Renommer (F2)", command=self.local_rename_selected)
        menu.add_command(label="Delete" if lang == "EN" else "Supprimer", command=self.local_delete_selected)
        menu.add_separator()
        menu.add_command(label="Refresh (F5)" if lang == "EN" else "Actualiser (F5)", command=self.list_local)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def remote_context_menu(self, event):
        self._select_row_under_pointer(self.remote_tree, event)
        lang = self.language.get()
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Open" if lang == "EN" else "Ouvrir", command=self.remote_open)
        menu.add_command(label="Edit remote file" if lang == "EN" else "Éditer le fichier distant", command=self.remote_edit_selected)
        menu.add_command(label="Download" if lang == "EN" else "Télécharger", command=self.download_selected)
        menu.add_separator()
        menu.add_command(label="Rename (F2)" if lang == "EN" else "Renommer (F2)", command=self.remote_rename_selected)
        menu.add_command(label="Delete" if lang == "EN" else "Supprimer", command=self.remote_delete_selected)
        menu.add_separator()
        menu.add_command(label="Refresh (F5)" if lang == "EN" else "Actualiser (F5)", command=self.list_remote)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _file_refresh_shortcut(self, _event=None):
        try:
            focus = self.focus_get()
            if self._widget_is_or_inside(focus, self.remote_tree):
                if self.sftp:
                    self.list_remote()
            else:
                self.list_local()
        except Exception:
            self.list_local()
            if self.sftp:
                self.list_remote()
        return "break"

    # ---------- Rename ----------
    def _ask_rename(self, old_name, remote=False):
        lang = self.language.get()
        dlg = ctk.CTkInputDialog(
            title="Rename" if lang == "EN" else "Renommer",
            text=(f"New name for {old_name}:" if lang == "EN" else f"Nouveau nom pour {old_name} :"),
        )
        return dlg.get_input()

    def local_rename_selected(self):
        items = self._selected_local_paths()
        if len(items) != 1:
            messagebox.showwarning(
                "Rename" if self.language.get() == "EN" else "Renommer",
                "Select exactly one item." if self.language.get() == "EN" else "Sélectionne exactement un élément.",
            )
            return "break"
        src = Path(items[0])
        name = self._ask_rename(src.name)
        if not name or name == src.name:
            return "break"
        if Path(name).name != name:
            messagebox.showerror("Rename", "Invalid name.")
            return "break"
        dst = src.with_name(name)
        if dst.exists():
            messagebox.showerror("Rename", "Destination already exists." if self.language.get() == "EN" else "La destination existe déjà.")
            return "break"
        try:
            src.rename(dst)
            self.list_local()
        except Exception as exc:
            messagebox.showerror("Rename", str(exc))
        return "break"

    def remote_rename_selected(self):
        if not self.need():
            return "break"
        entries = self._selected_remote_entries()
        if len(entries) != 1:
            messagebox.showwarning(
                "Rename" if self.language.get() == "EN" else "Renommer",
                "Select exactly one item." if self.language.get() == "EN" else "Sélectionne exactement un élément.",
            )
            return "break"
        e = entries[0]
        name = self._ask_rename(e.filename, remote=True)
        if not name or name == e.filename:
            return "break"
        if posixpath.basename(name) != name or name in (".", ".."):
            messagebox.showerror("Rename", "Invalid name.")
            return "break"
        base = self.path.get().strip() or "/"
        src = posixpath.join(base, e.filename)
        dst = posixpath.join(base, name)
        if self._remote_exists(dst):
            messagebox.showerror("Rename", "Destination already exists." if self.language.get() == "EN" else "La destination existe déjà.")
            return "break"
        try:
            self.sftp.rename(src, dst)
            self.list_remote()
        except Exception as exc:
            messagebox.showerror("SFTP", str(exc))
        return "break"

    # ---------- Local delete ----------
    def local_delete_selected(self):
        items = self._selected_local_paths()
        if not items:
            return "break"
        preview = "\n".join(str(p) for p in items[:10])
        if len(items) > 10:
            preview += f"\n... +{len(items) - 10}"
        lang = self.language.get()
        msg = (
            f"Permanently delete {len(items)} selected item(s)?\n\n{preview}\n\nFolders and all their contents will be deleted."
            if lang == "EN"
            else f"Supprimer définitivement les {len(items)} élément(s) sélectionné(s) ?\n\n{preview}\n\nLes dossiers et tout leur contenu seront supprimés."
        )
        if not messagebox.askyesno("Delete" if lang == "EN" else "Supprimer", msg):
            return "break"
        try:
            for item in items:
                p = Path(item)
                if p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p)
                else:
                    p.unlink()
            self.list_local()
        except Exception as exc:
            messagebox.showerror("Delete", str(exc))
        return "break"

    # ---------- Remote edit / automatic upload ----------
    def _remote_edit_key(self, remote_path):
        return hashlib.sha256(remote_path.encode("utf-8", errors="replace")).hexdigest()[:16]

    def remote_edit_selected(self):
        if not self.need():
            return
        entries = self._selected_remote_entries()
        if len(entries) != 1:
            messagebox.showwarning(
                "Edit" if self.language.get() == "EN" else "Éditer",
                "Select exactly one remote file." if self.language.get() == "EN" else "Sélectionne exactement un fichier distant.",
            )
            return
        e = entries[0]
        if stat.S_ISDIR(e.st_mode):
            messagebox.showwarning("Edit", "Folders cannot be edited." if self.language.get() == "EN" else "Un dossier ne peut pas être édité.")
            return

        remote = posixpath.join(self.path.get().strip() or "/", e.filename)
        root = Path(tempfile.gettempdir()) / "AzerothErasControl" / "edit" / self._remote_edit_key(remote)
        root.mkdir(parents=True, exist_ok=True)
        local = root / e.filename

        try:
            self.sftp.get(remote, str(local))
            baseline = local.stat().st_mtime_ns
            self._remote_edit_sessions[remote] = {
                "local": local,
                "mtime": baseline,
                "busy": False,
                "remote_mtime": int(e.st_mtime or 0),
            }
            self._windows_open_with(local)
            self.transfer_status.configure(
                text=(f"Editing: {e.filename}" if self.language.get() == "EN" else f"Édition : {e.filename}")
            )
            self.after(800, lambda r=remote: self._watch_remote_edit(r))
        except Exception as exc:
            messagebox.showerror("Edit remote file", str(exc))

    def _watch_remote_edit(self, remote):
        session = self._remote_edit_sessions.get(remote)
        if not session:
            return
        local = Path(session["local"])
        if not local.exists():
            self._remote_edit_sessions.pop(remote, None)
            return

        try:
            mtime = local.stat().st_mtime_ns
        except Exception:
            self.after(1000, lambda r=remote: self._watch_remote_edit(r))
            return

        if mtime != session["mtime"] and not session["busy"]:
            session["mtime"] = mtime
            session["busy"] = True
            name = posixpath.basename(remote)
            lang = self.language.get()
            msg = (
                f"{name} was saved locally.\n\nUpload the modified file back to the server?"
                if lang == "EN"
                else f"{name} vient d'être sauvegardé localement.\n\nRenvoyer le fichier modifié sur le serveur ?"
            )
            if messagebox.askyesno("Remote edit" if lang == "EN" else "Édition distante", msg):
                try:
                    # Warn if the server copy changed independently while the file was open.
                    try:
                        current_remote_mtime = int(self.sftp.stat(remote).st_mtime or 0)
                    except Exception:
                        current_remote_mtime = session.get("remote_mtime", 0)
                    if current_remote_mtime != session.get("remote_mtime", 0):
                        warning = (
                            "The remote file also changed since you opened it. Overwrite it anyway?"
                            if lang == "EN"
                            else "Le fichier distant a aussi été modifié depuis son ouverture. L'écraser quand même ?"
                        )
                        if not messagebox.askyesno("Conflict" if lang == "EN" else "Conflit", warning):
                            session["busy"] = False
                            self.after(1000, lambda r=remote: self._watch_remote_edit(r))
                            return
                    self.sftp.put(str(local), remote)
                    try:
                        session["remote_mtime"] = int(self.sftp.stat(remote).st_mtime or 0)
                    except Exception:
                        pass
                    self.transfer_status.configure(
                        text=(f"Uploaded: {name}" if lang == "EN" else f"Renvoyé : {name}")
                    )
                    self.list_remote()
                except Exception as exc:
                    messagebox.showerror("SFTP", str(exc))
            session["busy"] = False

        self.after(1000, lambda r=remote: self._watch_remote_edit(r))


if __name__ == "__main__":
    EmberAdmin().mainloop()
