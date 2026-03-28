#!/bin/bash
# =============================================================================
# Citrix Auto-Login — Installer
# =============================================================================
# Double-click this file to install everything automatically.
# No terminal experience needed!
# =============================================================================

set -e  # Exit immediately if any command fails

# Make sure we're running in the directory where this installer lives
cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"

clear
echo ""
echo "  ╔═══════════════════════════════════════╗"
echo "  ║   Citrix Auto-Login — Installer       ║"
echo "  ╚═══════════════════════════════════════╝"
echo ""
echo "  This will install everything you need."
echo "  You may be prompted for your Mac password"
echo "  during some steps — this is normal."
echo ""
echo "  Press Enter to begin (or close this window to cancel)."
read -r

# ---- Step 1: Homebrew ----
echo ""
echo "━━━ Step 1 of 5: Checking for Homebrew ━━━"
if ! command -v brew &> /dev/null; then
    echo ""
    echo "  Homebrew (a tool installer for Mac) is required."
    echo "  It will now be installed — this may take a few minutes."
    echo ""
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add Homebrew to PATH for Apple Silicon Macs
    if [[ $(uname -m) == "arm64" ]]; then
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
    echo ""
    echo "  ✅ Homebrew installed!"
else
    echo "  ✅ Homebrew is already installed."
fi

# ---- Step 2: Python 3 ----
echo ""
echo "━━━ Step 2 of 5: Checking for Python 3 ━━━"
if ! command -v python3 &> /dev/null; then
    echo "  Installing Python 3..."
    brew install python3
    echo "  ✅ Python 3 installed!"
else
    echo "  ✅ Python 3 is already installed."
fi

# ---- Step 3: Python packages ----
echo ""
echo "━━━ Step 3 of 5: Installing Python packages ━━━"
pip3 install selenium webdriver-manager
echo "  ✅ Python packages installed."
echo "  (ChromeDriver will be auto-managed — no manual install needed)"

# ---- Step 4: Store credentials in Keychain ----
echo ""
echo "━━━ Step 4 of 5: Storing your Citrix credentials ━━━"
echo ""
echo "  Your password will be stored securely in macOS Keychain"
echo "  (encrypted, not in plain text)."
echo ""
echo "  Note: Your username should be in the format: username@scmc.org"
echo ""
read -p "  Enter your Citrix username: " citrix_user

# Validate username isn't empty
while [[ -z "$citrix_user" ]]; do
    echo "  ⚠️  Username cannot be empty."
    read -p "  Enter your Citrix username: " citrix_user
done

read -s -p "  Enter your Citrix password: " citrix_pass
echo ""

# Validate password isn't empty
while [[ -z "$citrix_pass" ]]; do
    echo "  ⚠️  Password cannot be empty."
    read -s -p "  Enter your Citrix password: " citrix_pass
    echo ""
done

# Delete any existing entry (ignore errors if it doesn't exist)
security delete-generic-password -s "citrix-autologin" 2>/dev/null || true

# Store credentials
security add-generic-password -a "$citrix_user" -s "citrix-autologin" -w "$citrix_pass"
echo "  ✅ Credentials stored in Keychain."

# ---- Step 5: Create keyboard shortcut via Automator ----
echo ""
echo "━━━ Step 5 of 5: Creating keyboard shortcut ━━━"

# Create a .command launcher file
LAUNCHER="$SCRIPT_DIR/run_citrix.command"
cat > "$LAUNCHER" << LAUNCHER_SCRIPT
#!/bin/bash
# Launcher for Citrix Auto-Login
# This file is opened by macOS, which runs it in a new Terminal window.
python3 "$SCRIPT_DIR/citrix_autologin.py"
LAUNCHER_SCRIPT
chmod +x "$LAUNCHER"

# Create an Automator Quick Action
WORKFLOW_DIR="$HOME/Library/Services/Citrix Auto-Login.workflow"
CONTENTS_DIR="$WORKFLOW_DIR/Contents"

mkdir -p "$CONTENTS_DIR"

