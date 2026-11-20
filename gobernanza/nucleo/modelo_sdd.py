"""Modelo puro del registro SDD y sus referencias contractuales."""

import json
from pathlib import PurePosixPath
import re

from .documentos import json_estricto
from .modelo import coincide, diagnostico


_REFERENCIAS = {
    "spec": r"SPEC-[0-9]{4}@v[1-9][0-9]*",
    "modulo": r"M-[A-Z0-9][A-Z0-9_-]*",
    "funcionalidad": r"F-[0-9]{4}@r[1-9][0-9]*",
    "sesion": r"[SG][0-9]{2}-[0-9]{2}",
    "enmienda": r"E-[0-9]{4}",
}
_ID_SECCION = r"[A-Z][A-Z0-9_-]*"
_CITA = re.compile(rf"({_REFERENCIAS['spec']})#({_ID_SECCION})")
_ANCLA = re.compile(rf" {{0,3}}<!-- gobernanza:seccion ({_ID_SECCION}) -->[ \t]*")
_CERCA = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")

_CONTRATO = {"borrador": {"vigente"}, "vigente": {"retirado"}, "retirado": set()}
_TRANSICIONES = {
    "spec": _CONTRATO,
    "modulo": _CONTRATO,
    "funcionalidad": _CONTRATO,
    "sesion": {
        "borrador": {"preparacion", "cancelada"},
        "preparacion": {"ejecucion", "pausada", "bloqueada", "cancelada"},
        "ejecucion": {"pendiente_humana", "lista", "pausada", "bloqueada", "cancelada"},
        "pendiente_humana": {"ejecucion", "lista", "pausada", "bloqueada", "cancelada"},
        "pausada": {"preparacion", "ejecucion", "pendiente_humana", "cancelada"},
        "bloqueada": {"preparacion", "ejecucion", "pendiente_humana", "cancelada"},
        "lista": set(),
        "cancelada": set(),
    },
    "enmienda": {
        "borrador": {"aceptada", "rechazada"},
        "aceptada": {"incorporada"},
        "incorporada": set(),
        "rechazada": set(),
    },
}


