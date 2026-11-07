# Job Hub

Privater, selbst gehosteter Jobmonitor mit deutschsprachiger Oberfläche: Stellen recherchieren,
Passung bewerten, Gehaltsspannen mit Quellen einordnen, Bewerbungswege verwalten und
Bewerbungsentwürfe freigeben. Recherche nutzt eine separat installierte und angemeldete
Claude-Code-CLI. Modellnutzung kann Kosten verursachen. Keine Garantie für Stellen- oder Gehaltsdaten.

## Start

Python 3.9 oder neuer; aus der Repository-Wurzel:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m job_monitor.cli --profile demo init
python -m job_monitor.cli --profile demo status
```

Das erzeugte `job_monitor/data/profiles/demo/profile.json` lokal ausfüllen. Die Vorlage
ist absichtlich unvollständig und pausiert. `examples/` enthält nur erfundene Beispiele,
keine einsatzbereiten Bewerberdaten. `verified_at` im Anzeigenbeispiel muss vor einem
Ingest auf den tatsächlichen Prüfzeitpunkt gesetzt werden. Alle Befehle: `python -m job_monitor.cli --help`.

## Weboberfläche und Zugang

`python -m job_monitor.server` lauscht ausschließlich auf 127.0.0.1:8792.
Die eigentliche Oberfläche ist durch Tailscale-Identität UND Passkey geschützt; der lokale
Start allein schaltet sie nicht frei. Für den Zugriff werden Tailscale Serve (HTTPS),
OpenSSL und diese exportierten Variablen benötigt:

```sh
export JOB_HUB_PUBLIC_HOST='your-device.your-tailnet.ts.net'
export JOB_HUB_HTTPS_PORT=8446
export JOB_HUB_ALLOWED_LOGINS='your-tailscale-login@example.invalid'
python -m job_monitor.auth enroll
```

Den lokalen Port mittels Tailscale Serve im eigenen Tailnet auf den passenden HTTPS-Port
weiterleiten, dann dem Enrollment-Link folgen. Login und Host durch eigene Werte ersetzen.
Die Beispiele in `.env.example` werden NICHT automatisch geladen. Leere Login-Liste sperrt
alle Benutzer. `/health` ist ein öffentlich lesbarer Healthcheck. Das öffentliche GitHub-
Repository bedeutet keine öffentliche Freigabe des laufenden Hubs. Keine öffentliche
Internetbereitstellung oder Tailscale Funnel ohne gesonderte Sicherheitsprüfung.

## Bewerbungsentwürfe

Für angepasste Texte wird zusätzlich ein lokaler Ollama-Server benötigt. Standardmodell:
`qwen3.5:9b`; über JOB_MONITOR_MODEL anpassbar. OLLAMA_HOST konfiguriert den Server.
Ohne lokales Modell sind Recherche und Übersicht nutzbar, die Textgenerierung jedoch nicht.

## Recherche und Versand

Claude Code separat installieren, anmelden und `claude auth status` prüfen. Optional
`JOB_MONITOR_CLAUDE_BIN` setzen. Die Rechercheanweisungen liegen im Paket als Markdown.
Eine Zeitplanung ist in dieser Veröffentlichung nicht eingerichtet.

SMTP entweder über exportierte MAIL_SMTP_* Variablen oder eine private `smtp.env` im
Profilordner konfigurieren (siehe `examples/smtp.env.example`, Dateirechte 600 verwenden).
Kein external-Connector erforderlich. Versand ist standardmäßig NICHT freigeschaltet:
`JOB_MONITOR_APPLY_ARMED=0`, `application.auto_send=false`. Für echten Versand wird die
explizite Freigabe mit `JOB_MONITOR_APPLY_ARMED=1` benötigt. Private Unterlagen und Daten
gehören ausschließlich in den ignorierten Datenordner oder in JOB_MONITOR_DATA_DIR.

## Prüfung

```sh
python -m unittest discover -s tests -v
```

## Veröffentlichungsstand

Dies ist ein separater Export ohne private Git-Historie, Profile, Unterlagen, Fotos,
SMTP-Dateien, Logs oder Passkey-Daten. Kein Benutzerkonto und keine Zugangsdaten enthalten.
Lizenz: MIT (siehe LICENSE). Freie Nutzung, Änderung und Weitergabe, auch kommerziell,
unter Beibehaltung des Lizenz- und Copyright-Hinweises. Keine fremden Markenassets enthalten.
