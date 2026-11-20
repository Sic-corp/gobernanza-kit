"""Adaptador explícito de distribución; reglas en paquete/gestor, no en la CLI."""

import argparse
import json
from pathlib import Path
import sys

from ..nucleo.documentos import json_estricto
from ..nucleo.inicio import _escribir_bytes
from ..nucleo.modelo import diagnostico, resultado
from . import codex
from .gestor import aplicar, inspeccionar, planificar, recuperar
from .operacion import ejecutar as operar
from .paquete import crear_paquete


class UsoInvalido(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsoInvalido(message)


def _comunes(parser):
    parser.add_argument("--raiz", default=argparse.SUPPRESS, help="Raíz del consumidor (directorio actual por defecto)")
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Salida JSON estructurada")


def _parser():
    p = Parser(prog="python3 -m gobernanza.distribucion",
               description="Instalación local y actualización explícita.")
    _comunes(p)
    sub = p.add_subparsers(dest="verbo", required=True, parser_class=Parser)
    v = sub.add_parser("empaquetar", help="Crear paquete desde una referencia Git explícita")
    _comunes(v)
    v.add_argument("--fuente", required=True)
    v.add_argument("--ref", required=True)
    v.add_argument("--salida", required=True, help="Directorio nuevo del paquete")
    v.add_argument("--modo", choices=["ubicable"], help="Empaquetar la entrada documental apta para un slot ubicable")
    v = sub.add_parser("planificar", help="Preparar un plan revisable sin modificar la instalación")
    _comunes(v)
    v.add_argument("--paquete", required=True)
    v.add_argument("--accion", choices=["instalar", "actualizar"], default="instalar")
    v.add_argument("--modo", choices=["estandar", "aislado", "ubicable"],
                   help="Modo inicial; ubicable lee gobernanza/rutas-kit.json")
    v.add_argument("--migrar-navegacion", action="store_true",
                   help="Autorizar el cambio de entradas históricas al incorporar la guía")
    v.add_argument("--reemplazar-anteriores", action="store_true",
                   help="Retirar sólo los slots anteriores íntegros en la misma transacción")
    v.add_argument("--activar-hook-solucion", action="store_true",
                   help="Incluir expresamente el hook de ediciones directas de solución de Codex")
    v.add_argument("--salida", required=True, help="Archivo JSON nuevo para el plan")
    v = sub.add_parser("aplicar", help="Revalidar y aplicar el plan explícito")
    _comunes(v)
    v.add_argument("--paquete", required=True)
    v.add_argument("--plan", required=True)
    v.add_argument("--guardados-codex", metavar="SESION",
                   help="Autorizar también reglas Codex locales para el worktree de ejecución")
    v = sub.add_parser("guardados-codex", help="Activar reglas locales en un nuevo worktree de sesión")
    _comunes(v)
    v.add_argument("--sesion", required=True)
    for verbo, ayuda in (("estado", "Consultar identidad, integridad y transacciones"),
                          ("recuperar", "Recuperar explícitamente la operación pendiente")):
        v = sub.add_parser(verbo, help=ayuda)
        _comunes(v)
    v = sub.add_parser("operar", help="Ejecutar el núcleo desde el administrador local",
                       description="Usa gestionar.py [--raiz RUTA] operar VERBO [OPCIONES].")
    v.add_argument("argumentos", nargs=argparse.REMAINDER,
                   help="contexto, validar, iniciar, verificar o cerrar con sus argumentos")
    v = sub.add_parser("hook-solucion", help="Entrada local al hook de solución de Codex")
    acciones = v.add_subparsers(dest="accion_hook", required=True)
    acciones.add_parser("ejecutar", help="Leer el evento Codex de stdin")
    return p


def _ruta(raiz, texto):
    ruta = Path(texto)
    return ruta if ruta.is_absolute() else raiz / ruta


def _guardar_plan(raiz, ruta, plan):
    # La publicación fue pedida con --salida; la API planificar sigue siendo lectura.
    absoluta, base = ruta.absolute(), raiz.absolute()
    try:
        relativa = absoluta.relative_to(base).as_posix()
        ancla = base.resolve()
    except ValueError:
        ancla = Path(absoluta.anchor)
        relativa = absoluta.relative_to(ancla).as_posix()
    contenido = (json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    _escribir_bytes(ancla, relativa, contenido, exclusivo=True)


def _despachar(args, base_instalacion):
    raiz = Path(getattr(args, "raiz", ".")).absolute()
    ubicacion = {"base_instalacion": base_instalacion} if base_instalacion is not None else {}
    if args.verbo == "empaquetar":
        modo = {"modo": args.modo} if args.modo is not None else {}
        return crear_paquete(_ruta(raiz, args.fuente), args.ref, _ruta(raiz, args.salida), **modo)
    if args.verbo == "planificar":
        modo = {"modo": args.modo} if args.modo is not None else {}
        migracion = {"migrar_navegacion": True} if args.migrar_navegacion else {}
        extensiones = {nombre: True for nombre in ("reemplazar_anteriores", "activar_hook_solucion")
                       if getattr(args, nombre)}
        salida = planificar(raiz, _ruta(raiz, args.paquete), accion=args.accion,
                            **modo, **ubicacion, **migracion, **extensiones)
        if salida["codigo"] == 0:
            destino = _ruta(raiz, args.salida)
            _guardar_plan(raiz, destino, salida["plan"])
            salida = dict(salida, ruta_plan=str(destino))
        return salida
    if args.verbo == "aplicar":
        datos = json_estricto(_ruta(raiz, args.plan).read_text(encoding="utf-8"))
        preparada = None
        if args.guardados_codex is not None:
            preparada = codex.preparar(raiz, args.guardados_codex)
        salida = aplicar(raiz, _ruta(raiz, args.paquete), datos, **ubicacion)
        if preparada is not None and salida["codigo"] == 0:
            try:
                if codex.preparar(raiz, args.guardados_codex) != preparada:
                    raise ValueError("La rama o el destino de las reglas cambió durante la operación.")
                salida["guardados_codex"] = codex.publicar(preparada)
            except (ValueError, OSError) as exc:
                salida.update(codigo=1, estado="invalido",
                              resumen="Kit aplicado. La activación local de Codex quedó pendiente.",
                              guardados_codex={"publicadas": False},
                              errores=[diagnostico("REGLAS_CODEX_PENDIENTES", "guardados-codex",
                                                   "Reglas locales publicadas", str(exc),
                                                   "Corrige la causa y ejecuta guardados-codex para esta sesión.")])
        return salida
    if args.verbo == "guardados-codex":
        reglas = codex.publicar(codex.preparar(raiz, args.sesion))
        return dict(resultado("guardados-codex"), guardados_codex=reglas,
                    resumen="Reglas locales publicadas. Reinicia Codex para cargarlas.")
    if args.verbo == "estado":
        return inspeccionar(raiz, **ubicacion)
    if args.verbo == "operar":
        return operar(raiz, args.argumentos, **ubicacion)
    if args.verbo == "hook-solucion":
        return dict(resultado("hook-solucion"), _evento_codex=True)
    return recuperar(raiz, **ubicacion)


def ejecutar(argv=None, *, base_instalacion=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        return _despachar(_parser().parse_args(argv), base_instalacion)
    except SystemExit as exc:
        if exc.code == 0:
            return dict(resultado("ayuda"), _ayuda=True)
        raise
    except UsoInvalido as exc:
        return resultado("distribucion", [diagnostico("USO_INVALIDO", "argumentos", "Opciones públicas válidas",
                         str(exc), "Consulta --help de la operación.")], codigo=2)
    except Exception as exc:
        return resultado("distribucion", [diagnostico("DISTRIBUCION_FALLIDA", "operacion", "Operación satisfecha",
                         str(exc) or type(exc).__name__, "Conserva el contenido y corrige la causa indicada antes de repetir.")])


def _identidad(etiqueta, datos):
    if isinstance(datos, dict):
        for campo in ("version", "fuente_commit", "huella_paquete"):
            if datos.get(campo):
                print(f"{etiqueta} · {campo}: {datos[campo]}")


def main(argv=None, *, base_instalacion=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    salida = ejecutar(argv, base_instalacion=base_instalacion)
    if salida.get("_ayuda"):
        return salida["codigo"]
    if salida.get("_evento_codex"):
        from .hook_solucion import ejecutar as ejecutar_hook

        return ejecutar_hook()
    if "--json" in argv:
        print(json.dumps(salida, ensure_ascii=False, allow_nan=False))
    else:
        print(f"{salida['operacion']}: {salida['estado']} (código {salida['codigo']})")
        print(salida["resumen"])
        _identidad("Versión", salida)
        for clave in ("manifiesto", "activo", "selector", "instalacion"):
            _identidad("Versión", salida.get(clave))
        if "recuperado" in salida:
            print("Recuperación:", "realizada" if salida["recuperado"] else "sin operación pendiente")
        if salida.get("transaccion_pendiente"):
            print("Recuperación pendiente: sí; conserva el diario y usa el administrador local.")
        if salida.get("modo"):
            print("Modo:", salida["modo"])
        if salida.get("base_instalacion"):
            print("Ubicación:", salida["base_instalacion"])
        plan = salida.get("plan")
        if isinstance(plan, dict):
            print("Acción:", plan.get("accion"))
            if plan.get("modo"):
                print("Modo:", plan["modo"])
            if plan.get("migracion_navegacion"):
                print("Transición de navegación: sí")
            if plan.get("antepone_arranque"):
                print("AGENTS.md: el bloque de arranque se publicará al inicio.")
            if plan.get("reemplazar_anteriores"):
                print("Slots anteriores para retirar:", ", ".join(sorted(plan["retirados"])))
            if plan.get("activar_hook_solucion"):
                print("Activación explícita del hook de solución de Codex: sí.")
            _identidad("Anterior", plan.get("anterior"))
            _identidad("Nueva", plan.get("nuevo"))
            print("Cambios:", json.dumps(plan.get("diff", []), ensure_ascii=False, indent=2))
            print("Destinos en el consumidor:", json.dumps(plan.get("destinos", {}), ensure_ascii=False, indent=2))
            print("Sin cambios:", plan.get("sin_cambios", False))
        reglas = salida.get("guardados_codex")
        if reglas and reglas["publicadas"]:
            print("Reglas locales de Codex:", reglas["archivo"])
            print("Reinicia Codex para cargarlas.")
        if salida.get("ruta_plan"):
            print("Plan guardado:", salida["ruta_plan"])
        if salida.get("ruta_informe"):
            print("Informe:", salida["ruta_informe"])
        for error in salida["errores"]:
            print(f"{error['codigo']} · {error['ruta']}: {error['mensaje']}")
            print(error["resolucion"])
    return salida["codigo"]
