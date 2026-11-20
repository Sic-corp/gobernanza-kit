# Gobernanza Kit

Kit local para mantener trazables los cambios que hacen personas y agentes en
un proyecto Git. Registra contratos, funcionalidades y sesiones con referencias
exactas. Comprueba permisos y evidencias en operaciones explícitas, y puede
reconstruir la traza de un cambio desde el historial del proyecto.

## Instalar o actualizar

Requiere Git, Python 3.10 o posterior y un entorno POSIX. Ejecuta desde la raíz
Git del proyecto consumidor. En Bash o Zsh, `pipefail` hace que el bloque
devuelva un error si falla `curl`.

```bash
(
  set -o pipefail
  curl -fsSL https://github.com/Sic-corp/gobernanza-kit/releases/latest/download/instalar.sh | sh -s -- instalar
)
```

En un shell POSIX, esta variante ejecuta el script después de que `curl`
termine correctamente.

```sh
kit=$(curl -fsSL https://github.com/Sic-corp/gobernanza-kit/releases/latest/download/instalar.sh) &&
  printf '%s\n' "$kit" | sh -s -- instalar
```

Para actualizar una instalación existente, conserva su modalidad.

```sh
./gobernanza-kit actualizar
```

Para una instalación anterior a la que introdujo el lanzador local, usa el
bootstrap con el verbo `actualizar`. En Bash o Zsh, usa este bloque. En la
variante POSIX, sustituye `instalar` por `actualizar`.

```bash
(
  set -o pipefail
  curl -fsSL https://github.com/Sic-corp/gobernanza-kit/releases/latest/download/instalar.sh | sh -s -- actualizar
)
```

El bootstrap descarga la versión indicada, coteja el SHA-256 del ZIP completo
y ejecuta el instalador autónomo. El comando planifica y aplica el cambio.
Usa `--solo-plan` para inspeccionar el plan, `--modo aislado` para reservar un
espacio Python propio, o `--modo ubicable` si el proyecto declara la raíz de
instalación en `gobernanza/rutas-kit.json`. El modo de instalación predeterminado
es estándar. El hook de edición de solución para Codex se activa sólo con
`--activar-hook-solucion`.

El [código del bootstrap](gobernanza/distribucion/recursos/instalar.sh) está en
el repositorio. Para inspeccionar el activo de una release concreta, descarga
su contenido en `kit` y muéstralo con `printf '%s\n' "$kit"` después de que la
descarga termine correctamente. Este ejemplo selecciona V3.02 desde la primera
descarga y sólo genera el plan.

```sh
kit=$(curl -fsSL https://github.com/Sic-corp/gobernanza-kit/releases/download/V3.02/instalar.sh) &&
  printf '%s\n' "$kit" | sh -s -- instalar --modo aislado --solo-plan
```

Para instalar sin una descarga en el proyecto, conserva el ZIP de la release
y usa `instalar.py` desde la carpeta extraída. El
[formato de distribución](docs/kit-local/FORMATO_DISTRIBUCION.md)
explica las operaciones, sus modos y recuperación.

## Usar el kit

El bloque gestionado de `AGENTS.md` identifica la modalidad y las instrucciones
instaladas. En un proyecto con registro SDD, el índice enlaza los contratos y
el kit puede abrir la sección exacta y reconstruir la traza de una sesión.
En modalidad estándar, usa la CLI de trabajo desde la raíz del proyecto.

```sh
python3 -m gobernanza sdd --help
python3 -m gobernanza sdd indice --json
```

Consulta el [modelo de trabajo](docs/kit-local/DISENO.md), el
[ejemplo de adopción](docs/kit-local/SESION_PILOTO.md) o el
[formato SDD](docs/kit-local/FORMATO_NUCLEO.md#registro-documental-sdd).

## Probar desde este repositorio

```sh
python3 -B -m unittest discover -s pruebas -p 'test_*.py' -v
```

Las pruebas públicas crean repositorios y documentos de ejemplo en directorios
temporales. Basta con el código, Git y la biblioteca estándar de Python.

Distribuido bajo [MIT](LICENSE).
