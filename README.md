# Fotos BYD Simone — carpeta estandarizada

Una sola carpeta plana con todas las fotos de los autos, nombres uniformes y sin duplicados.
Generada por `estandarizar.py` desde las carpetas crudas, que **no se tocan** y quedan en `origen/`.

Esta carpeta es la que va al repo público de GitHub para que las URLs de las imágenes sean
deterministas y no se caigan como las de la KB de laburen.com.

Mismo pipeline que [`fotos-dalian`](https://github.com/Laburen/fotos-dalian), con cuatro
diferencias que están explicadas abajo: la metadata sale del path, el nombre tiene 5 campos,
las fotos se redimensionan y el detalle se extrae de nombres en tres idiomas.

## Convención de nombres

```
<marca>_<modelo>_<vista>_<color>_<detalle>.<ext>
```

Cinco campos fijos separados por `_`. Todo minúscula, solo `a-z 0-9 . - _`.

| Campo | Valores |
|---|---|
| `marca` | `byd` siempre |
| `modelo` | `atto2` · `dolphinmini` · `seal5` · `sealu` · `shark` · `songpro` · `ti7` · `yuanpro` |
| `vista` | `exterior` · `interior` · `detalle` · `sd` (sin dato) |
| `color` | de la carpeta: `malachite-darkcyan`, `snow-white`, `gravel-beige`… · `sd` si no aplica |
| `detalle` | descriptor con `-`: `high-end-wheels-left-diagonal`, `instrument-panel`, `luz-trasera` |

**`campo[1]` es siempre el modelo.** Ese es el punto de tener campos fijos: el script del catálogo
parsea por posición sin ambigüedad, y a simple vista se ve si un archivo está mal nombrado.

`fotos-dalian` usa 4 campos porque ahí el color no venía separado. Acá sí, y es dato de venta:
el cliente pregunta "¿la tenés en negro?", así que el color merece campo propio y el catálogo
agrupa por color.

### Carrocería y tapizado no son la misma escala

`interior_black` es el **tapizado**, `exterior_obsidian-black` es la **carrocería**. El catálogo
los lista en dos líneas separadas a propósito: el Atto 2 tiene tapizado Black pero ninguna foto
de carrocería negra, y mezclados en una sola lista el agente le diría al cliente que tiene fotos
del negro y después no encontraría ninguna.

## La metadata sale del path, no del filename

En `fotos-dalian` el nombre del archivo era la única fuente. Acá el árbol de carpetas ya dice todo:

```
Atto 2 / Exterior / Malachite Darkcyan / 04.ATTO 2 DMi_LHD_..._Left 45°_download_JPG_RGB.jpg
modelo   vista      color                filename -> solo el <detalle>
```

**El path es la autoridad.** Hay fotos en `Malachite Darkcyan` cuyo filename dice "Midnight Blue",
y fotos en `Detalles/` que se llaman "Exterior12": gana la carpeta, y el script las lista en la
sección **A REVISAR** del informe para que las mires. Si alguna está mal archivada, movela en
`origen/` y volvé a correr — el script nunca adivina.

| Carpeta nivel 2 | vista | color |
|---|---|---|
| `Exterior/<Color>/` | `exterior` | el nombre de la subcarpeta |
| `Exterior/` (Ti7) | `exterior` | `sd` |
| `Interior Black/` | `interior` | `black` |
| `Interior Gravel Beige/` | `interior` | `gravel-beige` |
| `Interior/` (Ti7) | `interior` | `sd` |
| `Detalles/` | `detalle` | `sd` |
| sueltas en la raíz del modelo (Shark) | `sd` | `sd` |

## Las fotos se redimensionan

Es lo único que rompe con el "los bytes quedan intactos" de `fotos-dalian`, y es obligado: las
fotos que manda BYD son masters de imprenta. La más pesada era de **17.730 × 9.974 px / 66 MB**.
**35 de las 194 superaban los 20 MB, que es el límite por archivo de jsDelivr**, o sea que tal cual
estaban esas URLs no iban a servir.

- `sips -Z 2000` sobre el lado largo. **Se redimensiona, no se recorta**: la proporción y el
  encuadre quedan intactos, solo bajan los píxeles. WhatsApp recomprime todo a ~1600 px, así que
  arriba de 2000 el cliente no vería un pixel más — solo tardaría más en cargar.
- JPEG a calidad 85.
- **Los PNG se mantienen PNG.** Tres de los cuatro tienen canal alpha; pasarlos a JPEG les pondría
  fondo negro.
- El master original no se toca: queda en `origen/`, fuera de git.

Resultado: **2017 MB → 90 MB (96% menos)**, con las proporciones verificadas contra el original.

El md5 se calcula sobre el **original**, antes del resize. Es lo que hace idempotente el modo
incremental y lo que detecta los duplicados.

## El detalle sale de nombres sucios

Los filenames vienen en tres estados y el script no adivina en ninguno:

- **Inglés aprovechable**: `Instrument Panel` → `instrument-panel`, `Left 45°` → `left-diagonal`,
  `Wheel Hub` → `wheel-hub`.
- **Chino**: tabla de traducción en `modelos.json` para los tokens que describen la foto
  (`车尾灯` → `luz-trasera`, `俯视` → `vista-superior`, `蓝侧` → `lateral`, `蓝45` → `diagonal`).
  La jerga de la web de BYD (`官网配图选配页` = página de opciones, `拷贝` = copia) va a stopwords:
  no describe la foto.
- **Basura y mojibake** (`Copia de 1 (13).jpg`, `H-189 (1).jpg`, `┐¢▒┤`): sin detalle, se numeran.

Dos detalles de implementación que no son obvios y que rompen si se tocan:

1. **La traducción corre antes de `sin_acentos()`.** El mojibake `íó` lleva acentos; si se
   normaliza primero queda en `io` y se cuela al nombre como `01iodolphin`.
2. **El filename se pasa a NFC antes de traducir.** macOS guarda los nombres en NFD
   (descompuesto), así que `íó` del filesystem no matchea el `íó` de la tabla, que está en NFC.

A diferencia de `fotos-dalian`, un carácter fuera de `[a-z0-9._-]` **no aborta** la corrida: se
descarta ese token. Acá la mitad de los nombres tiene chino o mojibake. El nombre final igual
pasa entero por `RE_LIMPIO` en `validar()`.

## Qué hay acá

| | |
|---|---|
| `fotos/` | 193 archivos, una sola carpeta plana, 90 MB. Es lo que se sube al repo. |
| `origen/` | Carpetas crudas tal como llegan, 2.0 GB. **Fuera de git** (`.gitignore`). |
| `inventario.csv` | 193 filas: nombre · modelo · vista · color · detalle · origen · md5 · dimensiones · bytes antes y después. |
| `modelos.json` | Mapeo carpeta→modelo, vistas, colores, traducción del chino, stopwords. |
| `estandarizar.py` | El script. Solo stdlib + `sips` (viene con macOS). |
| `generar_catalogo.py` | Lee el inventario → arma las URLs de jsDelivr → `catalogos/*.md` + `*.pdf`. |
| `catalogos/` | Un `.md` + un `.pdf` **por fecha de generación**. El `.pdf` del día es lo que se sube a la KB. |

`inventario.csv` es la fuente del catálogo PDF y lo que hace todo esto auditable.

## Cómo agregar fotos nuevas

**No pisa nada de lo ya publicado**: el script descarta por md5 lo que ya está en el inventario y
apendea solo las filas nuevas, así que el diff de git muestra exactamente qué se agregó.

1. Meté la carpeta cruda en `origen/`, con el mismo árbol: `<Modelo>/<Vista>/<Color>/`.
2. Si el modelo es nuevo, agregalo a `carpetas` en `modelos.json`. Si aparece un color nuevo no
   hace falta tocar nada: sale de la carpeta.
3. `python3 estandarizar.py` → dry-run. **Leé la tabla de renombres y la sección A REVISAR.**
4. `python3 estandarizar.py --aplicar`
5. `git add fotos/ inventario.csv && git commit && git push` — hasta acá las URLs dan 404.
6. `python3 generar_catalogo.py` y después `--verificar`.
7. Subí a la KB de laburen.com el PDF del día: `catalogos/catalogo-fotos-byd-simone-<DD_MM_AAAA>.pdf`.
   El script lo imprime al final, con la ruta completa.

El paso 5 va **antes** del 6 a propósito: `--verificar` hace un `curl` real contra cada URL, y eso
solo puede pasar si los archivos ya están pusheados.

**Dale unos minutos entre el push y el `--verificar`.** jsDelivr re-arma su caché del repo después
de cada push y en esa ventana puede devolver 404 en archivos que existen. Si `--verificar` marca
fallas, volvé a correrlo antes de salir a buscar el problema.

El script es idempotente y aborta antes de escribir si falla cualquier validación: colisiones
contra lo ya publicado, caracteres fuera de `[a-z0-9._-]`, extensión doble, un archivo sin 5
campos, o un nombre de más de 75 chars.

### Por qué el tope de 75 chars

La URL final es `https://cdn.jsdelivr.net/gh/Laburen/fotos-byd-simone/fotos/` (59 chars) + el
nombre. Medido en Chrome —el mismo motor que imprime el PDF— en Menlo a 6.5pt cada char ocupa
1,379 mm, y la página deja 192 mm útiles: entran 139 chars. **Una URL que no entra se parte en dos
líneas, y una URL partida la extrae mal el parser de la KB**, así que `send_files` recibe una URL
rota. 75 + 59 = 134, con aire.

Hoy el nombre más largo mide 71 chars y la URL más ancha ocupa 179 de los 192 mm. El tope es una
guarda para que un filename largo del futuro no se cuele sin aviso: el script recorta el
`<detalle>` por palabra entera antes de pasarse.

### El catálogo va fechado

Cada corrida escribe `catalogo-fotos-byd-simone-DD_MM_AAAA.{md,pdf}` con la fecha del día, y los
catálogos viejos quedan. La fecha va **también impresa abajo del título**, adentro del documento:
el PDF se sube a la KB a mano y el nombre del archivo puede no sobrevivir a la subida, así que sin
eso no habría forma de saber qué versión quedó cargada.

Si generás dos veces el mismo día se pisa el archivo de ese día, que es lo que querés.

## Estado

**194 archivos en origen → 193 en `fotos/` + 1 duplicado exacto descartado + 0 en POR-REVISAR.**

| Modelo | Fotos |
|---|---|
| BYD Song Pro | 51 |
| BYD Yuan Pro | 46 |
| BYD Ti7 | 32 |
| BYD Atto 2 | 28 |
| BYD Dolphin Mini | 26 |
| BYD Shark | 6 |
| BYD Seal U | 4 |
| **BYD Seal 5** | **0 — sin ninguna foto** |

`BYD Seal 5` tiene carpeta pero está vacía. Se cubre desde el **catálogo**: `generar_catalogo.py`
le escribe su propia sección con el aviso de que no hay fotos y de que no las ofrezca (ver
`SIN_FOTOS` en el script y `sin_fotos` en `modelos.json`). Como el agente tiene que buscar en la
KB antes de mandar nada, se encuentra con el aviso en vez de con URLs. Si algún día aparecen
fotos del Seal 5, sacalo de las dos listas.

### Pendientes conocidos

- **Los nombres de modelo no están atados a un prompt.** En `fotos-dalian` los valores de `modelos`
  son los literales exactos de la lista `lead_model` del prompt. Todavía no existe un prompt de BYD
  Simone, así que acá salen del nombre de la carpeta. **Cuando exista, hay que re-atarlos en
  `modelos.json` y regenerar el catálogo**, o el agente va a buscar un modelo con un nombre que no
  coincide.
- **6 archivos con vista `sd`**: los del Shark, que vienen sueltos sin carpeta de vista ni color.
  El modelo es correcto, que es lo único que define qué fotos manda el agente; falta la etiqueta
  interior/exterior, que solo afecta el texto descriptivo del PDF. Para arreglarlo, ordenalos en
  `origen/Shark/Exterior/<Color>/` y volvé a correr.
- **16 archivos con el filename contradiciendo la carpeta** (`Detalles/` con nombres que dicen
  "Interior", `Interior Gravel Beige/Copia de Exterior16.jpg`). Gana la carpeta. El informe los
  lista en cada corrida.
- **19 fotos del Dolphin Mini** tienen filename `DOLPHIN SURF` / `DOLPHIN SUER` (el nombre
  internacional del modelo). Se toman como Dolphin Mini por el path.
- **Carpetas vacías** que el script ignora: `Seal 5/`, `Atto 2/Exterior/Obsidian Black/`,
  `Atto 2/Exterior/Time Grey/`, `Dolphin Mini/Interior/`, `Song Pro/Interior Black/`.
