"""Planifica ediciones Heimdall sobre la imagen privada que entrega el servicio."""

from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Callable

from .arboles import _clave_portable, _leer_trabajo, _ruta
from .convivencia import FICHA, PROYECTO, _patron, contratos_en, frontal
from .indice_heimdall import (
    carga_enmiendas, carga_modulos, carga_specs, contrasta, lee_campos, redacta,
)
from .modelo_sdd import serializar


INDICE = "sdd/INDICE.md"
RAICES = ("sdd", "gobernanza/sdd")
FICHA_ARCHIVO = rf"({FICHA})_[a-z0-9]+(?:-[a-z0-9]+)*\.md"
PATRONES = {
    "ficha": rf"funcionalidades/{FICHA_ARCHIVO}",
    "spec": r"spec_([a-z0-9-]+)\.md",
    "enmienda": r"enmienda_([0-9]{1,3})_[a-zA-Z0-9_-]+\.md",
    "auxiliar": (
        r"(?:(?:insumo|propuesta)[-_][a-zA-Z0-9_-]+\.md|"
        r"referencias/(?:[a-zA-Z0-9][a-zA-Z0-9_.-]*/)*"
        r"[a-zA-Z0-9][a-zA-Z0-9_.-]*\.(?:md|html|txt|css|json|svg))"
    ),
}
ESTADOS_FICHA = {"Borrador", "Validado", "Archivado", "Deprecado"}
ESTADOS_SPEC = {"Borrador", "Propuesta", "Propuesto", "Validado", "Validada", "Archivado"}
ESTADOS_ENMIENDA = {"Borrador", "Propuesta", "Diferida", "Validada", "Aprobada", "Incorporada"}
BORRADORES = {"Borrador", "Propuesta", "Propuesto", "Diferida"}


def _fallo(ruta, motivo):
    raise ValueError(f"{ruta}: {motivo}")


def _contenido(raiz, ruta):
    imagen = _leer_trabajo(raiz, ruta)
    if imagen is None:
        return None
    modo, bytes_ = imagen
    if modo != "100644":
        _fallo(ruta, "Se requiere un archivo regular de datos, sin permiso de ejecución.")
    return bytes_


def _camino(raiz, ruta, tipo):
    _ruta(ruta)
    base = next((base for base in RAICES if ruta.startswith(base + "/")), None)
    if base is None or tipo not in PATRONES:
        _fallo(ruta, "Destino ajeno a las clases documentales de Heimdall.")
    interno = ruta.removeprefix(base + "/")
    forma = re.fullmatch(PATRONES[tipo], interno)
    if forma is None:
        _fallo(ruta, f"La ruta no corresponde al tipo {tipo}.")
    padre = raiz
    for parte in Path(ruta).parts:
        if padre.is_dir() and any(
            hijo.name != parte and _clave_portable(hijo.name) == _clave_portable(parte)
            for hijo in padre.iterdir()
        ):
            _fallo(ruta, "La ruta difiere en mayúsculas o normalización de otra existente.")
        padre /= parte
    return base, forma


def _texto(ruta, valor, tipo):
    if not isinstance(valor, str) or not valor.strip() or "\x00" in valor:
        _fallo(ruta, "Se requiere texto UTF-8 no vacío.")
    if tipo != "auxiliar" and re.match(r"^# [^\r\n]+", valor) is None:
        _fallo(ruta, "Se requiere título Markdown de primer nivel.")
    return valor


def _lista_cadenas(datos, campo, ruta):
    valores = datos.get(campo)
    if (not isinstance(valores, list) or any(not isinstance(v, str) or not v for v in valores)
            or len(set(valores)) != len(valores)):
        _fallo(ruta, f"{campo} debe ser una lista de cadenas sin duplicados.")
    return valores


