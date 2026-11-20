"""Lectura, navegación y guardado de la hoja de ruta local de un proyecto."""

from dataclasses import dataclass, field
import re
import unicodedata

from .arboles import LectorArbol, _git
from .inicio import guardar_documentos
from .modelo import diagnostico, resultado


RUTA = "sdd/ruta-de-desarrollo.md"
_TITULO = "# Ruta de desarrollo"
_ESTADOS = {estado.casefold(): estado for estado in ("Pendiente", "En curso", "Bloqueado", "Completado")}
_ESTADOS.update(bloqueada="Bloqueado", completada="Completado")
_META = re.compile(r" {0,3}## (META-[0-9]+)\s*·\s*(\S.*?)\s*$")
_OBJETIVO = re.compile(r"OBJ-[0-9]+")
_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_CERCA = re.compile(r" {0,3}(\x60{3,}|~{3,})(.*)")
_CABECERA = ("Objetivo", "Resultado", "Estado")
_COLUMNAS = {("Referencia",), ("Criterio", "Evidencia"), ("Referencia", "Criterio", "Evidencia")}
_CAMPOS = {"criterio", "evidencia", "estado", "titulo"}
_OPERACIONES = {
    "crear_meta": (_CAMPOS | {"posicion"}, {"titulo"}),
    "crear_objetivo": (_CAMPOS | {"meta", "posicion"}, {"meta", "titulo"}),
    "actualizar": (_CAMPOS | {"id"}, {"id"}),
    "mover": ({"id", "posicion"}, {"id", "posicion"}),
}


@dataclass
class _Bloque:
    datos: dict
    inicio: int
    fin: int
    propiedades: dict = field(default_factory=dict)
    tabla: int | None = None
    columnas: tuple = ()
    filas: dict = field(default_factory=dict)


def _normal(texto):
    letras = (c for c in unicodedata.normalize("NFKD", texto.casefold()) if not unicodedata.combining(c))
    return " ".join("".join(letras).split())


def _estado(valor):
    estado = _ESTADOS.get(_normal(valor).removesuffix("."))
    if estado is None:
        raise ValueError(f"Estado de ruta inválido: {valor!r}.")
    return estado


def _visible(lineas):
    cerca = None
    for numero, cruda in enumerate(lineas):
        linea = cruda.rstrip("\r\n")
        if numero == 0:
            linea = linea.removeprefix("\ufeff")
        marca = _CERCA.fullmatch(linea)
        if cerca is not None:
            if marca and marca[1].startswith(cerca) and not marca[2].strip():
                cerca = None
        elif marca and (marca[1][0] == "~" or chr(96) not in marca[2]):
            cerca = marca[1]
        else:
            yield numero, linea


def _celdas(linea):
    """Conserva los espacios de las celdas y distingue tuberías escapadas."""
    cuerpo = linea.rstrip("\r\n")
    separadores, barras = [], 0
    for posicion, caracter in enumerate(cuerpo):
        if caracter == "|" and barras % 2 == 0:
            separadores.append(posicion)
        barras = barras + 1 if caracter == "\\" else 0
    if len(separadores) < 2 or cuerpo[:separadores[0]].strip() or cuerpo[separadores[-1] + 1:].strip():
        return []
    return [cuerpo[a + 1:b] for a, b in zip(separadores, separadores[1:])]


def _decodificar(valor):
    return re.sub(r"\\([\\|])", r"\1", valor.strip())


def _codificar(valor):
    return valor.replace("\\", "\\\\").replace("|", "\\|")


def _dato(identidad, titulo, estado="", criterio="", evidencia=""):
    return dict(id=identidad, titulo=titulo, estado=estado, criterio=criterio, evidencia=evidencia)


def _registrar(identidades, identidad):
    if identidad in identidades or int(identidad.split("-")[1]) == 0:
        raise ValueError(f"Identificador de ruta repetido o inválido: {identidad}.")
    identidades.add(identidad)


