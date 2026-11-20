"""Operaciones documentales y cotejo de sus guardados en Git."""

from functools import lru_cache
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from .acuerdos import _cambios_fuente, _capturar, _salidas, _zonas_solapadas, exige_ruta_desarrollo
from .arboles import ErrorArbol, LectorArbol, _git
from .inicio import guardar_documentos
from .modelo import coincide, diagnostico, resultado
from .modelo_sdd import leer, serializar, validar_edicion, validar_grafo


REGISTRO = "sdd/registro"
OPERACIONES = "sdd/operaciones"
APROBACIONES = "sdd/aprobaciones"
_OID = r"(?:[0-9a-f]{40}|[0-9a-f]{64})"
_REF = r"[A-Z][A-Z0-9_-]*(?:@[rv][1-9]\d*)?"
_FOLIO = r"[SG]\d{2}-\d{2}"


class ErrorRegistro(ValueError):
    def __init__(self, ruta, mensaje, codigo="REGISTRO_SDD_INVALIDO"):
        super().__init__(mensaje)
        self.ruta = ruta
        self.codigo = codigo


def _error(ruta, mensaje, codigo="REGISTRO_SDD_INVALIDO"):
    return diagnostico(codigo, ruta, "Cambio documental registrado sobre Git", str(mensaje),
                       "Corrige la propuesta o restaura el registro a su estado cotejado.")


def _diagnostico(exc):
    return _error(getattr(exc, "ruta", REGISTRO), exc, getattr(exc, "codigo", "REGISTRO_SDD_INVALIDO"))


def _sha(contenido):
    return hashlib.sha256(contenido).hexdigest()