def _datos_ficha(datos, ruta, identidad, base):
    campos = {"id", "modulo", "estado", "rutas", "revisiones", "dependencias", "componentes"}
    if not isinstance(datos, dict) or set(datos) != campos or datos["id"] != identidad:
        _fallo(ruta, "Campos o identidad de ficha incompatibles con la ruta.")
    modulo, estado = datos["modulo"], datos["estado"]
    if not isinstance(modulo, str) or not re.fullmatch(r"[a-z0-9-]+", modulo):
        _fallo(ruta, "Módulo de ficha inválido.")
    if not isinstance(estado, str) or estado not in ESTADOS_FICHA:
        _fallo(ruta, "Estado de ficha inválido.")
    dominio = "S" if base == "sdd" else "G"
    for objeto in _lista_cadenas(datos, "rutas", ruta):
        _patron(objeto, dominio, {"solucion"}, ruta)
    _lista_cadenas(datos, "dependencias", ruta)
    _lista_cadenas(datos, "componentes", ruta)
    revisiones = datos["revisiones"]
    if not isinstance(revisiones, list) or not revisiones:
        _fallo(ruta, "Se requiere una revisión inicial con criterios.")
    for numero, revision in enumerate(revisiones, 1):
        if (not isinstance(revision, dict) or set(revision) != {"revision", "criterios"}
                or type(revision["revision"]) is not int or revision["revision"] != numero):
            _fallo(ruta, "Las revisiones de ficha deben ser consecutivas desde 1.")
        criterios = revision["criterios"]
        if (not isinstance(criterios, dict) or not criterios
                or any(not isinstance(codigo, str) or not re.fullmatch(r"C[0-9]{2}", codigo)
                       or not isinstance(descripcion, str) or not descripcion.strip()
                       for codigo, descripcion in criterios.items())):
            _fallo(ruta, "Cada revisión necesita criterios con ID C## y descripción.")


def _historia_ficha(ruta, anterior, datos):
    antes, _ = frontal(anterior.decode(), ruta)
    if antes.get("id") != datos["id"] or antes.get("modulo") != datos["modulo"]:
        _fallo(ruta, "La identidad y el módulo dueño de la ficha son estables.")
    historicas = antes["revisiones"]
    nuevas = datos["revisiones"]
    acordadas = historicas if antes["estado"] != "Borrador" else historicas[:-1]
    if (nuevas[:len(acordadas)] != acordadas
            or not len(historicas) <= len(nuevas) <= len(historicas) + 1):
        _fallo(ruta, "La edición reescribe o salta una revisión histórica.")
    if antes["estado"] != "Borrador" and datos["estado"] == "Borrador":
        _fallo(ruta, "Una ficha aceptada conserva su estado al evolucionar.")
    return antes["estado"] != "Borrador"


def _fichas(raiz, lote):
    fichas = {}
    for base in RAICES:
        prefijo = f"{base}/funcionalidades/"
        rutas = {p.relative_to(raiz).as_posix() for p in (raiz / prefijo).rglob("*") if not p.is_dir()}
        rutas.update(r for r in lote if r.startswith(prefijo))
        for ruta in sorted(rutas):
            forma = re.fullmatch(FICHA_ARCHIVO, Path(ruta).name)
            if forma is None:
                _fallo(ruta, "Nombre de ficha nativa inválido.")
            identidad = forma[1]
            if (base, identidad) in fichas:
                _fallo(ruta, "La identidad de ficha figura en dos rutas.")
            contenido = lote[ruta] if ruta in lote else _contenido(raiz, ruta)
            ficha, _ = frontal(contenido.decode(), ruta)
            if ficha.get("id") != identidad:
                _fallo(ruta, "La identidad de la ficha difiere del nombre del archivo.")
            fichas[base, identidad] = (ruta, ficha)
    return fichas


def _existe_en_lote(raiz, lote, ruta):
    return ruta in lote or _contenido(raiz, ruta) is not None


def _validar_vinculos(raiz, lote, fichas_editadas):
    fichas = _fichas(raiz, lote)
    for ruta, base, datos in fichas_editadas:
        propietario = f"{base}/spec_{datos['modulo']}.md"
        if not _existe_en_lote(raiz, lote, propietario):
            _fallo(ruta, f"No existe el spec del módulo dueño: {propietario}.")

    # La comprobación arista por arista termina también con los ciclos nativos.
    for (base, _), (ruta, datos) in fichas.items():
        componentes = datos.get("componentes", [])
        if not isinstance(componentes, list):
            _fallo(ruta, "Los componentes de la ficha deben formar una lista.")
        for componente in componentes:
            if (not isinstance(componente, str)
                    or not re.fullmatch(r"(?:gobernanza/)?sdd/spec_[a-z0-9_-]+\.md", componente)
                    or not _existe_en_lote(raiz, lote, componente)):
                _fallo(ruta, f"No existe el componente declarado: {componente}.")
        dependencias = datos.get("dependencias")
        if not isinstance(dependencias, list):
            _fallo(ruta, "Las dependencias de la ficha deben formar una lista.")
        for dependencia in dependencias:
            if not isinstance(dependencia, str) or re.fullmatch(FICHA, dependencia) is None:
                _fallo(ruta, f"Identidad de dependencia inválida: {dependencia}.")
            destino = fichas.get((base, dependencia))
            if destino is None:
                _fallo(ruta, f"No existe la dependencia de ficha: {dependencia}.")
            if datos.get("estado") == "Validado" and destino[1].get("estado") == "Borrador":
                _fallo(ruta, f"Una ficha validada requiere dependencias fuera de borrador: {dependencia}.")


