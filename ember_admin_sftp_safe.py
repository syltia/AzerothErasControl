from ember_admin_winscp import EmberAdmin as _WinSCPApp


class EmberAdmin(_WinSCPApp):
    """Safer SFTP drag/drop layer for Windows/Tk.

    The previous implementation used bind_all(<ButtonRelease-1>), which installs
    a global Tcl/Tk mouse-release callback. On Windows this can destabilize the
    process during cross-pane dragging. This layer removes that global binding
    and handles release only on the two file panes.
    """

    def _install_sftp_enhancements(self):
        super()._install_sftp_enhancements()

        # Remove the global ButtonRelease binding installed by ember_admin_files.
        # Keeping drag handling scoped to the two Treeviews avoids a native Tk
        # callback firing against unrelated widgets/window teardown states.
        try:
            self.unbind_all("<ButtonRelease-1>")
        except Exception:
            pass

        self.local_tree.bind("<ButtonRelease-1>", self._safe_finish_drag, add="+")
        self.remote_tree.bind("<ButtonRelease-1>", self._safe_finish_drag, add="+")

    def _safe_finish_drag(self, event):
        source = getattr(self, "_sftp_drag_source", None)
        active = bool(getattr(self, "_sftp_drag_active", False))

        self._sftp_drag_source = None
        self._sftp_drag_active = False

        if not source or not active:
            return "break"

        target = event.widget

        if source == "local" and self._widget_is_or_inside(target, self.remote_tree):
            # Give Tk enough time to fully finish the mouse-release dispatch.
            self.after(75, self.upload_selected)
        elif source == "remote" and self._widget_is_or_inside(target, self.local_tree):
            self.after(75, self.download_selected)

        return "break"


if __name__ == "__main__":
    EmberAdmin().mainloop()