def _leer_bloque(bloque, visibles, identidades):
    tabla_activa = False
    for numero in range(bloque.inicio + 1, bloque.fin):
        linea = visibles.get(numero, "")
        atributo = re.fullmatch(r" {0,3}(Estado|Criterio|Evidencia):[ \t]*(.*)", linea, re.IGNORECASE)
        if atributo:
            nombre, valor = atributo[1].casefold(), atributo[2].strip()
            if nombre in bloque.propiedades:
                raise ValueError(f"{bloque.datos['id']} declara {nombre} más de una vez.")
            bloque.propiedades[nombre] = numero
            bloque.datos[nombre] = _estado(valor) if nombre == "estado" else valor
        campos = tuple(_decodificar(celda) for celda in _celdas(linea))
        if not campos:
            tabla_activa = False
            continue
        if campos[0] == "Objetivo":
            if bloque.tabla is not None or campos[:3] != _CABECERA or campos[3:] not in _COLUMNAS:
                raise ValueError(f"Tabla de objetivos inválida en {bloque.datos['id']}.")
            bloque.tabla, bloque.columnas = numero, campos
            tabla_activa = True
        elif tabla_activa and numero == bloque.tabla + 1:
            if len(campos) != len(bloque.columnas) or any(not re.fullmatch(r":?-{3,}:?", c) for c in campos):
                raise ValueError(f"Falta el separador de la tabla en {bloque.datos['id']}.")
        elif tabla_activa:
            if len(campos) != len(bloque.columnas) or not _OBJETIVO.fullmatch(campos[0]) or not campos[1]:
                raise ValueError(f"Fila de objetivo inválida en {bloque.datos['id']} (línea {numero + 1}).")
            identidad, titulo, estado_bruto = campos[:3]
            _registrar(identidades, identidad)
            detalles = dict(zip(bloque.columnas[3:], campos[3:]))
            estado = _estado(estado_bruto)
            referencia = detalles.get("Referencia", "")
            evidencia = detalles.get("Evidencia", "")
            objetivo = _dato(identidad, titulo, estado, detalles.get("Criterio", ""),
                             evidencia or (referencia if estado == "Completado" else ""))
            if referencia and estado != "Completado":
                objetivo["referencia"] = referencia
            bloque.datos["objetivos"].append(objetivo)
            bloque.filas[identidad] = numero
        elif _OBJETIVO.fullmatch(campos[0]):
            raise ValueError(f"Fila de objetivo sin cabecera en la línea {numero + 1}.")
    if bloque.tabla is not None and not _celdas(visibles.get(bloque.tabla + 1, "")):
        raise ValueError(f"Falta el separador de la tabla en {bloque.datos['id']}.")
    if not bloque.datos["estado"]:
        raise ValueError(f"Falta el estado de {bloque.datos['id']}.")


def _hoja(texto):
    if not isinstance(texto, str):
        raise ValueError("La hoja de ruta debe ser texto Markdown.")
    lineas = texto.splitlines(keepends=True)
    visibles = dict(_visible(lineas))
    if next((linea.strip() for linea in visibles.values() if linea.strip()), None) != _TITULO:
        raise ValueError(f"La hoja debe comenzar con «{_TITULO}».")
    bloques, identidades = [], set()
    limite = len(lineas)
    activo = None
    for numero, linea in visibles.items():
        if not re.match(r" {0,3}#{1,2}(?:\s|$)", linea):
            continue
        if activo is not None:
            activo.fin = numero
            activo = None
        meta = _META.fullmatch(linea)
        if meta:
            identidad, titulo = meta.groups()
            _registrar(identidades, identidad)
            activo = _Bloque(dict(_dato(identidad, titulo), objetivos=[]), numero, len(lineas))
            bloques.append(activo)
        elif re.match(r" {0,3}##\s+META-", linea):
            raise ValueError(f"Encabezado de meta inválido en la línea {numero + 1}.")
        elif not bloques and re.match(r" {0,3}##\s+Cómo mantener y consultar la ruta\s*$", linea, re.IGNORECASE):
            limite = numero
    for bloque in bloques:
        _leer_bloque(bloque, visibles, identidades)
    return lineas, bloques, limite


def leer_ruta(texto):
    """Devuelve las metas y objetivos, en orden, desde el Markdown de la ruta."""
    return [bloque.datos for bloque in _hoja(texto)[1]]


def _hito(datos, meta, tipo):
    return dict(datos, tipo=tipo, meta=meta)


