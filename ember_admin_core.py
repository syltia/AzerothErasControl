import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import paramiko, threading, queue, os, posixpath, stat, datetime, json, base64, hashlib, re, webbrowser
from pathlib import Path

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class EmberAdmin(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Azeroth Eras Control")
        try:
            icon_file = Path(__file__).resolve().with_name("wow_icon.ico")
            if icon_file.exists():
                self.iconbitmap(str(icon_file))
        except Exception:
            pass
        self.geometry("1380x860")
        self.minsize(1150, 720)
        self.ssh = self.sftp = None
        self.shell = None
        self.shell_reader_alive = False
        self.q = queue.Queue()
        self.remote_entries = []
        appdata_root = Path(os.environ.get("APPDATA", os.path.expanduser("~")))
        self.legacy_appdata_dir = appdata_root / "EmberAdmin"
        self.legacy_settings_file = self.legacy_appdata_dir / "settings.json"
        self.appdata_dir = appdata_root / "AzerothErasControl"
        self.appdata_dir.mkdir(parents=True, exist_ok=True)
        self.settings_file = self.appdata_dir / "settings.aec"
        self._fernet = None
        self._master_password = None
        self._saved_settings = self._read_settings_file()
        self.language = ctk.StringVar(
            value=self._saved_settings.get("ui", {}).get("language", "EN")
        )
        self.selected_remote = None

        # Dashboard monitoring
        self.current_page = "Dashboard"
        self._monitor_busy = False
        self._net_prev = None
        self._net_prev_time = None
        self._cpu_prev = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, width=220, corner_radius=0)
        side.grid(row=0,column=0,sticky="nsew")
        side.grid_propagate(False)
        ctk.CTkLabel(side,text="AZEROTH ERAS",font=ctk.CTkFont(size=24,weight="bold")).pack(anchor="w",padx=18,pady=(25,2))
        ctk.CTkLabel(side,text="Control Center",text_color="gray65").pack(anchor="w",padx=18,pady=(0,22))

        self.pages={}
        for name in ["Dashboard","Installation","Comptes & droits","Personnages","Sauvegardes","Console","Fichiers","Connexion"]:
            ctk.CTkButton(side,text=name,anchor="w",command=lambda n=name:self.show(n)).pack(fill="x",padx=12,pady=4)

        ctk.CTkButton(side,text="🔒 Verrouiller",fg_color="gray30",command=self.lock_app).pack(fill="x",padx=12,pady=(18,4))
        ctk.CTkButton(side,text="Changer mot de passe",fg_color="gray30",command=self.change_master_password).pack(fill="x",padx=12,pady=4)

        github_link=ctk.CTkLabel(
            side,
            text="GitHub — syltia",
            text_color="#5fa8ff",
            cursor="hand2",
            font=ctk.CTkFont(size=12,underline=True)
        )
        github_link.pack(side="bottom",anchor="w",padx=18,pady=(0,10))
        github_link.bind(
            "<Button-1>",
            lambda _event: webbrowser.open_new_tab("https://github.com/syltia")
        )

        self.active_server_label=ctk.CTkLabel(
            side,text="Server: —",text_color="gray65",anchor="w",font=ctk.CTkFont(size=11)
        )
        self.active_server_label.pack(side="bottom",anchor="w",padx=18,pady=(0,4))

        self.conn_label=ctk.CTkLabel(side,text="● Déconnecté",text_color="#d9534f")
        self.conn_label.pack(side="bottom",anchor="w",padx=18,pady=(8,8))

        lang_row=ctk.CTkFrame(side,fg_color="transparent")
        lang_row.pack(side="bottom",fill="x",padx=12,pady=(4,2))
        ctk.CTkLabel(lang_row,text="Language",width=82,anchor="w").pack(side="left")
        self.language_menu=ctk.CTkOptionMenu(
            lang_row,values=["EN","FR"],variable=self.language,width=92
        )
        self.language_menu.pack(side="right")

        # StringVar trace is more reliable than relying only on CTkOptionMenu.command.
        self._language_trace_busy=False
        self.language.trace_add("write", self._on_language_var_changed)

        self.main=ctk.CTkFrame(self,fg_color="transparent")
        self.main.grid(row=0,column=1,sticky="nsew",padx=18,pady=18)
        self.main.grid_columnconfigure(0,weight=1)
        self.main.grid_rowconfigure(0,weight=1)

        self.make_connection()
        self.make_dashboard()
        self.make_installer()
        self.make_accounts()
        self.make_characters()
        self.make_backups()
        self.make_console()
        self.make_files()
        self.after(20,self.apply_language)
        self.after(100,self.drain)
        self.after(150,self.security_gate)
        self.after(1200,self.monitor_tick)
        self.protocol("WM_DELETE_WINDOW",self.close)


    # ---------- Language ----------
    _EN_TEXT = {
        "Comptes & droits":"Accounts & permissions",
        "Personnages":"Characters",
        "Sauvegardes":"Backups",
        "Fichiers":"Files",
        "Connexion":"Connection",
        "🔒 Verrouiller":"🔒 Lock",
        "Changer mot de passe":"Change password",
        "● Déconnecté":"● Disconnected",
        "Connexion SSH":"SSH connection",
        "Connexion à la VM locale, publique ou via DNS":"Connect to a local/public VM or DNS host",
        "IP / domaine":"IP / domain",
        "Utilisateur":"User",
        "Mot de passe":"Password",
        "Clé SSH (optionnel)":"SSH key (optional)",
        "Parcourir":"Browse",
        "Sauvegarder le mot de passe SSH chiffré":"Save encrypted SSH password",
        "Chiffrement lié au mot de passe maître de l'application":"Encryption is tied to the application master password",
        "Se connecter":"Connect",
        "Déconnexion":"Disconnect",
        "Sauvegarder les infos":"Save settings",
        "État du serveur et monitoring en temps réel":"Server status and real-time monitoring",
        "Utilisation CPU":"CPU usage",
        "Mémoire RAM":"RAM memory",
        "Disque /":"Disk /",
        "Réseau":"Network",
        "Comptes WoW, niveau GM et permissions RBAC":"WoW accounts, GM level and RBAC permissions",
        "Nom du compte":"Account name",
        "Email (optionnel)":"Email (optional)",
        "GM level (0-3)":"GM level (0-3)",
        "Créer":"Create",
        "Appliquer GM":"Apply GM",
        "Lister comptes":"List accounts",
        "Lister les comptes":"List accounts",
        "Permissions RBAC":"RBAC permissions",
        "Lister droits":"List permissions",
        "Rôles rapides :":"Quick roles:",
        "Realm -1 = tous les realms":"Realm -1 = all realms",
        "Sélectionner ce compte":"Select account",
        "Fermer":"Close",
        "Fiche personnage, changements de compte et actions AzerothCore":"Character details, account moves and AzerothCore actions",
        "Compte":"Account",
        "Lister":"List",
        "Lister tous les persos humains":"List all human characters",
        "Personnage":"Character",
        "Charger fiche":"Load details",
        "Actions personnage":"Character actions",
        "Sauvegarde complète":"Full backup",
        "Bases MySQL":"MySQL databases",
        "Configs serveur":"Server configs",
        "Sauvegarde Playerbots":"Playerbots backup",
        "Crée une sauvegarde du module mod-playerbots complet ainsi que de playerbots.conf. Ce bouton n’applique PAS le patch de niveau dynamique 60/70/80 et ne modifie aucun fichier du serveur.":"Creates a backup of the full mod-playerbots module and playerbots.conf. This button does NOT apply the dynamic 60/70/80 level-cap patch and does not modify any server files.",


        "Actualiser":"Refresh",
        "Ouvrir le dossier":"Open folder",
        "Supprimer le backup":"Delete backup",
        "Backups datés avant de casser quelque chose xD":"Dated backups before breaking something xD",
        "Console SSH interactive":"Interactive SSH console",
        "Session persistante — alias, cd et tmux fonctionnent":"Persistent session — aliases, cd and tmux work",
        "Envoyer":"Send",
        "SFTP — Double vue":"SFTP — Dual pane",
        "Explorateur local ↔ serveur façon WinSCP":"Local ↔ server explorer, WinSCP style",
        "Rechercher un fichier ou dossier...":"Search for a file or folder...",
        "Chercher local":"Search local",
        "Chercher serveur":"Search server",
        "PC LOCAL":"LOCAL PC",
        "TRANSFERT":"TRANSFER",
        "Télécharger":"Download",
        "SERVEUR SFTP":"SFTP SERVER",
        "Nouveau dossier serveur":"New server folder",
        "Supprimer":"Delete",
        "Ouvrir dossier local":"Open local folder",
        "Prêt":"Ready",
        "Étape 1 - Préparer Debian":"Step 1 - Prepare Debian",
        "Envoyer setup.sh":"Upload setup.sh",
        "Envoyer finalize.sh":"Upload finalize.sh",
        "Envoyer les deux":"Upload both",
        "Classe":"Class",
        "Niveau":"Level",
        "Argent":"Money",
        "Changer race":"Change race",
        "Changer faction":"Change faction",
        "Apparence":"Appearance",
        "Renommer":"Rename",
        "Reset sorts":"Reset spells",
        "Appliquer niveau":"Apply level",
        "Compte cible":"Target account",
        "Déplacer":"Move",
        "Supprimer personnage":"Delete character",
        "Créer depuis un personnage modèle":"Create from a template character",
        "Utilise pdump pour éviter des INSERT SQL fragiles dans la base personnages.":"Uses pdump to avoid fragile SQL INSERTs in the character database.",
        "Modèle":"Template",
        "Nouveau nom":"New name",
        "Connecté":"Connected",
        "● Connecté":"● Connected",
        "Destination distante : /root/setup.sh  •  /root/finalize.sh":"Remote destination: /root/setup.sh  •  /root/finalize.sh",
        "Actualiser maintenant":"Refresh now",
        "Profil serveur":"Server profile",
        "Nouveau":"New",
        "Renommer":"Rename",
        "Supprimer":"Delete",
        "Sauvegarder ce profil":"Save this profile",

        "Playerbots patch":"Playerbots patch",
        "Patch Playerbots — limite dynamique":"Playerbots — Dynamic level cap",
        "Adapte le niveau maximum des bots au joueur réel le plus haut : 1–60 → 60, 61–70 → 70, 71–80 → 80. Les bots sont exclus du calcul.":"Adapts the maximum bot level to the highest real player: 1–60 → 60, 61–70 → 70, 71–80 → 80. Bots are excluded from the calculation.",
        "⚠ Le Worldserver doit être arrêté avant d'appliquer ce patch.":"⚠ Worldserver must be stopped before applying this patch.",
        "Configuration requise dans playerbots.conf :":"Required settings in playerbots.conf:",
        "Après application du patch et compilation, exécute cette commande dans la console AzerothCore :":"After applying the patch and compiling, run this command in the AzerothCore console:",
        "Puis redémarre le Worldserver pour repartir avec le plafond dynamique actif.":"Then restart Worldserver so it starts with the dynamic cap active.",
        "Copier":"Copy",

        "Ce patch modifie Playerbots pour imposer un plafond dynamique basé sur le plus haut niveau d’un vrai joueur connecté.":"This patch modifies Playerbots to enforce a dynamic cap based on the highest level of a real connected player.",
        "1–60 → bots max 60  •  61–70 → bots max 70  •  71–80 → bots max 80":"1–60 → bots max 60  •  61–70 → bots max 70  •  71–80 → bots max 80",
        "Les Playerbots ne comptent pas dans le calcul. Sans vrai joueur connecté, le plafond retombe à 60.":"Playerbots are excluded from the calculation. With no real player connected, the cap falls back to 60.",
        "Configuration requise dans playerbots.conf : AiPlayerbot.SyncLevelWithPlayers = 1, AiPlayerbot.LevelBrackets.Enabled = 1, AiPlayerbot.LevelBrackets.FlaggedProcessLimit = 0.":"Required playerbots.conf settings: AiPlayerbot.SyncLevelWithPlayers = 1, AiPlayerbot.LevelBrackets.Enabled = 1, AiPlayerbot.LevelBrackets.FlaggedProcessLimit = 0.",
        "Après application du patch et compilation, lance playerbots rndbot reset puis redémarre le serveur.":"After applying the patch and compiling, run playerbots rndbot reset and then restart the server.",


        "Processus serveur":"Server processes",
        "Système":"System",
        "Serveur : —":"Server: —",
        "Dernière maj : —":"Last update: —",
        "En attente…":"Waiting…",
        "Installation serveur":"Server installation",
        "Scripts Azeroth Eras intégrés — envoi vers la machine distante via SSH/SFTP":"Built-in Azeroth Eras scripts — upload to the remote machine via SSH/SFTP",
        "Préparation d'un nouveau serveur":"Preparing a new server",
        "Connexion SSH ROOT requise pour l’installation serveur. L’étape 1 met Debian à jour et installe les dépendances avant le lancement de setup.sh.":"ROOT SSH connection required for server installation. Step 1 updates Debian and installs dependencies before running setup.sh.",
        "Ouvrir la console":"Open console",
    }

    def _on_language_var_changed(self, *_):
        if getattr(self, "_language_trace_busy", False):
            return
        value=self.language.get()
        if value not in ("EN","FR"):
            return
        self.after_idle(self._apply_language_from_trace)

    def _apply_language_from_trace(self):
        if getattr(self, "_language_trace_busy", False):
            return
        self._language_trace_busy=True
        try:
            # UI-only refresh: keep the existing SSH/SFTP session untouched.
            self.apply_language()
            self._save_language_only()
        finally:
            self._language_trace_busy=False

    def _save_language_only(self):
        """Persist language without touching SSH/SFTP or rebuilding the connection."""
        try:
            if not isinstance(self._saved_settings,dict):
                self._saved_settings={}
            self._saved_settings.setdefault("ui",{})["language"]=self.language.get()
            # Before unlock, only update the bootstrap header if an encrypted file exists.
            if self._fernet is not None:
                self._write_settings_file(self._saved_settings)
            elif self.settings_file.exists():
                raw=self.settings_file.read_bytes()
                if raw.startswith(b"AEC1") and len(raw)>=8:
                    hlen=int.from_bytes(raw[4:8],"big")
                    header=json.loads(raw[8:8+hlen].decode("utf-8"))
                    header["language"]=self.language.get()
                    hb=json.dumps(header,separators=(",",":"),ensure_ascii=False).encode("utf-8")
                    blob=b"AEC1"+len(hb).to_bytes(4,"big")+hb+raw[8+hlen:]
                    tmp=self.settings_file.with_suffix(".tmp")
                    tmp.write_bytes(blob)
                    os.replace(tmp,self.settings_file)
        except Exception:
            pass

    def set_language(self, value=None):
        # Kept as a public helper for code paths that may call it directly.
        value=value if value in ("EN","FR") else self.language.get()
        if value not in ("EN","FR"):
            value="FR"
        if self.language.get()!=value:
            self.language.set(value)  # trace applies the UI refresh
        else:
            self.apply_language()

    def apply_language(self):
        """Refresh visible UI language only.

        Important: this must never rebuild pages or touch SSH/SFTP/shell state.
        Only text-bearing widgets are updated in place.
        """
        lang=self.language.get() if hasattr(self,"language") else "EN"
        en_to_fr={v:k for k,v in self._EN_TEXT.items()}

        def canonical_fr(text):
            return en_to_fr.get(text,text)

        # Only touch text-capable widgets. Do not rebuild frames/pages and do not
        # recreate connection/session objects.
        for widget in self.winfo_children():
            stack=[widget]
            while stack:
                current_widget=stack.pop()
                try:
                    children=current_widget.winfo_children()
                    if children:
                        stack.extend(children)
                except Exception:
                    pass

                try:
                    current=current_widget.cget("text")
                except Exception:
                    continue

                try:
                    src=getattr(current_widget,"_aeras_fr_text",None)
                    if src is None:
                        src=canonical_fr(current)
                    else:
                        src=canonical_fr(src)
                    current_widget._aeras_fr_text=src
                    target=self._EN_TEXT.get(src,src) if lang=="EN" else src
                    if current != target:
                        current_widget.configure(text=target)
                except Exception:
                    pass

        try:
            self.language_menu.set(lang)
        except Exception:
            pass

        try:
            if hasattr(self,"backup_tree"):
                self.backup_tree.heading("date",text="Date")
                self.backup_tree.heading(
                    "path",
                    text="Backup folder" if lang=="EN" else "Dossier de sauvegarde"
                )
        except Exception:
            pass

        # Dynamic connection label is language-aware without touching connection state.
        try:
            current_conn=getattr(self,"_conn_state","disconnected")
            self._render_connection_state(current_conn)
        except Exception:
            pass

    def _render_connection_state(self, state):
        self._conn_state=state
        if not hasattr(self,"conn_label"):
            return
        lang=self.language.get() if hasattr(self,"language") else "EN"
        labels={
            "connecting": ("● Connecting…","● Connexion…","#d6a84b"),
            "connected": ("● Connected","● Connecté","#4caf50"),
            "failed": ("● Failed","● Échec","#d9534f"),
            "disconnected": ("● Disconnected","● Déconnecté","#d9534f"),
        }
        en,fr,color=labels.get(state,labels["disconnected"])
        self.conn_label.configure(text=en if lang=="EN" else fr,text_color=color)

        if hasattr(self,"active_server_label"):
            if state=="connected":
                profile=self.profile_name.get().strip() if hasattr(self,"profile_name") else "Default"
                host=self.host.get().strip() if hasattr(self,"host") else ""
                if not profile:
                    profile="Default"
                text=(f"Server: {profile} — {host}" if lang=="EN"
                      else f"Serveur : {profile} — {host}")
            else:
                text="Server: —" if lang=="EN" else "Serveur : —"
            self.active_server_label.configure(text=text)

    def base(self,name,title,sub):
        p=ctk.CTkFrame(self.main,fg_color="transparent")
        p.grid(row=0,column=0,sticky="nsew")
        self.pages[name]=p
        ctk.CTkLabel(p,text=title,font=ctk.CTkFont(size=28,weight="bold")).pack(anchor="w")
        ctk.CTkLabel(p,text=sub,text_color="gray65").pack(anchor="w",pady=(2,14))
        return p

    # ---------- Sécurité locale ----------
    def _read_settings_file(self):
        """Read encrypted AEC envelope bootstrap or migrate legacy JSON in memory."""
        try:
            if self.settings_file.exists():
                raw=self.settings_file.read_bytes()
                if not raw.startswith(b"AEC1"):
                    return {}
                if len(raw) < 8:
                    return {}
                hlen=int.from_bytes(raw[4:8],"big")
                header=json.loads(raw[8:8+hlen].decode("utf-8"))
                self._encrypted_payload=raw[8+hlen:]
                return {
                    "security":header.get("security",{}),
                    "ui":{"language":header.get("language","EN")}
                }
        except Exception:
            return {}

        # One-time legacy migration source. It is removed only after a successful
        # encrypted write, never before.
        try:
            if self.legacy_settings_file.exists():
                with open(self.legacy_settings_file,"r",encoding="utf-8") as f:
                    data=json.load(f)
                self._legacy_settings_pending=data
                return data
        except Exception:
            pass
        return {}

    def _write_settings_file(self,data):
        """Write settings as an authenticated encrypted binary .aec container."""
        f=self._fernet
        if f is None and self._master_password:
            sec=data.get("security",{})
            if sec.get("salt"):
                f=self._derive_fernet(self._master_password,sec["salt"])

        # During first master-password creation the caller may not have assigned
        # self._fernet yet. Keep data in memory until the key is available.
        if f is None:
            self._saved_settings=data
            return

        sec=data.get("security",{})
        lang=data.get("ui",{}).get("language","EN")
        header={
            "version":1,
            "security":sec,
            "language":lang if lang in ("EN","FR") else "EN"
        }
        hb=json.dumps(header,separators=(",",":"),ensure_ascii=False).encode("utf-8")

        # Security bootstrap metadata is stored in the binary header so the app
        # can derive/verify the key. All profiles, hosts, users, preferences and
        # saved credentials are inside the encrypted payload.
        payload_data=dict(data)
        payload_data.pop("security",None)
        token=f.encrypt(
            json.dumps(payload_data,separators=(",",":"),ensure_ascii=False).encode("utf-8")
        )
        blob=b"AEC1"+len(hb).to_bytes(4,"big")+hb+token

        tmp=self.settings_file.with_suffix(".tmp")
        tmp.write_bytes(blob)
        os.replace(tmp,self.settings_file)

        # Successful migration: remove the old readable JSON.
        try:
            if self.legacy_settings_file.exists():
                self.legacy_settings_file.unlink()
            if self.legacy_appdata_dir.exists() and not any(self.legacy_appdata_dir.iterdir()):
                self.legacy_appdata_dir.rmdir()
        except Exception:
            pass

    def _unlock_encrypted_settings(self,fernet_obj):
        """Decrypt payload after the master password has been verified."""
        payload=getattr(self,"_encrypted_payload",None)
        if not payload:
            return self._saved_settings
        plain=fernet_obj.decrypt(payload)
        body=json.loads(plain.decode("utf-8"))
        body["security"]=self._saved_settings.get("security",{})
        # language is bootstrap metadata and remains authoritative at lock screen.
        body.setdefault("ui",{})["language"]=self._saved_settings.get("ui",{}).get("language","EN")
        self._saved_settings=body
        return body


    def _derive_fernet(self, password, salt_b64):
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=390000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
        return Fernet(key)

    def _make_recovery_code(self):
        alphabet="ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        groups=["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(5)]
        return "AERAS-"+"-".join(groups)

    def _derive_recovery_fernet(self, recovery_code, salt_b64):
        return self._derive_fernet(recovery_code.strip().upper(), salt_b64)

    def _derive_master_key_bytes(self, password, salt_b64):
        salt=base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        kdf=PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=390000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))

    def _show_recovery_code_dialog(self, recovery_code, parent=None):
        dlg=ctk.CTkToplevel(self)
        dlg.title("Code de récupération")
        dlg.geometry("560x330")
        dlg.resizable(False,False)
        dlg.grab_set()

        ctk.CTkLabel(
            dlg,text="CODE DE RÉCUPÉRATION",
            font=ctk.CTkFont(size=22,weight="bold")
        ).pack(pady=(25,8))
        ctk.CTkLabel(
            dlg,
            text="Conserve ce code hors du PC. Il permet de remplacer le mot de passe maître si tu l'oublies.",
            wraplength=490,justify="center",text_color="gray70"
        ).pack(pady=(0,16))

        box=ctk.CTkEntry(dlg,font=("Consolas",18),justify="center")
        box.insert(0,recovery_code)
        box.configure(state="readonly")
        box.pack(fill="x",padx=35,pady=8)

        def copy_code():
            self.clipboard_clear()
            self.clipboard_append(recovery_code)
            messagebox.showinfo("Récupération","Code copié.",parent=dlg)

        ctk.CTkButton(dlg,text="Copier le code",command=copy_code).pack(pady=(10,6))
        ctk.CTkLabel(
            dlg,text="Attention : ce code ne sera plus réaffiché après fermeture.",
            text_color="#d6a94b"
        ).pack(pady=5)
        ctk.CTkButton(dlg,text="J'ai sauvegardé le code",command=dlg.destroy).pack(pady=10)

    def _reset_local_security(self, unlock_dialog):
        answer=messagebox.askyesno(
            "Réinitialiser Azeroth Eras Control",
            "Tu n'as plus le mot de passe maître ni le code de récupération ?\n\n"
            "Cette action efface UNIQUEMENT la configuration locale de l'application :\n"
            "• connexion SSH enregistrée\n"
            "• mot de passe SSH chiffré\n"
            "• préférences locales\n\n"
            "AUCUNE donnée du serveur AzerothCore, MySQL, personnage ou sauvegarde distante ne sera supprimée.\n\n"
            "Continuer ?",
            parent=unlock_dialog
        )
        if not answer:
            return

        confirm=ctk.CTkInputDialog(
            text='Tape exactement RESET pour confirmer la suppression de la configuration locale.',
            title="Confirmation définitive"
        ).get_input()

        if confirm != "RESET":
            messagebox.showinfo(
                "Annulé",
                "Réinitialisation annulée.",
                parent=unlock_dialog
            )
            return

        try:
            if self.ssh:
                try:self.ssh.close()
                except:pass
            self.ssh=self.sftp=None
            self.shell=None
            self._fernet=None
            self._master_password=None

            if self.settings_file.exists():
                self.settings_file.unlink()
            if self.legacy_settings_file.exists():
                self.legacy_settings_file.unlink()

            self._saved_settings={}
            unlock_dialog.destroy()
            messagebox.showinfo(
                "Configuration réinitialisée",
                "La configuration locale a été effacée.\n"
                "Le serveur n'a pas été modifié.\n\n"
                "Tu peux maintenant créer un nouveau mot de passe maître."
            )
            self._show_setup_master_dialog()
        except Exception as e:
            messagebox.showerror(
                "Erreur",
                f"Impossible d'effacer la configuration locale :\n{e}",
                parent=unlock_dialog
            )

    def _show_password_recovery_dialog(self, unlock_dialog):
        sec=self._saved_settings.get("security",{})
        if not sec.get("recovery_verifier") or not sec.get("recovery_salt"):
            messagebox.showwarning(
                "Récupération",
                "Cette configuration a été créée avant l'ajout du code de récupération. "
                "Il faut encore connaître le mot de passe maître actuel pour activer cette fonction.",
                parent=unlock_dialog
            )
            return

        dlg=ctk.CTkToplevel(self)
        dlg.title("Récupérer l'accès")
        dlg.geometry("500x390")
        dlg.resizable(False,False)
        dlg.grab_set()

        ctk.CTkLabel(
            dlg,text="Mot de passe oublié",
            font=ctk.CTkFont(size=22,weight="bold")
        ).pack(pady=(24,8))
        ctk.CTkLabel(
            dlg,text="Entre ton code de récupération puis choisis un nouveau mot de passe maître.",
            wraplength=430,justify="center",text_color="gray70"
        ).pack(pady=(0,15))

        code=ctk.CTkEntry(dlg,placeholder_text="AERAS-XXXX-XXXX-XXXX-XXXX-XXXX")
        code.pack(fill="x",padx=38,pady=5)
        new1=ctk.CTkEntry(dlg,show="*",placeholder_text="Nouveau mot de passe maître")
        new1.pack(fill="x",padx=38,pady=5)
        new2=ctk.CTkEntry(dlg,show="*",placeholder_text="Confirmer le nouveau mot de passe")
        new2.pack(fill="x",padx=38,pady=5)

        def recover():
            recovery_code=code.get().strip().upper()
            try:
                rf=self._derive_recovery_fernet(recovery_code,sec["recovery_salt"])
                if rf.decrypt(sec["recovery_verifier"].encode("ascii")) != b"AERAS_RECOVERY_OK":
                    raise InvalidToken()
            except Exception:
                messagebox.showerror("Récupération","Code de récupération incorrect.",parent=dlg)
                return

            if len(new1.get()) < 6 or new1.get()!=new2.get():
                messagebox.showwarning(
                    "Récupération",
                    "Le nouveau mot de passe doit faire au moins 6 caractères et les deux champs doivent correspondre.",
                    parent=dlg
                )
                return

            # The recovery code unwraps the previous master encryption key.
            # This keeps saved SSH credentials recoverable without storing them in clear text.
            conn=self._saved_settings.get("connection",{})
            plain_password=None
            try:
                old_key=rf.decrypt(sec["recovery_master_key"].encode("ascii"))
                oldf=Fernet(old_key)
                if conn.get("password_enc"):
                    plain_password=oldf.decrypt(
                        conn["password_enc"].encode("ascii")
                    )
            except Exception:
                plain_password=None

            new_salt=base64.urlsafe_b64encode(os.urandom(16)).decode("ascii")
            newf=self._derive_fernet(new1.get(),new_salt)
            sec["salt"]=new_salt
            sec["verifier"]=newf.encrypt(b"EMBER_ADMIN_OK").decode("ascii")
            sec["recovery_master_key"]=rf.encrypt(
                self._derive_master_key_bytes(new1.get(),new_salt)
            ).decode("ascii")

            if plain_password is not None:
                conn["password_enc"]=newf.encrypt(plain_password).decode("ascii")

            self._saved_settings["security"]=sec
            self._saved_settings["connection"]=conn
            self._fernet=newf
            self._master_password=new1.get()
            self._write_settings_file(self._saved_settings)

            dlg.destroy()
            unlock_dialog.destroy()
            self.load_settings()
            self.show("Dashboard")
            messagebox.showinfo("Récupération","Nouveau mot de passe maître enregistré.")

        ctk.CTkButton(dlg,text="Réinitialiser le mot de passe",command=recover).pack(pady=18)

    def security_gate(self):
        data = self._saved_settings
        if data.get("security", {}).get("enabled"):
            self._show_unlock_dialog()
        else:
            self._show_setup_master_dialog()

    def _show_setup_master_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Sécuriser Azeroth Eras Control")
        dlg.geometry("470x330")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.protocol("WM_DELETE_WINDOW", self.destroy)

        ctk.CTkLabel(dlg,text="Première ouverture",font=ctk.CTkFont(size=24,weight="bold")).pack(pady=(26,6))
        ctk.CTkLabel(dlg,text="Crée un mot de passe maître pour protéger les identifiants SSH.",wraplength=410,justify="center",text_color="gray70").pack(pady=(0,18))

        p1=ctk.CTkEntry(dlg,show="*",placeholder_text="Mot de passe maître")
        p1.pack(fill="x",padx=42,pady=6)
        p2=ctk.CTkEntry(dlg,show="*",placeholder_text="Confirmer")
        p2.pack(fill="x",padx=42,pady=6)

        def create():
            a=p1.get()
            b=p2.get()
            if len(a) < 6:
                messagebox.showwarning("Sécurité","Utilise au moins 6 caractères.",parent=dlg); return
            if a != b:
                messagebox.showwarning("Sécurité","Les mots de passe ne correspondent pas.",parent=dlg); return
            salt_b64 = base64.urlsafe_b64encode(os.urandom(16)).decode("ascii")
            f = self._derive_fernet(a, salt_b64)
            verifier = f.encrypt(b"EMBER_ADMIN_OK").decode("ascii")
            data = self._saved_settings or {}
            recovery_code=self._make_recovery_code()
            recovery_salt=base64.urlsafe_b64encode(os.urandom(16)).decode("ascii")
            rf=self._derive_recovery_fernet(recovery_code,recovery_salt)
            data["security"] = {
                "enabled": True,
                "salt": salt_b64,
                "verifier": verifier,
                "kdf": "PBKDF2-HMAC-SHA256",
                "iterations": 390000,
                "recovery_salt": recovery_salt,
                "recovery_verifier": rf.encrypt(b"AERAS_RECOVERY_OK").decode("ascii"),
                "recovery_master_key": rf.encrypt(
                    self._derive_master_key_bytes(a,salt_b64)
                ).decode("ascii")
            }
            self._master_password = a
            self._fernet = f
            self._saved_settings = data
            self._write_settings_file(data)
            dlg.destroy()
            self.load_settings()
            self.show("Dashboard")
            self._show_recovery_code_dialog(recovery_code)

        ctk.CTkButton(dlg,text="Créer et ouvrir Azeroth Eras Control",command=create).pack(pady=20)

    def _show_unlock_dialog(self):
        lang=self.language.get() if self.language.get() in ("EN","FR") else "EN"
        en=(lang=="EN")

        dlg = ctk.CTkToplevel(self)
        dlg.title("Azeroth Eras Control — Locked" if en else "Azeroth Eras Control — Verrouillé")
        dlg.geometry("430x390")
        dlg.resizable(False,False)
        dlg.grab_set()
        dlg.protocol("WM_DELETE_WINDOW",self.destroy)

        ctk.CTkLabel(dlg,text="AZEROTH ERAS",font=ctk.CTkFont(size=24,weight="bold")).pack(pady=(24,4))
        subtitle=ctk.CTkLabel(
            dlg,
            text="Enter master password" if en else "Entre le mot de passe maître",
            text_color="gray70"
        )
        subtitle.pack(pady=(0,12))

        entry=ctk.CTkEntry(
            dlg,show="*",
            placeholder_text="Master password" if en else "Mot de passe maître"
        )
        entry.pack(fill="x",padx=42)
        entry.focus_set()

        def unlock(event=None):
            password=entry.get()
            sec=self._saved_settings.get("security",{})
            try:
                f=self._derive_fernet(password,sec["salt"])
                if f.decrypt(sec["verifier"].encode("ascii")) != b"EMBER_ADMIN_OK":
                    raise InvalidToken()
                self._master_password=password
                self._fernet=f
                self._unlock_encrypted_settings(f)
                # Legacy readable JSON is migrated immediately after successful unlock.
                if getattr(self,"_legacy_settings_pending",None) is not None:
                    self._write_settings_file(self._saved_settings)
                    self._legacy_settings_pending=None
                dlg.destroy()
                self.load_settings()
                self.show("Dashboard")
            except Exception:
                messagebox.showerror(
                    "Access denied" if self.language.get()=="EN" else "Accès refusé",
                    "Incorrect master password." if self.language.get()=="EN" else "Mot de passe maître incorrect.",
                    parent=dlg
                )
                entry.delete(0,"end")

        entry.bind("<Return>",unlock)

        unlock_btn=ctk.CTkButton(dlg,text="Unlock" if en else "Déverrouiller",command=unlock)
        unlock_btn.pack(pady=(16,7))
        forgot_btn=ctk.CTkButton(
            dlg,text="Forgot password?" if en else "Mot de passe oublié ?",
            fg_color="gray30",
            command=lambda:self._show_password_recovery_dialog(dlg)
        )
        forgot_btn.pack(pady=(0,7))
        reset_btn=ctk.CTkButton(
            dlg,text="Reset all local data" if en else "Tout réinitialiser localement",
            fg_color="#8c3434",
            command=lambda:self._reset_local_security(dlg)
        )
        reset_btn.pack(pady=(0,10))

        # The app can be locked before the main sidebar is usable, so language
        # must also be switchable directly from the lock screen.
        lang_row=ctk.CTkFrame(dlg,fg_color="transparent")
        lang_row.pack(side="bottom",fill="x",padx=42,pady=(4,14))
        lang_label=ctk.CTkLabel(lang_row,text="Language" if en else "Langue",anchor="w")
        lang_label.pack(side="left")
        lock_lang=ctk.CTkOptionMenu(lang_row,values=["EN","FR"],width=92)
        lock_lang.set(lang)
        lock_lang.pack(side="right")

        def switch_lock_language(value):
            if value not in ("EN","FR"):
                return
            self.language.set(value)
            self._save_language_only()
            is_en=(value=="EN")
            dlg.title("Azeroth Eras Control — Locked" if is_en else "Azeroth Eras Control — Verrouillé")
            subtitle.configure(text="Enter master password" if is_en else "Entre le mot de passe maître")
            entry.configure(placeholder_text="Master password" if is_en else "Mot de passe maître")
            unlock_btn.configure(text="Unlock" if is_en else "Déverrouiller")
            forgot_btn.configure(text="Forgot password?" if is_en else "Mot de passe oublié ?")
            reset_btn.configure(text="Reset all local data" if is_en else "Tout réinitialiser localement")
            lang_label.configure(text="Language" if is_en else "Langue")

        lock_lang.configure(command=switch_lock_language)

    def save_settings(self):
        if not hasattr(self, "host"):
            return
        data = self._saved_settings or {}
        data.setdefault("security", {})
        profile = {
            "host": self.host.get().strip(),
            "port": self.port.get().strip(),
            "user": self.user.get().strip(),
            "key": self.key.get().strip(),
            "save_password": bool(self.save_password.get()),
        }
        if self.save_password.get() and self.password.get():
            if not self._fernet:
                messagebox.showerror("Sécurité","Application non déverrouillée.")
                return
            profile["password_enc"] = self._fernet.encrypt(self.password.get().encode("utf-8")).decode("ascii")
        else:
            profile.pop("password_enc", None)
        data["connection"] = profile
        if hasattr(self,"profile_name"):
            try:
                name=self.profile_name.get().strip() or "Default"
                data.setdefault("profiles",{})[name]=self._current_profile_payload()
            except Exception:
                pass
        data["ui"] = {
            "last_path": self.path.get().strip() if hasattr(self,"path") else "/root",
            "language": self.language.get() if hasattr(self,"language") else "EN",
            "active_profile": self.profile_name.get().strip() if hasattr(self,"profile_name") else "Default"
        }
        self._write_settings_file(data)
        self._saved_settings = data

    def load_settings(self):
        data = self._saved_settings or {}
        saved_lang=data.get("ui",{}).get("language","EN")
        if saved_lang in ("EN","FR") and hasattr(self,"language") and self.language.get()!=saved_lang:
            self.language.set(saved_lang)
        c=data.get("connection",{})
        if hasattr(self,"host"):
            self.host.set(c.get("host", self.host.get()))
            self.port.set(c.get("port", self.port.get()))
            self.user.set(c.get("user", self.user.get()))
            self.key.set(c.get("key",""))
            self.save_password.set(bool(c.get("save_password",False)))
            enc=c.get("password_enc")
            if enc and self._fernet:
                try:
                    self.password.set(self._fernet.decrypt(enc.encode("ascii")).decode("utf-8"))
                except Exception:
                    self.password.set("")
        if hasattr(self,"path"):
            last=data.get("ui",{}).get("last_path")
            if last:
                self.path.delete(0,"end")
                self.path.insert(0,last)

    # ---------- Server profiles ----------
    def _profiles_get(self):
        data=self._read_settings_file()
        profiles=data.setdefault("profiles",{})
        return data,profiles

    def _profile_names(self):
        _,profiles=self._profiles_get()
        return sorted(profiles.keys(),key=str.lower)

    def _refresh_profile_menu(self,select=None):
        if not hasattr(self,"profile_menu"):
            return
        names=self._profile_names() or ["Default"]
        self.profile_menu.configure(values=names)
        target=select if select in names else names[0]
        self._profile_switch_busy=True
        try:
            self.profile_name.set(target)
            self.profile_menu.set(target)
        finally:
            self._profile_switch_busy=False

    def _current_profile_payload(self):
        payload={
            "host":self.host.get().strip(),
            "port":self.port.get().strip(),
            "user":self.user.get().strip(),
            "key":self.key.get().strip(),
            "save_password":bool(self.save_password.get()),
        }
        if self.save_password.get() and self.password.get() and self._fernet:
            payload["password_enc"]=self._fernet.encrypt(
                self.password.get().encode("utf-8")
            ).decode("ascii")
        return payload

    def _save_profile_named(self,name):
        name=(name or "").strip()
        if not name:
            return False
        data,profiles=self._profiles_get()
        profiles[name]=self._current_profile_payload()
        data["profiles"]=profiles
        data.setdefault("ui",{})["active_profile"]=name
        self._write_settings_file(data)
        self._saved_settings=data
        return True

    def save_current_profile(self):
        name=self.profile_name.get().strip() or "Default"
        if self._save_profile_named(name):
            self._refresh_profile_menu(name)
            messagebox.showinfo(
                "Azeroth Eras Control",
                "Server profile saved." if self.language.get()=="EN" else "Profil serveur sauvegardé."
            )

    def _load_profile_named(self,name):
        data,profiles=self._profiles_get()
        profile=profiles.get(name)
        if not profile:
            return
        self.host.set(profile.get("host",""))
        self.port.set(profile.get("port","22"))
        self.user.set(profile.get("user","root"))
        self.key.set(profile.get("key",""))
        self.save_password.set(bool(profile.get("save_password",False)))
        self.password.set("")
        enc=profile.get("password_enc")
        if enc and self._fernet:
            try:
                self.password.set(self._fernet.decrypt(enc.encode("ascii")).decode("utf-8"))
            except Exception:
                self.password.set("")
        data.setdefault("ui",{})["active_profile"]=name
        self._write_settings_file(data)
        self._saved_settings=data

    def on_profile_selected(self,value):
        if getattr(self,"_profile_switch_busy",False):
            return
        value=(value or "").strip()
        if value:
            self._load_profile_named(value)

    def _ask_profile_name(self,title,prompt,initial=""):
        """CustomTkinter modal dialog that stays visible above the main window."""
        dlg=ctk.CTkToplevel(self)
        dlg.title(title)
        dlg.geometry("430x175")
        dlg.resizable(False,False)
        dlg.transient(self)

        result={"value":None}

        ctk.CTkLabel(
            dlg,text=prompt,font=ctk.CTkFont(size=15,weight="bold")
        ).pack(anchor="w",padx=20,pady=(20,8))

        entry=ctk.CTkEntry(dlg)
        entry.pack(fill="x",padx=20)
        if initial:
            entry.insert(0,initial)
            entry.select_range(0,"end")

        buttons=ctk.CTkFrame(dlg,fg_color="transparent")
        buttons.pack(fill="x",padx=20,pady=18)

        def accept():
            value=entry.get().strip()
            if value:
                result["value"]=value
                dlg.destroy()

        def cancel():
            dlg.destroy()

        ctk.CTkButton(
            buttons,
            text="OK",
            width=100,
            command=accept
        ).pack(side="right")
        ctk.CTkButton(
            buttons,
            text="Cancel" if self.language.get()=="EN" else "Annuler",
            width=100,
            fg_color="gray35",
            command=cancel
        ).pack(side="right",padx=(0,8))

        dlg.protocol("WM_DELETE_WINDOW",cancel)
        dlg.bind("<Return>",lambda _e:accept())
        dlg.bind("<Escape>",lambda _e:cancel())

        dlg.update_idletasks()
        try:
            x=self.winfo_rootx()+(self.winfo_width()-dlg.winfo_width())//2
            y=self.winfo_rooty()+(self.winfo_height()-dlg.winfo_height())//2
            dlg.geometry(f"+{max(0,x)}+{max(0,y)}")
        except Exception:
            pass

        dlg.lift()
        dlg.focus_force()
        entry.focus_set()
        dlg.grab_set()
        self.wait_window(dlg)
        return result["value"]

    def new_server_profile(self):
        lang=self.language.get()
        name=self._ask_profile_name(
            "New server profile" if lang=="EN" else "Nouveau profil serveur",
            "Profile name:" if lang=="EN" else "Nom du profil :"
        )
        if not name:
            return
        name=name.strip()
        if not name:
            return
        data,profiles=self._profiles_get()
        if name in profiles:
            messagebox.showerror(
                "Azeroth Eras Control",
                "This profile already exists." if lang=="EN" else "Ce profil existe déjà."
            )
            return
        profiles[name]={"host":"","port":"22","user":"root","key":"","save_password":False}
        data["profiles"]=profiles
        data.setdefault("ui",{})["active_profile"]=name
        self._write_settings_file(data)
        self._saved_settings=data
        self._refresh_profile_menu(name)
        self._load_profile_named(name)

    def rename_server_profile(self):
        old=self.profile_name.get().strip()
        if not old:
            return
        lang=self.language.get()
        name=self._ask_profile_name(
            "Rename server profile" if lang=="EN" else "Renommer le profil serveur",
            "New name:" if lang=="EN" else "Nouveau nom :",
            initial=old
        )
        if not name:
            return
        name=name.strip()
        if not name or name==old:
            return
        data,profiles=self._profiles_get()
        if name in profiles:
            messagebox.showerror(
                "Azeroth Eras Control",
                "This profile already exists." if lang=="EN" else "Ce profil existe déjà."
            )
            return
        if old not in profiles:
            profiles[old]=self._current_profile_payload()
        profiles[name]=profiles.pop(old)
        data["profiles"]=profiles
        data.setdefault("ui",{})["active_profile"]=name
        self._write_settings_file(data)
        self._saved_settings=data
        self._refresh_profile_menu(name)

    def delete_server_profile(self):
        name=self.profile_name.get().strip()
        if not name:
            return
        lang=self.language.get()
        if not messagebox.askyesno(
            "Azeroth Eras Control",
            f"Delete server profile '{name}'?" if lang=="EN"
            else f"Supprimer le profil serveur « {name} » ?"
        ):
            return
        data,profiles=self._profiles_get()
        profiles.pop(name,None)
        if not profiles:
            profiles["Default"]={"host":"","port":"22","user":"root","key":"","save_password":False}
        next_name=sorted(profiles.keys(),key=str.lower)[0]
        data["profiles"]=profiles
        data.setdefault("ui",{})["active_profile"]=next_name
        self._write_settings_file(data)
        self._saved_settings=data
        self._refresh_profile_menu(next_name)
        self._load_profile_named(next_name)

    def make_connection(self):
        p=self.base("Connexion","Connexion SSH","Connexion à la VM locale, publique ou via DNS")

        prof=ctk.CTkFrame(p)
        prof.pack(fill="x",pady=(0,10))
        ctk.CTkLabel(prof,text="Profil serveur",width=180,anchor="w").pack(side="left",padx=(18,8),pady=12)

        self.profile_name=ctk.StringVar(value="Default")
        self._profile_switch_busy=False
        self.profile_menu=ctk.CTkOptionMenu(
            prof,variable=self.profile_name,values=["Default"],
            command=self.on_profile_selected,width=220
        )
        self.profile_menu.pack(side="left",pady=12)

        ctk.CTkButton(prof,text="Nouveau",width=90,command=self.new_server_profile).pack(side="left",padx=(10,4))
        ctk.CTkButton(prof,text="Renommer",width=90,command=self.rename_server_profile).pack(side="left",padx=4)
        ctk.CTkButton(prof,text="Supprimer",width=90,fg_color="gray35",command=self.delete_server_profile).pack(side="left",padx=4)

        self.host=ctk.StringVar(value="192.168.0.212")
        self.port=ctk.StringVar(value="22")
        self.user=ctk.StringVar(value="root")
        self.password=ctk.StringVar()
        self.key=ctk.StringVar()

        card=ctk.CTkFrame(p); card.pack(fill="x")
        for label,var,secret in [
            ("IP / domaine",self.host,False),("Port",self.port,False),("Utilisateur",self.user,False),
            ("Mot de passe",self.password,True),("Clé SSH (optionnel)",self.key,False)]:
            r=ctk.CTkFrame(card,fg_color="transparent"); r.pack(fill="x",padx=18,pady=7)
            ctk.CTkLabel(r,text=label,width=180,anchor="w").pack(side="left")
            ctk.CTkEntry(r,textvariable=var,show="*" if secret else "").pack(side="left",fill="x",expand=True)
            if label.startswith("Clé"):
                ctk.CTkButton(r,text="Parcourir",width=100,command=self.pick_key).pack(side="left",padx=(8,0))

        r=ctk.CTkFrame(card,fg_color="transparent"); r.pack(fill="x",padx=18,pady=(8,2))
        self.save_password=ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(r,text="Sauvegarder le mot de passe SSH chiffré",variable=self.save_password).pack(side="left")
        ctk.CTkLabel(r,text="Chiffrement lié au mot de passe maître de l'application",text_color="gray65").pack(side="left",padx=14)

        r=ctk.CTkFrame(card,fg_color="transparent"); r.pack(fill="x",padx=18,pady=(8,18))
        ctk.CTkButton(r,text="Se connecter",command=self.connect).pack(side="left")
        ctk.CTkButton(r,text="Déconnexion",fg_color="gray35",command=self.disconnect).pack(side="left",padx=8)
        ctk.CTkButton(r,text="Sauvegarder ce profil",fg_color="gray35",command=self.save_current_profile).pack(side="right")

        data,profiles=self._profiles_get()
        if not profiles:
            profiles["Default"]=self._current_profile_payload()
            data["profiles"]=profiles
            data.setdefault("ui",{})["active_profile"]="Default"
            self._write_settings_file(data)
            self._saved_settings=data

        active=data.get("ui",{}).get("active_profile")
        if active not in profiles:
            active=sorted(profiles.keys(),key=str.lower)[0]
        self._refresh_profile_menu(active)
        self._load_profile_named(active)

    def make_dashboard(self):
        p=self.base("Dashboard","Dashboard","État du serveur et monitoring en temps réel")
        self.status={}

        # Services
        services=ctk.CTkFrame(p)
        services.pack(fill="x",pady=(0,10))
        for n in ["SSH","Authserver","Worldserver","MySQL","UFW"]:
            c=ctk.CTkFrame(services)
            c.pack(side="left",fill="x",expand=True,padx=5,pady=8)
            ctk.CTkLabel(c,text=n,font=ctk.CTkFont(weight="bold")).pack(pady=(8,1))
            self.status[n]=ctk.CTkLabel(c,text="INCONNU",text_color="#d6a94b")
            self.status[n].pack(pady=(0,8))

        # Server resource cards
        stats=ctk.CTkFrame(p)
        stats.pack(fill="x",pady=(0,10))
        self.monitor_labels={}
        self.monitor_bars={}

        specs=[
            ("CPU","Utilisation CPU"),
            ("RAM","Mémoire RAM"),
            ("DISK","Disque /"),
            ("NET","Réseau"),
        ]
        for key,title in specs:
            card=ctk.CTkFrame(stats)
            card.pack(side="left",fill="both",expand=True,padx=5,pady=8)

            ctk.CTkLabel(
                card,text=title,
                font=ctk.CTkFont(size=15,weight="bold")
            ).pack(anchor="w",padx=12,pady=(10,2))

            value=ctk.CTkLabel(
                card,text="—",
                font=ctk.CTkFont(size=21,weight="bold")
            )
            value.pack(anchor="w",padx=12)
            self.monitor_labels[key]=value

            if key!="NET":
                bar=ctk.CTkProgressBar(card)
                bar.set(0)
                bar.pack(fill="x",padx=12,pady=(8,4))
                self.monitor_bars[key]=bar

            detail=ctk.CTkLabel(
                card,text="En attente…",
                text_color="gray65",
                justify="left"
            )
            detail.pack(anchor="w",padx=12,pady=(4,10))
            self.monitor_labels[key+"_DETAIL"]=detail

        # General server information
        meta=ctk.CTkFrame(p)
        meta.pack(fill="x",pady=(0,10))
        self.monitor_labels["HOST"]=ctk.CTkLabel(
            meta,text="Serveur : —",anchor="w",
            font=ctk.CTkFont(weight="bold")
        )
        self.monitor_labels["HOST"].pack(side="left",padx=12,pady=9)

        self.monitor_labels["UPTIME"]=ctk.CTkLabel(
            meta,text="Uptime : —",anchor="w"
        )
        self.monitor_labels["UPTIME"].pack(side="left",padx=20,pady=9)

        self.monitor_labels["LOAD"]=ctk.CTkLabel(
            meta,text="Load : —",anchor="w"
        )
        self.monitor_labels["LOAD"].pack(side="left",padx=20,pady=9)

        self.monitor_labels["UPDATED"]=ctk.CTkLabel(
            meta,text="Dernière maj : —",anchor="e",text_color="gray65"
        )
        self.monitor_labels["UPDATED"].pack(side="right",padx=12,pady=9)

        # Actions
        act=ctk.CTkFrame(p)
        act.pack(fill="x",pady=(0,10))
        buttons=[
            ("▶ Start","bash /root/start.sh"),
            ("↻ Restart world","tmux send-keys -t world-session 'server restart 4' C-m"),
            ("■ Stop","tmux kill-server"),
            ("⚙ Compile","cd /root/azerothcore-wotlk && ./acore.sh compiler all"),
            ("↻ Update","cd /root/azerothcore-wotlk && git pull && cd modules/mod-playerbots && git pull"),
            ("🤖 Reset bots","tmux send-keys -t world-session 'playerbots rndbot reset' C-m")
        ]
        for t,c in buttons:
            ctk.CTkButton(
                act,text=t,command=lambda x=c:self.run(x)
            ).pack(side="left",expand=True,fill="x",padx=5,pady=10)

        # Crash detection
        crash=ctk.CTkFrame(p)
        crash.pack(fill="x",pady=(0,10))
        ctk.CTkLabel(
            crash,text="Crashes",
            font=ctk.CTkFont(size=16,weight="bold")
        ).pack(side="left",padx=(12,8),pady=10)
        self.crash_status=ctk.CTkLabel(crash,text="Not checked",text_color="#d6a94b")
        self.crash_status.pack(side="left",padx=8,pady=10)
        self.crash_details=ctk.CTkLabel(crash,text="",text_color="gray65")
        self.crash_details.pack(side="left",padx=8,pady=10)
        ctk.CTkButton(crash,text="Open crash folder",width=145,command=self.open_crash_folder).pack(side="right",padx=6,pady=8)
        ctk.CTkButton(crash,text="Analyze latest",width=135,command=self.analyze_latest_crash).pack(side="right",padx=6,pady=8)
        ctk.CTkButton(crash,text="Refresh crashes",width=135,command=self.refresh_crashes).pack(side="right",padx=6,pady=8)

        # Processes / details
        lower=ctk.CTkFrame(p)
        lower.pack(fill="both",expand=True)

        left=ctk.CTkFrame(lower)
        left.pack(side="left",fill="both",expand=True,padx=(0,5),pady=0)
        ctk.CTkLabel(
            left,text="Processus serveur",
            font=ctk.CTkFont(size=16,weight="bold")
        ).pack(anchor="w",padx=10,pady=(8,3))
        self.proc_info=ctk.CTkTextbox(left,height=135,font=("Consolas",12))
        self.proc_info.pack(fill="both",expand=True,padx=8,pady=(0,8))

        right=ctk.CTkFrame(lower)
        right.pack(side="left",fill="both",expand=True,padx=(5,0),pady=0)
        ctk.CTkLabel(
            right,text="Système",
            font=ctk.CTkFont(size=16,weight="bold")
        ).pack(anchor="w",padx=10,pady=(8,3))
        self.sys=ctk.CTkTextbox(right,height=135,font=("Consolas",12))
        self.sys.pack(fill="both",expand=True,padx=8,pady=(0,8))

        ctk.CTkButton(
            p,text="Actualiser maintenant",command=self.refresh
        ).pack(anchor="e",pady=(8,0))


    def refresh_crashes(self):
        if not self.ssh:
            return
        cmd=r"""DIR=/root/azerothcore-wotlk/env/dist/bin; find "$DIR" -maxdepth 1 -type f \( -name 'core' -o -name 'core.*' \) -printf '%T@\t%TY-%Tm-%Td %TH:%TM:%TS\t%s\t%p\n' 2>/dev/null | sort -nr"""
        def worker():
            try:
                out=self.exec(cmd).strip()
                rows=[]
                for line in out.splitlines():
                    parts=line.split("\t",3)
                    if len(parts)==4:
                        rows.append(parts)
                self.q.put(("crashes",rows))
            except Exception as exc:
                self.q.put(("crash_error",str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def open_crash_folder(self):
        if not self.need(): return
        self.show("Fichiers")
        self.path.delete(0,"end")
        self.path.insert(0,"/root/azerothcore-wotlk/env/dist/bin")
        self.list_remote()

    def analyze_latest_crash(self):
        if not self.need(): return
        cmd=r"""cd /root/azerothcore-wotlk/env/dist/bin && CORE=$(find . -maxdepth 1 -type f \( -name 'core' -o -name 'core.*' \) -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n1 | cut -d' ' -f2-) && if [ -z "$CORE" ]; then echo 'No core dump found.'; elif ! command -v gdb >/dev/null 2>&1; then echo 'gdb is not installed.'; else echo "Analyzing $CORE"; gdb -batch ./worldserver "$CORE" -ex 'thread apply all bt' 2>&1; fi"""
        self.show("Console")
        threading.Thread(target=lambda:self.q.put(("log",f"$ Analyze latest crash\\n{self.exec(cmd)}\\n")),daemon=True).start()

    def make_installer(self):
        p=self.base(
            "Installation",
            "Installation serveur",
            "Scripts Azeroth Eras intégrés — envoi vers la machine distante via SSH/SFTP"
        )

        info=ctk.CTkFrame(p)
        info.pack(fill="x",pady=(0,12))
        ctk.CTkLabel(
            info,
            text="Préparation d'un nouveau serveur",
            font=ctk.CTkFont(size=18,weight="bold")
        ).pack(anchor="w",padx=14,pady=(12,4))
        ctk.CTkLabel(
            info,
            text=(
                "Connexion SSH ROOT requise pour l’installation serveur. "
                "L’étape 1 met Debian à jour et installe les dépendances avant le lancement de setup.sh."
            ),
            wraplength=900,justify="left",text_color="gray70"
        ).pack(anchor="w",padx=14,pady=(0,6))

        install_git=ctk.CTkLabel(
            info,
            text="📖 Installation guide & documentation — GitHub",
            text_color="#5fa8ff",
            cursor="hand2",
            font=ctk.CTkFont(size=12,underline=True)
        )
        install_git.pack(anchor="w",padx=14,pady=(0,12))
        install_git.bind(
            "<Button-1>",
            lambda _event:webbrowser.open_new_tab("https://github.com/syltia/wow")
        )

        actions=ctk.CTkFrame(p)
        actions.pack(fill="x",pady=(0,12))
        ctk.CTkButton(
            actions,text="Étape 1 - Préparer Debian",
            command=self.install_server_prerequisites
        ).pack(side="left",padx=8,pady=12)
        ctk.CTkButton(
            actions,text="Envoyer setup.sh",
            command=lambda:self.upload_embedded_script("setup.sh","/root/setup.sh")
        ).pack(side="left",padx=8,pady=12)
        ctk.CTkButton(
            actions,text="Envoyer finalize.sh",
            command=lambda:self.upload_embedded_script("finalize.sh","/root/finalize.sh")
        ).pack(side="left",padx=8,pady=12)
        ctk.CTkButton(
            actions,text="Envoyer les deux",
            command=self.upload_install_scripts
        ).pack(side="left",padx=8,pady=12)

        ctk.CTkButton(
            actions,text="Ouvrir la console",
            fg_color="gray30",
            command=lambda:self.show("Console")
        ).pack(side="right",padx=8,pady=12)

        ctk.CTkLabel(
            p,
            text="Destination distante : /root/setup.sh  •  /root/finalize.sh",
            text_color="gray65"
        ).pack(anchor="w",pady=(0,8))

        self.install_out=ctk.CTkTextbox(p,font=("Consolas",13))
        self.install_out.pack(fill="both",expand=True)
        if self.language.get()=="EN":
            initial_install_text=(
                "Ready.\n\n"
                "ROOT is required for server installation.\n"
                "Step 1: update Debian and install dependencies.\n"
                "Then upload setup.sh/finalize.sh and run setup.sh.\n"
            )
        else:
            initial_install_text=(
                "Prêt.\n\n"
                "ROOT requis pour l'installation serveur.\n"
                "Étape 1 : mise à jour Debian + installation des dépendances.\n"
                "Puis envoie setup.sh/finalize.sh et lance setup.sh.\n"
            )
        self.install_out.insert("end",initial_install_text)

    def require_remote_root(self):
        if not self.need():
            return False
        try:
            _,o,e=self.ssh.exec_command("id -u")
            uid=o.read().decode(errors="replace").strip()
            _=e.read()
            if uid != "0":
                messagebox.showerror(
                    "Root required",
                    "Server installation requires a ROOT SSH connection.\n\n"
                    "Reconnect as root, then try again."
                )
                return False
            return True
        except Exception as exc:
            messagebox.showerror("Root check",f"Unable to verify remote user:\n{exc}")
            return False

    def install_server_prerequisites(self):
        if not self.require_remote_root():
            return

        packages="git curl unzip p7zip-full sudo tmux net-tools php php-mysqli ufw"
        cmd=(
            "export DEBIAN_FRONTEND=noninteractive; "
            "apt-get update && "
            "apt-get upgrade -y && "
            f"apt-get install -y {packages}"
        )

        if not messagebox.askyesno(
            "Étape 1 - Préparer Debian",
            "ROOT connection verified.\n\n"
            "This will update Debian and install the required packages:\n\n"
            + packages + "\n\nContinue?"
        ):
            return

        self.install_out.insert(
            "end",
            "\n--- 1. Mise à jour de Debian et installation des dépendances ---\n"
        )
        self.install_out.see("end")

        def worker():
            try:
                _,stdout,stderr=self.ssh.exec_command(cmd,get_pty=True)
                channel=stdout.channel

                while True:
                    if channel.recv_ready():
                        data=channel.recv(4096).decode("utf-8",errors="replace")
                        if data:
                            self.q.put(("install_log",data))
                    elif channel.exit_status_ready():
                        while channel.recv_ready():
                            data=channel.recv(4096).decode("utf-8",errors="replace")
                            if data:
                                self.q.put(("install_log",data))
                        break
                    else:
                        import time
                        time.sleep(0.04)

                rc=channel.recv_exit_status()

                def finish():
                    self.install_out.insert(
                        "end",
                        "\n==> Étape 1 terminée avec succès.\n" if rc == 0
                        else f"\n==> Échec de l'étape 1 (code {rc}).\n"
                    )
                    self.install_out.see("end")

                    if rc:
                        messagebox.showerror(
                            "Installation",
                            f"Debian/package installation failed (exit code {rc})."
                        )
                        return

                    _,o,_=self.ssh.exec_command("test -x /root/setup.sh && echo YES || echo NO")
                    exists=o.read().decode(errors="replace").strip()=="YES"

                    if not exists:
                        messagebox.showinfo(
                            "Step 1 complete",
                            "Debian update and package installation completed successfully.\n\n"
                            "Now upload setup.sh and finalize.sh using 'Envoyer les deux'."
                        )
                        return

                    if messagebox.askyesno(
                        "Step 1 complete",
                        "Debian update and package installation completed successfully.\n\n"
                        "Do you want to start the installation now?\n\n"
                        "Yes: ./setup.sh will be launched in the interactive console.\n"
                        "No: run ./setup.sh manually later."
                    ):
                        self.show("Console")
                        try:
                            self.shell.send("cd /root && ./setup.sh\n")
                        except Exception as exc:
                            messagebox.showerror(
                                "Installation",
                                f"Could not launch setup.sh:\n{exc}\n\nRun manually:\ncd /root\n./setup.sh"
                            )
                    else:
                        messagebox.showinfo(
                            "Installation",
                            "Installation was not started.\n\n"
                            "Run this later in the console:\n\ncd /root\n./setup.sh"
                        )
                self.after(0,finish)
            except Exception as exc:
                self.after(0,lambda err=exc:messagebox.showerror("Installation",str(err)))

        threading.Thread(target=worker,daemon=True).start()

    def _bundled_path(self,filename):
        # PyInstaller onefile extracts bundled files under sys._MEIPASS.
        import sys
        base=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))
        return base/filename

    def upload_embedded_script(self,filename,remote_path,quiet=False):
        if not self.require_remote_root():
            return False
        local=self._bundled_path(filename)
        if not local.exists():
            messagebox.showerror(
                "Installation",
                f"Script intégré introuvable : {filename}"
            )
            return False

        try:
            if not self.sftp:
                self.sftp=self.ssh.open_sftp()
            self.sftp.put(str(local),remote_path)
            self.sftp.chmod(remote_path,0o755)
            if hasattr(self,"install_out"):
                self.install_out.insert(
                    "end",
                    f"OK  {filename}  ->  {remote_path}  (chmod +x)\n"
                )
                self.install_out.see("end")
            if not quiet:
                messagebox.showinfo(
                    "Installation",
                    f"{filename} envoyé avec succès vers :\n{remote_path}"
                )
            return True
        except Exception as e:
            if hasattr(self,"install_out"):
                self.install_out.insert("end",f"ERREUR {filename}: {e}\n")
                self.install_out.see("end")
            if not quiet:
                messagebox.showerror("Installation",str(e))
            return False

    def upload_install_scripts(self):
        if not self.need():
            return
        ok1=self.upload_embedded_script("setup.sh","/root/setup.sh",quiet=True)
        ok2=self.upload_embedded_script("finalize.sh","/root/finalize.sh",quiet=True)
        if ok1 and ok2:
            messagebox.showinfo(
                "Installation",
                "setup.sh et finalize.sh ont été envoyés dans /root et rendus exécutables."
            )
        else:
            messagebox.showerror(
                "Installation",
                "Au moins un des deux scripts n'a pas pu être envoyé. Consulte le journal."
            )

    def make_accounts(self):
        p=self.base("Comptes & droits","Comptes & droits","Comptes WoW, niveau GM et permissions RBAC")
        card=ctk.CTkFrame(p); card.pack(fill="x",pady=(0,12))
        self.acc_name=ctk.StringVar(); self.acc_pass=ctk.StringVar(); self.acc_email=ctk.StringVar(); self.acc_gm=ctk.StringVar(value="0")
        for label,var,secret in [("Nom du compte",self.acc_name,False),("Mot de passe",self.acc_pass,True),("Email (optionnel)",self.acc_email,False),("GM level (0-3)",self.acc_gm,False)]:
            r=ctk.CTkFrame(card,fg_color="transparent"); r.pack(fill="x",padx=16,pady=6)
            ctk.CTkLabel(r,text=label,width=170,anchor="w").pack(side="left")
            ctk.CTkEntry(r,textvariable=var,show="*" if secret else "").pack(side="left",fill="x",expand=True)
        r=ctk.CTkFrame(card,fg_color="transparent"); r.pack(fill="x",padx=16,pady=14)
        ctk.CTkButton(r,text="Créer",command=self.create_account).pack(side="left")
        ctk.CTkButton(r,text="Mot de passe",command=self.change_password).pack(side="left",padx=8)
        ctk.CTkButton(r,text="Appliquer GM",command=self.set_gm).pack(side="left")
        ctk.CTkButton(r,text="Lister comptes",command=self.list_accounts).pack(side="right")

        rb=ctk.CTkFrame(p); rb.pack(fill="x",pady=(0,12))
        ctk.CTkLabel(rb,text="Permissions RBAC",font=ctk.CTkFont(size=18,weight="bold")).pack(anchor="w",padx=16,pady=(12,6))
        rr=ctk.CTkFrame(rb,fg_color="transparent"); rr.pack(fill="x",padx=16,pady=(0,8))
        self.rbac_perm=ctk.StringVar()
        self.rbac_realm=ctk.StringVar(value="-1")
        ctk.CTkLabel(rr,text="Permission ID",width=110,anchor="w").pack(side="left")
        ctk.CTkEntry(rr,textvariable=self.rbac_perm,width=130).pack(side="left",padx=(0,12))
        ctk.CTkLabel(rr,text="Realm",width=55).pack(side="left")
        ctk.CTkEntry(rr,textvariable=self.rbac_realm,width=80).pack(side="left",padx=(0,12))
        ctk.CTkButton(rr,text="Grant",command=lambda:self.rbac_action("grant")).pack(side="left",padx=3)
        ctk.CTkButton(rr,text="Deny",fg_color="#8c5a34",command=lambda:self.rbac_action("deny")).pack(side="left",padx=3)
        ctk.CTkButton(rr,text="Revoke",fg_color="#8c3434",command=lambda:self.rbac_action("revoke")).pack(side="left",padx=3)
        ctk.CTkButton(rr,text="Lister droits",command=self.rbac_list).pack(side="right")

        roles=ctk.CTkFrame(rb,fg_color="transparent")
        roles.pack(fill="x",padx=16,pady=(0,12))
        ctk.CTkLabel(roles,text="Rôles rapides :",text_color="gray65").pack(side="left",padx=(0,8))
        for label,perm in [("Player 195","195"),("Moderator 194","194"),("Gamemaster 193","193"),("Administrator 192","192")]:
            ctk.CTkButton(
                roles,text=label,width=125,
                command=lambda p=perm:self.select_rbac_role(p)
            ).pack(side="left",padx=3)
        ctk.CTkLabel(roles,text="Realm -1 = tous les realms",text_color="gray65").pack(side="left",padx=(12,0))
        self.acc_out=ctk.CTkTextbox(p,font=("Consolas",13)); self.acc_out.pack(fill="both",expand=True)
        listbar=ctk.CTkFrame(p,fg_color="transparent")
        listbar.pack(fill="x",pady=(0,8))
        ctk.CTkButton(listbar,text="Lister les comptes",command=self.list_accounts).pack(side="left")

    def make_characters(self):
        p=self.base(
            "Personnages",
            "Personnages",
            "Fiche personnage, changements de compte et actions AzerothCore"
        )

        # Identification / recherche
        top=ctk.CTkFrame(p)
        top.pack(fill="x",pady=(0,10))

        self.char_account=ctk.StringVar()
        self.char_name=ctk.StringVar()
        self.char_level=ctk.StringVar(value="1")
        self.char_target_account=ctk.StringVar()

        r=ctk.CTkFrame(top,fg_color="transparent")
        r.pack(fill="x",padx=14,pady=(12,5))
        ctk.CTkLabel(r,text="Compte",width=80,anchor="w").pack(side="left")
        ctk.CTkEntry(r,textvariable=self.char_account,width=180).pack(side="left",padx=(0,8))
        ctk.CTkButton(r,text="Lister",width=85,command=self.list_characters).pack(side="left")
        ctk.CTkButton(r,text="Lister tous les persos humains",width=185,command=self.list_human_characters).pack(side="left",padx=(8,0))

        ctk.CTkLabel(r,text="Personnage",width=95).pack(side="left",padx=(18,0))
        ctk.CTkEntry(r,textvariable=self.char_name,width=180).pack(side="left",padx=(0,8))
        ctk.CTkButton(r,text="Charger fiche",command=self.load_character_info).pack(side="left")

        # Character summary cards
        cards=ctk.CTkFrame(p)
        cards.pack(fill="x",pady=(0,10))
        self.char_info_labels={}
        for key,title in [
            ("guid","GUID"),("account","Compte"),("race","Race"),("class","Classe"),
            ("level","Niveau"),("money","Argent"),("map","Map"),("zone","Zone")
        ]:
            c=ctk.CTkFrame(cards)
            c.pack(side="left",fill="x",expand=True,padx=3,pady=8)
            ctk.CTkLabel(c,text=title,text_color="gray65").pack(pady=(6,0))
            lab=ctk.CTkLabel(c,text="-",font=ctk.CTkFont(weight="bold"))
            lab.pack(pady=(0,7))
            self.char_info_labels[key]=lab

        # Core character actions
        actions=ctk.CTkFrame(p)
        actions.pack(fill="x",pady=(0,10))
        ctk.CTkLabel(
            actions,text="Actions personnage",
            font=ctk.CTkFont(size=18,weight="bold")
        ).grid(row=0,column=0,columnspan=6,sticky="w",padx=14,pady=(10,6))

        buttons=[
            ("Changer race",self.char_change_race),
            ("Changer faction",self.char_change_faction),
            ("Apparence",self.char_customize),
            ("Renommer",self.char_rename),
            ("Reset talents",self.char_reset_talents),
            ("Reset sorts",self.char_reset_spells),
            ("Reset stats",self.char_reset_stats),
        ]
        for i,(txt,fn) in enumerate(buttons):
            ctk.CTkButton(actions,text=txt,command=fn).grid(
                row=1+i//4,column=i%4,padx=6,pady=5,sticky="ew"
            )
        for i in range(4):
            actions.grid_columnconfigure(i,weight=1)

        # Level / account
        edit=ctk.CTkFrame(p)
        edit.pack(fill="x",pady=(0,10))

        r=ctk.CTkFrame(edit,fg_color="transparent")
        r.pack(fill="x",padx=14,pady=(10,5))
        ctk.CTkLabel(r,text="Niveau",width=100,anchor="w").pack(side="left")
        ctk.CTkEntry(r,textvariable=self.char_level,width=100).pack(side="left",padx=(0,8))
        ctk.CTkButton(r,text="Appliquer niveau",command=self.char_set_level).pack(side="left")

        ctk.CTkLabel(r,text="Compte cible",width=110).pack(side="left",padx=(25,0))
        ctk.CTkEntry(r,textvariable=self.char_target_account,width=180).pack(side="left",padx=(0,8))
        ctk.CTkButton(r,text="Déplacer",command=self.char_move).pack(side="left")

        ctk.CTkButton(
            r,text="Supprimer personnage",fg_color="#8c3434",command=self.char_delete
        ).pack(side="right")

        # Clone/template creation
        clone=ctk.CTkFrame(p)
        clone.pack(fill="x",pady=(0,10))
        ctk.CTkLabel(
            clone,text="Créer depuis un personnage modèle",
            font=ctk.CTkFont(size=18,weight="bold")
        ).pack(anchor="w",padx=14,pady=(10,4))
        ctk.CTkLabel(
            clone,
            text="Utilise pdump pour éviter des INSERT SQL fragiles dans la base personnages.",
            text_color="gray65"
        ).pack(anchor="w",padx=14,pady=(0,7))

        rr=ctk.CTkFrame(clone,fg_color="transparent")
        rr.pack(fill="x",padx=14,pady=(0,10))
        self.template_char=ctk.StringVar()
        self.new_char_name=ctk.StringVar()
        self.new_char_account=ctk.StringVar()

        for label,var in [
            ("Modèle",self.template_char),
            ("Nouveau nom",self.new_char_name),
            ("Compte",self.new_char_account)
        ]:
            ctk.CTkLabel(rr,text=label).pack(side="left",padx=(0,5))
            ctk.CTkEntry(rr,textvariable=var,width=150).pack(side="left",padx=(0,10))
        ctk.CTkButton(rr,text="Créer",command=self.clone_character).pack(side="left")

        self.char_out=ctk.CTkTextbox(p,height=155,font=("Consolas",13))
        self.char_out.pack(fill="both",expand=True)

    def make_backups(self):
        p=self.base("Sauvegardes","Sauvegardes","Backups datés avant de casser quelque chose xD")
        card=ctk.CTkFrame(p); card.pack(fill="x",pady=(0,12))
        items=[
            ("Sauvegarde complète",self.backup_all),
            ("Bases MySQL",self.backup_mysql),
            ("Configs serveur",self.backup_configs),
            ("Scripts / Lua",self.backup_scripts),
            ("Sauvegarde Playerbots",self.backup_playerbots),
            ("Actualiser",self.list_backups)]
        for i,(t,fn) in enumerate(items):
            ctk.CTkButton(card,text=t,command=fn).grid(row=i//3,column=i%3,padx=8,pady=10,sticky="ew")
        for i in range(3): card.grid_columnconfigure(i,weight=1)

        pb_info=ctk.CTkFrame(p)
        pb_info.pack(fill="x",pady=(0,10))

        ctk.CTkLabel(
            pb_info,
            text="Sauvegarde Playerbots",
            font=ctk.CTkFont(size=15,weight="bold"),
            anchor="w"
        ).pack(fill="x",padx=14,pady=(10,2))

        ctk.CTkLabel(
            pb_info,
            text=(
                "Crée une sauvegarde du module mod-playerbots complet ainsi que de playerbots.conf. "
                "Ce bouton n’applique PAS le patch de niveau dynamique 60/70/80 et ne modifie aucun fichier du serveur."
            ),
            text_color="gray65",
            anchor="w",
            justify="left",
            wraplength=950
        ).pack(fill="x",padx=14,pady=(0,10))

        patch_info=ctk.CTkFrame(p)
        patch_info.pack(fill="x",pady=(0,10))

        ctk.CTkLabel(
            patch_info,
            text="Patch Playerbots — limite dynamique",
            font=ctk.CTkFont(size=16,weight="bold"),
            anchor="w"
        ).pack(fill="x",padx=14,pady=(10,2))

        ctk.CTkLabel(
            patch_info,
            text="Ce patch modifie Playerbots pour imposer un plafond dynamique basé sur le plus haut niveau d’un vrai joueur connecté.",
            text_color="gray70",
            anchor="w",
            justify="left",
            wraplength=950
        ).pack(fill="x",padx=14,pady=(0,4))

        ctk.CTkLabel(
            patch_info,
            text="1–60 → bots max 60  •  61–70 → bots max 70  •  71–80 → bots max 80",
            anchor="w",
            justify="left"
        ).pack(fill="x",padx=14,pady=(0,4))

        ctk.CTkLabel(
            patch_info,
            text="Les Playerbots ne comptent pas dans le calcul. Sans vrai joueur connecté, le plafond retombe à 60.",
            text_color="gray65",
            anchor="w",
            justify="left",
            wraplength=950
        ).pack(fill="x",padx=14,pady=(0,4))

        ctk.CTkLabel(
            patch_info,
            text="Configuration requise dans playerbots.conf :",
            text_color="gray65",
            anchor="w",
            justify="left"
        ).pack(fill="x",padx=14,pady=(0,4))

        self.pb_conf_commands=[]
        for setting in (
            "AiPlayerbot.SyncLevelWithPlayers = 1",
            "AiPlayerbot.LevelBrackets.Enabled = 1",
            "AiPlayerbot.LevelBrackets.FlaggedProcessLimit = 0",
        ):
            setting_row=ctk.CTkFrame(patch_info,fg_color="transparent")
            setting_row.pack(fill="x",padx=14,pady=2)
            entry=ctk.CTkEntry(setting_row,font=("Consolas",12))
            entry.insert(0,setting)
            entry.configure(state="readonly")
            entry.pack(side="left",fill="x",expand=True)
            self.pb_conf_commands.append(entry)

            ctk.CTkButton(
                setting_row,
                text="Copier",
                width=90,
                command=lambda value=setting: (
                    self.clipboard_clear(),
                    self.clipboard_append(value),
                    self.update_idletasks()
                )
            ).pack(side="left",padx=(8,0))

        ctk.CTkLabel(
            patch_info,
            text="⚠ Le Worldserver doit être arrêté avant d'appliquer ce patch.",
            text_color="#d6a84b",
            anchor="w",
            justify="left"
        ).pack(fill="x",padx=14,pady=(0,4))

        ctk.CTkLabel(
            patch_info,
            text="Après application du patch et compilation, exécute cette commande dans la console AzerothCore :",
            text_color="gray65",
            anchor="w",
            justify="left",
            wraplength=950
        ).pack(fill="x",padx=14,pady=(0,5))

        cmd_row=ctk.CTkFrame(patch_info,fg_color="transparent")
        cmd_row.pack(fill="x",padx=14,pady=(0,5))
        self.pb_reset_command=ctk.CTkEntry(cmd_row,font=("Consolas",13))
        self.pb_reset_command.insert(0,"playerbots rndbot reset")
        self.pb_reset_command.configure(state="readonly")
        self.pb_reset_command.pack(side="left",fill="x",expand=True)

        def copy_pb_reset():
            self.clipboard_clear()
            self.clipboard_append("playerbots rndbot reset")
            self.update_idletasks()

        ctk.CTkButton(
            cmd_row,
            text="Copier",
            width=90,
            command=copy_pb_reset
        ).pack(side="left",padx=(8,0))

        ctk.CTkLabel(
            patch_info,
            text="Puis redémarre le Worldserver pour repartir avec le plafond dynamique actif.",
            text_color="gray65",
            anchor="w",
            justify="left",
            wraplength=950
        ).pack(fill="x",padx=14,pady=(0,10))

        f=ctk.CTkFrame(p); f.pack(fill="both",expand=True,pady=(0,10))
        self.backup_tree=ttk.Treeview(f,columns=("date","path"),show="headings",selectmode="browse",style="Ember.Treeview")
        self.backup_tree.heading("date",text="Date")
        self.backup_tree.heading("path",text="Dossier de sauvegarde")
        self.backup_tree.column("date",width=170,anchor="w")
        self.backup_tree.column("path",width=650,anchor="w")
        sb=ttk.Scrollbar(f,orient="vertical",command=self.backup_tree.yview)
        self.backup_tree.configure(yscrollcommand=sb.set)
        self.backup_tree.pack(side="left",fill="both",expand=True,padx=(8,0),pady=8)
        sb.pack(side="right",fill="y",padx=(0,8),pady=8)
        self.backup_tree.bind("<Double-Button-1>",lambda e:self.open_selected_backup())
        self.backup_tree.bind("<Delete>",lambda e:self.delete_selected_backup())
        self.backup_tree.bind("<Button-3>",self.backup_context_menu)

        a=ctk.CTkFrame(p,fg_color="transparent"); a.pack(fill="x",pady=(0,8))
        ctk.CTkButton(a,text="Ouvrir le dossier",command=self.open_selected_backup).pack(side="left")
        ctk.CTkButton(a,text="Supprimer le backup",fg_color="#8c3434",command=self.delete_selected_backup).pack(side="left",padx=8)
        self.back_out=ctk.CTkTextbox(p,height=120,font=("Consolas",12)); self.back_out.pack(fill="x")

    def make_console(self):
        p=self.base("Console","Console SSH interactive","Session persistante — alias, cd et tmux fonctionnent")
        self.console=ctk.CTkTextbox(p,font=("Consolas",13))
        self.console.pack(fill="both",expand=True)

        r=ctk.CTkFrame(p,fg_color="transparent")
        r.pack(fill="x",pady=(10,0))

        self.cmd=ctk.CTkEntry(r,placeholder_text="Commande interactive : wow, cd, tmux attach -t world-session...")
        self.cmd.pack(side="left",fill="x",expand=True,padx=(0,8))
        self.cmd.bind("<Return>",lambda e:self.send_shell())

        ctk.CTkButton(r,text="Envoyer",command=self.send_shell).pack(side="left")
        ctk.CTkButton(r,text="Ctrl+C",width=70,fg_color="gray35",command=lambda:self.send_raw("\\x03")).pack(side="left",padx=(8,0))

    def make_files(self):
        p=self.base("Fichiers","SFTP — Double vue","Explorateur local ↔ serveur façon WinSCP")

        # Barre de recherche
        search=ctk.CTkFrame(p)
        search.pack(fill="x",pady=(0,8))
        self.file_search=ctk.StringVar()
        ctk.CTkEntry(
            search,textvariable=self.file_search,
            placeholder_text="Rechercher un fichier ou dossier..."
        ).pack(side="left",fill="x",expand=True,padx=(10,8),pady=9)
        ctk.CTkButton(search,text="Chercher local",width=120,command=self.search_local).pack(side="left",padx=4)
        ctk.CTkButton(search,text="Chercher serveur",width=135,command=self.search_remote).pack(side="left",padx=(4,10))

        body=ctk.CTkFrame(p,fg_color="transparent")
        body.pack(fill="both",expand=True)
        body.grid_columnconfigure(0,weight=1)
        body.grid_columnconfigure(1,weight=0)
        body.grid_columnconfigure(2,weight=1)
        body.grid_rowconfigure(0,weight=1)

        # -------- Local pane --------
        left=ctk.CTkFrame(body)
        left.grid(row=0,column=0,sticky="nsew",padx=(0,6))
        ctk.CTkLabel(left,text="PC LOCAL",font=ctk.CTkFont(size=17,weight="bold")).pack(anchor="w",padx=10,pady=(9,4))

        lr=ctk.CTkFrame(left,fg_color="transparent")
        lr.pack(fill="x",padx=8,pady=(0,6))
        self.local_path=ctk.StringVar(value=str(Path.home()))
        ctk.CTkEntry(lr,textvariable=self.local_path).pack(side="left",fill="x",expand=True)
        ctk.CTkButton(lr,text="↑",width=38,command=self.local_parent).pack(side="left",padx=(5,0))
        ctk.CTkButton(lr,text="⟳",width=38,command=self.list_local).pack(side="left",padx=(5,0))

        self.local_tree=ttk.Treeview(left,columns=("size","type"),show="tree headings",selectmode="browse")
        self.local_tree.heading("#0",text="Nom")
        self.local_tree.heading("size",text="Taille")
        self.local_tree.heading("type",text="Type")
        self.local_tree.column("#0",width=310,anchor="w")
        self.local_tree.column("size",width=90,anchor="e")
        self.local_tree.column("type",width=80,anchor="center")
        self.local_tree.pack(fill="both",expand=True,padx=8,pady=(0,8))
        self.local_tree.bind("<Double-Button-1>",self.local_open)
        self.local_tree.bind("<Button-3>",lambda e:self.local_parent())

        # -------- Transfer controls --------
        mid=ctk.CTkFrame(body,width=105)
        mid.grid(row=0,column=1,sticky="ns",padx=4)
        mid.grid_propagate(False)
        ctk.CTkLabel(mid,text="TRANSFERT",font=ctk.CTkFont(size=12,weight="bold")).pack(pady=(80,12))
        ctk.CTkButton(mid,text="→",width=62,height=42,command=self.upload_selected).pack(pady=6)
        ctk.CTkLabel(mid,text="Envoyer",text_color="gray65").pack()
        ctk.CTkButton(mid,text="←",width=62,height=42,command=self.download_selected).pack(pady=(18,6))
        ctk.CTkLabel(mid,text="Télécharger",text_color="gray65").pack()

        # -------- Remote pane --------
        right=ctk.CTkFrame(body)
        right.grid(row=0,column=2,sticky="nsew",padx=(6,0))
        ctk.CTkLabel(right,text="SERVEUR SFTP",font=ctk.CTkFont(size=17,weight="bold")).pack(anchor="w",padx=10,pady=(9,4))

        rr=ctk.CTkFrame(right,fg_color="transparent")
        rr.pack(fill="x",padx=8,pady=(0,6))
        self.path=ctk.CTkEntry(rr)
        self.path.insert(0,"/root")
        self.path.pack(side="left",fill="x",expand=True)
        ctk.CTkButton(rr,text="↑",width=38,command=self.parent).pack(side="left",padx=(5,0))
        ctk.CTkButton(rr,text="⟳",width=38,command=self.list_remote).pack(side="left",padx=(5,0))

        self.remote_tree=ttk.Treeview(right,columns=("size","type"),show="tree headings",selectmode="browse")
        self.remote_tree.heading("#0",text="Nom")
        self.remote_tree.heading("size",text="Taille")
        self.remote_tree.heading("type",text="Type")
        self.remote_tree.column("#0",width=310,anchor="w")
        self.remote_tree.column("size",width=90,anchor="e")
        self.remote_tree.column("type",width=80,anchor="center")
        self.remote_tree.pack(fill="both",expand=True,padx=8,pady=(0,8))
        self.remote_tree.bind("<Double-Button-1>",self.remote_open)
        self.remote_tree.bind("<Delete>",lambda e:self.remote_delete_selected())
        self.remote_tree.bind("<Button-3>",self.remote_context_menu)

        # Bottom actions
        bottom=ctk.CTkFrame(p)
        bottom.pack(fill="x",pady=(8,0))
        ctk.CTkButton(bottom,text="Nouveau dossier serveur",command=self.remote_new_folder).pack(side="left",padx=(8,4),pady=8)
        ctk.CTkButton(bottom,text="Supprimer",fg_color="#8c3434",command=self.remote_delete_selected).pack(side="left",padx=4,pady=8)
        ctk.CTkButton(bottom,text="Ouvrir dossier local",command=self.choose_local_folder).pack(side="left",padx=4,pady=8)
        self.transfer_status=ctk.CTkLabel(bottom,text="Prêt",text_color="gray65")
        self.transfer_status.pack(side="right",padx=12)

        # Treeview ttk est blanc par défaut sous Windows : on force un thème sombre.
        style=ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(
            "Ember.Treeview",
            background="#242424",
            fieldbackground="#242424",
            foreground="#e8e8e8",
            borderwidth=0,
            rowheight=24
        )
        style.map(
            "Ember.Treeview",
            background=[("selected","#1f6aa5")],
            foreground=[("selected","#ffffff")]
        )
        style.configure(
            "Ember.Treeview.Heading",
            background="#303030",
            foreground="#e8e8e8",
            relief="flat",
            borderwidth=0
        )
        style.map(
            "Ember.Treeview.Heading",
            background=[("active","#3a3a3a")]
        )

        self.local_tree.configure(style="Ember.Treeview")
        self.remote_tree.configure(style="Ember.Treeview")

        self.local_entries={}
        self.remote_entries={}


    def lock_app(self):
        try:
            self.save_settings()
        except Exception:
            pass
        self.disconnect()
        self._fernet=None
        self._master_password=None
        self._show_unlock_dialog()

    def change_master_password(self):
        if not self._fernet:
            return
        dlg=ctk.CTkToplevel(self)
        dlg.title("Changer le mot de passe maître")
        dlg.geometry("520x370")
        dlg.resizable(False,False)
        dlg.grab_set()

        ctk.CTkLabel(
            dlg,
            text="Nouveau mot de passe maître",
            font=ctk.CTkFont(size=21,weight="bold")
        ).pack(pady=(24,12))

        old=ctk.CTkEntry(dlg,show="*",placeholder_text="Mot de passe actuel")
        old.pack(fill="x",padx=38,pady=5)

        new1=ctk.CTkEntry(dlg,show="*",placeholder_text="Nouveau mot de passe")
        new1.pack(fill="x",padx=38,pady=5)

        new2=ctk.CTkEntry(dlg,show="*",placeholder_text="Confirmer")
        new2.pack(fill="x",padx=38,pady=5)

        recovery=ctk.CTkEntry(
            dlg,placeholder_text="Code de récupération AERAS-... (pour conserver la récupération)"
        )
        recovery.pack(fill="x",padx=38,pady=5)

        def apply():
            sec=self._saved_settings.get("security",{})
            try:
                oldf=self._derive_fernet(old.get(),sec["salt"])
                oldf.decrypt(sec["verifier"].encode("ascii"))
            except Exception:
                messagebox.showerror(
                    "Sécurité",
                    "Mot de passe actuel incorrect.",
                    parent=dlg
                )
                return

            if len(new1.get()) < 6 or new1.get() != new2.get():
                messagebox.showwarning(
                    "Sécurité",
                    "Nouveau mot de passe invalide ou confirmation différente.",
                    parent=dlg
                )
                return

            plain_password=None
            conn=self._saved_settings.get("connection",{})
            enc=conn.get("password_enc")

            if enc:
                try:
                    plain_password=oldf.decrypt(enc.encode("ascii"))
                except Exception:
                    plain_password=None

            salt_b64=base64.urlsafe_b64encode(os.urandom(16)).decode("ascii")
            newf=self._derive_fernet(new1.get(),salt_b64)

            sec["salt"]=salt_b64
            sec["verifier"]=newf.encrypt(b"EMBER_ADMIN_OK").decode("ascii")

            # Keep password recovery valid after a normal master-password change.
            if sec.get("recovery_verifier"):
                try:
                    rf=self._derive_recovery_fernet(recovery.get(),sec["recovery_salt"])
                    if rf.decrypt(sec["recovery_verifier"].encode("ascii")) != b"AERAS_RECOVERY_OK":
                        raise InvalidToken()
                    sec["recovery_master_key"]=rf.encrypt(
                        self._derive_master_key_bytes(new1.get(),salt_b64)
                    ).decode("ascii")
                except Exception:
                    messagebox.showerror(
                        "Sécurité",
                        "Code de récupération incorrect. Le mot de passe n'a pas été changé.",
                        parent=dlg
                    )
                    return

            if plain_password is not None:
                conn["password_enc"]=newf.encrypt(plain_password).decode("ascii")

            self._saved_settings["security"]=sec
            self._saved_settings["connection"]=conn
            self._write_settings_file(self._saved_settings)

            self._fernet=newf
            self._master_password=new1.get()

            dlg.destroy()
            messagebox.showinfo("Sécurité","Mot de passe maître changé.")

        ctk.CTkButton(dlg,text="Changer",command=apply).pack(pady=18)

    def show(self,n):
        self.current_page=n
        for p in self.pages.values(): p.grid_remove()
        self.pages[n].grid()
        if n=="Dashboard" and self.ssh:self.refresh()
        if n=="Fichiers":
            self.list_local()
            if self.sftp:self.list_remote()

    def pick_key(self):
        x=filedialog.askopenfilename()
        if x:self.key.set(x)

    def connect(self):
        threading.Thread(target=self._connect,daemon=True).start()

    def _connect(self):
        self.disconnect()
        try:
            self.q.put(("conn","Connexion…"))
            c=paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            kw={
                "hostname":self.host.get().strip(),
                "port":int(self.port.get()),
                "username":self.user.get().strip(),
                "timeout":10,
                "allow_agent":True,
                "look_for_keys":True
            }
            if self.password.get():
                kw["password"]=self.password.get()
            if self.key.get().strip():
                kw["key_filename"]=self.key.get().strip()

            c.connect(**kw)
            self.ssh=c
            self.sftp=c.open_sftp()

            self.shell=c.invoke_shell(term="xterm",width=180,height=45)
            self.shell.settimeout(0.0)
            self.shell_reader_alive=True
            threading.Thread(target=self._shell_reader,daemon=True).start()

            self.q.put(("conn","Connecté"))
            self.refresh()
            self.refresh_crashes()
        except Exception as e:
            self.q.put(("conn","Échec"))
            self.q.put(("log",f"Connexion: {e}\n"))

    def disconnect(self):
        self.shell_reader_alive=False
        try:
            if self.shell:
                self.shell.close()
            if self.sftp:
                self.sftp.close()
            if self.ssh:
                self.ssh.close()
        except:
            pass
        self.shell=None
        self.sftp=self.ssh=None
        self.q.put(("conn","Déconnecté"))

    def need(self):
        if not self.ssh:
            msg="Connect to the VM first." if self.language.get()=="EN" else "Connecte-toi d'abord à la VM."
            messagebox.showwarning("Azeroth Eras Control",msg)
            return False
        return True

    def exec(self,cmd):
        _,o,e=self.ssh.exec_command(cmd,get_pty=True)
        return o.read().decode(errors="replace")+e.read().decode(errors="replace")

    def run(self,cmd=None):
        if not self.need():
            return
        if cmd is None:
            self.send_shell()
            return
        c=cmd
        self.show("Console")
        threading.Thread(
            target=lambda:self.q.put(("log",f"$ {c}\n{self.exec(c)}\n")),
            daemon=True
        ).start()

    def send_shell(self):
        if not self.need():
            return
        if not self.shell or self.shell.closed:
            messagebox.showerror("Console","Session SSH interactive indisponible.")
            return

        c=self.cmd.get()
        if not c.strip():
            return

        try:
            self.shell.send(c + "\n")
            self.cmd.delete(0,"end")
        except Exception as e:
            self.q.put(("log",f"\n[Console] {e}\n"))

    def send_raw(self,data):
        if self.shell and not self.shell.closed:
            try:
                self.shell.send(data)
            except Exception as e:
                self.q.put(("log",f"\n[Console] {e}\n"))

    def _shell_reader(self):
        ansi = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        import time
        while self.shell_reader_alive and self.shell:
            try:
                if self.shell.recv_ready():
                    data=self.shell.recv(65535).decode("utf-8",errors="replace")
                    data=ansi.sub("",data).replace("\r","")
                    if data:
                        self.q.put(("shell",data))
                else:
                    time.sleep(0.04)
            except Exception:
                time.sleep(0.08)

    def refresh(self):
        if not self.need() or self._monitor_busy:
            return

        self._monitor_busy=True

        def w():
            try:
                checks={
                    "SSH":"echo ONLINE",
                    "Authserver":"pgrep -x authserver >/dev/null && echo ONLINE || echo OFFLINE",
                    "Worldserver":"pgrep -x worldserver >/dev/null && echo ONLINE || echo OFFLINE",
                    "MySQL":"systemctl is-active mysql 2>/dev/null || true",
                    "UFW":"ufw status 2>/dev/null | head -n1"
                }
                vals={k:self.exec(v).strip() for k,v in checks.items()}

                # One compact SSH request for monitoring values.
                script=r"""
LC_ALL=C
echo "HOST=$(hostname)"
echo "IP=$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "UPTIME=$(uptime -p 2>/dev/null || true)"
echo "LOAD=$(awk '{print $1" "$2" "$3}' /proc/loadavg 2>/dev/null)"

read cpu user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat
CPU_IDLE=$((idle + iowait))
CPU_TOTAL=$((user + nice + system + idle + iowait + irq + softirq + steal))
echo "CPU_IDLE=$CPU_IDLE"
echo "CPU_TOTAL=$CPU_TOTAL"

free -b 2>/dev/null | awk '/^Mem:/ {print "RAM_TOTAL="$2; print "RAM_USED="$3; print "RAM_AVAILABLE="$7}'

df -B1 / 2>/dev/null | awk 'NR==2 {print "DISK_TOTAL="$2; print "DISK_USED="$3; print "DISK_FREE="$4; print "DISK_PCT="$5}'

IFACE=$(ip route show default 2>/dev/null | awk '{print $5; exit}')
echo "IFACE=$IFACE"
if [ -n "$IFACE" ]; then
    echo "RX=$(cat /sys/class/net/$IFACE/statistics/rx_bytes 2>/dev/null || echo 0)"
    echo "TX=$(cat /sys/class/net/$IFACE/statistics/tx_bytes 2>/dev/null || echo 0)"
fi

TEMP=""
for z in /sys/class/thermal/thermal_zone*/temp; do
    [ -r "$z" ] || continue
    TEMP=$(cat "$z" 2>/dev/null)
    [ -n "$TEMP" ] && break
done
echo "TEMP=$TEMP"

echo "PROC_BEGIN"
ps -C worldserver -o comm=,%cpu=,%mem=,rss= 2>/dev/null
ps -C authserver -o comm=,%cpu=,%mem=,rss= 2>/dev/null
ps -C mysqld -o comm=,%cpu=,%mem=,rss= 2>/dev/null
echo "PROC_END"

echo "SYS_BEGIN"
uname -srmo 2>/dev/null
grep '^PRETTY_NAME=' /etc/os-release 2>/dev/null | cut -d= -f2- | tr -d '"'
ip -br addr 2>/dev/null
echo "SYS_END"
"""
                # Send the script through stdin to bash to avoid quoting/newline corruption.
                marker="__EMBER_MONITOR_EOF__"
                remote_cmd=f"bash -s <<'{marker}'\n{script}\n{marker}"
                raw=self.exec(remote_cmd)
                parsed=self._parse_monitor_output(raw)
                self.q.put(("monitor",(vals,parsed)))
            except Exception as e:
                self.q.put(("monitor_error",str(e)))
            finally:
                self._monitor_busy=False

        threading.Thread(target=w,daemon=True).start()

    def monitor_tick(self):
        # Refresh only while the Dashboard is visible.
        if self.current_page=="Dashboard" and self.ssh:
            self.refresh()
        self.after(3000,self.monitor_tick)

    def _parse_monitor_output(self,raw):
        data={}
        procs=[]
        syslines=[]
        mode=None

        for line in raw.splitlines():
            if line=="PROC_BEGIN":
                mode="proc"
                continue
            if line=="PROC_END":
                mode=None
                continue
            if line=="SYS_BEGIN":
                mode="sys"
                continue
            if line=="SYS_END":
                mode=None
                continue

            if mode=="proc":
                if line.strip():
                    procs.append(line.rstrip())
                continue
            if mode=="sys":
                if line.strip():
                    syslines.append(line.rstrip())
                continue

            if "=" in line:
                k,v=line.split("=",1)
                data[k.strip()]=v.strip()

        data["PROCS"]=procs
        data["SYSLINES"]=syslines
        return data

    def _human_bytes(self,n):
        try:
            n=float(n)
        except:
            return "—"
        units=["B","KB","MB","GB","TB"]
        for u in units:
            if n < 1024 or u=="TB":
                return f"{n:.0f} {u}" if u=="B" else f"{n:.1f} {u}"
            n/=1024

    def _set_monitor_ui(self,vals,data):
        import time as _time
        import datetime as _datetime

        for k,x in vals.items():
            good=("ONLINE" in x.upper() or "ACTIVE" in x.upper())
            if k=="UFW":
                good=("ACTIVE" in x.upper())
            self.status[k].configure(
                text=x.upper() or "INCONNU",
                text_color="#56b870" if good else "#d9534f"
            )

        # CPU: calculate utilisation from two /proc/stat samples.
        try:
            cpu_total=int(data.get("CPU_TOTAL","0") or 0)
            cpu_idle=int(data.get("CPU_IDLE","0") or 0)
        except:
            cpu_total=cpu_idle=0

        cpu=0.0
        if self._cpu_prev is not None:
            prev_total,prev_idle=self._cpu_prev
            delta_total=cpu_total-prev_total
            delta_idle=cpu_idle-prev_idle
            if delta_total > 0:
                cpu=100.0*(1.0-(delta_idle/delta_total))
                cpu=max(0.0,min(100.0,cpu))
        self._cpu_prev=(cpu_total,cpu_idle)

        self.monitor_labels["CPU"].configure(text=f"{cpu:.1f} %")
        self.monitor_bars["CPU"].set(cpu/100.0)
        self.monitor_labels["CPU_DETAIL"].configure(
            text=f"Load : {data.get('LOAD','—')}"
        )

        # RAM
        try:
            ram_total=float(data.get("RAM_TOTAL","0"))
            ram_used=float(data.get("RAM_USED","0"))
            ram_available=float(data.get("RAM_AVAILABLE","0"))
            ram_pct=(ram_used/ram_total*100) if ram_total else 0
        except:
            ram_total=ram_used=ram_available=ram_pct=0
        self.monitor_labels["RAM"].configure(text=f"{ram_pct:.1f} %")
        self.monitor_bars["RAM"].set(min(1,max(0,ram_pct/100)))
        self.monitor_labels["RAM_DETAIL"].configure(
            text=f"{self._human_bytes(ram_used)} / {self._human_bytes(ram_total)}\n"
                 f"Disponible : {self._human_bytes(ram_available)}"
        )

        # Disk
        try:
            disk_total=float(data.get("DISK_TOTAL","0"))
            disk_used=float(data.get("DISK_USED","0"))
            disk_free=float(data.get("DISK_FREE","0"))
            disk_pct=(disk_used/disk_total*100) if disk_total else 0
        except:
            disk_total=disk_used=disk_free=disk_pct=0
        self.monitor_labels["DISK"].configure(text=f"{disk_pct:.1f} %")
        self.monitor_bars["DISK"].set(min(1,max(0,disk_pct/100)))
        self.monitor_labels["DISK_DETAIL"].configure(
            text=f"{self._human_bytes(disk_used)} / {self._human_bytes(disk_total)}\n"
                 f"Libre : {self._human_bytes(disk_free)}"
        )

        # Network rate, calculated between dashboard polls.
        try:
            rx=int(data.get("RX","0") or 0)
            tx=int(data.get("TX","0") or 0)
        except:
            rx=tx=0
        now=_time.monotonic()
        rx_rate=tx_rate=0.0
        if self._net_prev is not None and self._net_prev_time is not None:
            dt=max(0.001,now-self._net_prev_time)
            rx_rate=max(0,(rx-self._net_prev[0])/dt)
            tx_rate=max(0,(tx-self._net_prev[1])/dt)
        self._net_prev=(rx,tx)
        self._net_prev_time=now

        self.monitor_labels["NET"].configure(
            text=f"↓ {self._human_bytes(rx_rate)}/s"
        )
        self.monitor_labels["NET_DETAIL"].configure(
            text=f"↑ {self._human_bytes(tx_rate)}/s  •  {data.get('IFACE','—')}\n"
                 f"Total ↓ {self._human_bytes(rx)}  ↑ {self._human_bytes(tx)}"
        )

        self.monitor_labels["HOST"].configure(
            text=f"Serveur : {data.get('HOST','—')}  •  {data.get('IP','—')}"
        )
        self.monitor_labels["UPTIME"].configure(
            text=f"Uptime : {data.get('UPTIME','—')}"
        )
        self.monitor_labels["LOAD"].configure(
            text=f"Load : {data.get('LOAD','—')}"
        )

        self.monitor_labels["UPDATED"].configure(
            text="Maj : "+_datetime.datetime.now().strftime("%H:%M:%S")
        )

        procs=data.get("PROCS",[])
        self.proc_info.delete("1.0","end")
        self.proc_info.insert(
            "end",
            "PROCESSUS              CPU      RAM    MÉMOIRE\n"
            "------------------------------------------------\n"
        )
        if procs:
            for line in procs:
                parts=line.split()
                if len(parts) >= 4:
                    name,cpu_p,ram_p,rss_kb=parts[0],parts[1],parts[2],parts[3]
                    try:
                        rss_bytes=float(rss_kb)*1024
                        rss_txt=self._human_bytes(rss_bytes)
                    except:
                        rss_txt=rss_kb
                    try:
                        cpu_txt=f"{float(cpu_p):.1f} %"
                    except:
                        cpu_txt=cpu_p
                    try:
                        ram_txt=f"{float(ram_p):.1f} %"
                    except:
                        ram_txt=ram_p
                    self.proc_info.insert(
                        "end",
                        f"{name:<18} {cpu_txt:>8} {ram_txt:>8} {rss_txt:>10}\n"
                    )
                else:
                    self.proc_info.insert("end",line+"\n")
        else:
            self.proc_info.insert("end","Aucun processus serveur détecté.\n")

        self.sys.delete("1.0","end")
        for line in data.get("SYSLINES",[]):
            self.sys.insert("end",line+"\n")


    # AzerothCore account commands are used deliberately instead of writing auth tables by hand.
    def world_console(self,command):
        safe=command.replace("'","'\"'\"'")
        return self.exec(f"tmux send-keys -t world-session '{safe}' C-m")

    def create_account(self):
        if not self.need():return
        u=self.acc_name.get().strip(); p=self.acc_pass.get()
        if not u or not p:messagebox.showwarning("Compte","Nom + mot de passe requis.");return
        # AC syntax: account create <user> <pass> [email]
        cmd=f"account create {u} {p}" + (f" {self.acc_email.get().strip()}" if self.acc_email.get().strip() else "")
        self.world_console(cmd)
        if self.acc_gm.get().strip() not in ("","0"): self.world_console(f"account set gmlevel {u} {self.acc_gm.get().strip()} -1")
        self.acc_out.insert("end",f"Envoyé: création du compte {u}\n")
    def change_password(self):
        u=self.acc_name.get().strip(); p=self.acc_pass.get()
        if u and p:self.world_console(f"account set password {u} {p} {p}");self.acc_out.insert("end",f"Mot de passe demandé pour {u}\n")
    def set_gm(self):
        u=self.acc_name.get().strip(); g=self.acc_gm.get().strip() or "0"
        if u:self.world_console(f"account set gmlevel {u} {g} -1");self.acc_out.insert("end",f"GM level {g} demandé pour {u}\n")
    def list_accounts(self):
        if not self.need():
            return

        cmd = """mysql -N -B -e "SELECT id,username,email,last_ip,expansion FROM acore_auth.account ORDER BY id;" 2>&1"""

        def worker():
            out=self.exec(cmd).strip()
            rows=[]
            if out:
                for line in out.splitlines():
                    cols=line.split("\t")
                    while len(cols)<5:
                        cols.append("")
                    rows.append(cols[:5])
            self.q.put(("accounts_popup",rows))

        threading.Thread(target=worker,daemon=True).start()

    def show_accounts_popup(self,rows):
        win=ctk.CTkToplevel(self)
        win.title("Comptes AzerothCore")
        win.geometry("980x620")
        win.minsize(760,420)
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(
            win,
            text=f"Comptes AzerothCore — {len(rows)} compte(s)",
            font=ctk.CTkFont(size=22,weight="bold")
        ).pack(anchor="w",padx=16,pady=(16,8))

        search_var=ctk.StringVar()
        search=ctk.CTkEntry(
            win,
            textvariable=search_var,
            placeholder_text="Rechercher un compte..."
        )
        search.pack(fill="x",padx=16,pady=(0,10))

        frame=ctk.CTkFrame(win)
        frame.pack(fill="both",expand=True,padx=16,pady=(0,12))

        tree=ttk.Treeview(
            frame,
            columns=("id","username","email","last_ip","expansion"),
            show="headings",
            selectmode="browse",
            style="Ember.Treeview"
        )
        tree.heading("id",text="ID")
        tree.heading("username",text="Compte")
        tree.heading("email",text="Email")
        tree.heading("last_ip",text="Dernière IP")
        tree.heading("expansion",text="Extension")

        tree.column("id",width=70,anchor="center")
        tree.column("username",width=180,anchor="w")
        tree.column("email",width=260,anchor="w")
        tree.column("last_ip",width=160,anchor="w")
        tree.column("expansion",width=90,anchor="center")

        scroll=ttk.Scrollbar(frame,orient="vertical",command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)

        tree.pack(side="left",fill="both",expand=True)
        scroll.pack(side="right",fill="y")

        def fill(filter_text=""):
            filter_text=filter_text.lower().strip()
            for item in tree.get_children():
                tree.delete(item)
            for row in rows:
                joined=" ".join(str(x) for x in row).lower()
                if not filter_text or filter_text in joined:
                    tree.insert("", "end", values=row)

        fill()

        def on_search(*_):
            fill(search_var.get())

        search_var.trace_add("write",on_search)

        def use_selected():
            sel=tree.selection()
            if not sel:
                return
            vals=tree.item(sel[0],"values")
            if len(vals)>=2:
                self.acc_name.set(str(vals[1]))
                win.destroy()

        tree.bind("<Double-Button-1>",lambda e:use_selected())

        bottom=ctk.CTkFrame(win,fg_color="transparent")
        bottom.pack(fill="x",padx=16,pady=(0,14))
        ctk.CTkButton(
            bottom,
            text="Sélectionner ce compte",
            command=use_selected
        ).pack(side="left")
        ctk.CTkButton(
            bottom,
            text="Fermer",
            fg_color="gray35",
            command=win.destroy
        ).pack(side="right")


    def select_rbac_role(self,permission_id):
        self.rbac_perm.set(str(permission_id))
        self.rbac_realm.set("-1")

    def rbac_action(self,action):
        if not self.need(): return
        account=self.acc_name.get().strip()
        perm=self.rbac_perm.get().strip()
        realm=self.rbac_realm.get().strip() or "-1"
        if not account or not perm:
            messagebox.showwarning("RBAC","Compte + Permission ID requis."); return
        if not perm.isdigit():
            messagebox.showwarning("RBAC","Permission ID doit être numérique."); return
        self.auto_auth_backup("rbac")
        self.world_console(f"rbac account {action} {account} {perm} {realm}")
        self.acc_out.insert("end",f"RBAC {action}: {account} / permission {perm} / realm {realm}\n")

    def rbac_list(self):
        if not self.need(): return
        account=self.acc_name.get().strip()
        if not account:
            messagebox.showwarning("RBAC","Indique le compte."); return
        self.world_console(f"rbac account list {account}")
        self.acc_out.insert("end",f"Commande envoyée: rbac account list {account}\nRegarde aussi la console Worldserver pour le détail.\n")

    def auto_auth_backup(self,label="change"):
        # Petite sauvegarde auth avant les changements de droits.
        stamp=datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        cmd=f"mkdir -p /root/ember-backups/auto && mysqldump acore_auth > /root/ember-backups/auto/auth_{label}_{stamp}.sql 2>/dev/null || true"
        try: self.exec(cmd)
        except: pass

    def list_characters(self):
        if not self.need():
            return
        account=self.char_account.get().strip()
        if not account:
            messagebox.showwarning("Personnages","Indique le nom du compte.")
            return
        esc=account.replace("'","''")
        cmd=f"""mysql -N -e "SELECT c.guid,c.name,c.race,c.class,c.level FROM acore_characters.characters c JOIN acore_auth.account a ON a.id=c.account WHERE a.username='{esc}' ORDER BY c.guid;" 2>&1"""
        def w():
            self.q.put(("char",self.exec(cmd)))
        threading.Thread(target=w,daemon=True).start()

    def list_human_characters(self):
        """Liste les personnages appartenant à des comptes humains, sans Playerbots."""
        if not self.need():
            return

        # Primary filter: exclude accounts referenced by the Playerbots DB if its
        # account table exists. Fallback patterns also exclude the usual rndbot/playerbot names.
        sql = """SELECT c.guid,c.name,a.username,c.race,c.class,c.level
FROM acore_characters.characters c
JOIN acore_auth.account a ON a.id=c.account
WHERE LOWER(a.username) NOT LIKE 'rndbot%'
  AND LOWER(a.username) NOT LIKE 'playerbot%'
  AND LOWER(a.username) NOT LIKE 'randomplayerbot%'
ORDER BY a.username,c.name;"""
        safe_sql=sql.replace('"','\\\"').replace("\n"," ")
        cmd=f'mysql -N -B -e "{safe_sql}" 2>&1'

        def w():
            out=self.exec(cmd).strip()
            if not out:
                out="Aucun personnage humain trouvé."
            else:
                lines=["GUID\tPERSONNAGE\tCOMPTE\tRACE\tCLASSE\tNIVEAU",out]
                out="\n".join(lines)
            self.q.put(("char",out))
        threading.Thread(target=w,daemon=True).start()

    def _require_character(self):
        name=self.char_name.get().strip()
        if not name:
            messagebox.showwarning("Personnage","Indique le nom du personnage.")
            return None
        return name

    def load_character_info(self):
        if not self.need():
            return
        name=self._require_character()
        if not name:
            return
        esc=name.replace("'","''")
        cmd=f"""mysql -N -B -e "SELECT c.guid,a.username,c.race,c.class,c.level,c.money,c.map,c.zone FROM acore_characters.characters c JOIN acore_auth.account a ON a.id=c.account WHERE c.name='{esc}' LIMIT 1;" 2>&1"""
        def w():
            out=self.exec(cmd).strip()
            if not out:
                self.q.put(("charinfo",None))
                return
            cols=out.split("\t")
            if len(cols) < 8:
                self.q.put(("char",out+"\n"))
                return
            self.q.put(("charinfo",{
                "guid":cols[0],"account":cols[1],"race":cols[2],"class":cols[3],
                "level":cols[4],"money":cols[5],"map":cols[6],"zone":cols[7]
            }))
        threading.Thread(target=w,daemon=True).start()

    def _char_command(self,command,message):
        if not self.need():
            return
        self.world_console(command)
        self.char_out.insert("end",message+"\n")
        self.char_out.see("end")

    def char_set_level(self):
        name=self._require_character()
        level=self.char_level.get().strip()
        if not name:
            return
        if not level.isdigit() or not 1 <= int(level) <= 80:
            messagebox.showwarning("Niveau","Entre un niveau entre 1 et 80.")
            return
        self._char_command(
            f"character level {name} {level}",
            f"Niveau {level} demandé pour {name}."
        )

    def char_rename(self):
        name=self._require_character()
        if not name:
            return
        self._char_command(
            f"character rename {name}",
            f"{name} devra choisir un nouveau nom à la prochaine connexion."
        )

    def char_change_race(self):
        name=self._require_character()
        if not name:
            return
        if not messagebox.askyesno(
            "Changer la race",
            f"Autoriser {name} à changer de race à sa prochaine connexion ?"
        ):
            return
        self._char_command(
            f"character changerace {name}",
            f"Changement de race activé pour {name}."
        )

    def char_change_faction(self):
        name=self._require_character()
        if not name:
            return
        if not messagebox.askyesno(
            "Changer la faction",
            f"Autoriser {name} à changer de faction à sa prochaine connexion ?\n\n"
            "Cette opération peut convertir des éléments liés à la faction."
        ):
            return
        self._char_command(
            f"character changefaction {name}",
            f"Changement de faction activé pour {name}."
        )

    def char_customize(self):
        name=self._require_character()
        if not name:
            return
        self._char_command(
            f"character customize {name}",
            f"Personnalisation d'apparence activée pour {name}."
        )

    def char_reset_talents(self):
        name=self._require_character()
        if not name:
            return
        if not messagebox.askyesno("Reset talents",f"Réinitialiser les talents de {name} ?"):
            return
        self._char_command(f"reset talents {name}",f"Reset talents demandé pour {name}.")

    def char_reset_spells(self):
        name=self._require_character()
        if not name:
            return
        if not messagebox.askyesno(
            "Reset sorts",
            f"Réinitialiser les sorts non originaux de {name} ?\n\n"
            "Attention : AzerothCore indique que cette commande touche aussi les professions."
        ):
            return
        self._char_command(f"reset spells {name}",f"Reset sorts demandé pour {name}.")

    def char_reset_stats(self):
        name=self._require_character()
        if not name:
            return
        if not messagebox.askyesno("Reset stats",f"Recalculer les stats de {name} ?"):
            return
        self._char_command(f"reset stats {name}",f"Reset stats demandé pour {name}.")

    def char_move(self):
        name=self._require_character()
        target=self.char_target_account.get().strip()
        if not name:
            return
        if not target:
            messagebox.showwarning("Personnage","Indique le compte cible.")
            return
        if not messagebox.askyesno(
            "Déplacer personnage",
            f"Déplacer {name} vers le compte {target} ?"
        ):
            return
        self._char_command(
            f"character changeaccount {target} {name}",
            f"Déplacement demandé : {name} -> {target}."
        )

    def char_delete(self):
        name=self._require_character()
        if not name:
            return
        if not messagebox.askyesno(
            "Supprimer personnage",
            f"Supprimer définitivement {name} ?\n\n"
            "Un pdump de sécurité sera demandé avant la suppression."
        ):
            return
        stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dump=f"/root/ember-backups/characters/{name}_{stamp}.pdump"
        self.exec("mkdir -p /root/ember-backups/characters")
        self.world_console(f"pdump write {dump} {name}")
        self.world_console(f"character erase {name}")
        self.char_out.insert(
            "end",
            f"Backup pdump demandé puis suppression de {name}.\n{dump}\n"
        )

    def clone_character(self):
        if not self.need():
            return
        template=self.template_char.get().strip()
        newname=self.new_char_name.get().strip()
        account=self.new_char_account.get().strip()
        if not template or not newname or not account:
            messagebox.showwarning(
                "Création","Modèle + nouveau nom + compte requis."
            )
            return
        stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dump=f"/root/ember-backups/templates/{template}_{stamp}.pdump"
        self.exec("mkdir -p /root/ember-backups/templates")
        self.world_console(f"pdump write {dump} {template}")
        self.world_console(f"pdump load {dump} {account} {newname}")
        self.char_out.insert(
            "end",
            f"Création demandée depuis modèle {template} -> {newname} sur {account}\n"
            f"Dump : {dump}\n"
        )

    def backup_cmd(self,parts,kind="backup"):
        if not self.need(): return
        stamp=datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base="/root/ember-backups"
        tmp=f"{base}/.tmp_{kind}_{stamp}"
        archive=f"{base}/{kind}_{stamp}.7z"
        commands=[
            f"mkdir -p '{base}'",
            f"rm -rf '{tmp}'",
            f"mkdir -p '{tmp}'",
        ]+parts(tmp)+[
            f"7z a -t7z -mx=5 '{archive}' '{tmp}/.'",
            f"7z t '{archive}'",
            f"rm -rf '{tmp}'",
            f"echo 'Backup: {archive}'",
            f"du -h '{archive}'"
        ]
        def w():
            out=self.exec(" && ".join(commands))
            self.q.put(("backup",out))
            self.q.put(("refresh_backups",None))
        threading.Thread(target=w,daemon=True).start()

    def backup_mysql(self):
        self.backup_cmd(lambda d:[
            f"mkdir -p '{d}/mysql'",
            f"mysqldump --all-databases --single-transaction --routines --events > '{d}/mysql/all-databases.sql'"
        ],"mysql")

    def backup_configs(self):
        self.backup_cmd(lambda d:[
            f"mkdir -p '{d}/configs'",
            f"cp -a /root/azerothcore-wotlk/env/dist/etc/. '{d}/configs/'"
        ],"configs")

    def backup_scripts(self):
        self.backup_cmd(lambda d:[
            f"mkdir -p '{d}/scripts'",
            f"for x in /root/azerothcore-wotlk/env/dist/bin/lua_scripts /root/azerothcore-wotlk/lua_scripts /root/azerothcore-wotlk/modules/mod-ale; do [ ! -e \"$x\" ] || cp -a \"$x\" '{d}/scripts/'; done"
        ],"scripts")

    def backup_playerbots(self):
        self.backup_cmd(lambda d:[
            f"mkdir -p '{d}/playerbots'",
            f"cp -a /root/azerothcore-wotlk/modules/mod-playerbots '{d}/playerbots/'",
            f"cp -a /root/azerothcore-wotlk/env/dist/etc/modules/playerbots.conf '{d}/playerbots/' 2>/dev/null || true"
        ],"playerbots")

    def backup_all(self):
        self.backup_cmd(lambda d:[
            f"mkdir -p '{d}/mysql' '{d}/configs' '{d}/source'",
            f"mysqldump --all-databases --single-transaction --routines --events > '{d}/mysql/all-databases.sql'",
            f"cp -a /root/azerothcore-wotlk/env/dist/etc/. '{d}/configs/'",
            f"tar -czf '{d}/source/azerothcore-custom.tar.gz' -C /root/azerothcore-wotlk modules 2>/dev/null",
            f"cp -a /root/start.sh /root/.bashrc '{d}/' 2>/dev/null || true"
        ],"full")

    def list_backups(self):
        if not self.need():
            return
        cmd=r"""find /root/ember-backups -mindepth 1 -maxdepth 1 \( -type d -o -type f -name '*.7z' \) ! -name '.tmp_*' -printf '%TY-%Tm-%Td %TH:%TM\t%p\n' 2>/dev/null | sort -r"""
        def worker():
            out=self.exec(cmd).strip()
            rows=[]
            for line in out.splitlines():
                if "\t" in line:
                    date,path=line.split("\t",1)
                    rows.append((date.strip(),path.strip()))
            self.q.put(("backup_list",rows))
        threading.Thread(target=worker,daemon=True).start()

    def _selected_backup_path(self):
        sel=self.backup_tree.selection() if hasattr(self,"backup_tree") else ()
        if not sel:
            return None
        vals=self.backup_tree.item(sel[0],"values")
        return str(vals[1]) if len(vals)>=2 else None

    def open_selected_backup(self):
        path=self._selected_backup_path()
        if not path:
            messagebox.showwarning("Backups","Select a backup first." if self.language.get()=="EN" else "Sélectionne d'abord un backup.")
            return
        self.show("Fichiers")
        target=posixpath.dirname(path) if path.lower().endswith(".7z") else path
        self.path.delete(0,"end"); self.path.insert(0,target)
        self.list_remote()

    def delete_selected_backup(self):
        path=self._selected_backup_path()
        if not path:
            return "break"
        norm=posixpath.normpath(path)
        if not norm.startswith("/root/ember-backups/") or norm == "/root/ember-backups":
            messagebox.showerror("Backups","Refusing to delete a path outside /root/ember-backups.")
            return "break"
        title="Delete backup" if self.language.get()=="EN" else "Supprimer le backup"
        msg=(f"Permanently delete this backup?\\n\\n{norm}" if self.language.get()=="EN"
             else f"Supprimer définitivement ce backup ?\\n\\n{norm}")
        if not messagebox.askyesno(title,msg):
            return "break"
        import shlex
        try:
            out=self.exec(f"rm -rf -- {shlex.quote(norm)} 2>&1")
            if out.strip(): self.back_out.insert("end",out+"\\n")
            self.list_backups()
        except Exception as exc:
            messagebox.showerror("Backups",str(exc))
        return "break"

    def backup_context_menu(self,event):
        row=self.backup_tree.identify_row(event.y)
        if row:
            self.backup_tree.selection_set(row); self.backup_tree.focus(row)
        menu=tk.Menu(self,tearoff=0)
        if self.language.get()=="EN":
            menu.add_command(label="Open folder",command=self.open_selected_backup)
            menu.add_command(label="Delete backup",command=self.delete_selected_backup)
        else:
            menu.add_command(label="Ouvrir le dossier",command=self.open_selected_backup)
            menu.add_command(label="Supprimer le backup",command=self.delete_selected_backup)
        try: menu.tk_popup(event.x_root,event.y_root)
        finally: menu.grab_release()

    def _fmt_size(self,size):
        try:
            size=float(size)
            for unit in ["B","KB","MB","GB","TB"]:
                if size < 1024 or unit=="TB":
                    return f"{size:.0f} {unit}" if unit=="B" else f"{size:.1f} {unit}"
                size/=1024
        except:
            return ""

    # ---------- Local pane ----------
    def list_local(self):
        path=Path(self.local_path.get()).expanduser()
        try:
            path=path.resolve()
            self.local_path.set(str(path))
            for x in self.local_tree.get_children():
                self.local_tree.delete(x)
            self.local_entries={}
            items=sorted(path.iterdir(),key=lambda q:(not q.is_dir(),q.name.lower()))
            for item in items:
                try:
                    isdir=item.is_dir()
                    size="" if isdir else self._fmt_size(item.stat().st_size)
                    kind="Dossier" if isdir else item.suffix.lower().lstrip(".") or "Fichier"
                    iid=self.local_tree.insert("", "end", text=item.name, values=(size,kind))
                    self.local_entries[iid]=item
                except Exception:
                    pass
        except Exception as e:
            messagebox.showerror("Fichiers locaux",str(e))

    def local_parent(self):
        p=Path(self.local_path.get()).expanduser()
        parent=p.parent
        if parent == p:
            return
        self.local_path.set(str(parent))
        self.list_local()

    def local_open(self,event=None):
        sel=self.local_tree.selection()
        if not sel:
            return
        item=self.local_entries.get(sel[0])
        if item and item.is_dir():
            self.local_path.set(str(item))
            self.list_local()

    def choose_local_folder(self):
        d=filedialog.askdirectory(initialdir=self.local_path.get())
        if d:
            self.local_path.set(d)
            self.list_local()

    # ---------- Remote pane ----------
    def list_remote(self):
        if not self.need():
            return
        p=self.path.get().strip() or "/"
        try:
            entries=self.sftp.listdir_attr(p)
            entries.sort(key=lambda e:(not stat.S_ISDIR(e.st_mode),e.filename.lower()))
            for x in self.remote_tree.get_children():
                self.remote_tree.delete(x)
            self.remote_entries={}
            for e in entries:
                isdir=stat.S_ISDIR(e.st_mode)
                size="" if isdir else self._fmt_size(e.st_size)
                kind="Dossier" if isdir else posixpath.splitext(e.filename)[1].lstrip(".") or "Fichier"
                iid=self.remote_tree.insert("", "end", text=e.filename, values=(size,kind))
                self.remote_entries[iid]=e
        except Exception as e:
            messagebox.showerror("SFTP",str(e))

    def remote_open(self,event=None):
        sel=self.remote_tree.selection()
        if not sel:
            return
        e=self.remote_entries.get(sel[0])
        if e and stat.S_ISDIR(e.st_mode):
            n=posixpath.join(self.path.get(),e.filename)
            self.path.delete(0,"end")
            self.path.insert(0,n)
            self.list_remote()

    def parent(self):
        n=posixpath.dirname(self.path.get().rstrip("/")) or "/"
        self.path.delete(0,"end")
        self.path.insert(0,n)
        self.list_remote()

    def sftp_back(self,event=None):
        self.parent()
        return "break"

    # ---------- Transfers ----------
    def upload_selected(self):
        if not self.need():
            return
        sel=self.local_tree.selection()
        if not sel:
            messagebox.showwarning("SFTP","Sélectionne un fichier local.")
            return
        local=self.local_entries.get(sel[0])
        if not local or local.is_dir():
            messagebox.showwarning("SFTP","L'envoi de dossier complet sera ajouté ensuite ; sélectionne un fichier.")
            return
        remote=posixpath.join(self.path.get(),local.name)

        def w():
            try:
                self.q.put(("transfer",f"Envoi de {local.name}..."))
                self.sftp.put(str(local),remote)
                self.q.put(("transfer","Envoi terminé"))
                self.q.put(("refresh_remote",None))
            except Exception as e:
                self.q.put(("transfer",f"Erreur : {e}"))
        threading.Thread(target=w,daemon=True).start()

    def download_selected(self):
        if not self.need():
            return
        sel=self.remote_tree.selection()
        if not sel:
            messagebox.showwarning("SFTP","Sélectionne un fichier serveur.")
            return
        e=self.remote_entries.get(sel[0])
        if not e or stat.S_ISDIR(e.st_mode):
            messagebox.showwarning("SFTP","Le téléchargement de dossier complet sera ajouté ensuite ; sélectionne un fichier.")
            return
        remote=posixpath.join(self.path.get(),e.filename)
        local=Path(self.local_path.get()) / e.filename

        def w():
            try:
                self.q.put(("transfer",f"Téléchargement de {e.filename}..."))
                self.sftp.get(remote,str(local))
                self.q.put(("transfer","Téléchargement terminé"))
                self.q.put(("refresh_local",None))
            except Exception as ex:
                self.q.put(("transfer",f"Erreur : {ex}"))
        threading.Thread(target=w,daemon=True).start()

    def remote_new_folder(self):
        if not self.need():
            return
        dlg=ctk.CTkInputDialog(text="Nom du nouveau dossier :",title="Nouveau dossier serveur")
        name=dlg.get_input()
        if not name:
            return
        try:
            self.sftp.mkdir(posixpath.join(self.path.get(),name))
            self.list_remote()
        except Exception as e:
            messagebox.showerror("SFTP",str(e))

    def remote_delete_selected(self):
        if not self.need():
            return
        sel=self.remote_tree.selection()
        if not sel:
            return
        e=self.remote_entries.get(sel[0])
        if not e:
            return
        remote=posixpath.join(self.path.get(),e.filename)
        if not messagebox.askyesno("Supprimer la sélection",f"Supprimer uniquement cet élément sur le serveur ?\n\n{remote}"):
            return
        try:
            if stat.S_ISDIR(e.st_mode):
                self.sftp.rmdir(remote)
            else:
                self.sftp.remove(remote)
            self.list_remote()
        except Exception as ex:
            messagebox.showerror("SFTP",str(ex))

    def remote_context_menu(self,event):
        row=self.remote_tree.identify_row(event.y)
        if row:
            self.remote_tree.selection_set(row); self.remote_tree.focus(row)
        menu=tk.Menu(self,tearoff=0)
        if self.language.get()=="EN":
            menu.add_command(label="Open",command=self.remote_open)
            menu.add_command(label="Delete",command=self.remote_delete_selected)
        else:
            menu.add_command(label="Ouvrir",command=self.remote_open)
            menu.add_command(label="Supprimer",command=self.remote_delete_selected)
        try: menu.tk_popup(event.x_root,event.y_root)
        finally: menu.grab_release()

    # ---------- Search ----------
    def search_local(self):
        q=self.file_search.get().strip().lower()
        if not q:
            return
        root=Path(self.local_path.get())
        self.transfer_status.configure(text=f"Recherche locale : {q}")

        def w():
            results=[]
            try:
                for base,dirs,files in os.walk(root):
                    dirs[:]=[d for d in dirs if d.lower() not in {
                        ".git","__pycache__",".cache","node_modules"
                    }]
                    for name in dirs+files:
                        if q in name.lower():
                            full=Path(base)/name
                            try:
                                isdir=full.is_dir()
                                size="" if isdir else self._fmt_size(full.stat().st_size)
                            except:
                                isdir=False
                                size=""
                            results.append({
                                "name":name,"folder":str(Path(base)),"full":str(full),
                                "type":"Dossier" if isdir else (full.suffix.lower().lstrip(".") or "Fichier"),
                                "size":size,"isdir":isdir
                            })
                            if len(results)>=300: break
                    if len(results)>=300: break
            except Exception as e:
                results=[{"name":"ERREUR","folder":"","full":str(e),"type":"","size":"","isdir":False}]
            self.q.put(("search_results",("local",q,results)))
        threading.Thread(target=w,daemon=True).start()

    def search_remote(self):
        if not self.need():
            return
        q=self.file_search.get().strip()
        if not q:
            return
        root=self.path.get().strip() or "/"
        self.transfer_status.configure(text=f"Recherche serveur : {q}")

        import shlex
        rootq=shlex.quote(root)
        qq=shlex.quote(f"*{q}*")
        cmd=(
            f"find {rootq} "
            "\\( -path '*/.git' -o -path '*/.git/*' "
            "-o -path '*/var/build' -o -path '*/var/build/*' "
            "-o -path '*/__pycache__' -o -path '*/__pycache__/*' \\) -prune -o "
            f"-iname {qq} -printf '%y\\t%s\\t%f\\t%h\\n' 2>/dev/null | head -n 300"
        )

        def w():
            out=self.exec(cmd)
            results=[]
            for line in out.splitlines():
                cols=line.split("\t",3)
                if len(cols)!=4: continue
                typ,size,name,folder=cols
                isdir=(typ=="d")
                results.append({
                    "name":name,"folder":folder,"full":posixpath.join(folder,name),
                    "type":"Dossier" if isdir else (posixpath.splitext(name)[1].lstrip(".") or "Fichier"),
                    "size":"" if isdir else self._fmt_size(size),"isdir":isdir
                })
            self.q.put(("search_results",("remote",q,results)))
        threading.Thread(target=w,daemon=True).start()

    def show_search_results(self,side,q,results):
        dlg=ctk.CTkToplevel(self)
        dlg.title(f"Recherche {'serveur' if side=='remote' else 'locale'} — {q}")
        dlg.geometry("1120x650")
        dlg.minsize(850,450)
        dlg.transient(self)

        head=ctk.CTkFrame(dlg,fg_color="transparent")
        head.pack(fill="x",padx=16,pady=(14,8))
        ctk.CTkLabel(head,text=f"{len(results)} résultat(s)",
                     font=ctk.CTkFont(size=22,weight="bold")).pack(side="left")
        ctk.CTkLabel(head,text="Recherche par nom • .git et var/build ignorés",
                     text_color="gray65").pack(side="right")

        frame=ctk.CTkFrame(dlg)
        frame.pack(fill="both",expand=True,padx=16,pady=(0,10))
        tree=ttk.Treeview(frame,columns=("name","folder","type","size"),
                          show="headings",selectmode="browse",style="Ember.Treeview")
        for col,title,width,anchor in [
            ("name","Nom",260,"w"),("folder","Dossier",560,"w"),
            ("type","Type",100,"center"),("size","Taille",100,"e")
        ]:
            tree.heading(col,text=title)
            tree.column(col,width=width,anchor=anchor)

        sy=ttk.Scrollbar(frame,orient="vertical",command=tree.yview)
        sx=ttk.Scrollbar(frame,orient="horizontal",command=tree.xview)
        tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        tree.grid(row=0,column=0,sticky="nsew")
        sy.grid(row=0,column=1,sticky="ns")
        sx.grid(row=1,column=0,sticky="ew")
        frame.grid_rowconfigure(0,weight=1)
        frame.grid_columnconfigure(0,weight=1)

        item_map={}
        for result in results:
            iid=tree.insert("","end",values=(
                result["name"],result["folder"],result["type"],result["size"]))
            item_map[iid]=result

        def open_selected():
            sel=tree.selection()
            if not sel: return
            result=item_map.get(sel[0])
            if not result: return
            if side=="remote":
                target=result["full"] if result["isdir"] else result["folder"]
                self.path.delete(0,"end"); self.path.insert(0,target)
                dlg.destroy(); self.list_remote()
            else:
                target=Path(result["full"]) if result["isdir"] else Path(result["folder"])
                self.local_path.set(str(target))
                dlg.destroy(); self.list_local()

        tree.bind("<Double-Button-1>",lambda e:open_selected())

        bottom=ctk.CTkFrame(dlg,fg_color="transparent")
        bottom.pack(fill="x",padx=16,pady=(0,14))
        ctk.CTkLabel(bottom,text="Double-clic = ouvrir l'emplacement",
                     text_color="gray65").pack(side="left")
        ctk.CTkButton(bottom,text="Ouvrir l'emplacement",
                      command=open_selected).pack(side="right",padx=(8,0))
        ctk.CTkButton(bottom,text="Fermer",fg_color="gray35",
                      command=dlg.destroy).pack(side="right")
        self.transfer_status.configure(text=f"Recherche terminée : {len(results)} résultat(s)")

    def drain(self):
        try:
            while True:
                t,v=self.q.get_nowait()
                if t=="conn":
                    state_map={
                        "Connecté":"connected","Connected":"connected",
                        "Connexion…":"connecting","Connecting…":"connecting",
                        "Échec":"failed","Failed":"failed",
                        "Déconnecté":"disconnected","Disconnected":"disconnected",
                    }
                    self._render_connection_state(state_map.get(v,"disconnected"))
                elif t=="log":self.console.insert("end",v);self.console.see("end")
                elif t=="shell":self.console.insert("end",v);self.console.see("end")
                elif t=="install_log":
                    if hasattr(self,"install_out"):
                        self.install_out.insert("end",v)
                        self.install_out.see("end")
                elif t=="monitor":
                    vals,data=v
                    self._set_monitor_ui(vals,data)
                elif t=="monitor_error":
                    self.monitor_labels["UPDATED"].configure(text="Erreur monitoring")
                elif t=="acc":self.acc_out.delete("1.0","end");self.acc_out.insert("end",v)
                elif t=="char":self.char_out.delete("1.0","end");self.char_out.insert("end",v)
                elif t=="accounts_popup":self.show_accounts_popup(v)
                elif t=="charinfo":
                    if v is None:
                        self.char_out.insert("end","Personnage introuvable.\n")
                    else:
                        for key,val in v.items():
                            if key in self.char_info_labels:
                                self.char_info_labels[key].configure(text=str(val))
                        self.char_level.set(str(v.get("level","1")))
                        self.char_account.set(str(v.get("account","")))
                        self.char_out.insert("end",f"Fiche chargée : {self.char_name.get()}\n")
                elif t=="backup":
                    self.back_out.insert("end",v+"\n");self.back_out.see("end")
                elif t=="refresh_backups":
                    self.list_backups()
                elif t=="crashes":
                    if hasattr(self,"crash_status"):
                        if v:
                            latest=v[0]
                            count=len(v)
                            date=latest[1].split(".")[0]
                            try: size=self._human_bytes(float(latest[2]))
                            except: size=latest[2]
                            self.crash_status.configure(text=f"{count} crash(es) detected",text_color="#d9534f")
                            self.crash_details.configure(text=f"Last: {date}  •  {size}  •  {latest[3]}")
                        else:
                            self.crash_status.configure(text="No crash detected",text_color="#56b870")
                            self.crash_details.configure(text="")
                elif t=="crash_error":
                    if hasattr(self,"crash_status"):
                        self.crash_status.configure(text="Crash check failed",text_color="#d9534f")
                        self.crash_details.configure(text=v)
                elif t=="backup_list":
                    if hasattr(self,"backup_tree"):
                        for item in self.backup_tree.get_children():
                            self.backup_tree.delete(item)
                        for date,path in v:
                            self.backup_tree.insert("","end",values=(date,path))
                    if not v and hasattr(self,"back_out"):
                        self.back_out.insert("end","No backups found.\n" if self.language.get()=="EN" else "Aucun backup trouvé.\n")
                elif t=="transfer":
                    self.transfer_status.configure(text=v)
                elif t=="refresh_remote":
                    self.list_remote()
                elif t=="refresh_local":
                    self.list_local()
                elif t=="search_results":
                    side,q,results=v
                    self.show_search_results(side,q,results)
        except queue.Empty:pass
        self.after(100,self.drain)

    def close(self):
        try:
            self.save_settings()
        except Exception:
            pass
        self.disconnect()
        self.destroy()

if __name__=="__main__":
    EmberAdmin().mainloop()
