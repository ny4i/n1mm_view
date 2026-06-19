# Using the n1mm_view Web Server

`webserver.py` is a small Flask app that serves the dashboard and a JSON API
over HTTP. It binds to `0.0.0.0:8080` by default (see the `[WEBSERVER]`
section in `n1mm_view.ini.sample`), so it is reachable on every interface the
Pi has. Installation of the service itself is covered in `INSTALL_RASPI.md`
(the "built-in web server" section); this document covers the features it
serves and how to use them.

Browse to `http://<pi-ip>:8080/` (e.g. `http://pi400.local:8080/`).

## Mobile view

Phones and tablets that load `http://<pi-ip>:8080/` are auto-redirected (by
User-Agent) to a single-column **mobile view**: event countdown/clock, last
QSO, live radio status, the QSOs-by-band/mode summary, and new operators. It
pulls the live JSON API and refreshes itself — no slideshow scaling.

- Direct link: `http://<pi-ip>:8080/m`
- Force the full slideshow on a phone: `http://<pi-ip>:8080/?big=1`
- Large screens are unaffected and still get the slideshow at `/`.

## Resilient kiosk display

If you drive a TV / HDMI-stick kiosk straight at `http://<pi-ip>:8080/`, the
browser will strand itself on its own "can't reach the site" error page any
time the Pi is briefly unreachable — a reboot, a network blip, or simply the
Pi not being up yet when the kiosk powers on. That error page runs no
JavaScript, so it never retries: the display stays dead until someone reloads
it by hand.

The web server serves a wrapper page that fixes this. It runs the dashboard
inside an iframe and pings the Pi every few seconds; while the Pi is
unreachable it shows a "Waiting for pi400…" overlay and keeps retrying, and
when the Pi returns it reloads the dashboard automatically. Because it never
navigates away, it can't land on the browser error page.

Two ways to point the kiosk at it:

1. **Pi-served (quickest):** set the kiosk URL to
   `http://<pi-ip>:8080/kiosk`. Once loaded it self-heals through any later
   outage. Caveat: if the Pi is *down at the moment the kiosk first opens the
   URL*, the wrapper itself can't load — you are back to the browser error
   page until the Pi is up.

2. **Local file (survives a cold start):** copy `kiosk_loader.html` onto the
   kiosk and open it as a local file. Because it loads from local disk it
   *always* comes up and waits for the Pi, even if the Pi is off when the
   kiosk powers on:

   ```
   chromium-browser --kiosk --app=file:///home/<user>/kiosk_loader.html
   ```

   `kiosk_loader.html` targets `http://pi400.local:8080` by default; if the Pi
   answers to a different name/IP or port, edit the `var PI = ...` line near
   the top of the file. It is generated from the `KIOSK_HTML` template in
   `webserver.py` — keep the two in sync if you change one.

To test either option: load it, then `sudo systemctl stop n1mm_view_webserver`
on the Pi — the overlay appears within a few seconds — and
`sudo systemctl start n1mm_view_webserver` — the dashboard returns on its own.

### Autostart the kiosk on boot (Windows stick PC)

To make a Windows kiosk (e.g. an HDMI stick PC) come up in the dashboard
automatically, launch Chrome from the **Startup** folder pointed at the local
`kiosk_loader.html`. With Option B this is fully cold-start safe: the stick can
boot before the Pi and simply waits on the "Waiting for pi400…" screen until
the Pi is ready.

1. **Copy the file to the stick's local disk**, e.g. `C:\kiosk\kiosk_loader.html`.

2. **Set the Pi address in the file.** Open `kiosk_loader.html` in a text editor
   and confirm the line near the top points at your Pi:

   ```
   var PI = 'http://pi400.local:8080';
   ```

   If `pi400.local` does not resolve on Windows (mDNS is often unavailable),
   use the Pi's IP, e.g. `var PI = 'http://192.168.0.100:8080';`.

3. **Create a Chrome shortcut** with this target (adjust the Chrome path and
   file path to match the machine):

   ```
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --kiosk "file:///C:/kiosk/kiosk_loader.html"
   ```

   Useful extra flags for an unattended kiosk: `--noerrdialogs`
   `--disable-session-crashed-bubble` `--disable-infobars` — these suppress the
   "Restore pages?" / crash bubbles that Chrome otherwise shows after a power
   cut, which would sit on top of the dashboard.

4. **Put the shortcut in the Startup folder** so it launches at login: press
   `Win+R`, type `shell:startup`, press Enter, and drop the shortcut into the
   folder that opens (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`).

On the next boot the stick logs in, Chrome opens full-screen on the wrapper,
and the dashboard appears as soon as the Pi's web server is reachable. Press
`Alt+F4` (or `Ctrl+W`) to exit kiosk mode. The same idea works on a Linux stick
using the autostart mechanism for its desktop (e.g. a `.desktop` entry in
`~/.config/autostart/`) running the `chromium-browser --kiosk` command above.
