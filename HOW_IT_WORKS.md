# Citrix Auto-Login: How It All Works

## The Big Picture

This automation replaces the tedious daily routine of:
1. Opening Chrome → navigating to the Citrix URL
2. Typing your username and password
3. Waiting for the Authenticator push
4. Going back to Chrome after approving
5. Clicking on each Citrix app to launch it

Instead, you press **one keyboard shortcut**, tap **Approve + Face ID** on your phone, and all your apps launch automatically.

---

## The Technology Stack (What Each Piece Does)

### Python
The scripting language that ties everything together. It's pre-installed on every Mac.

### Selenium
A Python library that **controls your web browser programmatically**. Originally built for testing websites, it's perfect for automating repetitive web tasks. When you write `driver.find_element(...)`, Selenium communicates with ChromeDriver, which tells Chrome what to do.

### ChromeDriver
A small program that acts as a translator between Selenium (Python) and Chrome (the browser). Selenium says "click this button" in its own protocol, and ChromeDriver converts that into something Chrome understands.

### macOS Keychain
Your Mac's built-in encrypted credential vault. Rather than storing your password in a text file (dangerous!), we store it in Keychain where it's encrypted and protected by your Mac's login password.

### Automator Quick Action
A built-in macOS feature that lets you create services that appear in menus and can be assigned keyboard shortcuts. We use it as the glue that connects your keyboard shortcut to running the Python script.

---

## The Flow, Step by Step

```
You press Ctrl+Shift+C (or your chosen shortcut)
        │
        ▼
macOS triggers the Automator Quick Action
        │
        ▼
Automator runs: python3 citrix_autologin.py
        │
        ▼
Script reads username/password from Keychain
  (security find-generic-password -s "citrix-autologin" -w)
        │
        ▼
Selenium opens Chrome → navigates to Citrix URL
        │
        ▼
IF a "New Login Instructions" splash page appears:
  → Script clicks the "Continue" button to dismiss it
        │
        ▼
Selenium fills in username (#login) + password (#passwd)
        │
        ▼
Selenium clicks "Log On" (#loginBtn)
  → Microsoft sends push notification to your phone
        │
        ▼
Script starts POLLING: checks browser URL every 2 seconds
  "Has the page changed? No → wait 2 more seconds"
  "Has the page changed? No → wait 2 more seconds"
        │
        ▼
YOU tap Approve + Face ID on your phone
        │
        ▼
Browser redirects to the Citrix portal
        │
        ▼
Script detects the URL change → "Login complete!"
        │
        ▼
Script waits for the Citrix portal to fully load
        │
        ▼
Script clicks the "All Apps" tab (#allAppsFilterBtn)
  → Makes all 21 apps visible (not just favorites)
        │
        ▼
Script launches apps in order:
  1. Epic Production
  2. Aria Home
  3. MIM
  4. RayStation 2024A SP3
  (clicks each icon, waits 3 seconds between launches)
        │
        ▼
All apps launched! Browser stays open, you're ready to work.
```

---

## Key Concepts Explained

### Polling (How We Detect Approval)
The script can't directly "know" when you've tapped Approve on your phone. Instead, it uses a technique called **polling** — checking the same thing over and over at regular intervals.

Think of it like checking your mailbox every 2 minutes to see if a package arrived. The script checks the browser URL every 2 seconds. Before you approve, the URL contains words like "login" or "auth". After you approve, the browser redirects to the Citrix portal (a completely different URL). The script detects this change and knows you're in.

This is better than using `time.sleep(30)` (a fixed wait), because polling proceeds the **instant** approval happens rather than waiting a fixed duration.

### CSS Selectors
These are patterns that identify elements on a web page. The script uses them to find the username field, password field, and buttons. The `#` symbol means "find by ID" — so `#login` finds the element with `id="login"`.

Here are the selectors used in this script:

| Selector | What it finds | The HTML element |
|----------|--------------|-----------------|
| `#login` | Username field | `<input id="login" ...>` |
| `#passwd` | Password field | `<input id="passwd" ...>` |
| `#loginBtn` | Log On / Continue button | `<a id="loginBtn" ...>` |
| `#allAppsFilterBtn` | "All Apps" tab on the portal | `<a id="allAppsFilterBtn" ...>` |

If your Citrix deployment changes these IDs in the future, you can find the new ones by right-clicking on the element in Chrome and selecting **Inspect**.

### WebDriverWait vs. time.sleep()
Both make the script pause, but they work very differently:

- `time.sleep(10)` → Always waits exactly 10 seconds, even if the page loaded in 1 second. Wasteful.
- `WebDriverWait(driver, 30)` → Checks every half-second if the thing you're waiting for has appeared. Proceeds instantly when ready, gives up after 30 seconds. Smart.

