"""Gemeinsame Test-Fixtures für die Backend-Testsuite.

Aktuell ohne eigene Fixtures - der `requests_mock`-Fixture kommt direkt vom
`requests-mock`-Pytest-Plugin, FastAPIs `TestClient` wird pro Testmodul lokal
instanziiert. Diese Datei existiert als zentraler Ort für künftige, über
mehrere Testmodule geteilte Fixtures.
"""
