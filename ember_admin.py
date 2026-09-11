import customtkinter as ctk
from tkinter import messagebox

from ember_admin_core import EmberAdmin as _EmberAdminBase


class EmberAdmin(_EmberAdminBase):
    def __init__(self):
        super().__init__()
        self._install_dashboard_action_controls()

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
