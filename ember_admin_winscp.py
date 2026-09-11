import hashlib
import os
import posixpath
import shutil
import stat
import tempfile
import time
import sys
import traceback
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk

import customtkinter as ctk
from tkinter import messagebox

from ember_admin_files import EmberAdmin as _FilesApp


def _crash_log_path():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "AzerothErasControl.log"
    return Path(__file__).resolve().parent / "AzerothErasControl.log"


def _write_crash_log(exc_type, exc_value, exc_tb, context="Unhandled exception"):
    try:
        path = _crash_log_path()
        with path.open("a", encoding="utf-8") as log:
            log.write("\n" + "=" * 78 + "\n")
            log.write(f"{datetime.now().isoformat(timespec='seconds')} - {context}\n")
            log.write("=" * 78 + "\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=log)
            log.flush()
    except Exception:
        pass


def _global_exception_hook(exc_type, exc_value, exc_tb):
    _write_crash_log(exc_type, exc_value, exc_tb)
    try:
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    except Exception:
        pass


sys.excepthook = _global_exception_hook


class EmberAdmin(_FilesApp):
    """WinSCP-inspired SFTP quality-of-life layer."""

    def report_callback_exception(self, exc, val, tb):
        _write_crash_log(exc, val, tb, context="Tkinter callback exception")
        try:
            messagebox.showerror(
                "Azeroth Eras Control",
                "Une erreur est survenue.\n\nLe diagnostic a été enregistré dans :\n"
                + str(_crash_log_path()),
            )
        except Exception:
            pass

    def _install_sftp_enhancements(self):
        super()._install_sftp_enhancements()

        self._remote_edit_sessions = {}
        self._transfer_in_progress = False

        for tree in (self.local_tree, self.remote_tree):
            tree.bind("<F5>", self._file_refresh_shortcut, add="+")

        self.local_tree.bind("<F2>", lambda _e: self.local_rename_selected(), add="+")
        self.remote_tree.bind("<F2>", lambda _e: self.remote_rename_selected(), add="+")
        self.local_tree.bind("<Delete>", lambda _e: self.local_delete_selected(), add="+")
        self.remote_tree.bind("<Delete>", lambda _e: self.remote_delete_selected(), add="+")
        self.local_tree.bind("<Button-3>", self.local_context_menu)
        self.remote_tree.bind("<Button-3>", self.remote_context_menu)

    # ---------- Dedicated transfer channel ----------
    # Do not share the browser SFTPClient with a worker thread. Paramiko's
    # SFTPClient is not designed for concurrent requests from multiple threads.
    def _new_transfer_sftp(self):
        if not self.ssh:
            raise RuntimeError("SSH connection is not available.")
        return self.ssh.open_sftp()

    @staticmethod
    def _transfer_remote_exists(sftp, path):
        try:
            sftp.stat(path)
            return True
        except IOError:
            return False

    def _transfer_remote_mkdirs(self, sftp, path):
        path = posixpath.normpath(path)
        parts = []
        while path not in ("", "/"):
            parts.append(path)
            path = posixpath.dirname(path)
        for folder in reversed(parts):
            try:
                sftp.stat(folder)
            except IOError:
                sftp.mkdir(folder)

    def _upload_path_on(self, sftp, local, target):
        local = Path(local)
        if local.is_dir():
            self._transfer_remote_mkdirs(sftp, target)
            for child in local.iterdir():
                self._upload_path_on(sftp, child, posixpath.join(target, child.name))
        else:
            sftp.put(str(local), target)

    def _download_path_on(self, sftp, remote, local, mode=None):
        if mode is None:
            mode = sftp.stat(remote).st_mode
        local = Path(local)
        if stat.S_ISDIR(mode):
            local.mkdir(parents=True, exist_ok=True)
            for child in sftp.listdir_attr(remote):
                self._download_path_on(
                    sftp,
                    posixpath.join(remote, child.filename),
                    local / child.filename,
                    child.st_mode,
                )
        else:
            local.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(remote, str(local))

    def upload_selected(self):
        if not self.need():
            return
        if self._transfer_in_progress:
            return

        items = list(self._selected_local_paths())
        if not items:
            messagebox.showwarning(
                "SFTP",
                "Select local files/folders." if self.language.get() == "EN" else "Sélectionne des fichiers/dossiers locaux.",
            )
            return

        remote_dir = self.path.get().strip() or "/"
        conflicts = self._collect_upload_conflicts(items, remote_dir)
        if not self._confirm_overwrite(conflicts):
            return

        self._transfer_in_progress = True

        def worker():
            sftp = None
            try:
                sftp = self._new_transfer_sftp()
                for i, item in enumerate(items, 1):
                    self.q.put(("transfer", f"Upload {i}/{len(items)} : {item.name}"))
                    self._upload_path_on(sftp, item, posixpath.join(remote_dir, item.name))
                self.q.put(("transfer", f"Upload complete ({len(items)} item(s))"))
                self.q.put(("refresh_remote", None))
            except Exception as exc:
                self.q.put(("transfer", f"Error: {exc}"))
                _write_crash_log(type(exc), exc, exc.__traceback__, context="SFTP upload worker exception")
            finally:
                try:
                    if sftp is not None:
                        sftp.close()
                except Exception:
                    pass
                self._transfer_in_progress = False

        threading.Thread(target=worker, daemon=True, name="aec-sftp-upload").start()

    def download_selected(self):
        if not self.need():
            return
        if self._transfer_in_progress:
            return

        entries = list(self._selected_remote_entries())
        if not entries:
            messagebox.showwarning(
                "SFTP",
                "Select server files/folders." if self.language.get() == "EN" else "Sélectionne des fichiers/dossiers serveur.",
            )
            return

        remote_dir = self.path.get().strip() or "/"
        local_dir = Path(self.local_path.get())
        conflicts = self._collect_download_conflicts(entries, local_dir)
        if not self._confirm_overwrite(conflicts):
            return

        self._transfer_in_progress = True

        def worker():
            sftp = None
            try:
                sftp = self._new_transfer_sftp()
                for i, e in enumerate(entries, 1):
                    self.q.put(("transfer", f"Download {i}/{len(entries)} : {e.filename}"))
                    self._download_path_on(
                        sftp,
                        posixpath.join(remote_dir, e.filename),
                        local_dir / e.filename,
                        e.st_mode,
                    )
                self.q.put(("transfer", f"Download complete ({len(entries)} item(s))"))
                self.q.put(("refresh_local", None))
            except Exception as exc:
                self.q.put(("transfer", f"Error: {exc}"))
                _write_crash_log(type(exc), exc, exc.__traceback__, context="SFTP download worker exception")
            finally:
                try:
                    if sftp is not None:
                        sftp.close()
                except Exception:
                    pass
                self._transfer_in_progress = False

        threading.Thread(target=worker, daemon=True, name="aec-sftp-download").start()

    def _files_auto_refresh_tick(self):
        # Never browse the main SFTP channel while a transfer worker is active.
        if getattr(self, "_transfer_in_progress", False):
            self.after(500, self._files_auto_refresh_tick)
            return
        super()._files_auto_refresh_tick()

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
        if getattr(self, "_transfer_in_progress", False):
            return "break"
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
    try:
        EmberAdmin().mainloop()
    except BaseException:
        exc_type, exc_value, exc_tb = sys.exc_info()
        _write_crash_log(exc_type, exc_value, exc_tb, context="Fatal application exception")
        raise