def _cabecera(ruta, tipo, camino, identidad):
    titulo, campos, _ = lee_campos(camino)

    def campo(nombre):
        valores = [valor.strip().strip("`") for campo, valor in campos if campo == nombre]
        if len(valores) != 1 or not valores[0]:
            _fallo(ruta, f"La cabecera debe declarar un solo {nombre}.")
        return valores[0]

    if not titulo or campo("proyecto") != PROYECTO:
        _fallo(ruta, "La cabecera no identifica el proyecto Heimdall.")
    estado = campo("estado").split(maxsplit=1)[0]
    estados = ESTADOS_SPEC if tipo == "spec" else ESTADOS_ENMIENDA
    if estado not in estados:
        _fallo(ruta, f"Estado editorial no reconocido: {estado}.")
    modulo = campo("modulo")
    if not re.fullmatch(r"[a-z0-9-]+", modulo):
        _fallo(ruta, "La cabecera requiere un módulo válido.")
    if tipo == "spec" and modulo != identidad:
        _fallo(ruta, "La ruta del spec identifica otro módulo.")
    if tipo == "enmienda" and not re.match(
        rf"^Enmienda\s+0*{int(identidad)}\b", titulo, re.IGNORECASE
    ):
        _fallo(ruta, "El folio de la enmienda no coincide con el título.")
    return estado


def _imagen_indice(raiz, candidata, lote):
    for base in RAICES:
        (candidata / base).mkdir(parents=True, exist_ok=True)
    fuentes = {
        p.relative_to(raiz).as_posix()
        for base in RAICES if (raiz / base).is_dir()
        for p in (raiz / base).iterdir() if not p.is_dir()
    }
    for base in ("sesiones/modulos", "gobernanza/sesiones/modulos"):
        fuentes.update(p.relative_to(raiz).as_posix() for p in (raiz / base).glob("*/estado.md"))
    fuentes.update(r for r in lote if Path(r).parent.as_posix() in RAICES)
    for ruta in sorted(fuentes):
        datos = lote[ruta] if ruta in lote else _contenido(raiz, ruta)
        destino = candidata / ruta
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(datos)


def _validar_enmienda(raiz, ruta, ficha, specs):
    destinos = ficha["specs"]
    if not destinos or ficha["destino_inferido"]:
        _fallo(ruta, "La enmienda debe declarar un spec de destino en su cabecera.")
    for destino in destinos + ficha["toca"]:
        if destino not in specs:
            _fallo(ruta, f"El spec citado no existe: {destino}.md.")
    _, _, preambulo = lee_campos(raiz / ruta)
    contratos = set(contratos_en(preambulo, ruta))
    contratos.update(re.findall(r"(?<![\w./])(?:gobernanza/)?sdd/spec_[a-z0-9-]+\.md", preambulo))
    for contrato in sorted(contratos):
        if Path(contrato).name.startswith("spec_") and not (raiz / contrato).is_file():
            _fallo(ruta, f"No existe la ruta de spec citada: {contrato}.")
    if ficha["estado"] == "Incorporada" and any(
        ficha["numero"] not in specs[destino]["incorporadas"] for destino in destinos
    ):
        _fallo(ruta, "Los specs de destino deben registrar la enmienda incorporada.")