def _json(datos):
    return (json.dumps(datos, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _objeto(contenido, ruta):
    from .documentos import json_estricto

    try:
        datos = json_estricto(contenido.decode("utf-8"))
        if not isinstance(datos, dict):
            raise ValueError("Se requiere un objeto JSON.")
        return datos
    except ValueError as exc:
        raise ErrorRegistro(ruta, f"JSON inválido: {exc}") from exc


def _ruta(ref):
    if not isinstance(ref, str) or re.fullmatch(_REF, ref) is None:
        raise ErrorRegistro(REGISTRO, f"Referencia documental inválida: {ref!r}.")
    return f"{REGISTRO}/{ref}.md"


def _en(ruta, directorio):
    return ruta == directorio or ruta.startswith(directorio + "/")


def _playground(ruta):
    return any(parte.casefold() == "playground" for parte in PurePosixPath(ruta).parts)


def _rutas(lector):
    return {ruta for ruta in lector.rutas if _en(ruta, REGISTRO) or _en(ruta, OPERACIONES)}


def _documentos(lector):
    documentos = {}
    for ruta in sorted(r for r in lector.rutas if _en(r, REGISTRO)):
        modo, imagen = lector.entrada(ruta)
        if modo != "100644":
            raise ErrorRegistro(ruta, "El registro exige un archivo Markdown regular sin permiso de ejecución.")
        try:
            datos, texto = leer(imagen.decode("utf-8"))
            ref = datos.get("ref")
            if _ruta(ref) != ruta:
                raise ValueError(f"La ruta no coincide con la identidad {ref!r}.")
        except (TypeError, ValueError) as exc:
            raise ErrorRegistro(ruta, str(exc)) from exc
        documentos[ref] = (datos, texto)
    return documentos


def cargar_registro(raiz, arbol="HEAD"):
    """Lee documentos canónicos del árbol indicado; auditar coteja su linaje."""
    return _documentos(LectorArbol(raiz, arbol))


def _operacion(operacion):
    if not isinstance(operacion, dict) or set(operacion) - {"base", "cambios", "sesion", "aprobacion"}:
        raise ErrorRegistro(REGISTRO, "La operación admite base, cambios y una fuente de autorización opcional.")
    base = operacion.get("base")
    if not isinstance(base, str) or not re.fullmatch(_OID, base):
        raise ErrorRegistro(REGISTRO, "La base debe ser el SHA completo del árbol propuesto.")
    sesion, cambios = operacion.get("sesion"), operacion.get("cambios")
    if sesion is not None and (not isinstance(sesion, str) or not re.fullmatch(_FOLIO, sesion)):
        raise ErrorRegistro(REGISTRO, f"Sesión del acuerdo inválida: {sesion!r}.")
    if not isinstance(cambios, list) or not cambios:
        raise ErrorRegistro(REGISTRO, "La operación requiere una lista de cambios no vacía.")
    aprobacion = operacion.get("aprobacion")
    if aprobacion is not None:
        if sesion is not None:
            raise ErrorRegistro(REGISTRO, "Elige una sesión patrocinadora o una aprobación de arranque.")
        if (not isinstance(aprobacion, dict) or aprobacion.keys() != {"ruta", "commit"}
                or not isinstance(aprobacion["ruta"], str) or not isinstance(aprobacion["commit"], str)
                or not re.fullmatch(_OID, aprobacion["commit"])):
            raise ErrorRegistro(APROBACIONES, "La aprobación de arranque requiere ruta y SHA completo de Git.")
    return base, sesion, cambios, aprobacion


def _cambio(cambio):
    if (not isinstance(cambio, dict) or set(cambio) != {"accion", "datos", "texto"}
            or cambio["accion"] not in ("alta", "modificar", "transicion", "migrar")
            or not isinstance(cambio["datos"], dict) or not isinstance(cambio["texto"], str)):
        raise ErrorRegistro(REGISTRO, "Cada cambio requiere acción, datos estructurados y texto Markdown.")
    datos = cambio["datos"]
    return cambio["accion"], datos, cambio["texto"], _ruta(datos.get("ref"))


def _antecesor(lector, commit):
    try:
        _git(lector.raiz, "merge-base", "--is-ancestor", commit, lector.commit)
    except ValueError as exc:
        raise ErrorRegistro(REGISTRO, f"La fuente {commit} debe pertenecer a la historia de {lector.commit}.") from exc


def _frontal_v2(lector, ruta):
    imagen = lector.leer(ruta)
    lineas = imagen.splitlines()
    if not lineas or lineas[0] != b"---" or b"---" not in lineas[1:]:
        raise ErrorRegistro(ruta, "La fuente legada requiere frontmatter JSON delimitado.")
    return _objeto(b"\n".join(lineas[1:lineas.index(b"---", 1)]), ruta), imagen


def _colisiones_legadas(base, cambios):
    altas = {c["ref"]: c["ruta"] for c in cambios if c["accion"] == "alta" and not c["ref"].startswith("SPEC-")}
    if not altas:
        return []
    ruta_config = "gobernanza/config.json"
    entrada = base.entrada(ruta_config)
    if entrada is None:
        return []
    declaradas = _objeto(entrada[1], ruta_config).get("documentos", [])
    legadas = [ruta for ruta in sorted(base.rutas) if not _en(ruta, REGISTRO) and not _en(ruta, OPERACIONES)
               and not _playground(ruta)
               and any(coincide(ruta, patron) for patron in declaradas)]
    errores = []
    for ruta in legadas:
        datos, _ = _frontal_v2(base, ruta)
        ref = datos.get("id")
        if datos.get("schema") != 1 or not isinstance(ref, str):
            continue
        referencias = ({f"{ref}@r{revision}" for revision in datos.get("revisiones", [])}
                        if ref.startswith("F-") else {ref})
        for colision in sorted(referencias & altas.keys()):
            errores.append(_error(altas[colision], f"{colision} ya existe en {ruta}; requiere migración con procedencia.",
                                  "REGISTRO_SDD_COLISION"))
    return errores


def _procedencia(fuente_de, datos, destino):
    origen = datos["procedencia"]
    ruta, commit = origen["ruta"], origen["commit"]
    fuente, declaradas = fuente_de(commit)
    if not any(coincide(ruta, patron) for patron in declaradas) or _en(ruta, REGISTRO) or _playground(ruta):
        raise ErrorRegistro(ruta, "La procedencia debe citar un documento legado inventariado.")
    anterior, imagen = _frontal_v2(fuente, ruta)
    if _sha(imagen) != origen["sha256"] or anterior.get("schema") != 1:
        raise ErrorRegistro(ruta, "La huella o el esquema de la procedencia histórica no coincide.")
    identidad = anterior.get("id")
    ref = datos["ref"]
    tipo = datos["tipo"]
    if tipo == "funcionalidad":
        folio, revision = ref.split("@r", 1)
        corresponde = (identidad == folio and int(revision) in anterior.get("revisiones", [])
                       and anterior.get("modulo") == datos["modulo"]
                       and anterior.get("criterios", {}).get(revision) == datos["criterios"])
    elif tipo == "spec":
        corresponde = isinstance(identidad, str) and identidad.startswith("M-") and identidad in datos["modulos"]
    else:
        corresponde = identidad == ref
    if not corresponde:
        raise ErrorRegistro(destino, f"La procedencia {ruta} no corresponde a {ref}.")


def _promocion_sesion(base, sesion, fuente):
    promovida = LectorArbol(base.raiz, fuente)
    _, *padres = _git(base.raiz, "rev-list", "--parents", "-1", fuente).decode().split()
    if len(padres) != 1:
        return False
    anterior = LectorArbol(base.raiz, padres[0])
    nuevas = [ruta for ruta in _rutas(promovida) - _rutas(anterior) if _en(ruta, OPERACIONES)]
    if len(nuevas) != 1:
        return False
    recibo = _objeto(promovida.leer(nuevas[0]), nuevas[0])
    datos, _ = leer(promovida.leer(_ruta(sesion)).decode())
    return (datos.get("estado") == "preparacion" and any(
        c["ref"] == sesion and c["ruta"] == _ruta(sesion) and c["accion"] == "transicion"
        and c["estado"] == "preparacion" for c in recibo["cambios"]))


def _cotejar_enlaces_sesion(base, enlaces, *, alcance=None, base_alcance=None):
    if not enlaces:
        return
    grupos = dict.fromkeys(("acuerdo", "evidencias", "cambios"))
    inicial = base
    if alcance is not None:
        config = _objeto(base.leer("gobernanza/config.json"), "gobernanza/config.json")
        grupos = {"acuerdo": alcance["documentos"], "evidencias": [*alcance["documentos"], *_salidas(config)],
                  "cambios": [p for patrones in alcance.values() for p in patrones]}
        if base_alcance is not None and base_alcance != base.commit:
            inicial = LectorArbol(base.raiz, base_alcance)

    def rutas(datos, campo):
        valor = datos.get(campo, [])
        return {valor} if isinstance(valor, str) else set(valor)

    for anterior, nueva in enlaces:
        for campo, patrones in grupos.items():
            antes, despues = rutas(anterior, campo), rutas(nueva, campo)
            for ruta in sorted(antes ^ despues):
                if patrones is not None and not any(coincide(ruta, p) for p in patrones):
                    raise ErrorRegistro(ruta, f"El campo {campo} cita una ruta fuera del alcance autorizado.",
                                        "REGISTRO_SDD_AUTORIDAD")
                if ruta not in despues:
                    continue
                if _playground(ruta):
                    raise ErrorRegistro(ruta, f"El campo {campo} no admite fuentes de playground.", "REGISTRO_SDD_DESTINO")
                existe = (ruta in base.rutas or ruta in inicial.rutas if campo == "cambios"
                          else base.entrada(ruta) is not None)
                if not existe:
                    raise ErrorRegistro(ruta, f"El destino de {campo} no se encuentra en Git.", "REGISTRO_SDD_DESTINO")


def _permite(permisos, cambio):
    permiso = {k: cambio[k] for k in ("accion", "ref", "estado")}
    autorizables = [permiso]
    if cambio["accion"] == "migrar":
        autorizables.append({"accion": "migrar", "ref": "*", "estado": "*"})
    coincidentes = [p for p in permisos if isinstance(p, dict)
                    and {k: v for k, v in p.items() if k != "sha256"} in autorizables]
    acotados = [p["sha256"] for p in coincidentes if "sha256" in p]
    if not acotados:
        return bool(coincidentes)
    huella = cambio["antes"] if cambio["accion"] == "transicion" else cambio["despues"]
    if huella not in acotados:
        raise ErrorRegistro(cambio["ruta"], "La huella del documento no coincide con ninguna aprobación aplicable.",
                            "REGISTRO_SDD_AUTORIDAD")
    return True


def _autorizar(base, sesion, cambios, enlaces, *, reanudacion=False):
    exigidos = [cambio for cambio in cambios if cambio["accion"] in {"transicion", "migrar"}
                or (cambio["accion"] == "modificar" and cambio["estado_anterior"] != "borrador"
                    and re.fullmatch(_FOLIO, cambio["ref"]))]
    if sesion is None:
        if not exigidos:
            return None
        raise ErrorRegistro(exigidos[0]["ruta"], "La operación requiere una sesión con acuerdo guardado.",
                            "REGISTRO_SDD_AUTORIDAD")
    ruta = f"sesiones/estado/{sesion}/acuerdo.json"
    try:
        imagen = base.leer(ruta)
        capturado = _objeto(imagen, ruta)
        fuente = capturado["ref_acuerdo"]
        _antecesor(base, fuente)
        if capturado != _capturar(base.raiz, sesion, fuente, capturado["base"]):
            raise ValueError("El acuerdo guardado no coincide con el compromiso de origen.")
        if reanudacion:
            actual = _capturar(base.raiz, sesion, base.commit, capturado["base"], reanudacion=True)
        else:
            actual = _capturar(base.raiz, sesion, base.commit, capturado["base"])
        if (actual["ruta_sesion"], actual["huella_acuerdo"]) != (capturado["ruta_sesion"], capturado["huella_acuerdo"]):
            raise ValueError("La autoridad de la sesión cambió después del inicio.")
        ruta_sesion = actual["ruta_sesion"]
        if ruta_sesion == _ruta(sesion):
            datos, _ = leer(base.leer(ruta_sesion).decode())
            if (datos.get("schema"), datos.get("tipo"), datos.get("ref")) != (3, "sesion", sesion):
                raise ValueError("La sesión SDD discrepa de su identidad canónica.")
            if not _promocion_sesion(base, sesion, fuente):
                raise ValueError("La captura debe anclarse a la promoción registrada de la sesión SDD.")
        else:
            datos, _ = _frontal_v2(base, ruta_sesion)
            if datos.get("schema") != 1 or datos.get("inicio") != {"registro": ruta, "ref_acuerdo": fuente}:
                raise ValueError("La sesión no enlaza su acuerdo guardado exacto.")
        estados = {"preparacion", "ejecucion", "pendiente_humana"}
        if reanudacion and ruta_sesion == _ruta(sesion):
            estados.update({"pausada", "bloqueada"})
        if datos.get("estado") not in estados:
            raise ValueError("La sesión del acuerdo debe estar activa.")
        acuerdo = capturado["datos"]["acuerdo"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ErrorRegistro(ruta, f"Falta acuerdo vigente para la operación de {sesion}: {exc}",
                            "REGISTRO_SDD_AUTORIDAD") from exc
    permisos = acuerdo.get("registro_sdd", [])
    if not isinstance(permisos, list):
        raise ErrorRegistro(ruta, "registro_sdd debe listar los permisos expresos del acuerdo.",
                            "REGISTRO_SDD_AUTORIDAD")
    for cambio in exigidos:
        permitido = cambio["accion"] == "modificar" or _permite(permisos, cambio)
        if not permitido or not any(coincide(cambio["ruta"], p) for p in acuerdo["alcance"]["documentos"]):
            raise ErrorRegistro(cambio["ruta"], f"El acuerdo {sesion} no autoriza {cambio['accion']} de "
                                f"{cambio['ref']} en estado {cambio['estado']} en esa ruta.",
                                "REGISTRO_SDD_AUTORIDAD")
    _cotejar_enlaces_sesion(base, enlaces, alcance=acuerdo["alcance"], base_alcance=capturado["base"])
    return {"ruta": ruta, "ref_acuerdo": fuente, "sha256": _sha(imagen)}


def _aprobar_arranque(base, aprobacion, cambios, documentos, enlaces):
    ruta, commit = aprobacion["ruta"], aprobacion["commit"]
    if len(cambios) != 1:
        raise ErrorRegistro(ruta, "La aprobación de arranque sólo cubre la promoción de una sesión.",
                            "REGISTRO_SDD_AUTORIDAD")
    cambio = cambios[0]
    ref = cambio["ref"]
    datos = documentos[ref][0]
    if (datos["tipo"] != "sesion" or not datos.get("mandato") or ruta != f"{APROBACIONES}/{ref}.json"
            or (cambio["accion"], cambio["estado_anterior"], cambio["estado"])
            != ("transicion", "borrador", "preparacion")):
        raise ErrorRegistro(ruta, "La aprobación sólo habilita la transición a preparación de su propio borrador de sesión con mandato.",
                            "REGISTRO_SDD_AUTORIDAD")
    try:
        _antecesor(base, commit)
        fuente = LectorArbol(base.raiz, commit)
        imagen = fuente.leer(ruta)
        if fuente.entrada(ruta) != ("100644", imagen) or base.entrada(ruta) != ("100644", imagen):
            raise ValueError("La aprobación debe ser regular y conservar los mismos bytes en la base propuesta.")
        declarada = _objeto(imagen, ruta)
        if declarada.keys() != {"schema", "sesion", "sha256", "referencia_dueno"} or declarada.get("schema") != 3:
            raise ValueError("Se requieren schema 3, sesión, huella del borrador y referencia al dueño.")
        pedido = declarada["referencia_dueno"]
        if declarada["sesion"] != ref or not isinstance(pedido, str) or not pedido.strip():
            raise ValueError("La aprobación debe identificar la sesión y la decisión real del dueño.")
        if declarada["sha256"] != cambio["antes"]:
            raise ValueError("La huella de aprobación no coincide con el borrador exacto.")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise ErrorRegistro(ruta, str(exc), "REGISTRO_SDD_AUTORIDAD") from exc
    alcance = datos["mandato"]["alcance"]
    if not any(coincide(cambio["ruta"], patron) for patron in alcance["documentos"]):
        raise ErrorRegistro(ruta, "El mandato aprobado debe incluir su propia ruta documental.", "REGISTRO_SDD_AUTORIDAD")
    _cotejar_enlaces_sesion(base, enlaces, alcance=alcance)
    return dict(aprobacion, sesion=ref, sha256=_sha(imagen), sha256_borrador=cambio["antes"], referencia_dueno=pedido)


def _cotejar_destinos_ruta(base, destinos):
    from .ruta_desarrollo import RUTA, leer_ruta, validar_destinos

    entrada = base.entrada(RUTA)
    if entrada is None or entrada[0] != "100644":
        raise ErrorRegistro(RUTA, "Guarda la hoja de ruta del proyecto como archivo Markdown regular.",
                            "DESTINO_RUTA")
    if not destinos:
        raise ErrorRegistro(RUTA, "La ejecución de producto requiere un destino de la ruta de desarrollo.",
                            "DESTINO_RUTA")
    try:
        return validar_destinos(leer_ruta(entrada[1].decode("utf-8")), destinos)
    except (ValueError, TypeError) as exc:
        raise ErrorRegistro(RUTA, str(exc), "DESTINO_RUTA") from exc


def _exigir_destino_de_producto(base, datos):
    ruta_config = "gobernanza/config.json"
    actual = _objeto(base.leer(ruta_config), ruta_config)
    ref = datos["ref"]
    ruta_acuerdo = f"sesiones/estado/{ref}/acuerdo.json"
    entrada = base.entrada(ruta_acuerdo)
    captura = _objeto(entrada[1], ruta_acuerdo) if entrada is not None else None
    fuente = actual
    if captura is not None:
        ref_acuerdo = captura["ref_acuerdo"]
        _antecesor(base, ref_acuerdo)
        fuente = _objeto(LectorArbol(base.raiz, ref_acuerdo).leer(ruta_config), ruta_config)
    if not exige_ruta_desarrollo(actual, fuente):
        return

    mandato = datos["mandato"]
    alcance = mandato["alcance"]
    raices = (actual["raices"], fuente["raices"])
    excluidas = [patron for grupo in raices for clase in ("pruebas", "controles") for patron in grupo[clase]]
    solucion = [patron for grupo in raices for patron in grupo["solucion"]]
    otros_destinos = [ruta for clase, rutas in alcance.items() if clase != "producto" for ruta in rutas]

    def producto(ruta):
        return ruta not in mandato["scaffold"] and not any(coincide(ruta, patron) for patron in excluidas)

    previsto = (any(producto(ruta) for ruta in alcance["producto"])
                or any(producto(ruta) and any(_zonas_solapadas(ruta, patron) for patron in solucion)
                       for ruta in otros_destinos))
    if not previsto and captura is not None:
        cambios = _cambios_fuente(LectorArbol(base.raiz, captura["base"]), base)
        previsto = any(producto(ruta) and any(coincide(ruta, patron) for patron in solucion) for ruta in cambios)
    if previsto:
        _cotejar_destinos_ruta(base, datos.get("destinos_ruta"))


def _plan(base, operacion):
    ref_base, sesion, cambios, aprobacion = _operacion(operacion)
    if base.commit != ref_base:
        raise ErrorRegistro(REGISTRO, "La base declarada no coincide con el árbol de la operación.")
    documentos = _documentos(base)
    imagenes, declarados, errores = {}, [], []
    borradores, enlaces, fases, destinos = [], [], [], []
    reanudar_autoridad = False
    for cambio in cambios:
        accion, datos, texto, ruta = _cambio(cambio)
        if ruta in imagenes:
            raise ErrorRegistro(ruta, "El lote modifica el mismo destino más de una vez.")
        try:
            imagen = serializar(datos, texto).encode()
            nuevo = leer(imagen.decode())
        except (TypeError, ValueError) as exc:
            raise ErrorRegistro(ruta, str(exc)) from exc
        ref = datos["ref"]
        anterior = documentos.get(ref)
        errores.extend(validar_edicion(anterior, nuevo, accion))
        if datos.get("tipo") == "sesion":
            anteriores = anterior[0] if anterior else {}
            if accion in {"alta", "modificar"} and datos.get("estado") == "borrador":
                borradores.append(({}, datos))
            elif accion == "modificar":
                enlaces.append((anteriores, datos))
                if anteriores.get("destinos_ruta") != datos.get("destinos_ruta"):
                    if "destinos_ruta" in datos:
                        destinos.append(datos["destinos_ruta"])
                    reanudar_autoridad = (len(cambios) == 1 and ref == sesion
                                          and anteriores.get("estado") in {"pausada", "bloqueada"}
                                          and {k: v for k, v in datos.items() if k != "destinos_ruta"}
                                          == {k: v for k, v in anteriores.items() if k != "destinos_ruta"})
            elif accion == "transicion":
                if anteriores.get("estado") == "borrador" and datos.get("estado") == "preparacion":
                    enlaces.append(({}, datos))
                if datos.get("mandato") and datos.get("estado") in {"ejecucion", "pendiente_humana", "lista"}:
                    reanudar = datos["estado"] == "ejecucion" and anteriores.get("estado") in {"pausada", "bloqueada"}
                    reanudar_autoridad = reanudar and len(cambios) == 1 and ref == sesion
                    fases.append((datos, reanudar))
        antes = _sha(base.leer(ruta)) if anterior is not None else None
        despues = _sha(imagen)
        if antes == despues:
            errores.append(_error(ruta, f"El cambio de {ref} no altera el documento."))
        imagenes[ruta] = imagen
        documentos[ref] = nuevo
        declarados.append({"ref": ref, "ruta": ruta, "accion": accion, "antes": antes, "despues": despues,
                           "estado_anterior": anterior[0].get("estado") if anterior else None,
                           "estado": datos.get("estado")})
    errores.extend(validar_grafo(documentos))
    errores.extend(_colisiones_legadas(base, declarados))
    if errores:
        return errores, None, None
    _cotejar_enlaces_sesion(base, borradores)
    acuerdo, decision = None, None
    if aprobacion is None:
        acuerdo = _autorizar(base, sesion, declarados, enlaces, reanudacion=reanudar_autoridad)
    else:
        decision = _aprobar_arranque(base, aprobacion, declarados, documentos, enlaces)
    for vinculados in destinos:
        _cotejar_destinos_ruta(base, vinculados)
    if fases:
        from .flujo_sdd import comprobar_fase

        for datos, reanudar in fases:
            if datos["estado"] == "ejecucion":
                _exigir_destino_de_producto(base, datos)
            errores.extend(comprobar_fase(base.raiz, base.commit, datos, reanudacion=reanudar))
        if errores:
            return errores, None, None

    @lru_cache(maxsize=None)
    def fuente_de(commit):
        _antecesor(base, commit)
        fuente = LectorArbol(base.raiz, commit)
        configuracion = _objeto(fuente.leer("gobernanza/config.json"), "gobernanza/config.json")
        return fuente, configuracion.get("documentos", [])

    for cambio in declarados:
        if cambio["accion"] == "migrar":
            _procedencia(fuente_de, documentos[cambio["ref"]][0], cambio["ruta"])
    cuerpo = {"schema": 3, "base": base.commit, "sesion": sesion, "acuerdo": acuerdo,
              "cambios": sorted(declarados, key=lambda c: c["ruta"])}
    if decision is not None:
        cuerpo["aprobacion"] = decision
    recibo = dict(cuerpo, id="OP-" + _sha(_json(cuerpo)))
    imagenes[f"{OPERACIONES}/{recibo['id']}.json"] = _json(recibo)
    return [], recibo, imagenes


def _entradas(lector):
    return {ruta: lector.entradas[ruta] for ruta in _rutas(lector)}


def _con_diferencia(anterior, actual):
    return [ruta for ruta in sorted(set(anterior) | set(actual)) if anterior.get(ruta) != actual.get(ruta)]


def _reproducir(base, nuevo, rutas):
    antiguas, actuales = _entradas(base), _entradas(nuevo)
    constancias = [ruta for ruta in rutas if _en(ruta, OPERACIONES)]
    altas = [ruta for ruta in constancias if ruta not in antiguas and ruta in actuales]
    if len(constancias) != 1 or len(altas) != 1:
        errores = [_error(ruta, "Falta constancia nueva única o se alteró una constancia anterior.",
                          "REGISTRO_SDD_DERIVA") for ruta in rutas]
        return errores, None
    ruta_recibo = altas[0]
    try:
        recibo = _objeto(nuevo.leer(ruta_recibo), ruta_recibo)
        cambios = []
        for registrado in recibo["cambios"]:
            ruta = _ruta(registrado["ref"])
            datos, texto = leer(nuevo.leer(ruta).decode())
            cambios.append({"accion": registrado["accion"], "datos": datos, "texto": texto})
        operacion = {"base": recibo["base"], "sesion": recibo["sesion"], "cambios": cambios}
        if "aprobacion" in recibo:
            operacion["aprobacion"] = {k: recibo["aprobacion"][k] for k in ("ruta", "commit")}
        errores, esperado, imagenes = _plan(base, operacion)
        if errores:
            return errores, None
        if esperado != recibo or set(imagenes) != set(rutas):
            exceso = set(imagenes).symmetric_difference(rutas)
            detalles = ", ".join(sorted(exceso))
            raise ErrorRegistro(ruta_recibo, f"La constancia no describe el cambio exacto de Git. {detalles}",
                                "REGISTRO_SDD_DERIVA")
        for ruta, imagen in imagenes.items():
            if nuevo.entrada(ruta) != ("100644", imagen):
                raise ErrorRegistro(ruta, "Los bytes o el modo en Git difieren del lote registrado.",
                                    "REGISTRO_SDD_DERIVA")
        return [], dict(recibo, commit=nuevo.commit)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        error = _error(getattr(exc, "ruta", ruta_recibo), str(exc), "REGISTRO_SDD_DERIVA")
        return [error], None


def _cotejar_merge(nuevo, padres):
    sha, actual = nuevo.commit, _entradas(nuevo)
    imagenes = [_entradas(padre) for padre in padres]
    perdidas = {ruta for padre in imagenes for ruta, imagen in padre.items()
                if _en(ruta, OPERACIONES) and actual.get(ruta) != imagen}
    errores = [_error(ruta, f"El merge {sha} descarta o altera una constancia de sus padres.",
                      "REGISTRO_SDD_DERIVA") for ruta in sorted(perdidas)]
    if errores or actual in imagenes:
        return errores

    comunes = _git(nuevo.raiz, "merge-base", "--all", "--octopus", *(padre.commit for padre in padres)).decode().split()
    if len(comunes) != 1:
        return [_error(REGISTRO, f"El merge {sha} requiere un ancestro común inequívoco.", "REGISTRO_SDD_DERIVA")]
    origen = _entradas(LectorArbol(nuevo.raiz, comunes[0]))
    esperado = dict(origen)
    for ruta in sorted(set(origen).union(*imagenes)):
        cambios = {padre.get(ruta) for padre in imagenes if padre.get(ruta) != origen.get(ruta)}
        if len(cambios) > 1:
            errores.append(_error(ruta, f"El merge {sha} combina ediciones incompatibles de la misma ruta.",
                                  "REGISTRO_SDD_DERIVA"))
        elif cambios:
            imagen = cambios.pop()
            if imagen is None:
                esperado.pop(ruta, None)
            else:
                esperado[ruta] = imagen
    errores.extend(_error(ruta, f"El merge {sha} introduce una imagen distinta de los cambios registrados.",
                          "REGISTRO_SDD_DERIVA") for ruta in _con_diferencia(esperado, actual))
    return errores or validar_grafo(_documentos(nuevo))


def _historial(cabeza):
    raiz, punta = cabeza.raiz, cabeza.commit
    commits = _git(raiz, "rev-list", "--full-history", "--topo-order", "--reverse", punta,
                   "--", REGISTRO, OPERACIONES).decode().splitlines()

    @lru_cache(maxsize=8)
    def vista(sha):
        return cabeza if sha == punta else LectorArbol(raiz, sha)

    errores, recibos, migraciones, consumidas = [], [], [], {}
    for sha in commits:
        nuevo = vista(sha)
        actual = _entradas(nuevo)
        _, *padres = _git(raiz, "rev-list", "--parents", "-1", sha).decode().split()
        if not padres:
            errores.extend(_error(ruta, "El commit inicial requiere una base previa para registrar el SDD.") for ruta in actual)
            continue
        if len(padres) > 1:
            errores.extend(_cotejar_merge(nuevo, [vista(padre) for padre in padres]))
            continue
        base = vista(padres[0])
        rutas = _con_diferencia(_entradas(base), actual)
        if not rutas:
            continue
        fallos, recibo = _reproducir(base, nuevo, rutas)
        errores.extend(fallos)
        if recibo is not None:
            aprobacion = recibo.get("aprobacion")
            if aprobacion is not None:
                clave = (aprobacion["ruta"], aprobacion["sha256"])
                anterior = consumidas.setdefault(clave, recibo["id"])
                if anterior != recibo["id"]:
                    errores.append(_error(aprobacion["ruta"], "La aprobación ya fue consumida por otra operación.",
                                          "REGISTRO_SDD_AUTORIDAD"))
            anteriores = []
            for migracion in migraciones:
                try:
                    _antecesor(base, migracion["commit"])
                except ErrorRegistro:
                    continue
                anteriores.append(migracion)
            # Coteja el árbol que otorgó autoridad, incluso si una rama
            # restauró después los bytes del legado antes de integrarse.
            errores.extend(_cotejar_legado(base, [*anteriores, recibo]))
            if _es_migracion(recibo):
                migraciones.append(recibo)
            recibos.append(recibo)
    return errores, recibos


def _deriva(cabeza, candidato):
    errores = []
    for ruta in sorted(_rutas(cabeza) | _rutas(candidato)):
        try:
            if cabeza.entrada(ruta) == candidato.entrada(ruta):
                continue
            mensaje = "El árbol contiene cambios documentales sin una operación guardada."
        except ValueError as exc:
            mensaje = str(exc)
        errores.append(_error(ruta, mensaje, "REGISTRO_SDD_DERIVA"))
    return errores


def _es_migracion(operacion):
    return any(cambio["accion"] == "migrar" for cambio in operacion["cambios"])


def _cotejar_legado(candidato, operaciones):
    if not any(_es_migracion(op) for op in operaciones):
        return []
    from .flujo_sdd import auditar_legado

    return auditar_legado(candidato, operaciones)


def _seleccion(raiz, arbol):
    candidato = LectorArbol(raiz, arbol)
    try:
        cabeza = candidato if candidato.commit else LectorArbol(raiz, "HEAD")
    except ErrorArbol:
        # La primera rama de un consumidor todavía puede carecer de commits.
        rama = _git(raiz, "symbolic-ref", "HEAD").decode().strip()
        if rama in _git(raiz, "for-each-ref", "--format=%(refname)", rama).decode().splitlines():
            raise
        return [_error(ruta, "El alta SDD requiere un commit base.") for ruta in sorted(_rutas(candidato))], []
    errores, recibos = _historial(cabeza)
    if candidato is not cabeza:
        errores.extend(_deriva(cabeza, candidato))
    if not errores:
        errores.extend(_cotejar_legado(candidato, recibos))
    return errores, recibos


def auditar(raiz, arbol="HEAD"):
    """Devuelve discrepancias de todas las operaciones en la historia candidata."""
    try:
        return _seleccion(raiz, arbol)[0]
    except (ValueError, TypeError, KeyError, OSError) as exc:
        return [_diagnostico(exc)]


def listar_operaciones(raiz, arbol="HEAD"):
    """Lee constancias cotejadas con el commit que las publicó."""
    errores, recibos = _seleccion(raiz, arbol)
    if errores:
        raise ErrorRegistro(errores[0]["ruta"], errores[0]["mensaje"], errores[0]["codigo"])
    return recibos


def registrar(raiz, operacion, *, aplicar=False):
    """Simula el lote sobre HEAD o publica constancia y documentos juntos."""
    salida = resultado("registrar")
    salida.update(cambios=[], recibo=None, commit=None, idempotente=False)
    try:
        ref_base, _, _, _ = _operacion(operacion)
        cabeza = LectorArbol(Path(raiz), "HEAD")
        base = cabeza if ref_base == cabeza.commit else LectorArbol(cabeza.raiz, ref_base)
        errores, historial = _historial(cabeza)
        candidatos = [LectorArbol(cabeza.raiz, arbol) for arbol in ("worktree", "staged")]
        for candidato in candidatos:
            errores.extend(_deriva(cabeza, candidato))
        if errores:
            salida.update(resultado("registrar", errores))
            return salida
        errores, recibo, imagenes = _plan(base, operacion)
        if errores:
            salida.update(resultado("registrar", errores))
            return salida
        anterior = next((r for r in historial if r["id"] == recibo["id"]), None)
        operaciones = [*historial, recibo] if base is cabeza and anterior is None else historial
        for candidato in [cabeza, *candidatos]:
            errores.extend(_cotejar_legado(candidato, operaciones))
        if errores:
            salida.update(resultado("registrar", errores))
            return salida
        salida.update(cambios=recibo["cambios"], recibo=recibo,
                      resumen="La operación y sus vínculos satisfacen el registro documental.")
        if anterior is not None:
            return dict(salida, commit=anterior["commit"], idempotente=True)
        if base is not cabeza:
            raise ErrorRegistro(REGISTRO, f"La base de la propuesta {ref_base} ya no es HEAD.", "REGISTRO_SDD_BASE")
        if aplicar:
            salida["commit"] = guardar_documentos(cabeza.raiz, imagenes, f"docs: registrar {recibo['id']}",
                                                  esperado=cabeza.commit)
        return salida
    except (KeyError, TypeError, ValueError, OSError) as exc:
        salida.update(resultado("registrar", [_diagnostico(exc)]))
        return salida


def _reintento_vinculo(cabeza, ruta, destinos, base):
    _cotejar_destinos_ruta(cabeza, destinos)
    operaciones = listar_operaciones(cabeza.raiz, cabeza.commit)
    for operacion in reversed(operaciones):
        cambio = next((c for c in operacion["cambios"] if c["ruta"] == ruta), None)
        if cambio is None or (base not in (None, cabeza.commit, operacion["base"])):
            continue
        posterior = LectorArbol(cabeza.raiz, operacion["commit"])
        datos, _ = leer(posterior.leer(ruta).decode("utf-8"))
        if datos.get("destinos_ruta") != destinos:
            continue
        if cambio["antes"] is not None:
            anterior = LectorArbol(cabeza.raiz, operacion["base"])
            datos, _ = leer(anterior.leer(ruta).decode("utf-8"))
            if datos.get("destinos_ruta") == destinos:
                continue
        if _git(cabeza.raiz, "rev-parse", "HEAD").decode("ascii").strip() != cabeza.commit:
            raise ErrorRegistro(ruta, "HEAD cambió mientras se cotejaba el vínculo.", "DESTINO_RUTA_BASE")
        salida = resultado("vincular-ruta")
        salida.update(cambios=operacion["cambios"], commit=operacion["commit"], idempotente=True,
                      recibo={k: v for k, v in operacion.items() if k != "commit"},
                      resumen="El vínculo ya está registrado y su destino sigue vigente.")
        return salida
    raise ErrorRegistro(ruta, "No hay una constancia del vínculo para la base indicada.", "DESTINO_RUTA_BASE")


def vincular_ruta(raiz, sesion, destinos, *, base=None, aplicar=False):
    """Simula o registra destinos sin modificar el acuerdo de una sesión SDD."""
    try:
        if not isinstance(sesion, str) or not re.fullmatch(_FOLIO, sesion):
            raise ErrorRegistro(REGISTRO, f"Folio de sesión inválido: {sesion!r}.", "DESTINO_RUTA")
        if base is not None and (not isinstance(base, str) or not re.fullmatch(_OID, base)):
            raise ErrorRegistro(REGISTRO, "Indica el SHA completo de la base del vínculo.", "DESTINO_RUTA_BASE")
        cabeza = LectorArbol(raiz, "HEAD")
        ruta = _ruta(sesion)
        if cabeza.entrada(ruta) is None:
            raise ErrorRegistro(ruta, f"No existe la sesión SDD {sesion}.", "DESTINO_RUTA")
        datos, texto = leer(cabeza.leer(ruta).decode("utf-8"))
        if "destinos_ruta" in datos and datos["destinos_ruta"] == destinos:
            return _reintento_vinculo(cabeza, ruta, destinos, base)
        if base not in (None, cabeza.commit):
            raise ErrorRegistro(ruta, "La base del vínculo ya no es HEAD.", "DESTINO_RUTA_BASE")
        if datos["estado"] == "borrador":
            _cotejar_destinos_ruta(cabeza, destinos)
        lote = {"base": cabeza.commit, "cambios": [
            {"accion": "modificar", "datos": dict(datos, destinos_ruta=destinos), "texto": texto},
        ]}
        if datos["estado"] != "borrador":
            lote["sesion"] = sesion
        return dict(registrar(raiz, lote, aplicar=aplicar), operacion="vincular-ruta")
    except (ValueError, TypeError, KeyError, OSError) as exc:
        return resultado("vincular-ruta", [_diagnostico(exc)])
