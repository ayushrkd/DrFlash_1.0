"""Create a Windows startup shortcut for Dr. Flash.

Run this once to add Dr. Flash to Windows Startup.
It will start automatically when you log in.
"""

import os
import sys
from pathlib import Path


def create_shortcut():
    project_dir = Path(__file__).parent
    bat_path = project_dir / "start.bat"

    # Windows Startup folder
    startup_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    shortcut_path = startup_dir / "Dr. Flash.lnk"

    try:
        import winreg
        # Use COM to create a proper .lnk shortcut
        import subprocess
        ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{bat_path}"
$Shortcut.WorkingDirectory = "{project_dir}"
$Shortcut.Description = "Dr. Flash - Personal AI Companion"
$Shortcut.WindowStyle = 7
$Shortcut.Save()
'''
        subprocess.run(["powershell", "-Command", ps_script], check=True, capture_output=True)
        print(f"✅ Startup shortcut created at:")
        print(f"   {shortcut_path}")
        print(f"\n   Dr. Flash will start automatically on login.")
        print(f"   To remove, delete: {shortcut_path}")
    except Exception as e:
        print(f"❌ Failed to create shortcut: {e}")
        print(f"\n   Manual setup:")
        print(f"   1. Press Win+R, type: shell:startup")
        print(f"   2. Create a shortcut to: {bat_path}")


def remove_shortcut():
    startup_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    shortcut_path = startup_dir / "Dr. Flash.lnk"
    if shortcut_path.exists():
        shortcut_path.unlink()
        print("✅ Startup shortcut removed. Dr. Flash won't auto-start.")
    else:
        print("ℹ No startup shortcut found.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--remove":
        remove_shortcut()
    else:
        create_shortcut()