def _generar_indice(raiz, lote, editados):
    with TemporaryDirectory(prefix="sdd-heimdall-indice-") as temporal:
        candidata = Path(temporal)
        _imagen_indice(raiz, candidata, lote)
        rutas = [p for base in RAICES for p in (candidata / base).glob("*.md")
                 if p.name.startswith(("spec_", "enmienda_"))]
        if len({p.name for p in rutas}) != len(rutas):
            _fallo(INDICE, "Hay dos documentos con el mismo nombre entre dominios.")
        specs = carga_specs(candidata)
        enmiendas = carga_enmiendas(candidata)
        modulos = carga_modulos(candidata)
        originales = carga_specs(raiz)
        autorizaciones = []
        for ruta, accion, tipo, identidad, anterior in editados:
            estado = _cabecera(ruta, tipo, candidata / ruta, identidad)
            previo = _cabecera(ruta, tipo, raiz / ruta, identidad) if anterior else None
            if (previo is not None and previo not in BORRADORES and estado in BORRADORES
                    or previo == "Incorporada" and estado != previo):
                _fallo(ruta, "La edición pierde un estado editorial aceptado.")
            if tipo == "enmienda":
                _validar_enmienda(candidata, ruta, enmiendas[Path(ruta).name], specs)
            else:
                nombre = Path(ruta).stem
                if anterior and not originales[nombre]["incorporadas"] <= specs[nombre]["incorporadas"]:
                    _fallo(ruta, "La edición retira una incorporación histórica.")
                if any(folio not in {e["numero"] for e in enmiendas.values()}
                       for folio in specs[nombre]["incorporadas"]):
                    _fallo(ruta, "El spec cita una enmienda incorporada sin documento.")
            requiere_dueno = estado not in BORRADORES or previo is not None and previo not in BORRADORES
            autorizaciones.append((ruta, accion, requiere_dueno))
        hallazgos = contrasta(enmiendas, specs, modulos)
        if hallazgos["Contradicciones"]:
            _fallo(INDICE, "; ".join(hallazgos["Contradicciones"]))
        return redacta(candidata, enmiendas, specs, modulos, hallazgos).encode("utf-8"), autorizaciones


def planificar_heimdall(
    raiz: Path, cambios: list[dict], *, autorizar: Callable[[str, str, bool], None],
) -> dict[str, bytes]:
    """Devuelve un lote de datos validados. El llamador controla su publicación."""
    if not isinstance(cambios, list) or not cambios:
        _fallo(INDICE, "Se requiere un lote editorial no vacío.")
    lote, fichas, editados, autorizaciones = {}, [], [], []
    vistos = set()
    indice = False
    for cambio in cambios:
        if not isinstance(cambio, dict):
            _fallo(INDICE, "Cada operación debe ser un objeto.")
        accion = cambio.get("accion")
        if accion == "indice":
            if set(cambio) != {"accion"} or indice:
                _fallo(INDICE, "La regeneración se solicita una sola vez y sin contenido.")
            indice = True
            continue
        tipo, ruta = cambio.get("tipo"), cambio.get("ruta")
        campos = {"accion", "tipo", "ruta", "texto"}
        if tipo == "ficha":
            campos.add("datos")
        if accion not in ("alta", "modificar") or set(cambio) != campos or not isinstance(tipo, str):
            _fallo(ruta, "Operación o campos editoriales inválidos.")
        base, forma = _camino(raiz, ruta, tipo)
        clave = _clave_portable(ruta)
        if clave in vistos:
            _fallo(ruta, "El lote repite el mismo destino.")
        vistos.add(clave)
        anterior = _contenido(raiz, ruta)
        if (accion == "alta") != (anterior is None):
            _fallo(ruta, "La existencia del destino no corresponde a la operación.")
        texto = _texto(ruta, cambio["texto"], tipo)
        if tipo == "ficha":
            datos = cambio["datos"]
            _datos_ficha(datos, ruta, forma[1], base)
            estado_anterior = _historia_ficha(ruta, anterior, datos) if anterior is not None else False
            if not anterior and len(datos["revisiones"]) != 1:
                _fallo(ruta, "Una ficha nueva inicia con una sola revisión.")
            if re.match(rf"^#\s+{re.escape(datos['id'])}\b", texto) is None:
                _fallo(ruta, "El título debe identificar la ficha.")
            texto = serializar(datos, texto)
            fichas.append((ruta, base, datos))
            autorizaciones.append((ruta, accion, estado_anterior or datos["estado"] != "Borrador"))
        elif tipo in {"spec", "enmienda"}:
            editados.append((ruta, accion, tipo, forma[1], anterior))
        else:
            autorizaciones.append((ruta, accion, False))
        contenido = texto.encode("utf-8")
        if contenido != anterior:
            lote[ruta] = contenido
    _validar_vinculos(raiz, lote, fichas)
    if indice or editados or any(Path(r).parent.as_posix() == "sdd" for r in lote):
        contenido, editoriales = _generar_indice(raiz, lote, editados)
        autorizaciones.extend(editoriales)
        if contenido != _contenido(raiz, INDICE):
            lote[INDICE] = contenido
            autorizaciones.append((INDICE, "indice", False))
    for decision in autorizaciones:
        autorizar(*decision)
    return lote