def _destino(metas, consulta, *, solo_id=False):
    if not isinstance(consulta, str) or not consulta.strip():
        raise ValueError("Indica un ID o título de meta u objetivo.")
    titulo, identidad = _normal(consulta), consulta.strip().upper()
    exactos, parciales = [], []
    for meta in metas:
        hitos = [_hito(meta, meta["id"], "meta")]
        hitos.extend(_hito(objetivo, meta["id"], "objetivo") for objetivo in meta["objetivos"])
        for hito in hitos:
            if hito["id"] == identidad:
                return hito
            if solo_id:
                continue
            nombre = _normal(hito["titulo"])
            if nombre == titulo:
                exactos.append(hito)
            elif titulo and titulo in nombre:
                parciales.append(hito)
    candidatos = exactos or parciales
    if len(candidatos) == 1:
        return candidatos[0]
    if candidatos:
        alternativas = ", ".join(hito["id"] for hito in candidatos)
        raise ValueError(f"Destino ambiguo {consulta!r}; indica uno de {alternativas}.")
    orientacion = " Indica el ID de la meta u objetivo." if solo_id else ""
    raise ValueError(f"Destino sin registrar: {consulta!r}.{orientacion}")


def validar_destinos(metas, destinos):
    """Resuelve una meta o un conjunto de objetivos distintos de la misma meta."""
    if not isinstance(destinos, list) or not destinos:
        raise ValueError("Indica una meta o uno o varios objetivos de una misma meta.")
    hitos = [_destino(metas, consulta, solo_id=True) for consulta in destinos]
    meta = hitos[0]["meta"]
    if len(hitos) > 1 and (any(hito["meta"] != meta or hito["tipo"] != "objetivo" for hito in hitos)
                           or len({hito["id"] for hito in hitos}) != len(hitos)):
        raise ValueError("Indica una sola meta u objetivos distintos de una misma meta.")
    return meta


def _siguiente(metas):
    for meta in metas:
        if meta["estado"] == "Completado":
            continue
        objetivos = meta["objetivos"]
        if not objetivos or meta["estado"] == "Bloqueado":
            return _hito(meta, meta["id"], "meta")
        for objetivo in objetivos:
            if objetivo["estado"] != "Completado":
                return _hito(objetivo, meta["id"], "objetivo")
        return _confirmacion(meta)
    return None


def _confirmacion(meta):
    if (meta["estado"] in {"Pendiente", "En curso"} and meta["objetivos"]
            and all(hito["estado"] == "Completado" for hito in meta["objetivos"])):
        return dict(_hito(meta, meta["id"], "meta"), confirmar=True)
    return None


def proyeccion_ruta(metas, destino=None):
    """Consulta el siguiente hito y, al elegir destino, un recorrido inclusivo."""
    vista = dict(metas=metas, siguiente=_siguiente(metas))
    if destino is None:
        return vista
    elegido = _destino(metas, destino)
    recorrido = []
    for meta in metas:
        hitos = [_hito(objetivo, meta["id"], "objetivo") for objetivo in meta["objetivos"]]
        for hito in hitos or [_hito(meta, meta["id"], "meta")]:
            recorrido.append(hito)
            if hito["id"] == elegido["id"]:
                return dict(vista, destino=elegido, recorrido=recorrido)
        confirmacion = _confirmacion(meta)
        if confirmacion is not None:
            recorrido.append(confirmacion)
        if meta["id"] == elegido["id"]:
            break
    return dict(vista, destino=elegido, recorrido=recorrido)


def _operacion(operacion):
    if not isinstance(operacion, dict) or not isinstance(operacion.get("accion"), str):
        raise ValueError("La operación requiere un objeto con acción.")
    accion = operacion["accion"]
    if accion not in _OPERACIONES:
        raise ValueError(f"Acción de ruta desconocida: {accion!r}.")
    admitidos, exigidos = _OPERACIONES[accion]
    campos = operacion.keys() - {"accion", "base"}
    if campos - admitidos or exigidos - campos or (accion == "actualizar" and campos == {"id"}):
        raise ValueError(f"Campos incompatibles con {accion}; revisa los datos de la operación.")
    for campo in campos - {"posicion"}:
        valor = operacion[campo]
        if (not isinstance(valor, str) or not valor.strip() or valor.splitlines() != [valor] or "\x00" in valor):
            raise ValueError(f"El campo {campo} requiere texto no vacío de una sola línea.")
    if "base" in operacion and (not isinstance(operacion["base"], str) or not _SHA.fullmatch(operacion["base"])):
        raise ValueError("La base debe ser el SHA completo de Git.")
    cambios = {campo: operacion[campo].strip() for campo in campos & _CAMPOS}
    if "estado" in cambios:
        cambios["estado"] = _estado(cambios["estado"])
    return accion, cambios