# Info.plist — tells Automator this is a "no input" service
cat > "$CONTENTS_DIR/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>NSServices</key>
    <array>
        <dict>
            <key>NSMenuItem</key>
            <dict>
                <key>default</key>
                <string>Citrix Auto-Login</string>
            </dict>
            <key>NSMessage</key>
            <string>runWorkflowAsService</string>
        </dict>
    </array>
</dict>
</plist>
PLIST

# The workflow document
cat > "$CONTENTS_DIR/document.wflow" << WFLOW
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>AMApplicationBuild</key>
    <string>523</string>
    <key>AMApplicationVersion</key>
    <string>2.10</string>
    <key>AMDocumentVersion</key>
    <string>2</string>
    <key>actions</key>
    <array>
        <dict>
            <key>action</key>
            <dict>
                <key>AMAccepts</key>
                <dict>
                    <key>Container</key>
                    <string>List</string>
                    <key>Optional</key>
                    <true/>
                    <key>Types</key>
                    <array>
                        <string>com.apple.cocoa.string</string>
                    </array>
                </dict>
                <key>AMActionVersion</key>
                <string>2.0.3</string>
                <key>AMApplication</key>
                <array>
                    <string>Automator</string>
                </array>
                <key>AMComment</key>
                <string>Runs the Citrix auto-login Python script</string>
                <key>AMProvides</key>
                <dict>
                    <key>Container</key>
                    <string>List</string>
                    <key>Types</key>
                    <array>
                        <string>com.apple.cocoa.string</string>
                    </array>
                </dict>
                <key>ActionBundlePath</key>
                <string>/System/Library/Automator/Run Shell Script.action</string>
                <key>ActionName</key>
                <string>Run Shell Script</string>
                <key>ActionParameters</key>
                <dict>
                    <key>COMMAND_STRING</key>
                    <string>open "${SCRIPT_DIR}/run_citrix.command"</string>
                    <key>CheckedForUserDefaultShell</key>
                    <true/>
                    <key>inputMethod</key>
                    <integer>1</integer>
                    <key>shell</key>
                    <string>/bin/bash</string>
                    <key>source</key>
                    <string></string>
                </dict>
                <key>BundleIdentifier</key>
                <string>com.apple.RunShellScript</string>
                <key>CFBundleVersion</key>
                <string>2.0.3</string>
                <key>CanShowSelectedItemsWhenRun</key>
                <false/>
                <key>CanShowWhenRun</key>
                <true/>
                <key>Category</key>
                <array>
                    <string>AMCategoryUtilities</string>
                </array>
                <key>Class Name</key>
                <string>RunShellScriptAction</string>
                <key>InputUUID</key>
                <string>0</string>
                <key>Keywords</key>
                <array>
                    <string>Shell</string>
                    <string>Script</string>
                </array>
                <key>OutputUUID</key>
                <string>0</string>
                <key>UUID</key>
                <string>0</string>
                <key>UnlocalizedApplications</key>
                <array>
                    <string>Automator</string>
                </array>
            </dict>
        </dict>
    </array>
    <key>connectors</key>
    <dict/>
    <key>workflowMetaData</key>
    <dict>
        <key>serviceInputTypeIdentifier</key>
        <string>com.apple.Automator.nothing</string>
        <key>workflowTypeIdentifier</key>
        <string>com.apple.Automator.servicesMenu</string>
    </dict>
</dict>
</plist>
WFLOW

echo "  ✅ Keyboard shortcut created."

# ---- Done! ----
echo ""
echo ""
echo "  ╔═══════════════════════════════════════╗"
echo "  ║      ✅  INSTALLATION COMPLETE!       ║"
echo "  ╚═══════════════════════════════════════╝"
echo ""
echo "  ONE MORE THING — set up your keyboard shortcut:"
echo ""
echo "    1. Open System Settings"
echo "    2. Go to Keyboard → Keyboard Shortcuts → Services"
echo "    3. Find 'Citrix Auto-Login' in the General section"
echo "    4. Click 'Add Shortcut' and press Ctrl+Shift+C"
echo "       (or whatever combo you prefer)"
echo ""
echo "  To test right now, just run:"
echo "    Double-click 'run_citrix.command' in this folder"
echo ""
echo "  You can close this window now."
echo ""
