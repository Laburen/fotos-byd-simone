#!/usr/bin/env python3
"""
Estandariza las fotos de BYD Simone: una sola carpeta plana, nombres uniformes,
sin duplicados. No toca la carpeta origen.

Convencion de salida:  <marca>_<modelo>_<vista>_<color>_<detalle>.<ext>
                       (5 campos fijos: campo[1] SIEMPRE es el modelo)

A diferencia de fotos-dalian, la metadata sale del PATH, no del filename:

    Atto 2 / Exterior / Malachite Darkcyan / 04.ATTO 2 DMi_LHD_...jpg
    modelo   vista      color                filename -> solo el <detalle>

El arbol de carpetas es la autoridad. Si el filename dice otra cosa (hay fotos
en Malachite Darkcyan cuyo nombre dice "Midnight Blue"), gana la carpeta y el
informe lo lista.

Las fotos se REDIMENSIONAN a 2000 px de lado largo con sips: son masters de
imprenta de hasta 17730x9974 px / 66 MB y 35 pasan los 20 MB que es el limite
por archivo de jsDelivr. Se redimensiona, no se recorta: la proporcion y el
encuadre quedan intactos. El master original no se toca, queda en origen/.

Modo unico e incremental: lee origen/, descarta por md5 lo que ya esta en el
inventario y APENDEA solo las filas nuevas. Correrlo dos veces no duplica nada.

Uso:
    python3 estandarizar.py            # dry-run
    python3 estandarizar.py --aplicar
"""

import csv
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import unicodedata
from collections import defaultdict

AQUI = os.path.dirname(os.path.abspath(__file__))
ORIGEN = os.path.join(AQUI, "origen")
DESTINO_FOTOS = os.path.join(AQUI, "fotos")
DESTINO_REVISAR = os.path.join(AQUI, "POR-REVISAR")
INVENTARIO = os.path.join(AQUI, "inventario.csv")

MARCA = "byd"
EXT_VALIDAS = {"jpg", "jpeg", "png"}
RE_LIMPIO = re.compile(r"^[a-z0-9._-]+$")
CAMPOS = 5

# Techo al nombre de archivo. La URL final es base + nombre, y la base de
# jsDelivr mide 59 chars; el PDF del catalogo banca 139 chars de URL antes de
# partirla en dos lineas, y una URL partida la extrae mal el parser de la KB.
# 75 + 59 = 134, con aire. Hoy el nombre mas largo mide 71: esto es una
# guarda para que un filename largo del futuro no se cuele sin aviso.
MAX_NOMBRE = 75


# ---------------------------------------------------------------- utilidades