def serializar(datos, texto):
    """Escribe frontmatter canónico y conserva la prosa recibida."""
    if not isinstance(datos, dict) or not isinstance(texto, str):
        raise ValueError("El documento requiere un objeto de campos y prosa Markdown.")
    frontal = json.dumps(datos, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return f"---\n{frontal}\n---\n{texto}"


def leer(texto):
    """Lee un objeto JSON frontal estricto y entrega intacta la prosa."""
    if not isinstance(texto, str):
        raise ValueError("El documento SDD debe ser texto.")
    lineas = texto.splitlines(keepends=True)
    if not lineas or lineas[0].rstrip("\r\n") != "---":
        raise ValueError("Falta el delimitador inicial del frontmatter SDD.")
    for fin in range(1, len(lineas)):
        if lineas[fin].rstrip("\r\n") == "---":
            datos = json_estricto("".join(lineas[1:fin]))
            if not isinstance(datos, dict):
                raise ValueError("El frontmatter SDD debe ser un objeto JSON.")
            return datos, "".join(lineas[fin + 1:])
    raise ValueError("Falta el delimitador final del frontmatter SDD.")


def _forma(valor, patron):
    return isinstance(valor, str) and re.fullmatch(patron, valor) is not None


def _referencia(valor, tipo):
    # Reserva los cuatro caracteres de la extensión en la ruta canónica.
    return isinstance(valor, str) and len(valor) <= 251 and _forma(valor, _REFERENCIAS[tipo])


def _ruta(valor):
    if not isinstance(valor, str) or not valor or any(c in valor for c in "\\\x00\n\r"):
        return False
    ruta = PurePosixPath(valor)
    return not ruta.is_absolute() and bool(ruta.parts) and not any(
        parte.casefold() in {"..", ".git"} for parte in ruta.parts
    )


def _procedencia(valor):
    return (isinstance(valor, dict) and valor.keys() == {"ruta", "commit", "sha256"}
            and _ruta(valor["ruta"]) and _forma(valor["commit"], r"(?:[a-f0-9]{40}|[a-f0-9]{64})")
            and _forma(valor["sha256"], r"[a-f0-9]{64}"))


def _lista(valores, acepta, *, obligatoria):
    return (isinstance(valores, list) and (not obligatoria or bool(valores))
            and all(acepta(valor) for valor in valores) and len(set(valores)) == len(valores))


def _destinos_ruta(valores):
    return (_lista(valores, lambda valor: _forma(valor, r"(?:META|OBJ)-[0-9]*[1-9][0-9]*"), obligatoria=True)
            and (len(valores) == 1 or all(valor.startswith("OBJ-") for valor in valores)))


def _cita(valor):
    if not isinstance(valor, str):
        return False
    partes = _CITA.fullmatch(valor)
    return partes is not None and _referencia(partes[1], "spec")


def _edicion(campos):
    return {campo: valor for campo, valor in campos.items() if campo != "estado"}


def _cadena(valor):
    return isinstance(valor, str) and bool(valor.strip())


def _registros(registros, valida):
    if not isinstance(registros, list) or not all(
            isinstance(registro, dict) and _cadena(registro.get("id")) and valida(registro)
            for registro in registros):
        return False
    return len({r["id"] for r in registros}) == len(registros)


def _resultado_humano(registro):
    return (set(registro) == {"id", "resultado", "version", "referencia_comunicacion"}
            and registro["resultado"] in ("pasa", "falla")
            and _forma(registro["version"], r"[a-f0-9]{64}")
            and _cadena(registro["referencia_comunicacion"]))


def _deuda_asignada(registro):
    from .cierre import _destino_deuda

    return set(registro) == {"id", "destino"} and _destino_deuda(registro["destino"])


def _error(ref, codigo, mensaje, *, campo=None):
    ruta = f"sdd/registro/{ref}.md" if any(_referencia(ref, tipo) for tipo in _REFERENCIAS) else "sdd/registro/"
    salida = diagnostico(codigo, ruta, "Campos y vínculos del registro SDD V3", f"{ref}: {mensaje}",
                         "Corrige los campos declarados o registra la operación autorizada que corresponda.")
    salida["ref"] = ref if isinstance(ref, str) else repr(ref)
    if campo is not None:
        salida["campo"] = campo if isinstance(campo, str) else repr(campo)
    return salida


def _reglas(tipo):
    if tipo == "spec":
        return {"modulos": lambda ref: _referencia(ref, "modulo"),
                "secciones": lambda ref: _forma(ref, _ID_SECCION)}, {}
    if tipo == "funcionalidad":
        return {"criterios": lambda ref: _forma(ref, r"C[0-9]{2,}"), "secciones": _cita}, {
            "objetos": _ruta, "dependencias": lambda ref: _referencia(ref, "funcionalidad"),
        }
    if tipo == "sesion":
        return {"funcionalidades": lambda ref: _referencia(ref, "funcionalidad")}, {
            "evidencias": _ruta, "cambios": _ruta,
            "enmiendas_incorporadas": lambda ref: _referencia(ref, "enmienda"),
            "enmiendas_pendientes": lambda ref: _referencia(ref, "enmienda"),
            "deuda_sin_asignar": _cadena,
        }
    if tipo == "enmienda":
        return {"secciones": _cita}, {"resultantes": _cita}
    return {}, {}


def _mandato(ref, datos):
    mandato = datos["mandato"]

    def error(campo, mensaje):
        return _error(ref, "MANDATO_SDD", mensaje, campo=campo)

    if not isinstance(mandato, dict):
        return [error("mandato", "Se requiere un objeto de acuerdo.")]
    errores = []
    pedido = mandato.get("referencia_pedido")
    if not isinstance(pedido, str) or not pedido.strip():
        errores.append(error("mandato.referencia_pedido", "Se requiere referencia al pedido del dueño."))
    if "mantenimiento_fuera_de_ruta" in mandato and not _cadena(mandato["mantenimiento_fuera_de_ruta"]):
        errores.append(error("mandato.mantenimiento_fuera_de_ruta", "La justificación debe ser texto no vacío."))
    funcionalidades = mandato.get("funcionalidades")
    del_plan = datos.get("funcionalidades", [])
    acepta = lambda valor: _referencia(valor, "funcionalidad")
    if (not _lista(funcionalidades, acepta, obligatoria=True)
            or not _lista(del_plan, acepta, obligatoria=True)
            or set(funcionalidades) != set(del_plan)):
        errores.append(error("mandato.funcionalidades",
                             f"Las revisiones del mandato {funcionalidades!r} deben coincidir con las del plan."))
    grupos = {"producto", "pruebas", "documentos", "controles"}
    alcance = mandato.get("alcance")
    rutas = []
    if not isinstance(alcance, dict):
        errores.append(error("mandato.alcance", "El alcance requiere un objeto de grupos explícitos."))
    else:
        for grupo in sorted(grupos | alcance.keys(), key=repr):
            patrones = alcance.get(grupo)
            if grupo not in grupos or not _lista(patrones, _ruta, obligatoria=False):
                errores.append(error(f"mandato.alcance.{grupo}", f"Grupo de alcance inválido: {patrones!r}."))
            else:
                rutas.extend(patrones)
    scaffold = mandato.get("scaffold")
    if (not _lista(scaffold, _ruta, obligatoria=False)
            or any(ruta.endswith("/") or any(c in ruta for c in "*?[")
                   or not any(coincide(ruta, patron) for patron in rutas) for ruta in scaffold)):
        errores.append(error("mandato.scaffold", f"Se requieren archivos concretos y dentro del alcance: {scaffold!r}."))
    if "integracion_local" in mandato and type(mandato["integracion_local"]) is not bool:
        errores.append(error("mandato.integracion_local", "El valor debe ser booleano."))
    return errores


def _campos(ref, documento):
    if (not isinstance(documento, tuple) or len(documento) != 2
            or not isinstance(documento[0], dict) or not isinstance(documento[1], str)):
        return [_error(ref, "DOCUMENTO_SDD", "Se requieren campos JSON y prosa Markdown.", campo="documento")]
    datos, _ = documento
    tipo, estado = datos.get("tipo"), datos.get("estado")
    errores = []
    if type(datos.get("schema")) is not int or datos["schema"] != 3:
        errores.append(_error(ref, "ESQUEMA_SDD", "El esquema debe ser el entero 3.", campo="schema"))
    tipo_valido = isinstance(tipo, str) and tipo in _REFERENCIAS
    if not tipo_valido:
        errores.append(_error(ref, "TIPO_SDD", f"Tipo {tipo!r} desconocido.", campo="tipo"))
    if datos.get("ref") != ref or (tipo_valido and not _referencia(ref, tipo)):
        errores.append(_error(ref, "IDENTIDAD_SDD",
                              f"Identidad {datos.get('ref')!r} inválida para {tipo!r}.", campo="ref"))
    estado_valido = isinstance(estado, str) and (not tipo_valido or estado in _TRANSICIONES[tipo])
    if not estado_valido:
        errores.append(_error(ref, "ESTADO_SDD", f"Estado {estado!r} inválido para {tipo}.", campo="estado"))
    if not tipo_valido or not estado_valido:
        return errores

    exigibles, opcionales = _reglas(tipo)
    simples = {
        "titulo": _cadena,
        "procedencia": _procedencia,
    }
    if tipo == "funcionalidad":
        simples["modulo"] = lambda valor: _referencia(valor, "modulo")
    if tipo == "sesion":
        simples.update(plan=lambda valor: type(valor) is int and valor > 0, acuerdo=_ruta,
                       origen=lambda valor: _referencia(valor, "sesion"),
                       resultados_humanos=lambda valor: _registros(valor, _resultado_humano),
                       deuda_asignada=lambda valor: _registros(valor, _deuda_asignada),
                       destinos_ruta=_destinos_ruta)
    admitidos = {"schema", "tipo", "ref", "estado"} | exigibles.keys() | opcionales.keys() | simples.keys()
    tiene_mandato = tipo == "sesion" and "mandato" in datos
    if tiene_mandato:
        admitidos.add("mandato")
        errores.extend(_mandato(ref, datos))
    for campo in sorted(datos.keys() - admitidos, key=repr):
        errores.append(_error(ref, "CAMPO_SDD", f"Campo desconocido: {campo!r}.", campo=campo))
    for campo, controla in simples.items():
        presente = campo in datos or (campo == "modulo" and estado != "borrador") or (campo == "plan" and tiene_mandato)
        if presente and not controla(datos.get(campo)):
            errores.append(_error(ref, "CAMPO_SDD", f"{campo} inválido: {datos.get(campo)!r}.", campo=campo))
    incompleto_admisible = estado in {"borrador", "cancelada", "rechazada"}
    for campo, acepta in {**exigibles, **opcionales}.items():
        obligatorio = ((campo in exigibles and not incompleto_admisible)
                       or (campo == "resultantes" and estado == "incorporada"))
        valor = datos.get(campo, [])
        if not _lista(valor, acepta, obligatoria=obligatorio):
            errores.append(_error(ref, "CAMPO_SDD", f"{campo} requiere una lista válida sin duplicados: {valor!r}.",
                                  campo=campo))
    return errores


def _secciones(texto):
    lineas = texto.splitlines(keepends=True)
    cercado = None
    marcas = []
    for numero, linea in enumerate(lineas):
        contenido = linea.rstrip("\r\n")
        cerca = _CERCA.fullmatch(contenido)
        if cercado is not None:
            if cerca and cerca[1].startswith(cercado) and not cerca[2].strip():
                cercado = None
            continue
        if cerca and (cerca[1][0] != "`" or "`" not in cerca[2]):
            cercado = cerca[1]
            continue
        ancla = _ANCLA.fullmatch(contenido)
        if ancla:
            marcas.append((numero, ancla[1]))
    tramos, duplicadas = {}, set()
    finales = [numero for numero, _ in marcas[1:]] + [len(lineas)]
    for (inicio, nombre), fin in zip(marcas, finales):
        if nombre in tramos:
            duplicadas.add(nombre)
        tramos[nombre] = "".join(lineas[inicio + 1:fin])
    return tramos, duplicadas


def _enlaces(datos):
    tipo = datos["tipo"]
    if tipo == "spec":
        campos = ("modulos",)
    elif tipo == "funcionalidad":
        campos = ("modulo", "dependencias")
    elif tipo == "sesion":
        campos = ("funcionalidades", "origen", "enmiendas_incorporadas", "enmiendas_pendientes")
    else:
        campos = ()
    for campo in campos:
        destinos = datos.get(campo, [])
        for destino in [destinos] if isinstance(destinos, str) else destinos:
            yield campo, destino


def _antiguo(ref, destino):
    spec_anterior, _ = destino.split("#", 1)
    identidad, _, version = spec_anterior.rpartition("@v")
    spec_actual, _ = ref.split("#", 1)
    actual, _, revision = spec_actual.rpartition("@v")
    return identidad == actual and int(version) < int(revision)


def validar_grafo(documentos):
    """Comprueba las fichas y los destinos dentro del mismo candidato."""
    errores, validos, bloques = [], {}, {}
    if not isinstance(documentos, dict):
        return [_error("candidato", "DOCUMENTO_SDD", "El candidato requiere un mapa de documentos.", campo="documentos")]
    for ref, documento in sorted(documentos.items(), key=lambda par: str(par[0])):
        fallos = _campos(ref, documento)
        errores.extend(fallos)
        if fallos:
            continue
        datos, texto = documento
        validos[ref] = datos
        if datos["tipo"] == "spec":
            tramos, duplicadas = _secciones(texto)
            declaradas = set(datos.get("secciones", []))
            for nombre in sorted((tramos.keys() ^ declaradas) | duplicadas):
                errores.append(_error(ref, "ANCLA_SDD",
                                      f"{ref}#{nombre} debe estar declarada y aparecer una sola vez en la prosa.",
                                      campo="secciones"))
            bloques[ref] = (tramos.keys() & declaradas) - duplicadas

    for ref, datos in validos.items():
        tipo = datos["tipo"]
        for campo, destino in _enlaces(datos):
            if destino not in validos:
                errores.append(_error(ref, "REFERENCIA_SDD", f"No existe el destino {destino}.", campo=campo))
            elif campo == "enmiendas_incorporadas" and validos[destino]["estado"] != "incorporada":
                errores.append(_error(ref, "RELACION_SDD", f"{destino} debe estar incorporada.", campo=campo))
        if tipo == "funcionalidad":
            identidad, _, numero = ref.rpartition("@r")
            if int(numero) > 1:
                anterior = f"{identidad}@r{int(numero) - 1}"
                if anterior not in validos:
                    errores.append(_error(ref, "REVISION_SDD", f"Falta la revisión anterior {anterior}.", campo="ref"))
        if tipo not in {"funcionalidad", "enmienda"}:
            continue
        originales = datos.get("secciones", [])
        resultantes = datos.get("resultantes", [])
        for campo, destinos in (("secciones", originales), ("resultantes", resultantes)):
            for destino in destinos:
                spec, nombre = destino.split("#", 1)
                if nombre not in bloques.get(spec, ()):
                    errores.append(_error(ref, "SECCION_SDD", f"No existe una sección única para {destino}.", campo=campo))
                elif tipo == "funcionalidad" and "modulo" in datos:
                    if datos["modulo"] not in validos[spec].get("modulos", []):
                        errores.append(_error(ref, "RELACION_SDD", f"{destino} no aplica al módulo {datos['modulo']}.",
                                              campo=campo))
        for destino in resultantes:
            if not any(_antiguo(destino, anterior) for anterior in originales):
                errores.append(_error(ref, "RELACION_SDD",
                                      f"{destino} debe citar una versión posterior de un spec enmendado.",
                                      campo="resultantes"))
        if tipo == "enmienda" and datos["estado"] == "incorporada":
            for destino in originales:
                if not any(_antiguo(resultado, destino) for resultado in resultantes):
                    errores.append(_error(ref, "RELACION_SDD", f"Falta una versión resultante para {destino}.",
                                          campo="resultantes"))
    return errores


def validar_edicion(anterior, nuevo, accion):
    """Valida la operación local; el grafo y la autoridad se cotejan aparte."""
    ref = "documento"
    for documento in (anterior, nuevo):
        if isinstance(documento, tuple) and len(documento) == 2 and isinstance(documento[0], dict):
            ref = documento[0].get("ref", ref)
            break
    if accion not in ("alta", "migrar", "modificar", "transicion"):
        return [_error(ref, "ACCION_SDD", f"Acción de registro desconocida: {accion!r}.")]
    errores = _campos(ref, nuevo)
    if errores:
        return errores
    datos, texto = nuevo
    if accion in {"alta", "migrar"}:
        if anterior is not None:
            return [_error(ref, "ALTA_SDD", "La identidad ya está registrada.")]
        if accion == "migrar" and "procedencia" not in datos:
            return [_error(ref, "PROCEDENCIA_SDD", "La migración requiere procedencia histórica explícita.")]
        if accion == "alta" and (datos["estado"] != "borrador" or "procedencia" in datos):
            return [_error(ref, "ALTA_SDD", "El alta ordinaria inicia en borrador y carece de procedencia de migración.")]
        return []
    if anterior is None:
        return [_error(ref, "EDICION_SDD", "La operación requiere un documento registrado.")]
    errores = _campos(ref, anterior)
    if errores:
        return errores
    previos, prosa_anterior = anterior
    if datos["tipo"] != previos["tipo"] or datos.get("procedencia") != previos.get("procedencia"):
        return [_error(ref, "EDICION_SDD", "La identidad y la procedencia del documento son permanentes.")]
    estado, destino = previos["estado"], datos["estado"]
    mismo_contenido = _edicion(datos) == _edicion(previos) and texto == prosa_anterior
    if accion == "transicion":
        if destino not in _TRANSICIONES[datos["tipo"]][estado] or not mismo_contenido:
            return [_error(ref, "TRANSICION_SDD",
                           f"Transición inválida de {estado} a {destino}, o acompañada de cambios de contenido.")]
    elif estado != destino:
        return [_error(ref, "TRANSICION_SDD", f"El paso de {estado} a {destino} requiere transición explícita.")]
    elif not mismo_contenido:
        if datos["tipo"] in {"spec", "funcionalidad"} and estado != "borrador":
            return [_error(ref, "CONTRATO_SDD", "El contrato publicado requiere una versión o revisión nueva.")]
        if datos["tipo"] == "sesion" and estado != "borrador":
            if (datos.get("destinos_ruta") != previos.get("destinos_ruta")
                    and estado not in {"preparacion", "pausada", "bloqueada"}):
                return [_error(ref, "DESTINO_RUTA", "El vínculo de ruta está fijo durante la ejecución y el cierre.",
                               campo="destinos_ruta")]
            campos = [campo for campo in ("mandato", "plan", "funcionalidades")
                      if datos.get(campo) != previos.get(campo)]
            if texto != prosa_anterior:
                campos.append("prosa")
            return [_error(ref, "PLAN_SDD", "Los cambios al plan aprobado requieren otro borrador y aprobación.",
                           campo=campo) for campo in campos]
        if datos["tipo"] == "enmienda" and estado != "borrador":
            previos_sin_resultado = {k: v for k, v in previos.items() if k != "resultantes"}
            datos_sin_resultado = {k: v for k, v in datos.items() if k != "resultantes"}
            if (estado != "aceptada" or datos_sin_resultado != previos_sin_resultado
                    or texto != prosa_anterior):
                return [_error(ref, "ENMIENDA_SDD",
                               "Sólo se pueden agregar o precisar las secciones resultantes antes de incorporar.")]
    return []


def seccion(documentos, ref_seccion):
    """Extrae el tramo exacto de Markdown delimitado por la referencia citada."""
    if isinstance(documentos, dict) and _cita(ref_seccion):
        ref, nombre = ref_seccion.split("#", 1)
        documento = documentos.get(ref)
        if documento is not None and not _campos(ref, documento):
            datos, texto = documento
            tramos, duplicadas = _secciones(texto)
            if nombre in datos.get("secciones", []) and nombre in tramos and nombre not in duplicadas:
                return tramos[nombre]
    raise ValueError(f"No existe una sección única para {ref_seccion!r}.")
