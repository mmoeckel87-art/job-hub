# Prüfung des Veröffentlichungsexports

- Ausschließlich Python-Quelldateien aus dem Job-Hub-Modul übernommen; keine privaten Datenordner.
- Private Profilnamen, Serveradresse und Login-Allowlist entfernt beziehungsweise konfigurierbar gemacht.
- Rechercheauftrag durch profilneutrale Anleitung ersetzt; zweites persönliches Recherchebriefing nicht übernommen.
- Keine Git-Historie, Deployment-Plist, SMTP-Konfiguration, PDFs, Fotos, Logs oder Passkey-Daten übernommen.
- Externer Mailconnector durch optionale SMTP-Umgebungsvariablen ersetzt.
- Sieben Prüfungen bestanden: Datenschutz-Export, Offline-Oberfläche mit leerem Profil, SMTP-Konfiguration,
  allgemeine Kontaktadresse als ungeeigneter Bewerbungsempfänger, Gehaltsschwelle bei überlappender Spanne.
- Alle Python-Dateien erfolgreich kompiliert; zusätzliche Suche nach typischen Tokens, privaten Schlüsseln
  und internen IP-Adressen ohne Treffer. Kein vollständiges Security-Audit oder Live-Versandtest.
- ZIP enthält ausschließlich die geprüften Textdateien, keine alte Commit-Autorenschaft.
- MIT-Lizenz ergänzt, mit neutraler Urheberangabe. Prüfung des späteren GitHub-Kontos/Commit-Absenders steht vor Veröffentlichung aus.
- Datenstand: separater lokaler Export; spätere Änderungen am privaten Hub werden nicht automatisch übernommen.

Aktualisiert auf den lokal verifizierten Stand 450f9cd: Stellenzusammenfassungen, Nicht-passend-Aktion mit optionalem Grund, Rückgängig und dauerhafte Ablehnung. Der private Arbeitsbaum für das Modul war unverändert. Private Originaltests wurden nicht übernommen oder als Exporttests ausgegeben.

Zusätzlich geprüft: Ablehnung bleibt nach Portalwechsel erhalten und lässt sich rückgängig machen; nachrecherchierte Zusammenfassungen bleiben erhalten.