The script uses `WebDriverWait` for page elements and polling for the push approval.

### macOS Keychain Security
When you run `security add-generic-password`, your password is encrypted using your Mac's login credentials and stored in the system keychain. The Python script retrieves it with `security find-generic-password` — macOS may prompt you to allow access the first time. After that, it's seamless. Your password is **never** stored as plain text anywhere.

### XPath vs. CSS Selectors (How We Find Apps)
For the login form, we use CSS selectors (like `input[name='username']`). But for finding apps on the Citrix portal, we also use **XPath** — a more powerful way to search a web page.

XPath lets us search by **text content**, which is perfect for finding an app by its name. For example, `//*[contains(text(), 'Outlook')]` means "find any element anywhere on the page that contains the text 'Outlook'." CSS selectors can't do text matching, which is why we need XPath here.

The script tries multiple strategies (XPath text match, CSS data attributes, image alt text, title attributes) because different Citrix deployments build their portals differently.

### Why We Delay Between App Launches
When you click an app in Citrix, the portal starts a process: it contacts the Citrix server, provisions a virtual session, downloads an ICA file (the connection file), and launches the Citrix client. This takes a few seconds. If you click three apps instantly, the portal can get confused and some launches may fail. The configurable delay (`APP_LAUNCH_DELAY`) gives each launch time to initiate before starting the next.

---

## Files In This Package

| File | Purpose |
|------|---------|
| `citrix_autologin.py` | The main script — automates the login flow |
| `setup.sh` | One-time setup — installs dependencies, stores credentials |
| `HOW_IT_WORKS.md` | This file — explains everything |

---

## What Can and Can't Be Automated

| Step | Automated? | Why? |
|------|-----------|------|
| Open Chrome to login URL | Yes | Selenium controls the browser |
| Dismiss "New Login Instructions" page | Yes | Script detects the page and clicks Continue |
| Type username + password | Yes | Pulled from Keychain, typed by Selenium |
| Click Log On | Yes | Selenium clicks the button |
| Approve push notification | **No** | Requires your phone + Face ID (by design) |
| Detect approval happened | Yes | Script polls the browser URL for changes |
| Click "All Apps" tab | Yes | Script clicks the tab to reveal all apps |
| Launch Citrix apps | Yes | Selenium clicks each app icon on the portal |

The push notification approval is the one step you still do manually — and that's intentional. It's the security boundary that proves *you* (not just your computer) are authorizing the login.

---

## Troubleshooting

### Chrome doesn't open / "session not created"
- Make sure Chrome is **closed** before running (first time only)
- Check that ChromeDriver version matches your Chrome version: `chromedriver --version`
- Update with: `brew upgrade --cask chromedriver`

### "No credentials found in Keychain"
- Re-run: `security add-generic-password -a "YOUR_USER" -s "citrix-autologin" -w "YOUR_PASS"`

### Script says "Login detected!" but Citrix isn't fully loaded
- Increase the post-login wait: add `time.sleep(5)` after the success message in the script
- Or use Option B (element detection) — see the comments in the script

### Script times out waiting for approval
- Default timeout is 120 seconds — increase `PUSH_APPROVAL_TIMEOUT` if needed
- Make sure you're approving the notification promptly

### The selectors aren't working (fields not found)
- The script is configured for the current login page (`#login`, `#passwd`, `#loginBtn`). If your IT department updates the login page in the future, the selectors may need updating
- Right-click the field that isn't working → Inspect, and look for a new `id` attribute
- Update the matching selector at the top of `citrix_autologin.py`

### Push notification never arrives
- This is a Microsoft Authenticator issue, not a script issue
- Make sure Authenticator is set up correctly and notifications are enabled
- Try logging in manually once to confirm the push flow works

### Apps not found on portal ("WARNING: Could not find...")
- The app name must match **exactly** what's displayed on the portal (case-sensitive)
- Log in manually, look at the app icon labels, and copy the names precisely
- Some portals require scrolling or switching tabs/categories to see all apps — the script can only find apps that are currently visible on the page
- If apps are in a different tab/category on the portal, you may need to add a step in the script to click that tab first

### Only some apps launch
- Increase `APP_LAUNCH_DELAY` — your Citrix server may need more time between launches
- Try launching fewer apps at once to see if that helps

---

## Security Notes

- **Passwords are never stored in plain text** — they live in macOS Keychain (encrypted)
- **The script never sends your credentials anywhere** except to your Citrix login page
- **2FA still requires your physical phone + Face ID** — the script can't bypass this
- **No special macOS permissions needed** — unlike the SMS approach, we don't read any databases