def _posicion(operacion, limite, defecto):
    posicion = operacion.get("posicion", defecto)
    if type(posicion) is not int or not 1 <= posicion <= limite:
        raise ValueError(f"Posición inválida: introduce un entero entre 1 y {limite}.")
    return posicion - 1


def _asignar(prefijo, datos):
    correlativos = (int(hito["id"].split("-")[1]) for hito in datos)
    return f"{prefijo}-{max(correlativos, default=0) + 1:02d}"


def _revisar_datos(anterior, nuevo, vecinos):
    if any(hito["id"] != nuevo["id"] and _normal(hito["titulo"]) == _normal(nuevo["titulo"]) for hito in vecinos):
        raise ValueError(f"El título {nuevo['titulo']!r} ya está registrado en el mismo nivel.")
    if nuevo["estado"] == "Completado" and anterior["estado"] != "Completado":
        if not nuevo["criterio"] or not nuevo["evidencia"]:
            raise ValueError("Un logro nuevo requiere criterio de cumplimiento y evidencia.")
        if any(hito["estado"] != "Completado" for hito in nuevo.get("objetivos", [])):
            raise ValueError("La meta aún tiene objetivos abiertos.")


def _salto(linea):
    return linea[len(linea.rstrip("\r\n")):]


def _separado(lineas, indice, nuevas, salto):
    if indice > 0 and lineas[indice - 1].strip():
        if not _salto(lineas[indice - 1]):
            lineas[indice - 1] += salto
        nuevas = [salto, *nuevas]
    lineas[indice:indice] = nuevas


def _linea_fila(celdas, cruda, salto):
    inicio = cruda[:cruda.index("|")] if cruda else ""
    cuerpo = cruda.rstrip("\r\n") if cruda else "|"
    fin = cuerpo[cuerpo.rindex("|") + 1:]
    return inicio + "|" + "|".join(celdas) + "|" + fin + salto


def _celda(valor):
    return f" {_codificar(valor)} "


def _modernizar_tabla(lineas, bloque):
    if bloque.columnas[-1] == "Evidencia":
        return
    for numero in (bloque.tabla, bloque.tabla + 1, *bloque.filas.values()):
        cruda = lineas[numero]
        agregado = (" Criterio ", " Evidencia ") if numero == bloque.tabla else (
            (" --- ", " --- ") if numero == bloque.tabla + 1 else ("  ", "  "))
        lineas[numero] = _linea_fila([*_celdas(cruda), *agregado], cruda, _salto(cruda))
    bloque.columnas = (*bloque.columnas, "Criterio", "Evidencia")


def _insertar_objetivo(lineas, bloque, nuevo, posicion, salto):
    cambios = dict(zip(_CABECERA, (nuevo["id"], nuevo["titulo"], nuevo["estado"])))
    cambios.update(Criterio=nuevo["criterio"], Evidencia=nuevo["evidencia"])
    if bloque.tabla is None:
        columnas = (*_CABECERA, "Criterio", "Evidencia")
        tabla = [_linea_fila([_celda(c) for c in columnas], "", salto),
                 _linea_fila([" --- "] * len(columnas), "", salto),
                 _linea_fila([_celda(cambios[c]) for c in columnas], "", salto), salto]
        indice = bloque.fin
        while indice > bloque.inicio + 1 and not lineas[indice - 1].strip():
            indice -= 1
        _separado(lineas, indice, tabla, salto)
        return
    if nuevo["criterio"] or nuevo["evidencia"]:
        _modernizar_tabla(lineas, bloque)
    indice = bloque.tabla + 2 + posicion
    if not _salto(lineas[indice - 1]):
        lineas[indice - 1] += salto
    lineas.insert(indice, _linea_fila([_celda(cambios.get(c, "")) for c in bloque.columnas], "", salto))


