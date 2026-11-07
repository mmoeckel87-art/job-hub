# Sicherheit und Datenschutz

Keine Passwörter, Tokens, CVs, Fotos, echten Profile, Bewerbungen, Sitzungen oder Logs in
Issues, Screenshots oder Commits einstellen. `.gitignore` schützt nur ungetrackte Dateien.
Die ausgelieferte Konfiguration sperrt Zugriff ohne explizit konfigurierte Identität.
SMTP sendet ausschließlich; private Postfächer werden nicht abgerufen.
Die Anwendung besitzt einen eigenen WebAuthn-Parser und nutzt System-OpenSSL. Diese
Veröffentlichung ist kein unabhängiges Sicherheitsaudit. Betrieb im privaten Tailnet;
Proxy muss eingehende Identitätsheader zuverlässig überschreiben.
