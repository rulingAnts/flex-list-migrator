#!/usr/bin/env bash
# =============================================================================
#  Set up Run/Build on Parallels VM   —  edit the SETTINGS block, then reuse.
# -----------------------------------------------------------------------------
#  What it does (it does NOT run/build anything itself):
#    1. Deletes the old snapshot of this repo on the VM  (DEST_ROOT\<repo>)
#    2. Copies the current repo there fresh (via the Parallels shared folder)
#    3. Writes BATCH_NAME into that snapshot containing RUN_CMD
#  You then double-click BATCH_NAME inside the VM to build/run in your own
#  desktop session (prlctl runs as SYSTEM/session-0, where GUIs are invisible,
#  so the actual launch is left to you).
#
#  Reuse in another project: copy the whole .vscode/ folder over and edit only
#  the SETTINGS block below (usually just RUN_CMD).
# =============================================================================

# ----------------------------- SETTINGS --------------------------------------
VM_NAME="Windows 11"                 # Parallels VM name (prlctl list -a)

# The Parallels shared folder that exposes your Mac repos to the VM.
MAC_SHARE_ROOT="/Users/Seth/GIT"     # Mac side of that shared folder
VM_UNC_ROOT='\\Mac\GIT'              # how the VM sees the SAME folder (UNC)

DEST_ROOT='C:\GIT'                   # where snapshots are placed inside the VM
BATCH_NAME="run-on-vm.bat"           # batch dropped into the snapshot

# The build/run command the batch will execute. Working dir = the snapshot repo.
# Runs in YOUR VM session when you launch the batch, so PATH is available;
# a full python path is used here to be safe. Edit per project.
RUN_CMD='"C:\Users\Seth\AppData\Local\Programs\Python\Python313\python.exe" flex_list_migrator.py'

# Folders to skip when copying (space-separated, robocopy /XD).
EXCLUDE_DIRS='.git .venv __pycache__ node_modules'
# --------------------------- END SETTINGS ------------------------------------

set -euo pipefail

# Workspace folder is passed as $1 (VSCode ${workspaceFolder}; prompts to pick
# one in a multi-root workspace). Fall back to the script's parent repo.
WS="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
WS="${WS%/}"
REPO="$(basename "$WS")"

# Path of this repo relative to the share root -> mirror it on both sides.
case "$WS" in
  "$MAC_SHARE_ROOT"/*) REL="${WS#"$MAC_SHARE_ROOT"/}" ;;
  *) echo "ERROR: workspace '$WS' is not under MAC_SHARE_ROOT '$MAC_SHARE_ROOT'."
     echo "       Adjust MAC_SHARE_ROOT/VM_UNC_ROOT in the SETTINGS block."; exit 1 ;;
esac
RELWIN="${REL//\//\\}"                 # forward slashes -> backslashes
SRC_UNC="$VM_UNC_ROOT\\$RELWIN"        # e.g. \\Mac\GIT\flex-list-migrator
DEST="$DEST_ROOT\\$RELWIN"             # e.g. C:\GIT\flex-list-migrator

echo "VM            : $VM_NAME"
echo "Source (Mac)  : $WS"
echo "Source (VM)   : $SRC_UNC"
echo "Destination   : $DEST"
echo "Run command   : $RUN_CMD"
echo "------------------------------------------------------------------------"

# --- 0. Make sure the VM is awake -------------------------------------------
STATUS="$(prlctl status "$VM_NAME" 2>/dev/null | awk '{print $NF}')"
echo "VM status: ${STATUS:-unknown}"
case "$STATUS" in
  running)            : ;;                       # already up
  suspended|paused)   echo "Resuming VM..."; prlctl resume "$VM_NAME" ;;
  stopped|*)          echo "Starting VM...";  prlctl start  "$VM_NAME" ;;
esac
# Wait until Parallels Tools answers, so the shared folder / exec are ready.
for i in $(seq 1 30); do
  if prlctl exec "$VM_NAME" cmd /c "echo ok" >/dev/null 2>&1; then break; fi
  echo "  waiting for VM tools ($i)..."; sleep 2
done

# --- 1. Delete the old snapshot ---------------------------------------------
echo "Deleting old snapshot..."
prlctl exec "$VM_NAME" cmd /c "if exist \"$DEST\" rmdir /s /q \"$DEST\""

# --- 2. Copy the repo fresh --------------------------------------------------
echo "Copying repo to VM..."
XD=""; for d in $EXCLUDE_DIRS; do XD="$XD /XD \"$DEST\\$d\" \"$SRC_UNC\\$d\""; done
# robocopy exit codes 0-7 are success; treat >=8 as failure.
prlctl exec "$VM_NAME" cmd /c "robocopy \"$SRC_UNC\" \"$DEST\" /E /NFL /NDL /NJH /NJS /R:1 /W:1 $XD & if errorlevel 8 (exit /b 1) else (exit /b 0)"

# --- 3. Write the launch batch into the snapshot ----------------------------
echo "Writing $BATCH_NAME ..."
# Assemble the batch body with CRLF line endings.
BATCH="$(printf '@echo off\r\ncd /d "%s"\r\n%s\r\necho.\r\npause\r\n' "$DEST" "$RUN_CMD")"
# Ferry it in as base64 so RUN_CMD may contain any quotes/backslashes safely.
B64="$(printf '%s' "$BATCH" | base64 | tr -d '\n')"
prlctl exec "$VM_NAME" powershell -NoProfile -Command \
  "[IO.File]::WriteAllBytes('$DEST\\$BATCH_NAME', [Convert]::FromBase64String('$B64'))"

echo "------------------------------------------------------------------------"
echo "Done. On the VM, launch:"
echo "    $DEST\\$BATCH_NAME"
