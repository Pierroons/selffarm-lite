# Bibliothèques et polices servies par l'app

Copiées ici pour que les pages ne chargent rien d'un autre domaine. Une mise à jour
remplace le fichier, sa ligne ci-dessous et le chemin versionné dans les templates.

| Fichier | Source | Licence |
|---|---|---|
| `htmx/1.9.12/htmx.min.js` | tarball npm `htmx.org@1.9.12`, `dist/` | 0BSD (`htmx/1.9.12/LICENSE`) |
| `leaflet/1.9.4/` (js, css, images) | tarball npm `leaflet@1.9.4`, `dist/` | BSD-2-Clause (`leaflet/1.9.4/LICENSE`) |
| `fonts/inter-*.woff2` | Google Fonts, Inter v20, sous-ensembles latin et latin-ext | OFL-1.1 (`fonts/OFL-inter.txt`) |
| `fonts/fraunces-*.woff2` | Google Fonts, Fraunces v38, axes opsz et wght, latin et latin-ext | OFL-1.1 (`fonts/OFL-fraunces.txt`) |

Les tarballs npm ont été vérifiés contre l'empreinte `integrity` publiée par le registre.

## SHA-256

```
a2930b27d13a228bd9ab6a49269b5f800237892ad560cb9dd7fab01b1620f88e  ./fonts/fraunces-latin-ext.woff2
7234ed860a9cc83045413c4faee63c960a8f2d1917adcf728119307d56e0d783  ./fonts/fraunces-latin.woff2
34b9c504cab7a73e37b746343a449132e56cf7b5481af2cb81dc74dcff25c956  ./fonts/inter-latin-ext.woff2
3100e775e8616cd2611beecfa23a4263d7037586789b43f035236a2e6fbd4c62  ./fonts/inter-latin.woff2
449317ade7881e949510db614991e195c3a099c4c791c24dacec55f9f4a2a452  ./htmx/1.9.12/htmx.min.js
066daca850d8ffbef007af00b06eac0015728dee279c51f3cb6c716df7c42edf  ./leaflet/1.9.4/images/layers-2x.png
1dbbe9d028e292f36fcba8f8b3a28d5e8932754fc2215b9ac69e4cdecf5107c6  ./leaflet/1.9.4/images/layers.png
00179c4c1ee830d3a108412ae0d294f55776cfeb085c60129a39aa6fc4ae2528  ./leaflet/1.9.4/images/marker-icon-2x.png
574c3a5cca85f4114085b6841596d62f00d7c892c7b03f28cbfa301deb1dc437  ./leaflet/1.9.4/images/marker-icon.png
264f5c640339f042dd729062cfc04c17f8ea0f29882b538e3848ed8f10edb4da  ./leaflet/1.9.4/images/marker-shadow.png
a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6  ./leaflet/1.9.4/leaflet.css
db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a  ./leaflet/1.9.4/leaflet.js
```
