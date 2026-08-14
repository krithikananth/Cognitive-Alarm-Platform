# Maestro device E2E flows

Flows live here as YAML (spec §9, task 12). Target flow:

`login -> create alarm 2 minutes out -> lock phone -> alarm fires -> solve challenge ->
verified wake appears on the web dashboard.`

Run against a real device with `maestro test maestro/<flow>.yaml`. Maestro is used instead
of Detox because Detox on Windows/Android is painful to configure (AD-8).
