import customtkinter as ctk
from tkinter import messagebox
import os
import posixpath
import stat
import subprocess
import tempfile
import threading
from pathlib import Path

from ember_admin_core import EmberAdmin as _EmberAdminBase


class EmberAdmin(_EmberAdminBase):
    def __init__(self):
        super().__init__()
        self._install_dashboard_action_controls()
        self._install_sftp_enhancements()

    def _find_dashboard_button(self, text):
        root=self.pages.get("Dashboard")
        if root is None:
            return None
        stack=[root]
        while stack:
            widget=stack.pop()
            try:
                stack.extend(widget.winfo_children())
            except Exception:
                pass
            try:
                if isinstance(widget,ctk.CTkButton) and widget.cget("text")==text:
                    return widget
            except Exception:
                pass
        return None

    def _install_dashboard_action_controls(self):
        restart_btn=self._find_dashboard_button("↻ Restart world")
        stop_btn=self._find_dashboard_button("■ Stop")
        update_btn=self._find_dashboard_button("↻ Update")

        if restart_btn is not None and stop_btn is not None:
            restart_btn.configure(command=lambda:self.schedule_world_action("restart"))
            stop_btn.configure(command=lambda:self.schedule_world_action("shutdown"))

            self.world_action_delay=ctk.StringVar(value="60")
            delay_box=ctk.CTkFrame(stop_btn.master,fg_color="transparent")
            delay_box.pack(side="left",padx=(2,5),pady=10,after=stop_btn)
            ctk.CTkEntry(
                delay_box,
                textvariable=self.world_action_delay,
                width=52,
                justify="center"
            ).pack(side="left")
            ctk.CTkLabel(
                delay_box,
                text="sec",
                text_color="gray65"
            ).pack(side="left",padx=(4,0))

            ctk.CTkButton(
                stop_btn.master,
                text="⚡ Server controls",
                width=125,
                fg_color="gray30",
                command=self.open_server_controls
            ).pack(side="left",padx=(2,5),pady=10,after=delay_box)

        if update_btn is not None:
            update_btn.configure(command=self.update_core_and_modules)

    # ---------- SFTP enhancements ----------
    def _install_sftp_enhancements(self):
        """WinSCP-like quality-of-life additions without touching the SSH core."""
        self._sftp_drag_source=None
        self.local_tree.configure(selectmode="extended")
        self.remote_tree.configure(selectmode="extended")

        # Double-click opens folders; files use Windows "Open with".
        self.local_tree.bind("<Double-Button-1>",self.local_open)
        self.remote_tree.bind("<Double-Button-1>",self.remote_open)

        # Drag selected entries between the two panes.
        self.local_tree.bind("<ButtonPress-1>",lambda e:self._remember_drag("local"),add="+")
        self.remote_tree.bind("<ButtonPress-1>",lambda e:self._remember_drag("remote"),add="+")
        self.local_tree.bind("<ButtonRelease-1>",self._finish_drag,add="+")
        self.remote_tree.bind("<ButtonRelease-1>",self._finish_drag,add="+")

    def _remember_drag(self,side):
        self._sftp_drag_source=side

    def _finish_drag(self,event):
        source=self._sftp_drag_source
        self._sftp_drag_source=None
        try:
            target=self.winfo_containing(event.x_root,event.y_root)
        except Exception:
            return
        if source=="local" and target is self.remote_tree:
            self.upload_selected()
        elif source=="remote" and target is self.local_tree:
            self.download_selected()

    def _selected_local_paths(self):
        return [self.local_entries[i] for i in self.local_tree.selection() if i in self.local_entries]

    def _selected_remote_entries(self):
        return [self.remote_entries[i] for i in self.remote_tree.selection() if i in self.remote_entries]

    def _remote_exists(self,path):
        try:
            self.sftp.stat(path)
            return True
        except IOError:
            return False

    def _remote_mkdirs(self,path):
        path=posixpath.normpath(path)
        parts=[]
        while path not in ("","/"):
            parts.append(path)
            path=posixpath.dirname(path)
        for folder in reversed(parts):
            try:
                self.sftp.stat(folder)
            except IOError:
                self.sftp.mkdir(folder)

    def _collect_upload_conflicts(self,items,remote_dir):
        conflicts=[]
        for item in items:
            target=posixpath.join(remote_dir,item.name)
            if self._remote_exists(target):
                conflicts.append(target)
        return conflicts

    def _collect_download_conflicts(self,entries,local_dir):
        return [str(local_dir/e.filename) for e in entries if (local_dir/e.filename).exists()]

    def _confirm_overwrite(self,conflicts):
        if not conflicts:
            return True
        preview="\n".join(conflicts[:8])
        if len(conflicts)>8:
            preview+=f"\n... +{len(conflicts)-8}"
        msg=(
            f"{len(conflicts)} item(s) already exist at the destination.\n\n"
            f"{preview}\n\nOverwrite them?"
            if self.language.get()=="EN" else
            f"{len(conflicts)} élément(s) existent déjà à destination.\n\n"
            f"{preview}\n\nLes écraser ?"
        )
        return messagebox.askyesno("Overwrite" if self.language.get()=="EN" else "Écrasement",msg)

    def _upload_path(self,local,target):
        local=Path(local)
        if local.is_dir():
            self._remote_mkdirs(target)
            for child in local.iterdir():
                self._upload_path(child,posixpath.join(target,child.name))
        else:
            self.sftp.put(str(local),target)

    def _download_path(self,remote,local,mode=None):
        if mode is None:
            mode=self.sftp.stat(remote).st_mode
        local=Path(local)
        if stat.S_ISDIR(mode):
            local.mkdir(parents=True,exist_ok=True)
            for child in self.sftp.listdir_attr(remote):
                self._download_path(
                    posixpath.join(remote,child.filename),
                    local/child.filename,
                    child.st_mode
                )
        else:
            local.parent.mkdir(parents=True,exist_ok=True)
            self.sftp.get(remote,str(local))

    def upload_selected(self):
        if not self.need():
            return
        items=self._selected_local_paths()
        if not items:
            messagebox.showwarning("SFTP","Select local files/folders." if self.language.get()=="EN" else "Sélectionne des fichiers/dossiers locaux.")
            return
        remote_dir=self.path.get().strip() or "/"
        conflicts=self._collect_upload_conflicts(items,remote_dir)
        if not self._confirm_overwrite(conflicts):
            return

        def worker():
            try:
                for i,item in enumerate(items,1):
                    self.q.put(("transfer",f"Upload {i}/{len(items)} : {item.name}"))
                    self._upload_path(item,posixpath.join(remote_dir,item.name))
                self.q.put(("transfer",f"Upload complete ({len(items)} item(s))"))
                self.q.put(("refresh_remote",None))
            except Exception as exc:
                self.q.put(("transfer",f"Error: {exc}"))
        threading.Thread(target=worker,daemon=True).start()

    def download_selected(self):
        if not self.need():
            return
        entries=self._selected_remote_entries()
        if not entries:
            messagebox.showwarning("SFTP","Select server files/folders." if self.language.get()=="EN" else "Sélectionne des fichiers/dossiers serveur.")
            return
        remote_dir=self.path.get().strip() or "/"
        local_dir=Path(self.local_path.get())
        conflicts=self._collect_download_conflicts(entries,local_dir)
        if not self._confirm_overwrite(conflicts):
            return

        def worker():
            try:
                for i,e in enumerate(entries,1):
                    self.q.put(("transfer",f"Download {i}/{len(entries)} : {e.filename}"))
                    self._download_path(
                        posixpath.join(remote_dir,e.filename),
                        local_dir/e.filename,
                        e.st_mode
                    )
                self.q.put(("transfer",f"Download complete ({len(entries)} item(s))"))
                self.q.put(("refresh_local",None))
            except Exception as exc:
                self.q.put(("transfer",f"Error: {exc}"))
        threading.Thread(target=worker,daemon=True).start()

    def _remote_remove_recursive(self,path,mode=None):
        if mode is None:
            mode=self.sftp.stat(path).st_mode
        if stat.S_ISDIR(mode):
            for child in self.sftp.listdir_attr(path):
                self._remote_remove_recursive(posixpath.join(path,child.filename),child.st_mode)
            self.sftp.rmdir(path)
        else:
            self.sftp.remove(path)

    def remote_delete_selected(self):
        if not self.need():
            return "break"
        entries=self._selected_remote_entries()
        if not entries:
            return "break"
        base=self.path.get().strip() or "/"
        paths=[posixpath.join(base,e.filename) for e in entries]
        preview="\n".join(paths[:10])
        if len(paths)>10:
            preview+=f"\n... +{len(paths)-10}"
        msg=(
            f"Permanently delete {len(paths)} selected item(s)?\n\n{preview}\n\nFolders and all their contents will be deleted."
            if self.language.get()=="EN" else
            f"Supprimer définitivement les {len(paths)} élément(s) sélectionné(s) ?\n\n{preview}\n\nLes dossiers et tout leur contenu seront supprimés."
        )
        if not messagebox.askyesno("Delete" if self.language.get()=="EN" else "Supprimer",msg):
            return "break"
        try:
            for path,e in zip(paths,entries):
                self._remote_remove_recursive(path,e.st_mode)
            self.list_remote()
        except Exception as exc:
            messagebox.showerror("SFTP",str(exc))
        return "break"

    def _windows_open_with(self,path):
        path=str(Path(path))
        if os.name=="nt":
            subprocess.Popen(["rundll32.exe","shell32.dll,OpenAs_RunDLL",path])
        else:
            subprocess.Popen(["xdg-open",path])

    def local_open(self,event=None):
        sel=self.local_tree.selection()
        if not sel:
            return
        item=self.local_entries.get(sel[0])
        if not item:
            return
        if item.is_dir():
            self.local_path.set(str(item))
            self.list_local()
        else:
            try:
                self._windows_open_with(item)
            except Exception as exc:
                messagebox.showerror("Open file",str(exc))

    def remote_open(self,event=None):
        sel=self.remote_tree.selection()
        if not sel:
            return
        e=self.remote_entries.get(sel[0])
        if not e:
            return
        remote=posixpath.join(self.path.get().strip() or "/",e.filename)
        if stat.S_ISDIR(e.st_mode):
            self.path.delete(0,"end")
            self.path.insert(0,remote)
            self.list_remote()
            return

        # Remote files are downloaded to a temporary preview directory first.
        preview_dir=Path(tempfile.gettempdir())/"AzerothErasControl"/"preview"
        preview_dir.mkdir(parents=True,exist_ok=True)
        local=preview_dir/e.filename
        try:
            self.sftp.get(remote,str(local))
            self._windows_open_with(local)
        except Exception as exc:
            messagebox.showerror("Open file",str(exc))

    def schedule_world_action(self, action):
        if not self.need():
            return

        try:
            delay=int(self.world_action_delay.get().strip())
        except Exception:
            delay=60

        delay=max(1,min(3600,delay))
        self.world_action_delay.set(str(delay))

        if action=="restart":
            command=f"server restart {delay}"
            label="restart"
        else:
            command=f"server shutdown {delay}"
            label="shutdown"

        self.show("Console")
        self.world_console(command)
        self.q.put((
            "log",
            f"[Worldserver] {label} scheduled in {delay} second(s).\n"
        ))

    def open_server_controls(self):
        if not self.need():
            return

        dlg=ctk.CTkToplevel(self)
        dlg.title("Server controls")
        dlg.geometry("420x300")
        dlg.resizable(False,False)
        dlg.transient(self)
        dlg.grab_set()

        ctk.CTkLabel(
            dlg,
            text="Emergency server controls",
            font=ctk.CTkFont(size=21,weight="bold")
        ).pack(pady=(24,4))
        ctk.CTkLabel(
            dlg,
            text="Authserver can be controlled independently from Worldserver.",
            text_color="gray70"
        ).pack(pady=(0,18))

        row=ctk.CTkFrame(dlg,fg_color="transparent")
        row.pack(pady=5)
        ctk.CTkButton(row,text="▶ Start auth",width=115,command=lambda:self.auth_action("start",dlg)).pack(side="left",padx=4)
        ctk.CTkButton(row,text="↻ Restart auth",width=115,command=lambda:self.auth_action("restart",dlg)).pack(side="left",padx=4)
        ctk.CTkButton(row,text="■ Stop auth",width=115,command=lambda:self.auth_action("stop",dlg)).pack(side="left",padx=4)

        ctk.CTkButton(
            dlg,
            text="■ Stop ALL tmux sessions",
            width=250,
            fg_color="#8c3434",
            hover_color="#6f2929",
            command=lambda:self.stop_all_sessions(dlg)
        ).pack(pady=(20,7))
        ctk.CTkLabel(
            dlg,
            text="Emergency only — stops Authserver and Worldserver sessions.",
            text_color="gray60",
            font=ctk.CTkFont(size=11)
        ).pack()

    def auth_action(self, action, dialog=None):
        if not self.need():
            return

        base="cd /root/azerothcore-wotlk/env/dist/bin"
        if action=="start":
            command=(
                f"{base} && "
                "if tmux has-session -t auth-session 2>/dev/null; then "
                "cmd=$(tmux display-message -p -t auth-session '#{pane_current_command}'); "
                "if [ \"$cmd\" = \"authserver\" ]; then echo 'Authserver is already running.'; "
                "else tmux send-keys -t auth-session './authserver' C-m; echo 'Authserver started.'; fi; "
                "else tmux new-session -d -s auth-session './authserver'; echo 'Authserver session created and started.'; fi"
            )
        elif action=="restart":
            command=(
                f"{base} && "
                "if tmux has-session -t auth-session 2>/dev/null; then "
                "tmux send-keys -t auth-session C-c; sleep 2; "
                "tmux send-keys -t auth-session './authserver' C-m; echo 'Authserver restarted.'; "
                "else tmux new-session -d -s auth-session './authserver'; echo 'Authserver session created and started.'; fi"
            )
        else:
            command=(
                "if tmux has-session -t auth-session 2>/dev/null; then "
                "tmux send-keys -t auth-session C-c; echo 'Authserver stop requested.'; "
                "else echo 'Authserver session does not exist.'; fi"
            )

        if dialog is not None:
            dialog.destroy()
        self.run(command)

    def stop_all_sessions(self, dialog=None):
        if not self.need():
            return
        if not messagebox.askyesno(
            "Stop all",
            "Stop ALL tmux sessions?\n\nThis immediately stops Authserver and Worldserver.",
            parent=dialog or self
        ):
            return
        if dialog is not None:
            dialog.destroy()
        self.run("tmux kill-server 2>/dev/null || true; echo 'All tmux sessions stopped.'")

    def update_core_and_modules(self):
        if not self.need():
            return

        command=(
            "cd /root/azerothcore-wotlk && "
            "git pull && "
            "cd modules && "
            "find . -mindepth 1 -maxdepth 1 -type d "
            "-exec sh -c 'if git -C \"$1\" rev-parse --is-inside-work-tree >/dev/null 2>&1; "
            "then echo; echo \"===== $1 =====\"; git -C \"$1\" pull; fi' _ {} \\;"
        )
        self.run(command)


if __name__=="__main__":
    EmberAdmin().mainloop()
