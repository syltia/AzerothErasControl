import os
import posixpath
from pathlib import Path
import tkinter as tk

import customtkinter as ctk
from tkinter import messagebox

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

        try:
            self.unbind_all("<ButtonRelease-1>")
        except Exception:
            pass
        self.local_tree.bind("<ButtonRelease-1>", self._safe_finish_drag, add="+")
        self.remote_tree.bind("<ButtonRelease-1>", self._safe_finish_drag, add="+")

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
        if event.state & 0x0005:
            return None

        row = tree.identify_row(event.y)
        selected = tree.selection()
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

    # ---------- WinSCP-style Create actions ----------
    def _ask_new_name(self, kind):
        lang = self.language.get()
        is_folder = kind == "folder"
        title = (
            ("New folder" if is_folder else "New file")
            if lang == "EN"
            else ("Nouveau dossier" if is_folder else "Nouveau fichier")
        )
        text = (
            ("Folder name:" if is_folder else "File name:")
            if lang == "EN"
            else ("Nom du dossier :" if is_folder else "Nom du fichier :")
        )
        return ctk.CTkInputDialog(title=title, text=text).get_input()

    @staticmethod
    def _valid_single_name(name):
        return bool(name) and name not in (".", "..") and "/" not in name and "\\" not in name

    def local_create_folder(self):
        name = self._ask_new_name("folder")
        if not name:
            return
        if not self._valid_single_name(name):
            messagebox.showerror("New folder", "Invalid name." if self.language.get() == "EN" else "Nom invalide.")
            return
        target = Path(self.local_path.get()).expanduser() / name
        try:
            target.mkdir()
            self.list_local()
        except FileExistsError:
            messagebox.showwarning("New folder", "This name already exists." if self.language.get() == "EN" else "Ce nom existe déjà.")
        except Exception as exc:
            messagebox.showerror("New folder", str(exc))

    def local_create_file(self):
        name = self._ask_new_name("file")
        if not name:
            return
        if not self._valid_single_name(name):
            messagebox.showerror("New file", "Invalid name." if self.language.get() == "EN" else "Nom invalide.")
            return
        target = Path(self.local_path.get()).expanduser() / name
        try:
            with target.open("x", encoding="utf-8"):
                pass
            self.list_local()
        except FileExistsError:
            messagebox.showwarning("New file", "This name already exists." if self.language.get() == "EN" else "Ce nom existe déjà.")
        except Exception as exc:
            messagebox.showerror("New file", str(exc))

    def remote_create_folder(self):
        if not self.need():
            return
        name = self._ask_new_name("folder")
        if not name:
            return
        if not self._valid_single_name(name):
            messagebox.showerror("New folder", "Invalid name." if self.language.get() == "EN" else "Nom invalide.")
            return
        target = posixpath.join(self.path.get().strip() or "/", name)
        try:
            if self._remote_exists(target):
                messagebox.showwarning("New folder", "This name already exists." if self.language.get() == "EN" else "Ce nom existe déjà.")
                return
            self.sftp.mkdir(target)
            self.list_remote()
        except Exception as exc:
            messagebox.showerror("SFTP", str(exc))

    def remote_create_file(self):
        if not self.need():
            return
        name = self._ask_new_name("file")
        if not name:
            return
        if not self._valid_single_name(name):
            messagebox.showerror("New file", "Invalid name." if self.language.get() == "EN" else "Nom invalide.")
            return
        target = posixpath.join(self.path.get().strip() or "/", name)
        try:
            if self._remote_exists(target):
                messagebox.showwarning("New file", "This name already exists." if self.language.get() == "EN" else "Ce nom existe déjà.")
                return
            handle = self.sftp.open(target, "w")
            handle.close()
            self.list_remote()
        except Exception as exc:
            messagebox.showerror("SFTP", str(exc))

    def local_context_menu(self, event):
        self._select_row_under_pointer(self.local_tree, event)
        lang = self.language.get()
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Open" if lang == "EN" else "Ouvrir", command=self.local_open)
        menu.add_command(label="Upload" if lang == "EN" else "Envoyer", command=self.upload_selected)
        menu.add_separator()
        new_menu = tk.Menu(menu, tearoff=0)
        new_menu.add_command(label="Folder" if lang == "EN" else "Dossier", command=self.local_create_folder)
        new_menu.add_command(label="File" if lang == "EN" else "Fichier", command=self.local_create_file)
        menu.add_cascade(label="New" if lang == "EN" else "Nouveau", menu=new_menu)
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
        new_menu = tk.Menu(menu, tearoff=0)
        new_menu.add_command(label="Folder" if lang == "EN" else "Dossier", command=self.remote_create_folder)
        new_menu.add_command(label="File" if lang == "EN" else "Fichier", command=self.remote_create_file)
        menu.add_cascade(label="New" if lang == "EN" else "Nouveau", menu=new_menu)
        menu.add_separator()
        menu.add_command(label="Rename (F2)" if lang == "EN" else "Renommer (F2)", command=self.remote_rename_selected)
        menu.add_command(label="Delete" if lang == "EN" else "Supprimer", command=self.remote_delete_selected)
        menu.add_separator()
        menu.add_command(label="Refresh (F5)" if lang == "EN" else "Actualiser (F5)", command=self.list_remote)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

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
            self.after(100, lambda p=paths: self._upload_external_paths(p))
        return "copy"

    def _upload_external_paths(self, items):
        if not self.need():
            return
        if getattr(self, "_transfer_in_progress", False):
            return

        remote_dir = self.path.get().strip() or "/"
        conflicts = self._collect_upload_conflicts(items, remote_dir)
        if not self._confirm_overwrite(conflicts):
            return

        import threading

        self._transfer_in_progress = True

        def worker():
            sftp = None
            try:
                sftp = self._new_transfer_sftp()
                total = len(items)
                for i, item in enumerate(items, 1):
                    self.q.put(("transfer", f"Upload {i}/{total} : {item.name}"))
                    self._upload_path_on(sftp, item, posixpath.join(remote_dir, item.name))
                self.q.put(("transfer", f"Upload complete ({total} item(s))"))
                self.q.put(("refresh_remote", None))
            except Exception as exc:
                self.q.put(("transfer", f"Error: {exc}"))
            finally:
                try:
                    if sftp is not None:
                        sftp.close()
                except Exception:
                    pass
                self._transfer_in_progress = False

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    EmberAdmin().mainloop()
