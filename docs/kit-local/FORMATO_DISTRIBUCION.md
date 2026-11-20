# Distribución e instalación local

El kit requiere POSIX, Git y Python 3.10 o posterior. La instalación pertenece
al repositorio consumidor y su modalidad queda registrada en `AGENTS.md`.
Los comandos de descarga son explícitos y la instalación sigue siendo local.

## Bootstrap de una release

Ejecuta el bootstrap desde la raíz Git del consumidor. En Bash o Zsh,
`pipefail` hace que el bloque devuelva un error si falla `curl`.

```bash
(
  set -o pipefail
  curl -fsSL https://github.com/Sic-corp/gobernanza-kit/releases/latest/download/instalar.sh | sh -s -- instalar
)
```

En un shell POSIX, descarga el script completo y ejecútalo después de que
`curl` termine correctamente.

```sh
kit=$(curl -fsSL https://github.com/Sic-corp/gobernanza-kit/releases/latest/download/instalar.sh) &&
  printf '%s\n' "$kit" | sh -s -- instalar
```

Para una instalación existente, usa el verbo `actualizar` en el comando
correspondiente. Usa `--raiz R` para actuar sobre otra raíz Git.
`--version V3.02` selecciona una release y `--solo-plan` permite inspeccionar
el cambio antes de aplicar.
El bootstrap contrasta la huella del ZIP completo y usa el instalador que
contiene. Para conectar la huella con una publicación concreta, revisa
`manifiesto.json`. Allí constan la V, el SHA del commit público y el SHA-256 de
los activos.

El lanzador instalado en la raíz del proyecto admite `./gobernanza-kit actualizar`
sin localizar a mano el slot activo. Usa `./gobernanza-kit actualizar --help`
para consultar sus opciones y la guía instalada para la CLI de trabajo.

## Artefacto autónomo de entrega

Tras extraer el ZIP, conserva juntos el lanzador `instalar.py`, `entrega.json`
y las carpetas de paquete. Selecciona el mismo modo del consumidor durante
una actualización. El modo ubicable requiere que el consumidor declare su
raíz en `gobernanza/rutas-kit.json`.

```sh
python3 -I instalar.py --raiz R planificar --accion instalar --modo aislado --salida PLAN.json
python3 -I instalar.py --raiz R aplicar --plan PLAN.json
python3 -I instalar.py --raiz R estado --json
```

En una instalación existente selecciona `--accion actualizar`. Revisa el plan
antes de aplicar. Para activar el hook de solución para Codex, añade
`--activar-hook-solucion` al plan de la operación. El host necesita cargar
la configuración del hook para aplicar sus reglas.

## Modalidades

- Estándar. Usa un espacio Python conocido dentro del consumidor y la entrada
  `python3 -m gobernanza` desde su raíz Git.
- Aislada. Usa la entrada `python3 -I .gobernanza-kit/gestionar.py operar` y
  mantiene su runtime separado del Python del proyecto.
- Ubicable. Usa un directorio asignado por el consumidor y la entrada
  `python3 -I RUTA/gestionar.py operar`. Declara la ruta en
  `gobernanza/rutas-kit.json` antes de planear.

```json
{"schema":1,"rutas":{"instalacion":"local/kit"}}
```

## Actualización, diario y recuperación

La actualización reemplaza las rutas gestionadas. El plan muestra fuentes,
huellas, modalidad y destinos. La transacción coteja las imágenes anteriores
y nuevas y preserva archivos, contratos, sesiones e instrucciones del consumidor.
Tras completar el cambio queda activo el slot de la nueva versión.

Si se interrumpe una operación, conserva el artefacto que la inició y usa su
lanzador para recuperar. El diario identifica los destinos y las imágenes
necesarias. Consulta el estado después de recuperar.

```sh
python3 -I instalar.py --raiz R recuperar --json
python3 -I instalar.py --raiz R estado --json
```
