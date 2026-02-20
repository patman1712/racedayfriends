# RaceDayFriends Logo
Du hast ein Logo zur Verfügung gestellt.
Um es anzuzeigen, speichere deine Logo-Datei (z.B. logo.png) in den Ordner:
`racedayfriends/static/img/logo.png`

Dann ändere in `templates/base.html` die Zeile:
`<a href="/"><h2 ...>RDF...</h2></a>`
zu:
`<a href="/"><img src="{{ url_for('static', filename='img/logo.png') }}" alt="RaceDayFriends"></a>`
