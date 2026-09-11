# Azeroth Eras Control

**Azeroth Eras Control** is a Windows administration application for managing an AzerothCore server from a single graphical interface.

It is designed for private AzerothCore environments and provides remote server administration over SSH/SFTP without requiring the MySQL port to be exposed publicly.

## Features

- Persistent SSH console with interactive shell support
- AzerothCore console access through tmux sessions
- SFTP file manager with upload, download, folder creation, deletion and search
- Multiple saved server profiles with one active connection at a time
- Server monitoring for CPU, memory, network and AzerothCore processes
- AzerothCore account management
- RBAC role and permission management
- Character administration tools
- `.7z` backups for databases, configuration, scripts, Playerbots and full server data
- Crash dump detection and optional GDB backtrace analysis
- Server installation and prerequisite helpers
- Playerbots backup tools
- Documentation for the custom Playerbots dynamic level-cap patch
- English and French interface
- Encrypted local configuration storage protected by a master password and recovery code

## Playerbots dynamic level cap

The application documents the optional Playerbots dynamic level-cap modification used by the server environment.

The cap follows the highest-level real connected player:

- Level 1–60 player → bots capped at level 60
- Level 61–70 player → bots capped at level 70
- Level 71–80 player → bots capped at level 80
- Playerbots themselves are excluded from the calculation
- If no real player is connected, the fallback cap is level 60

Required `playerbots.conf` settings:

```ini
AiPlayerbot.SyncLevelWithPlayers = 1
AiPlayerbot.LevelBrackets.Enabled = 1
AiPlayerbot.LevelBrackets.FlaggedProcessLimit = 0
```

The Worldserver must be stopped before replacing patched source files. After applying the source patch and compiling, run:

```text
playerbots rndbot reset
```

Then restart the Worldserver.

## Security

Azeroth Eras Control communicates with the server through SSH. Database administration is performed remotely through the SSH connection, so MySQL does **not** need to be exposed to the Internet on port `3306`.

Local application data is stored under:

```text
%APPDATA%\AzerothErasControl\settings.aec
```

Server profiles, addresses, usernames, preferences and saved credentials are stored in an authenticated encrypted payload. The master password is not stored in plaintext.

No local encryption scheme can protect credentials if the Windows session or the running application itself is already compromised. Keep the host system secured and use strong credentials.

## Building on Windows

Requirements:

- Windows 10/11
- Python 3
- Python available in `PATH`

Run:

```bat
build_exe.bat
```

The build script installs the Python dependencies and PyInstaller, builds `AzerothErasControl.exe`, and cleans temporary build files.

## Server installation

The companion AzerothCore server installation scripts and documentation are maintained here:

https://github.com/syltia/wow

## Disclaimer

This project is an independent administration utility for AzerothCore. It is not affiliated with or endorsed by Blizzard Entertainment or the AzerothCore project.

World of Warcraft and Blizzard Entertainment are trademarks or registered trademarks of Blizzard Entertainment, Inc.

## License

Released under the MIT License. See [LICENSE](LICENSE).
