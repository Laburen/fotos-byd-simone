#!/usr/bin/env python3
"""
Genera el catalogo de fotos que se sube a la KB de laburen.com.

Lee inventario.csv, arma las URLs por concatenacion (base fija + path del
archivo) y escribe un PDF + un .md con una seccion por modelo, y adentro de
cada modelo un bloque por (vista, color): el color es un campo propio del
nombre y es lo que pregunta el cliente ("la tenes en negro?").

La salida lleva la fecha del dia en el nombre (catalogo-fotos-byd-simone-15_09_2026)
y adentro del documento. Sin eso no hay forma de saber que version es la que esta
cargada en la KB: el PDF se sube a mano y el nombre del archivo puede no sobrevivir
a la subida, por eso la fecha va tambien impresa abajo del titulo.

Nunca se extrae ni se tipea una URL a mano. Si manana se agregan 50 fotos,
se corre estandarizar.py y despues este script.

Uso:
    python3 generar_catalogo.py              # genera .md + .html + .pdf
    python3 generar_catalogo.py --verificar  # curl -I sobre todas las URLs
"""

import csv
import datetime
import html
import os
import re
import subprocess
import sys
from collections import defaultdict, OrderedDict

# ---------------------------------------------------------------- CONFIG
# Lo unico que hay que editar si cambia el repo o el estilo de URL.

GITHUB_USER = "Laburen"
REPO = "fotos-byd-simone"
BRANCH = "main"
SUBDIR = "fotos"
URL_STYLE = "jsdelivr"  # "raw" | "jsdelivr" | "pages"

# jsdelivr vs raw: los dos sirven el mismo archivo del mismo repo. jsdelivr es
# un CDN y no tiene rate limit, pero cachea unas 12 h: si alguna vez se
# REEMPLAZA una foto conservando el nombre, la vieja puede seguir sirviendose un
# rato. Agregar fotos nuevas no tiene ese problema. Para reemplazar una foto ya
# publicada, subila con otro nombre.
#
# jsDelivr ademas no sirve archivos de mas de 20 MB. Por eso estandarizar.py
# redimensiona: los originales de BYD llegan a 66 MB.

# ------------------------------------------------------------------------

AQUI = os.path.dirname(os.path.abspath(__file__))
INVENTARIO = os.path.join(AQUI, "inventario.csv")
SALIDA = os.path.join(AQUI, "catalogos")

HOY = datetime.date.today()
FECHA_ARCHIVO = HOY.strftime("%d_%m_%Y")
FECHA_TEXTO = HOY.strftime("%d/%m/%Y")

# Modelos que tienen carpeta pero ninguna foto. Van avisados en el catalogo
# para que el agente no ofrezca lo que no existe.
SIN_FOTOS = ["BYD Seal 5"]

# orden de presentacion: primero lo que mas se pide
ORDEN_VISTA = {"exterior": 0, "interior": 1, "detalle": 2, "sd": 3}
NOMBRE_VISTA = {"exterior": "Exterior", "interior": "Interior",
                "detalle": "Detalles", "sd": "Otras fotos"}

CHROME = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
          "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")

# Medido en Chrome (el mismo motor que imprime el PDF): en Menlo a 6.5pt cada
# char ocupa 1.379mm. A4 con margenes laterales de 9mm deja 192mm utiles, o sea
# que entran 139 chars. Se avisa a partir de 134 para tener aire.
#
# fotos-dalian usa 7.5pt y tope 112, pero aca las URLs son mas largas: el repo
# tiene 4 chars mas que "fotos-dalian" y el nombre tiene 5 campos en vez de 4.
# A 7.5pt la mas larga (130 chars) ocupa 207mm y se partiria en dos lineas, que
# es justo lo que rompe la extraccion en la KB.
MAX_CHARS_URL = 134


def base_url():
    if URL_STYLE == "raw":
        return "https://raw.githubusercontent.com/%s/%s/%s/" % (GITHUB_USER, REPO, BRANCH)
    if URL_STYLE == "jsdelivr":
        # sin @version: resuelve a la rama por defecto del repo
        return "https://cdn.jsdelivr.net/gh/%s/%s/" % (GITHUB_USER, REPO)
    if URL_STYLE == "pages":
        return "https://%s.github.io/%s/" % (GITHUB_USER.lower(), REPO)
    sys.exit("URL_STYLE desconocido: %s" % URL_STYLE)


def url_de(nombre):
    return base_url() + ("%s/%s" % (SUBDIR, nombre) if SUBDIR else nombre)


