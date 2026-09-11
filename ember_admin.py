import customtkinter as ctk

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