def _editar_objetivo(lineas, bloque, identidad, cambios):
    if cambios.keys() & {"criterio", "evidencia"}:
        _modernizar_tabla(lineas, bloque)
    campos = dict(titulo="Resultado", estado="Estado", criterio="Criterio", evidencia="Evidencia")
    indice = bloque.filas[identidad]
    anterior = lineas[indice]
    celdas = _celdas(anterior)
    for nombre, valor in cambios.items():
        celdas[bloque.columnas.index(campos[nombre])] = _celda(valor)
    lineas[indice] = _linea_fila(celdas, anterior, _salto(anterior))


def _evidencia_objetivo(lineas, bloque, identidad):
    if "Evidencia" not in bloque.columnas:
        return ""
    celdas = _celdas(lineas[bloque.filas[identidad]])
    return _decodificar(celdas[bloque.columnas.index("Evidencia")])


def _editar_meta(lineas, bloque, cambios, salto):
    titulo = cambios.get("titulo")
    if titulo is not None:
        encabezado = lineas[bloque.inicio]
        lineas[bloque.inicio] = f"## {bloque.datos['id']} · {titulo}" + _salto(encabezado)
    nuevas = []
    for nombre in ("estado", "criterio", "evidencia"):
        if nombre not in cambios:
            continue
        valor = f"{nombre.capitalize()}: {cambios[nombre]}" + ("." if nombre == "estado" else "")
        indice = bloque.propiedades.get(nombre)
        if indice is None:
            nuevas.append(valor + salto)
        else:
            lineas[indice] = valor + _salto(lineas[indice])
    if nuevas:
        indice = bloque.propiedades["estado"] + 1
        if not _salto(lineas[indice - 1]):
            lineas[indice - 1] += salto
        lineas[indice:indice] = nuevas


def _mover(lineas, bloques, bloque, objetivo, operacion, salto):
    intervalos = ([(b.inicio, b.fin) for b in bloques] if objetivo is None else
                  [(indice, indice + 1) for indice in bloque.filas.values()])
    salida = _posicion(operacion, len(intervalos), 1)
    inicio = bloque.inicio if objetivo is None else bloque.filas[objetivo]
    origen = next(i for i, (a, _) in enumerate(intervalos) if a == inicio)
    if salida == origen:
        return
    secciones = [lineas[a:b] for a, b in intervalos]
    secciones.insert(salida, secciones.pop(origen))
    for (a, b), seccion in reversed(list(zip(intervalos, secciones))):
        if b < len(lineas) and not _salto(seccion[-1]):
            seccion[-1] += salto
        lineas[a:b] = seccion


def _crear_meta(lineas, bloques, limite, cambios, operacion, salto):
    metas = [bloque.datos for bloque in bloques]
    identidad = _asignar("META", metas)
    anterior = _dato(identidad, "", "Pendiente")
    nuevo = dict(anterior, **cambios)
    _revisar_datos(anterior, nuevo, metas)
    posicion = _posicion(operacion, len(bloques) + 1, len(bloques) + 1)
    indice = bloques[posicion].inicio if posicion < len(bloques) else (bloques[-1].fin if bloques else limite)
    encabezado = [f"## {identidad} · {nuevo['titulo']}{salto}", salto, f"Estado: {nuevo['estado']}.{salto}"]
    encabezado.extend(f"{campo.capitalize()}: {nuevo[campo]}{salto}" for campo in ("criterio", "evidencia") if nuevo[campo])
    _separado(lineas, indice, [*encabezado, salto], salto)
    return identidad


def _crear_objetivo(lineas, metas, bloque, destino, cambios, operacion, salto):
    if destino["tipo"] != "meta":
        raise ValueError("Un objetivo requiere una meta como padre.")
    if destino["estado"] == "Completado" and cambios.get("estado") != "Completado":
        raise ValueError("Reabre la meta antes de añadir un objetivo abierto.")
    identidad = _asignar("OBJ", (obj for meta in metas for obj in meta["objetivos"]))
    anterior = _dato(identidad, "", "Pendiente")
    nuevo = dict(anterior, **cambios)
    objetivos = bloque.datos["objetivos"]
    _revisar_datos(anterior, nuevo, objetivos)
    posicion = _posicion(operacion, len(objetivos) + 1, len(objetivos) + 1)
    _insertar_objetivo(lineas, bloque, nuevo, posicion, salto)
    return identidad