def bonito(token):
    """malachite-darkcyan -> Malachite Darkcyan"""
    return " ".join(p.capitalize() for p in token.split("-"))


def colores_por_vista(grupos, vista):
    """
    Los colores de carroceria y los de tapizado NO se pueden mezclar en una sola
    lista. El Atto 2 tiene tapizado Black pero ninguna foto de carroceria negra:
    listados juntos, el agente le dice al cliente que tiene fotos del negro y
    despues no encuentra ninguna.
    """
    return sorted({c for v, c in grupos if v == vista and c and c != "sd"})


def titulo_grupo(vista, color):
    """Encabezado del bloque: 'Exterior — Malachite Darkcyan'."""
    cabeza = NOMBRE_VISTA.get(vista, vista.capitalize())
    return "%s — %s" % (cabeza, bonito(color)) if color and color != "sd" else cabeza


def etiqueta(vista, color, detalle):
    """
    Descripcion de UNA foto, con vista y color repetidos adentro de la linea.

    Es redundante con el encabezado del bloque a proposito: la KB parte el
    documento en chunks y un chunk puede empezar en la mitad de una lista, sin
    el encabezado. Cada linea tiene que decir sola de que auto y color es.
    """
    partes = [NOMBRE_VISTA.get(vista, vista.capitalize())]
    if color and color != "sd":
        partes.append(bonito(color))
    if detalle:
        limpio = re.sub(r"-\d+$", "", detalle).replace("-", " ")
        if limpio:
            partes.append(limpio)
    return " · ".join(partes)


def leer_inventario():
    if not os.path.exists(INVENTARIO):
        sys.exit("no encuentro %s — corre estandarizar.py --aplicar primero" % INVENTARIO)
    with open(INVENTARIO, encoding="utf-8") as fh:
        filas = [r for r in csv.DictReader(fh) if r["nombre_nuevo"]]
    if not filas:
        sys.exit("el inventario no tiene filas con nombre_nuevo")

    por_modelo = defaultdict(lambda: defaultdict(list))
    for r in filas:
        for modelo in r["modelos"].split(";"):
            modelo = modelo.strip()
            if modelo:
                por_modelo[modelo][(r["vista"], r["color"])].append(r)

    ordenado = OrderedDict()
    for modelo in sorted(por_modelo):
        grupos = por_modelo[modelo]
        claves = sorted(grupos, key=lambda k: (ORDEN_VISTA.get(k[0], 9),
                                               k[1] == "sd", k[1]))
        ordenado[modelo] = OrderedDict(
            (k, sorted(grupos[k], key=lambda r: r["nombre_nuevo"])) for k in claves)
    return ordenado, filas


# ---------------------------------------------------------------- render

INTRO = (
    "Este documento lista las URLs de las fotos de cada modelo BYD. Para enviar una foto "
    "al cliente hay que copiar la URL <b>exacta</b> y pasarla a <code>send_files</code>. "
    "Las URLs no se arman a mano ni se deducen a partir del nombre de otro archivo: "
    "si un modelo no aparece en este documento, no hay fotos de ese modelo. "
    "Cuando el cliente pide un color puntual, buscá el bloque de ese color."
)


def render_md(por_modelo):
    L = ["# Catálogo de fotos BYD Simone", ""]
    L.append("Generado el %s." % FECHA_TEXTO)
    L.append("")
    L.append(re.sub(r"</?(b|code)>", "", INTRO))
    L.append("")
    for modelo, grupos in por_modelo.items():
        total = sum(len(v) for v in grupos.values())
        L.append("---")
        L.append("")
        L.append("## %s" % modelo)
        L.append("")
        L.append("Fotos disponibles de %s: %d." % (modelo, total))
        carroceria = colores_por_vista(grupos, "exterior")
        tapizado = colores_por_vista(grupos, "interior")
        if carroceria:
            L.append("")
            L.append("Colores de carrocería con fotos de %s: %s. No hay fotos de %s "
                     "en ningún otro color."
                     % (modelo, ", ".join(bonito(c) for c in carroceria), modelo))
        if tapizado:
            L.append("")
            L.append("Tapizados interiores con fotos de %s: %s."
                     % (modelo, ", ".join(bonito(c) for c in tapizado)))
        L.append("")
        for (vista, color), fotos in grupos.items():
            L.append("### %s — %s" % (modelo, titulo_grupo(vista, color)))
            L.append("")
            for r in fotos:
                L.append("- **%s** — %s" % (etiqueta(vista, color, r["detalle"]),
                                            url_de(r["nombre_nuevo"])))
            L.append("")
        L.append("Fin de las fotos de %s." % modelo)
        L.append("")
    for modelo in SIN_FOTOS:
        L.append("---")
        L.append("")
        L.append("## %s" % modelo)
        L.append("")
        L.append("No hay fotos disponibles de %s. No ofrecer ni prometer fotos de este "
                 "modelo: ofrecer las del modelo más parecido o invitar al local." % modelo)
        L.append("")
    return "\n".join(L)