def cargar_config():
    with open(os.path.join(AQUI, "modelos.json"), encoding="utf-8") as fh:
        return json.load(fh)


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for bloque in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def dimensiones(path):
    """Ancho x alto leyendo el header. Evita depender de sips o PIL."""
    try:
        with open(path, "rb") as fh:
            cab = fh.read(32)
            if cab[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", cab[16:24])
                return w, h
            if cab[:2] == b"\xff\xd8":
                fh.seek(2)
                while True:
                    b = fh.read(1)
                    if not b:
                        break
                    if b != b"\xff":
                        continue
                    marcador = fh.read(1)
                    while marcador == b"\xff":
                        marcador = fh.read(1)
                    if marcador in (b"\xc0", b"\xc1", b"\xc2", b"\xc3",
                                    b"\xc5", b"\xc6", b"\xc7", b"\xc9",
                                    b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf"):
                        fh.read(3)
                        h, w = struct.unpack(">HH", fh.read(4))
                        return w, h
                    largo = fh.read(2)
                    if len(largo) < 2:
                        break
                    fh.seek(struct.unpack(">H", largo)[0] - 2, os.SEEK_CUR)
    except (OSError, struct.error):
        pass
    return 0, 0


def sin_acentos(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if not unicodedata.combining(c))


def slug(texto, cfg_colores=None):
    """Nombre de carpeta -> token limpio. 'Malachite Darkcyan' -> malachite-darkcyan."""
    t = sin_acentos(texto.strip().lower())
    if cfg_colores and t in cfg_colores:
        return cfg_colores[t]
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or "sd"


def normalizar(nombre, cfg):
    """Minuscula, sin acentos, traduccion del chino y correcciones. -> (base, ext)."""
    # La traduccion va ANTES de sin_acentos: el mojibake "\u00ed\u00f3" lleva acentos y
    # sin_acentos lo dejaria en "io", que ya no matchea ninguna regla y se cuela
    # al detalle como "01iodolphin".
    # NFC primero: macOS guarda los filenames en NFD (descompuesto), asi que el
    # mojibake "io" del origen NO matchea la tabla, que esta en NFC.
    n = unicodedata.normalize("NFC", nombre).lower()
    for viejo, nuevo_ in cfg["traduccion"]:
        n = n.replace(viejo.lower(), nuevo_)
    n = sin_acentos(n)
    for viejo, nuevo_ in cfg["normalizacion"]:
        n = n.replace(viejo, nuevo_)
    partes = n.split(".")
    ext = partes[-1] if partes[-1] in EXT_VALIDAS else ""
    base = ".".join(partes[:-1]) if ext else n
    while True:
        p = base.split(".")
        if len(p) > 1 and p[-1] in EXT_VALIDAS:
            base = ".".join(p[:-1])
        else:
            break
    return base, ext


def palabras(base):
    """
    Trocea el nombre en palabras descriptivas.

    Dalian abortaba la corrida ante cualquier caracter fuera de [a-z0-9._-].
    Aca la mitad de los nombres tiene chino o mojibake que la tabla de traduccion
    no cubre, asi que esos tokens se DESCARTAN en vez de abortar: el nombre final
    igual pasa por RE_LIMPIO en validar().
    """
    base = re.sub(r"\.(jpe?g|png)", "", base)
    salida = []
    for p in re.split(r"[\s_\-()\[\].,+°、'\"]+", base):
        p = re.sub(r"[^a-z0-9]", "", p.strip())   # tira chino, mojibake, @, %, etc
        if not p or p.isdigit():
            continue
        if re.fullmatch(r"[\d.:]+", p):
            continue
        # 'exterior16' -> 'exterior', para que caiga como literal de vista
        sin_num = re.sub(r"\d+$", "", p)
        salida.append(sin_num or p)
    return salida


def resolver_path(rel, cfg):
    """
    Deriva (token_modelo, modelos, vista, color, motivo) del path relativo.
    token None = carpeta de modelo no mapeada -> POR-REVISAR.
    """
    tramos = [t for t in rel.split(os.sep)[:-1] if t]
    if not tramos:
        return None, None, "", "", "archivo suelto en la raiz de origen/"

    carpeta_modelo = slug(tramos[0]).replace("-", " ")
    reglas = cfg["carpetas"].get(carpeta_modelo)
    if reglas is None:
        return None, None, "", "", "carpeta de modelo no mapeada: %s" % tramos[0]

    token, modelos = reglas["token"], reglas["modelos"]

    # sin carpeta de vista: archivos sueltos en la raiz del modelo (Shark)
    if len(tramos) == 1:
        return token, modelos, "sd", "sd", "sin carpeta de vista"

    nivel2 = slug(tramos[1]).replace("-", " ")
    vreglas = cfg["vistas"].get(nivel2)
    if vreglas is None:
        return token, modelos, "sd", "sd", "carpeta de vista no mapeada: %s" % tramos[1]

    vista = vreglas["vista"]
    if vreglas.get("color_desde_subcarpeta"):
        color = slug(tramos[2], cfg["colores"]) if len(tramos) > 2 else "sd"
    else:
        color = vreglas.get("color", "sd")
    return token, modelos, vista, color, "path"


# ---------------------------------------------------------------- pipeline

def relevar(cfg):
    """Recorre origen/ recursivamente. En Dalian era un solo nivel."""
    registros = []
    for raiz, dirs, archivos in os.walk(ORIGEN):
        dirs.sort()
        for archivo in sorted(archivos):
            if archivo.startswith("."):
                continue
            ruta = os.path.join(raiz, archivo)
            rel = os.path.relpath(ruta, ORIGEN)
            base, ext = normalizar(archivo, cfg)
            if not ext:
                print("  ! extension no reconocida, se saltea: %s" % rel)
                continue
            token, modelos, vista, color, motivo = resolver_path(rel, cfg)
            w, h = dimensiones(ruta)
            registros.append({
                "rel": rel, "ruta": ruta, "archivo": archivo,
                "base": base, "ext": ext, "marca": MARCA,
                "token": token, "modelos": modelos or [],
                "vista": vista, "color": color, "motivo": motivo,
                "palabras": palabras(base),
                "md5": md5(ruta), "bytes": os.path.getsize(ruta), "w": w, "h": h,
            })
    return registros


def fusionar_duplicados(registros):
    """Un archivo fisico por md5 del ORIGINAL (antes del resize)."""
    grupos = defaultdict(list)
    for r in registros:
        grupos[r["md5"]].append(r)

    unicos = []
    for grupo in grupos.values():
        # representante: el que mas informacion aporta
        grupo.sort(key=lambda r: (r["token"] is None, r["vista"] == "sd",
                                  r["color"] == "sd", not r["palabras"],
                                  -r["bytes"], r["rel"]))
        rep = dict(grupo[0])
        rep["copias"] = [r["rel"] for r in grupo]
        rep["nota"] = "%d copias identicas en origen" % len(grupo) if len(grupo) > 1 else ""
        rep["modelos"] = sorted({m for r in grupo for m in r["modelos"]})
        unicos.append(rep)

    unicos.sort(key=lambda r: (r["token"] or "zzz", r["vista"], r["color"], r["rel"]))
    return unicos


def nombrar(unicos, cfg, ocupados=None):
    """`ocupados` = cuerpos ya publicados en fotos/, para no pisar URLs en circulacion."""
    stop = set(cfg["stopwords"])
    literales_vista = {"exterior", "interior", "detalle", "detalles", "sd"}
    ocupados = set(ocupados or ())
    revisar = [r for r in unicos if not r["token"]]
    buenos = [r for r in unicos if r["token"]]

    for r in buenos:
        toks = [p for p in r["palabras"] if p not in stop and p not in literales_vista]
        # dedup conservando orden: "interior interior" -> "interior"
        vistos, limpio = set(), []
        for t in toks:
            if t not in vistos:
                vistos.add(t)
                limpio.append(t)
        # el detalle se recorta por palabra entera si el nombre se pasa del techo
        fijo = len("%s_%s_%s_%s_." % (MARCA, r["token"], r["vista"], r["color"])) \
            + len(r["ext"])
        while limpio and fijo + len("-".join(limpio)) > MAX_NOMBRE:
            limpio.pop()
        r["detalle"] = "-".join(limpio)

    grupos = defaultdict(list)
    for r in buenos:
        grupos[(r["token"], r["vista"], r["color"], r["detalle"])].append(r)

    for (token, vista, color, detalle), grupo in grupos.items():
        grupo.sort(key=lambda r: r["rel"])
        # un solo archivo con detalle propio no lleva sufijo; el resto se numera
        libre = [detalle] if (len(grupo) == 1 and detalle) else []
        n = 0
        for r in grupo:
            while True:
                if libre:
                    sufijo = libre.pop()
                else:
                    n += 1
                    sufijo = "%s-%d" % (detalle, n) if detalle else str(n)
                cuerpo = "%s_%s_%s_%s_%s" % (MARCA, token, vista, color, sufijo)
                if cuerpo not in ocupados:
                    break
            ocupados.add(cuerpo)
            r["nuevo"] = "%s.%s" % (cuerpo, r["ext"])

    return buenos, revisar


def validar(buenos, previos=None):
    errores = []
    vistos = {n.rpartition(".")[0]: "(ya publicado)" for n in (previos or ())}
    for r in buenos:
        n = r["nuevo"]
        if not RE_LIMPIO.match(n):
            errores.append("caracteres invalidos: %s" % n)
        cuerpo, _, ext = n.rpartition(".")
        if ext not in EXT_VALIDAS:
            errores.append("extension invalida: %s" % n)
        if re.search(r"\.(jpe?g|png)$", cuerpo):
            errores.append("extension doble: %s" % n)
        if len(cuerpo.split("_")) != CAMPOS:
            errores.append("no tiene %d campos: %s" % (CAMPOS, n))
        if len(n) > MAX_NOMBRE:
            errores.append("nombre de %d chars (max %d), la URL se parte en el "
                           "PDF: %s" % (len(n), MAX_NOMBRE, n))
        if cuerpo in vistos:
            errores.append("colision: %s  (%s vs %s)" % (n, vistos[cuerpo], r["rel"]))
        vistos[cuerpo] = r["rel"]
    return errores


# ---------------------------------------------------------------- informe

def conflictos_path_filename(buenos):
    """
    La carpeta es la autoridad, pero si el filename dice otra vista o color hay
    que mirarlo: puede ser una foto mal archivada. No cambia nada, solo avisa.
    """
    out = []
    for r in buenos:
        b = r["base"]
        if r["vista"] == "interior" and "exterior" in b:
            out.append((r, "el filename dice 'exterior', la carpeta dice interior"))
        elif r["vista"] == "exterior" and "interior" in b:
            out.append((r, "el filename dice 'interior', la carpeta dice exterior"))
        elif r["vista"] == "detalle" and ("exterior" in b or "interior" in b):
            out.append((r, "el filename dice exterior/interior, la carpeta dice Detalles"))
    return out


def informe(registros, unicos, buenos, revisar, cfg, ya_estaban=()):
    print("=" * 78)
    print("RELEVAMIENTO")
    print("=" * 78)
    print("  archivos en origen : %d" % len(registros))
    print("  unicos por md5     : %d" % len(unicos))
    print("  duplicados exactos : %d descartados"
          % (len(registros) - len(unicos) - len(ya_estaban)))
    if ya_estaban:
        print("  ya en el inventario: %d salteados (mismo md5)" % len(ya_estaban))
    print("  a fotos/           : %d" % len(buenos))
    print("  a POR-REVISAR/     : %d" % len(revisar))

    dups = [r for r in buenos if len(r["copias"]) > 1]
    if dups:
        print("\n" + "=" * 78)
        print("DUPLICADOS EXACTOS (%d)" % len(dups))
        print("=" * 78)
        for r in dups:
            print("  se queda: %s" % r["rel"])
            for c in r["copias"]:
                if c != r["rel"]:
                    print("  descarta: %s" % c)

    print("\n" + "=" * 78)
    print("RENOMBRES")
    print("=" * 78)
    actual = None
    for r in buenos:
        if r["token"] != actual:
            actual = r["token"]
            print("\n  --- %s ---" % " / ".join(r["modelos"]))
        print("  %-62s -> %s" % (r["rel"][:62], r["nuevo"]))

    conf = conflictos_path_filename(buenos)
    if conf:
        print("\n" + "=" * 78)
        print("A REVISAR: el filename contradice la carpeta (%d)" % len(conf))
        print("=" * 78)
        print("  Gana la carpeta. Si alguna esta mal archivada, movela en origen/")
        print("  y volve a correr.\n")
        for r, por_que in conf:
            print("  %s" % r["rel"])
            print("      %s  ->  %s" % (por_que, r["nuevo"]))

    if revisar:
        print("\n" + "=" * 78)
        print("POR REVISAR: sin datos para determinar el modelo (%d)" % len(revisar))
        print("=" * 78)
        for r in revisar:
            print("  %s\n      motivo: %s" % (r["rel"], r["motivo"]))

    print("\n" + "=" * 78)
    print("FOTOS POR MODELO")
    print("=" * 78)
    cuenta = defaultdict(lambda: defaultdict(int))
    for r in buenos:
        for m in r["modelos"]:
            cuenta[m]["%s / %s" % (r["vista"], r["color"])] += 1
    for m in sorted(cuenta):
        print("  %-20s %d" % (m, sum(cuenta[m].values())))
        for k in sorted(cuenta[m]):
            print("      %-34s %d" % (k, cuenta[m][k]))
    for m in cfg.get("sin_fotos", []):
        print("  %-20s 0   <-- carpeta vacia, avisado en el catalogo" % m)

    pesados = sorted((r for r in buenos if r["bytes"] > 20 * 1024 * 1024),
                     key=lambda r: -r["bytes"])
    if pesados:
        px = cfg["resize"]["lado_largo_px"]
        print("\n  %d archivos pasan los 20 MB (limite de jsDelivr) en origen." % len(pesados))
        print("  Se redimensionan a %d px de lado largo al copiar. El mas pesado:" % px)
        r = pesados[0]
        print("      %d x %d  /  %.0f MB   %s"
              % (r["w"], r["h"], r["bytes"] / 1048576.0, r["rel"][:48]))

    sd = [r for r in buenos if r["vista"] == "sd"]
    if sd:
        print("\n  %d archivos con vista 'sd' (sin carpeta de vista). El modelo es" % len(sd))
        print("  correcto, que es lo unico que define que fotos manda el agente.")


# ---------------------------------------------------------------- salida

CABECERA = ["nombre_nuevo", "marca", "modelos", "vista", "color", "detalle",
            "origen", "copias_descartadas", "md5", "ancho", "alto",
            "bytes_original", "bytes_final", "nota"]


def leer_inventario_previo():
    if not os.path.exists(INVENTARIO):
        return {"md5": set(), "nombres": set()}
    with open(INVENTARIO, encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    return {"md5": {f["md5"] for f in filas if f["md5"]},
            "nombres": {f["nombre_nuevo"] for f in filas if f["nombre_nuevo"]}}


def redimensionar(ruta, px, calidad):
    """
    sips -Z redimensiona al lado largo manteniendo la proporcion: no recorta.
    Los PNG se mantienen PNG: 3 de los 4 tienen canal alpha y pasarlos a JPEG
    les pondria fondo negro. Devuelve (ok, bytes_finales).
    """
    cmd = ["sips", "-Z", str(px)]
    if ruta.lower().endswith((".jpg", ".jpeg")):
        cmd += ["-s", "formatOptions", str(calidad)]
    r = subprocess.run(cmd + [ruta], capture_output=True)
    if r.returncode != 0:
        return False, os.path.getsize(ruta)
    return True, os.path.getsize(ruta)


def escribir_inventario(buenos, revisar, apendear=False):
    with open(INVENTARIO, "a" if apendear else "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if not apendear:
            w.writerow(CABECERA)
        for r in buenos:
            w.writerow([r["nuevo"], r["marca"], ";".join(r["modelos"]), r["vista"],
                        r["color"], r.get("detalle", ""), r["rel"],
                        ";".join(c for c in r["copias"] if c != r["rel"]),
                        r["md5"], r["w"], r["h"], r["bytes"],
                        r.get("bytes_final", r["bytes"]), r["nota"]])
        for r in revisar:
            w.writerow(["", r["marca"], "", "", "", "", r["rel"], "", r["md5"],
                        r["w"], r["h"], r["bytes"], "",
                        "POR-REVISAR: " + r["motivo"]])


def aplicar(buenos, revisar, cfg):
    px = cfg["resize"]["lado_largo_px"]
    calidad = cfg["resize"]["calidad_jpeg"]
    for d in (DESTINO_FOTOS, DESTINO_REVISAR):
        os.makedirs(d, exist_ok=True)

    antes = despues = fallos = 0
    for i, r in enumerate(buenos, 1):
        destino = os.path.join(DESTINO_FOTOS, r["nuevo"])
        shutil.copy2(r["ruta"], destino)
        ok, nuevos_bytes = redimensionar(destino, px, calidad)
        if not ok:
            fallos += 1
            print("\n  ! sips fallo en %s, queda el original" % r["nuevo"])
        r["bytes_final"] = nuevos_bytes
        r["w"], r["h"] = dimensiones(destino)
        antes += r["bytes"]
        despues += nuevos_bytes
        print("\r  redimensionando %d/%d" % (i, len(buenos)), end="", flush=True)
    print()

    for r in revisar:
        shutil.copy2(r["ruta"], os.path.join(DESTINO_REVISAR, r["archivo"]))

    print("\n  copiados %d a fotos/ y %d a POR-REVISAR/" % (len(buenos), len(revisar)))
    print("  %.0f MB -> %.0f MB  (%.0f%% menos)"
          % (antes / 1048576.0, despues / 1048576.0,
             100 * (1 - despues / float(antes)) if antes else 0))
    if fallos:
        print("  ! %d archivos no se pudieron redimensionar" % fallos)


def main():
    aplicar_cambios = "--aplicar" in sys.argv
    cfg = cargar_config()
    if not os.path.isdir(ORIGEN):
        sys.exit("no encuentro la carpeta origen: %s" % ORIGEN)

    previo = leer_inventario_previo()
    if previo["nombres"]:
        print("INCREMENTAL: %d fotos ya publicadas en el inventario\n" % len(previo["nombres"]))

    registros = relevar(cfg)
    unicos = fusionar_duplicados(registros)

    ya_estaban = [r for r in unicos if r["md5"] in previo["md5"]]
    unicos = [r for r in unicos if r["md5"] not in previo["md5"]]

    ocupados = {n.rpartition(".")[0] for n in previo["nombres"]}
    buenos, revisar = nombrar(unicos, cfg, ocupados)

    errores = validar(buenos, previo["nombres"])
    informe(registros, unicos, buenos, revisar, cfg, ya_estaban)

    if errores:
        print("\n" + "!" * 78)
        print("VALIDACION FALLIDA - no se escribe nada")
        for e in errores:
            print("  - %s" % e)
        sys.exit(1)

    if len(buenos) + len(revisar) != len(unicos):
        sys.exit("\ncuadre roto: %d + %d != %d" % (len(buenos), len(revisar), len(unicos)))

    print("\n  validacion OK: %d campos, sin colisiones, sin caracteres raros, "
          "cuadre exacto" % CAMPOS)

    if not buenos and not revisar:
        print("\n  nada nuevo que incorporar.")
        return

    if aplicar_cambios:
        aplicar(buenos, revisar, cfg)
        escribir_inventario(buenos, revisar, apendear=bool(previo["nombres"]))
        print("  inventario: %s" % INVENTARIO)
    else:
        print("\n  DRY-RUN: no se escribio nada. Corre con --aplicar para hacerlo.")


if __name__ == "__main__":
    main()
