"""Entrada autónoma del entregable local. Ejecutar con python3 -I instalar.py --help."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

IDENTIDAD = None  # Sustituida al construir la entrega.
GUIA_RELEVO = Path("navegar-gobernanza/references/fases.md")


def comprobar(directorio, nombre):
    """Comprueba el inventario fijado en esta entrada antes de importar el runtime."""
    paquete = directorio / nombre
    manifiesto = paquete / "manifiesto.json"
    if paquete.is_symlink() or manifiesto.is_symlink() or not manifiesto.is_file():
        raise ValueError(f"Falta el paquete regular {nombre}.")
    bruto = manifiesto.read_bytes()
    pin = IDENTIDAD["paquetes"][nombre]
    if hashlib.sha256(bruto).hexdigest() != pin["sha256"]:
        raise ValueError(f"Manifiesto alterado en {nombre}.")
    datos = json.loads(bruto)
    if datos["fuente_commit"] != IDENTIDAD["commit"] or datos["huella_paquete"] != pin["huella"]:
        raise ValueError(f"Identidad distinta en {nombre}.")
    pendientes = set(datos["archivos"])
    for actual, directorios, archivos in os.walk(paquete):
        for entrada in directorios:
            if (Path(actual) / entrada).is_symlink():
                raise ValueError(f"Directorio enlazado en {actual}/{entrada}.")
        for entrada in archivos:
            ruta = Path(actual) / entrada
            if ruta == manifiesto:
                continue
            relativa = ruta.relative_to(paquete).as_posix()
            modo = ruta.lstat().st_mode
            if not stat.S_ISREG(modo) or relativa not in pendientes:
                raise ValueError(f"Archivo ajeno o enlazado: {relativa}")
            pendientes.remove(relativa)
            meta = datos["archivos"][relativa]
            if (("100755" if modo & 0o111 else "100644") != meta["modo"] or
                    hashlib.sha256(ruta.read_bytes()).hexdigest() != meta["sha256"]):
                raise ValueError(f"Contenido o modo modificado: {relativa}")
    if pendientes:
        raise ValueError(f"Falta {min(pendientes)} en {nombre}.")
    return paquete


def argumentos():
    p = argparse.ArgumentParser(description="Planificar, aplicar o recuperar esta versión del kit.")
    p.add_argument("--raiz", default=Path.cwd(), type=Path, help="Checkout del consumidor (directorio actual por defecto)")
    p.add_argument("--json", action="store_true")
    verbos = p.add_subparsers(dest="verbo", required=True)
    plan = verbos.add_parser("planificar")
    plan.add_argument("--accion", choices=("instalar", "actualizar"), required=True)
    plan.add_argument("--modo", choices=("estandar", "aislado", "ubicable"))
    plan.add_argument("--salida", required=True)
    plan.add_argument("--activar-hook-solucion", action="store_true")
    aplicar = verbos.add_parser("aplicar")
    aplicar.add_argument("--plan", required=True)
    estado = verbos.add_parser("estado")
    recuperar = verbos.add_parser("recuperar")
    directos = [verbos.add_parser(verbo) for verbo in ("instalar", "actualizar")]
    for sub in directos:
        sub.add_argument("--modo", choices=("estandar", "aislado", "ubicable"))
        sub.add_argument("--solo-plan", action="store_true", help="Muestra el plan sin aplicar cambios")
        sub.add_argument("--activar-hook-solucion", action="store_true")
    for sub in (plan, aplicar, estado, recuperar, *directos):
        sub.add_argument("--raiz", type=Path, default=argparse.SUPPRESS)
        sub.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    return p.parse_args()


def presentar(resultado, formato_json):
    if formato_json:
        print(json.dumps(resultado, ensure_ascii=False, allow_nan=False))
    else:
        print(f"{resultado['operacion']}: {resultado['estado']} (código {resultado['codigo']})")
        print(resultado["resumen"])
        if resultado.get("plan") is not None:
            print(json.dumps(resultado["plan"], ensure_ascii=False, indent=2, allow_nan=False))
        activo = resultado.get("activo")
        if isinstance(activo, dict):
            etiqueta = IDENTIDAD.get("version")
            version = f"{etiqueta} · " if etiqueta else ""
            print(f"Versión instalada: {version}{activo['fuente_commit']} · {activo['huella_paquete']}")
        for error in resultado["errores"]:
            print(f"{error['codigo']} · {error['mensaje']}", file=sys.stderr)
    return resultado["codigo"]


def preparar_relevo(paquete, raiz, base):
    guia = paquete / "contenido/skill" / GUIA_RELEVO
    if not guia.is_file():
        return None
    inicio = "<!-- gobernanza:relevo:inicio -->\n"
    inicio_codigo = "```text\n"
    fin = "\n```\n<!-- gobernanza:relevo:fin -->"
    _, delimitador, seccion = guia.read_text(encoding="utf-8").partition(inicio)
    if not delimitador:
        return None
    texto, delimitador, _ = seccion.removeprefix(inicio_codigo).partition(fin)
    if not seccion.startswith(inicio_codigo) or not delimitador or not texto.strip():
        raise ValueError("El bloque de relevo de la guía instalada está incompleto.")
    ruta = raiz / base / "skills" / GUIA_RELEVO
    version = IDENTIDAD["version"] or IDENTIDAD["commit"]
    return (f"\nGuía instalada: {json.dumps(str(ruta), ensure_ascii=False)}#relevo-para-el-agente\n"
            "\nPrompt de relevo para tu agente\n\n"
            f"El kit de gobernanza {version} ya está instalado.\n"
            f"Raíz Git del consumidor: {json.dumps(str(raiz), ensure_ascii=False)}\n\n"
            + texto)


def presentar_relevo(codigo, texto, formato_json):
    if codigo == 0 and texto is not None and not formato_json:
        print(texto)
    return codigo


def ejecutar(args):
    if not sys.flags.isolated:
        raise ValueError("Ejecuta el instalador con python3 -I.")
    sys.dont_write_bytecode = True
    directorio = Path(__file__).resolve().parent
    if IDENTIDAD != json.loads((directorio / "entrega.json").read_bytes()):
        raise ValueError("La identidad de entrega.json difiere del instalador.")
    paquetes = {nombre: comprobar(directorio, nombre) for nombre in IDENTIDAD["paquetes"]}
    sys.path.insert(0, str(paquetes["paquete"] / "contenido"))
    from gobernanza.distribucion import cli, gestor
    from gobernanza.distribucion.paquete import NAVEGACION

    raiz = args.raiz.resolve(strict=True)
    ubicacion = gestor._CLASICA
    modo = getattr(args, "modo", None)
    if args.verbo == "aplicar":
        plan = json.loads((raiz / args.plan).read_bytes())
        if not isinstance(plan, dict):
            raise ValueError("El plan revisado debe ser un objeto JSON.")
        modo = plan.get("modo", "estandar")
    if modo == "ubicable":
        ubicacion, _ = gestor._mapa_ubicable(raiz)
    elif (modo is None and not os.path.lexists(raiz / gestor.DIARIO_UBICABLE)
          and not os.path.lexists(raiz / gestor.DIARIO)
          and not os.path.lexists(raiz / gestor._CLASICA.activo)
          and os.path.lexists(raiz / gestor.MAPA_UBICABLE)):
        mapeada, _ = gestor._mapa_ubicable(raiz)
        if os.path.lexists(raiz / mapeada.activo):
            ubicacion = mapeada
    paquete = paquetes["paquete-ubicable" if ubicacion.ubicable else "paquete"]
    base = ubicacion.base if ubicacion.ubicable else None
    argv = ["--raiz", str(raiz), args.verbo]
    directo = args.verbo in ("instalar", "actualizar")
    relevo = None
    if directo or args.verbo == "planificar":
        accion = args.verbo if directo else args.accion
        migrar = False
        if accion == "actualizar":
            _, slot, _, _ = gestor._estado(raiz, ubicacion)
            migrar = bool(slot and not (slot / NAVEGACION[0]).exists() and (paquete / NAVEGACION[0]).is_file())
        cambios = dict(activar_hook_solucion=args.activar_hook_solucion,
                       reemplazar_anteriores=accion == "actualizar", migrar_navegacion=migrar)
        if directo:
            salida = gestor.planificar(raiz, paquete, accion=accion, modo=modo, base_instalacion=base, **cambios)
            if salida["codigo"] == 0 and not args.solo_plan:
                relevo = preparar_relevo(paquete, raiz, ubicacion.base)
                salida = gestor.aplicar(raiz, paquete, salida["plan"], base_instalacion=base)
            return presentar_relevo(presentar(salida, args.json), relevo, args.json)
        argv += ["--paquete", str(paquete), "--accion", accion, "--salida", args.salida]
        if modo:
            argv += ["--modo", modo]
        argv.extend("--" + nombre.replace("_", "-") for nombre, activo in cambios.items() if activo)
    elif args.verbo == "aplicar":
        argv += ["--paquete", str(paquete), "--plan", args.plan]
        relevo = preparar_relevo(paquete, raiz, ubicacion.base)
    if args.json:
        argv.append("--json")
    return presentar_relevo(cli.main(argv, base_instalacion=base), relevo, args.json)


if __name__ == "__main__":
    opciones = argumentos()
    try:
        sys.exit(ejecutar(opciones))
    except (OSError, TypeError, ValueError, KeyError) as exc:
        if opciones.json:
            print(json.dumps(dict(codigo=1, errores=[dict(mensaje=str(exc))]), ensure_ascii=False))
        else:
            print(str(exc), file=sys.stderr)
        sys.exit(1)