def render_html(por_modelo):
    e = html.escape
    P = ["""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Catálogo de fotos BYD Simone</title><style>
@page { margin: 14mm 9mm; }
body { font: 11pt/1.5 -apple-system, "Helvetica Neue", Arial, sans-serif; color: #111; }
h1 { font-size: 20pt; margin: 0 0 1.5mm; }
.fecha { font-size: 9pt; color: #666; margin: 0 0 4mm; }
/* con una sola marca el corte de pagina va por MODELO, que es la unidad que
   busca el agente. En fotos-dalian iba por marca. */
h2 { font-size: 16pt; margin: 0 0 3mm; padding: 2.5mm 4mm; color: #fff;
     background: #111; page-break-before: always; page-break-after: avoid; }
h2.primera { page-break-before: avoid; }
h3 { font-size: 11.5pt; margin: 0 0 1.5mm; padding-top: 3mm;
     border-top: 1.5px solid #111; page-break-after: avoid; }
.intro { background: #f4f4f5; border-left: 3px solid #777; padding: 3mm 4mm;
         margin-bottom: 6mm; font-size: 9.5pt; }
section { margin-bottom: 4mm; }
.cuenta { font-size: 9pt; color: #555; margin: 0 0 1mm; }
.colores { font-size: 9pt; color: #555; margin: 0 0 3mm; }
.foto { margin-bottom: 2.2mm; page-break-inside: avoid; }
.lbl { font-weight: 600; font-size: 9.5pt; }
/* nowrap es lo que importa: una URL partida en dos lineas la extrae mal el
   parser de la KB y send_files recibe una URL rota. El 6.5pt sale de medir:
   la URL mas larga (130 chars) ocupa 179mm de los 192mm utiles. */
.url { font-family: "SF Mono", Menlo, monospace; font-size: 6.5pt;
       color: #14418b; white-space: nowrap; }
.fin { font-size: 8.5pt; color: #666; font-style: italic; margin-top: 2mm; }
.aviso h2 { background: #c22; }
.aviso p { background: #fff4f4; border-left: 3px solid #c22; padding: 3mm 4mm; font-size: 9.5pt; }
</style></head><body>
<h1>Catálogo de fotos BYD Simone</h1>
<p class="fecha">Generado el %s.</p>
<div class="intro">%s</div>""" % (FECHA_TEXTO, INTRO)]

    primera = True
    for modelo, grupos in por_modelo.items():
        total = sum(len(v) for v in grupos.values())
        P.append('<h2%s>%s</h2>' % (' class="primera"' if primera else "", e(modelo)))
        primera = False
        P.append('<p class="cuenta">Fotos disponibles de %s: %d.</p>' % (e(modelo), total))
        carroceria = colores_por_vista(grupos, "exterior")
        tapizado = colores_por_vista(grupos, "interior")
        if carroceria:
            P.append('<p class="colores"><b>Colores de carrocería</b> con fotos de %s: '
                     '%s. No hay fotos de %s en ningún otro color.</p>'
                     % (e(modelo), e(", ".join(bonito(c) for c in carroceria)), e(modelo)))
        if tapizado:
            P.append('<p class="colores"><b>Tapizados interiores</b> con fotos de %s: '
                     '%s.</p>' % (e(modelo), e(", ".join(bonito(c) for c in tapizado))))
        for (vista, color), fotos in grupos.items():
            P.append("<section><h3>%s — %s</h3>"
                     % (e(modelo), e(titulo_grupo(vista, color))))
            for r in fotos:
                P.append('<div class="foto"><span class="lbl">%s</span><br>'
                         '<span class="url">%s</span></div>'
                         % (e(etiqueta(vista, color, r["detalle"])),
                            e(url_de(r["nombre_nuevo"]))))
            P.append("</section>")
        P.append('<p class="fin">Fin de las fotos de %s.</p>' % e(modelo))

    for modelo in SIN_FOTOS:
        P.append('<div class="aviso"><h2>%s</h2><p>No hay fotos disponibles de %s. '
                 'No ofrecer ni prometer fotos de este modelo: ofrecer las del modelo '
                 'más parecido o invitar al local.</p></div>' % (e(modelo), e(modelo)))

    P.append("</body></html>")
    return "\n".join(P)