def _transformar(texto, operacion, accion, cambios):
    lineas, bloques, limite = _hoja(texto)
    metas = [bloque.datos for bloque in bloques]
    salto = next((fin for linea in lineas if (fin := _salto(linea))), "\n")
    if accion == "crear_meta":
        identidad = _crear_meta(lineas, bloques, limite, cambios, operacion, salto)
    else:
        destino = _destino(metas, operacion["meta"] if accion == "crear_objetivo" else operacion["id"], solo_id=True)
        bloque = next(b for b in bloques if b.datos["id"] == destino["meta"])
        identidad = destino["id"]
        es_meta = destino["tipo"] == "meta"
        if accion == "crear_objetivo":
            identidad = _crear_objetivo(lineas, metas, bloque, destino, cambios, operacion, salto)
        elif accion == "mover":
            _mover(lineas, bloques, bloque, None if es_meta else identidad, operacion, salto)
        else:
            if not es_meta:
                destino["evidencia"] = _evidencia_objetivo(lineas, bloque, identidad)
            nuevo = dict(destino, **cambios)
            if not es_meta and bloque.datos["estado"] == "Completado" and nuevo["estado"] != "Completado":
                raise ValueError("Reabre la meta antes de reabrir su objetivo.")
            _revisar_datos(destino, nuevo, metas if es_meta else bloque.datos["objetivos"])
            if es_meta:
                _editar_meta(lineas, bloque, cambios, salto)
            else:
                _editar_objetivo(lineas, bloque, identidad, cambios)
    imagen = "".join(lineas)
    leer_ruta(imagen)
    return identidad, imagen.encode("utf-8")


def _texto(lector):
    entrada = lector.entrada(RUTA)
    if entrada is None:
        return _TITULO + "\n"
    if entrada[0] != "100644":
        raise ValueError("La hoja de ruta requiere un archivo Markdown sin permiso de ejecución.")
    return entrada[1].decode("utf-8")


def _reintento(cabeza, base, imagen, mensaje):
    """Comprueba el hijo observado de la base, sin replicar una escritura anterior."""
    entre = f"{base}..{cabeza.commit}"
    descendientes = _git(cabeza.raiz, "rev-list", "--first-parent", "--ancestry-path", "--reverse", entre).decode().splitlines()
    if descendientes:
        padre, titulo = _git(cabeza.raiz, "show", "-s", "--format=%P%n%s", descendientes[0]).decode().splitlines()
        if padre == base and titulo == mensaje:
            guardado = LectorArbol(cabeza.raiz, descendientes[0])
            if guardado.entrada(RUTA) == ("100644", imagen):
                return guardado.commit
    raise ValueError("La base de la operación ya no es HEAD; consulta de nuevo la ruta.")


def operar_ruta(raiz, operacion, *, aplicar=False):
    """Simula una edición o guarda exclusivamente la hoja de ruta sobre un HEAD fijo."""
    nombre = "ruta-desarrollo"
    try:
        if type(aplicar) is not bool:
            raise ValueError("La aplicación de la operación requiere un booleano.")
        accion, cambios = _operacion(operacion)
        cabeza = LectorArbol(raiz, "HEAD")
        base = operacion.get("base", cabeza.commit)
        lector = cabeza if base == cabeza.commit else LectorArbol(cabeza.raiz, base)
        texto = _texto(lector)
        identidad, imagen = _transformar(texto, operacion, accion, cambios)
        mensaje = f"docs: ruta {accion} {identidad}"
        salida = dict(resultado(nombre), accion=accion, base=base, ruta=RUTA, id=identidad,
                      resumen=f"{identidad} · {accion.replace('_', ' ')} · {'guardado solicitado' if aplicar else 'simulación'}.")
        if lector is not cabeza:
            commit = _reintento(cabeza, base, imagen, mensaje)
            return dict(salida, commit=commit, idempotente=True)
        if aplicar:
            salida["commit"] = guardar_documentos(cabeza.raiz, {RUTA: imagen}, mensaje, esperado=base)
        return salida
    except (ValueError, OSError) as exc:
        return resultado(nombre, [diagnostico("RUTA_DESARROLLO", RUTA, "Operación de ruta sobre un HEAD válido",
                                               str(exc), "Revisa la hoja, la base o el destino y vuelve a consultar.")])
