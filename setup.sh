#!/bin/bash
# =============================================================================
# Citrix Auto-Login — Setup Script
# =============================================================================
# Run this ONCE to install everything the auto-login script needs.
#
# WHAT THIS SCRIPT DOES:
# 1. Installs Homebrew (if not already installed) — macOS package manager
# 2. Installs Python 3 (if not already installed)
# 3. Installs ChromeDriver (the Selenium-to-Chrome bridge)
# 4. Installs the Python packages we need (selenium)
# 5. Stores your Citrix credentials in macOS Keychain
# 6. Creates a keyboard shortcut via an Automator Quick Action
#
# HOW TO RUN:
#   chmod +x setup.sh
#   ./setup.sh
# =============================================================================

set -e  # Exit immediately if any command fails

echo "========================================="
echo "  Citrix Auto-Login — Setup"
echo "========================================="
echo ""

# ---- Step 1: Homebrew ----
# Homebrew is the standard package manager for macOS. It lets you install
# command-line tools and applications from the terminal.
echo "Step 1: Checking for Homebrew..."
if ! command -v brew &> /dev/null; then
    echo "  Homebrew not found. Installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add Homebrew to PATH for Apple Silicon Macs
    if [[ $(uname -m) == "arm64" ]]; then
        echo '  eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
else
    echo "  Homebrew is already installed. ✓"
fi

# ---- Step 2: Python 3 ----
echo ""
echo "Step 2: Checking for Python 3..."
if ! command -v python3 &> /dev/null; then
    echo "  Installing Python 3 via Homebrew..."
    brew install python3
else
    echo "  Python 3 is already installed. ✓"
fi

# ---- Step 3: ChromeDriver ----
# ChromeDriver is a separate program that Selenium uses to control Chrome.
# It must match your installed Chrome version (roughly).
echo ""
echo "Step 3: Installing ChromeDriver..."
brew install --cask chromedriver 2>/dev/null || echo "  (chromedriver may already be installed)"

# On first run, macOS may block chromedriver. This removes the quarantine flag.
echo "  Removing macOS quarantine flag from chromedriver..."
xattr -d com.apple.quarantine $(which chromedriver) 2>/dev/null || true
echo "  ChromeDriver ready. ✓"

# ---- Step 4: Python packages ----
echo ""
echo "Step 4: Installing Python packages..."
pip3 install selenium
echo "  Python packages installed. ✓"

# ---- Step 5: Store credentials in Keychain ----
echo ""
echo "Step 5: Storing your Citrix credentials in macOS Keychain..."
echo "  (Your password will be stored encrypted, not in plain text)"
echo ""
read -p "  Enter your Citrix username: " citrix_user
read -s -p "  Enter your Citrix password: " citrix_pass
echo ""

# Delete any existing entry (ignore errors if it doesn't exist)
security delete-generic-password -s "citrix-autologin" 2>/dev/null || true

# Add the new entry
# -a = account (username)
# -s = service name (our label to find it later)
# -w = password
security add-generic-password -a "$citrix_user" -s "citrix-autologin" -w "$citrix_pass"
echo "  Credentials stored in Keychain. ✓"

# ---- Step 6: Create keyboard shortcut via Automator ----
echo ""
echo "Step 6: Creating keyboard shortcut..."

# Get the directory where this setup script lives
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Create an Automator Quick Action (workflow) that runs our Python script.
# Quick Actions can be assigned keyboard shortcuts in System Settings.
WORKFLOW_DIR="$HOME/Library/Services/Citrix Auto-Login.workflow"
CONTENTS_DIR="$WORKFLOW_DIR/Contents"

mkdir -p "$CONTENTS_DIR"

# The Info.plist tells Automator this is a "no input" service
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

# The workflow document (what actually runs)
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
                    <string>osascript -e 'tell application "Terminal"
    activate
    do script "python3 ${SCRIPT_DIR}/citrix_autologin.py"
end tell'</string>
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

echo "  Automator Quick Action created. ✓"
echo ""

# ---- Step 7: Remind about permissions ----
echo "========================================="
echo "  SETUP COMPLETE!"
echo "========================================="
echo ""
echo "REMAINING MANUAL STEPS:"
echo ""
echo "1. SET UP KEYBOARD SHORTCUT:"
echo "   → System Settings → Keyboard → Keyboard Shortcuts → Services"
echo "   → Find 'Citrix Auto-Login' in the General section"
echo "   → Click 'Add Shortcut' and press your desired key combo"
echo "   → Recommended: Ctrl+Shift+C"
echo ""
echo "3. UPDATE THE SCRIPT with your Citrix login page details:"
echo "   → Open citrix_autologin.py in a text editor"
echo "   → Change CITRIX_URL to your actual login URL"
echo "   → Update the CSS selectors to match your login page"
echo "   → (See the comments in the script for how to find selectors)"
echo ""
echo "4. CLOSE CHROME before first run (Selenium needs exclusive access"
echo "   to the Chrome profile on the first launch)."
echo ""
echo "To test, run:  python3 ${SCRIPT_DIR}/citrix_autologin.py"