def a_pdf(ruta_html, ruta_pdf):
    chrome = next((c for c in CHROME if os.path.exists(c)), None)
    if not chrome:
        print("    ! no encontre Chrome ni Brave: queda solo el .md y el .html")
        return False
    r = subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        "--print-to-pdf=%s" % ruta_pdf, "file://%s" % ruta_html],
                       capture_output=True)
    if not os.path.exists(ruta_pdf):
        print("    ! Chrome no genero el PDF: %s" % r.stderr.decode()[:300])
        return False
    return True


# ---------------------------------------------------------------- modos

def generar():
    por_modelo, filas = leer_inventario()
    os.makedirs(SALIDA, exist_ok=True)
    print("Base de URLs (%s):\n  %s\n" % (URL_STYLE, url_de("<archivo>")))

    # Un nombre de archivo largo hace que la URL no entre en el ancho de pagina
    # y se parta en dos lineas; una URL partida la extrae mal el parser de la KB.
    largas = sorted((url_de(r["nombre_nuevo"]) for r in filas
                     if len(url_de(r["nombre_nuevo"])) > MAX_CHARS_URL), key=len, reverse=True)
    if largas:
        print("  ! %d URLs pasan los %d chars y podrian cortarse en el PDF:"
              % (len(largas), MAX_CHARS_URL))
        for u in largas:
            print("      %d  %s" % (len(u), u))
        print("    Acorta el nombre del archivo y volve a correr estandarizar.py.\n")

    nombre = "catalogo-fotos-byd-simone-%s" % FECHA_ARCHIVO
    md = os.path.join(SALIDA, nombre + ".md")
    ht = os.path.join(SALIDA, nombre + ".html")
    pdf = os.path.join(SALIDA, nombre + ".pdf")

    with open(md, "w", encoding="utf-8") as fh:
        fh.write(render_md(por_modelo))
    with open(ht, "w", encoding="utf-8") as fh:
        fh.write(render_html(por_modelo))
    ok = a_pdf(ht, pdf)

    for modelo, grupos in por_modelo.items():
        print("  %-22s %d" % (modelo, sum(len(v) for v in grupos.values())))
        for (vista, color), fotos in grupos.items():
            print("      %-32s %d" % (titulo_grupo(vista, color), len(fotos)))
    for modelo in SIN_FOTOS:
        print("  %-22s 0  (avisado en el catalogo)" % modelo)

    fisicos = len({r["nombre_nuevo"] for r in filas})
    entradas = sum(len(v) for g in por_modelo.values() for v in g.values())
    print("\n  %d archivos fisicos -> %d entradas de catalogo" % (fisicos, entradas))
    print("\n  %s%s" % (nombre, ".pdf + .md" if ok else ".md (sin PDF)"))
    print("  salida: %s" % SALIDA)
    print("\n  A la KB va: %s" % pdf)


def verificar():
    _, filas = leer_inventario()
    urls = sorted({url_de(r["nombre_nuevo"]) for r in filas})
    print("Verificando %d URLs contra %s\n" % (len(urls), base_url()))
    fallas = []
    for i, u in enumerate(urls, 1):
        r = subprocess.run(["curl", "-sIL", "-o", "/dev/null",
                            "-w", "%{http_code} %{content_type}", u],
                           capture_output=True, text=True)
        code, _, ctype = r.stdout.partition(" ")
        bien = code == "200" and ctype.startswith("image/")
        if not bien:
            fallas.append((u, code, ctype.strip() or "?"))
        print("\r  %d/%d  %s" % (i, len(urls), "OK" if bien else "FALLA"), end="", flush=True)
    print("\n")
    if fallas:
        print("  %d de %d FALLARON:" % (len(fallas), len(urls)))
        for u, code, ctype in fallas:
            print("    HTTP %s  %s  %s" % (code, ctype, u))
        print("\n  Si dan 404: el repo esta privado o todavia no se pusheo.")
        print("  Dale unos minutos: jsDelivr re-arma su cache despues de cada push.")
        sys.exit(1)
    print("  %d/%d en HTTP 200 con content-type de imagen." % (len(urls), len(urls)))


if __name__ == "__main__":
    verificar() if "--verificar" in sys.argv else generar()
