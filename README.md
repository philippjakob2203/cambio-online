# Cambio Online

## Lokal spielen

Python 3.9 oder neuer genügt; zusätzliche Pakete sind nicht erforderlich.

```sh
python3 server.py
```

Öffne danach `http://localhost:8002`. Andere Geräte im selben Netzwerk können über die lokale IP-Adresse des Rechners beitreten, auf dem der Server läuft.

## Öffentlich bereitstellen

1. Lade das Projekt in ein GitHub-Repository hoch.
2. Erstelle bei Render einen neuen Blueprint und verbinde das Repository.
3. Render liest `render.yaml`, baut den Server und stellt die Website unter einer öffentlichen URL bereit.
4. Erstelle einen Raum und teile den Einladungslink.

Der Server verwendet nur Python-Standardbibliotheken. Räume und laufende Partien liegen vorerst im Arbeitsspeicher und gehen bei einem Serverneustart verloren. Ein einzelnes 55-Karten-Deck unterstützt bis zu 13 Sitzplätze; Menschen treten per Raumlink bei, CPUs kann die Spielleitung in der Lobby ergänzen oder entfernen.
