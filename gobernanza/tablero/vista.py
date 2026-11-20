"""Recursos del tablero, servidos localmente y sin dependencias externas."""

HTML = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tablero SDD</title>
  <link rel="stylesheet" href="/tablero.css">
  <script src="/tablero.js" defer></script>
</head>
<body>
<div id="gobernanza-tablero-sdd">
  <header class="sdd-header">
    <span class="sdd-project" data-project>Tablero SDD</span>
    <nav class="sdd-nav" aria-label="Vistas">
      <button type="button" data-view="specs">Especificaciones</button>
      <button type="button" data-view="ruta">Ruta de desarrollo</button>
    </nav>
  </header>
  <div class="sdd-capture" data-capture></div>
  <p class="sdd-note" data-status role="status" hidden></p>
  <main class="sdd-content" data-content><p>Leyendo el registro local…</p></main>
</div>
</body>
</html>
"""

CSS = """#gobernanza-tablero-sdd {
  color-scheme: light dark;
  --sdd-surface: light-dark(#fbfaf6, #191c18);
  --sdd-paper: light-dark(#fffefa, #20241f);
  --sdd-ink: light-dark(#252a23, #edeee6);
  --sdd-muted: light-dark(#525b50, #b8c1b4);
  --sdd-line: light-dark(#daddd0, #40483e);
  --sdd-hover: light-dark(#f0f2eb, #2a332a);
  --sdd-accent: light-dark(#2d624d, #a5dabf);
  --sdd-selected: light-dark(#e6eee4, #2a3e31);
  --sdd-draft: light-dark(#794925, #efc69e);
  --sdd-draft-bg: light-dark(#f4eadc, #3e3127);
  --sdd-mono: ui-monospace, Menlo, monospace;
  box-sizing: border-box;
  border: 1px solid var(--sdd-line);
  border-radius: 10px;
  font: 15px/1.45 system-ui, sans-serif;
  background: var(--sdd-surface);
  color: var(--sdd-ink);
}
#gobernanza-tablero-sdd *, #gobernanza-tablero-sdd *::before, #gobernanza-tablero-sdd *::after { box-sizing: inherit; }
#gobernanza-tablero-sdd :is(h1, h2, h3, p, ol, ul, dl, dd) { margin: 0; }
#gobernanza-tablero-sdd :is(button, summary) { font: inherit; color: inherit; }
#gobernanza-tablero-sdd button { border: 0; background: transparent; }
#gobernanza-tablero-sdd :focus-visible { outline: 2px solid var(--sdd-accent); outline-offset: 3px; }
#gobernanza-tablero-sdd h1 { font: 500 clamp(25px, 4vw, 35px)/1.16 Georgia, serif; letter-spacing: -.018em; overflow-wrap: anywhere; }
#gobernanza-tablero-sdd h2 { font-size: 19px; line-height: 1.3; font-weight: 620; }
#gobernanza-tablero-sdd h3 { font-size: 15px; font-weight: 640; }
#gobernanza-tablero-sdd code { font: 13px/1.45 var(--sdd-mono); overflow-wrap: anywhere; }
#gobernanza-tablero-sdd .sdd-header { display: flex; align-items: center; gap: 8px 22px; flex-wrap: wrap; padding: 8px clamp(12px, 4vw, 28px); border-bottom: 1px solid var(--sdd-line); }
#gobernanza-tablero-sdd .sdd-project { font-weight: 670; }
#gobernanza-tablero-sdd .sdd-nav { display: flex; flex-wrap: wrap; gap: 5px; }
#gobernanza-tablero-sdd .sdd-nav button { min-height: 36px; padding: 5px 10px; border-radius: 4px; font-size: 14px; text-align: start; }
#gobernanza-tablero-sdd .sdd-nav button[aria-current] { background: var(--sdd-selected); color: var(--sdd-accent); font-weight: 630; }
#gobernanza-tablero-sdd .sdd-content { padding: 19px clamp(12px, 4vw, 28px) 25px; }
#gobernanza-tablero-sdd .sdd-crumb { display: flex; flex-wrap: wrap; align-items: center; gap: 1px 7px; margin-bottom: 13px; font-size: 13px; color: var(--sdd-muted); }
#gobernanza-tablero-sdd .sdd-crumb button { min-height: 32px; padding: 3px 0; text-align: start; color: var(--sdd-accent); text-decoration: underline; text-underline-offset: 3px; }
#gobernanza-tablero-sdd .sdd-crumb span { overflow-wrap: anywhere; }
#gobernanza-tablero-sdd .sdd-meta { display: flex; flex-wrap: wrap; gap: 5px 9px; align-items: center; color: var(--sdd-muted); font-size: 13px; }
#gobernanza-tablero-sdd .sdd-title .sdd-meta { margin-top: 8px; }
#gobernanza-tablero-sdd .sdd-draft { width: fit-content; background: var(--sdd-draft-bg); color: var(--sdd-draft); border-radius: 4px; padding: 1px 7px; font-size: 13px; }
#gobernanza-tablero-sdd .sdd-list { list-style: none; margin: 15px 0 0; padding: 0; border-top: 1px solid var(--sdd-line); }
#gobernanza-tablero-sdd .sdd-list > li { border-bottom: 1px solid var(--sdd-line); }
#gobernanza-tablero-sdd .sdd-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 7px 12px; width: 100%; min-height: 54px; padding: 7px 10px; text-align: start; }
#gobernanza-tablero-sdd :is(.sdd-row, .sdd-nav button):hover { background: var(--sdd-hover); }
#gobernanza-tablero-sdd .sdd-row strong { display: block; overflow-wrap: anywhere; font-weight: 620; }
#gobernanza-tablero-sdd .sdd-row .sdd-chevron { font-size: 20px; color: var(--sdd-accent); line-height: 1; }
#gobernanza-tablero-sdd .sdd-module { margin-top: 22px; padding-top: 16px; border-top: 1px solid var(--sdd-line); }
#gobernanza-tablero-sdd .sdd-module .sdd-meta { margin-top: 4px; }
#gobernanza-tablero-sdd .sdd-module h3 { margin-top: 16px; }
#gobernanza-tablero-sdd .sdd-module .sdd-list { margin-top: 7px; }
#gobernanza-tablero-sdd .sdd-copy { margin-top: 10px; max-width: 70ch; overflow-wrap: anywhere; }
#gobernanza-tablero-sdd .sdd-citations { display: grid; gap: 4px; margin-top: 6px; padding-inline-start: 19px; }
#gobernanza-tablero-sdd .sdd-source { margin-top: 14px; color: var(--sdd-muted); font-size: 13px; }
#gobernanza-tablero-sdd .sdd-source summary { color: var(--sdd-accent); padding-block: 4px; }
#gobernanza-tablero-sdd .sdd-source p { padding: 5px 0 0 13px; }
#gobernanza-tablero-sdd .sdd-module-intro { padding: 0 10px 12px; max-width: 70ch; color: var(--sdd-muted); }
#gobernanza-tablero-sdd .sdd-cited { margin-block: 3px 8px; }
#gobernanza-tablero-sdd .sdd-cited .sdd-citations { padding-inline-start: 33px; }
#gobernanza-tablero-sdd .sdd-route-search { display: flex; gap: 7px; align-items: end; flex-wrap: wrap; max-width: 460px; margin-top: 13px; }
#gobernanza-tablero-sdd .sdd-route-search label { display: grid; flex: 1 1 190px; gap: 3px; min-width: 0; font-size: 13px; color: var(--sdd-muted); }
#gobernanza-tablero-sdd .sdd-route-search input, #gobernanza-tablero-sdd .sdd-route-search button { min-height: 42px; border: 1px solid var(--sdd-line); border-radius: 4px; }
#gobernanza-tablero-sdd .sdd-route-search input { width: 100%; min-width: 0; padding: 6px 8px; background: var(--sdd-paper); color: var(--sdd-ink); font: inherit; font-size: 16px; }
#gobernanza-tablero-sdd .sdd-route-search button { padding-inline: 11px; color: var(--sdd-accent); }
#gobernanza-tablero-sdd .sdd-route-search button:hover { background: var(--sdd-selected); }
#gobernanza-tablero-sdd .sdd-road { display: grid; grid-template-columns: minmax(0, .95fr) minmax(0, 1.05fr); gap: 16px 25px; margin-top: 17px; }
#gobernanza-tablero-sdd .sdd-road .sdd-list { margin-top: 8px; }
#gobernanza-tablero-sdd .sdd-road .sdd-row { min-height: 44px; }
#gobernanza-tablero-sdd .sdd-road .sdd-row[aria-pressed=true] { background: var(--sdd-selected); box-shadow: inset 3px 0 var(--sdd-accent); }
#gobernanza-tablero-sdd .sdd-objectives { list-style: none; padding: 0 0 4px 12px; }
#gobernanza-tablero-sdd .sdd-objectives .sdd-row strong { font-weight: 500; }
#gobernanza-tablero-sdd .sdd-next { margin-top: 13px; padding: 8px 12px; border-inline-start: 3px solid var(--sdd-accent); background: var(--sdd-selected); }
#gobernanza-tablero-sdd .sdd-next strong { display: block; font-size: 13px; color: var(--sdd-accent); }
#gobernanza-tablero-sdd .sdd-route-detail { min-width: 0; background: var(--sdd-paper); padding: 13px 15px; border: 1px solid var(--sdd-line); border-radius: 6px; }
#gobernanza-tablero-sdd .sdd-route-detail h3 { margin-top: 13px; }
#gobernanza-tablero-sdd .sdd-steps { padding-inline-start: 21px; margin-top: 6px; }
#gobernanza-tablero-sdd .sdd-steps li + li { margin-top: 8px; }
#gobernanza-tablero-sdd .sdd-status { display: block; color: var(--sdd-muted); font-size: 13px; }
@media (max-width: 610px) {
  #gobernanza-tablero-sdd .sdd-road { grid-template-columns: minmax(0, 1fr); }
}
@media (pointer: coarse) {
  #gobernanza-tablero-sdd :is(.sdd-crumb button, .sdd-nav button, .sdd-source summary, .sdd-route-search input, .sdd-route-search button) { min-height: 44px; }
}
#gobernanza-tablero-sdd .sdd-capture { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; padding: 4px clamp(12px, 4vw, 28px); color: var(--sdd-muted); border-bottom: 1px solid var(--sdd-line); font-size: 13px; }
#gobernanza-tablero-sdd .sdd-note { margin: 8px clamp(12px, 4vw, 28px) 0; color: var(--sdd-draft); overflow-wrap: anywhere; }
#gobernanza-tablero-sdd .sdd-links { margin: 6px 0 0; padding-inline-start: 20px; }
#gobernanza-tablero-sdd .sdd-links li { margin-bottom: 5px; overflow-wrap: anywhere; }
#gobernanza-tablero-sdd [hidden] { display: none !important; }
"""

JS = r"""
(() => {
  const root = document.querySelector('#gobernanza-tablero-sdd');
  const content = root.querySelector('[data-content]');
  const status = root.querySelector('[data-status]');
  const menus = [...root.querySelectorAll('[data-view]')];
  let catalog;
  let routeProjection;
  let routeRequest = 0;
  let refreshing = false;
  const state = { view: 'specs', spec: '', module: '', func: '', target: '', search: '' };
  const catalogFilters = new Map();

  function escape(value) {
    return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
  }

  function meta(record) {
    return `<span class="sdd-meta"><code>${escape(record.ref)}</code>
      <span${record.draft ? ' class="sdd-draft"' : ''}>${escape(record.draft ? 'Borrador' : record.estado)}</span></span>`;
  }

  function heading(title, record) {
    return `<div class="sdd-title"><h1 tabindex="-1">${escape(title)}</h1>${record ? meta(record) : ''}</div>`;
  }

  function row(title, secondary, attr, id, current) {
    return `<button type="button" class="sdd-row" ${attr}="${escape(id)}"${typeof current === 'boolean' ? ` aria-pressed="${current}"` : ''}>
      <span><strong>${escape(title)}</strong>${secondary}</span>
      <span class="sdd-chevron" aria-hidden="true">›</span></button>`;
  }

  function item(record, attr, id) {
    return row(record.title, meta(record), attr, id);
  }

  function source(path, references = [], note = '') {
    return `<details class="sdd-source"><summary>Ver fuente</summary>
      ${note ? `<p>${escape(note)}</p>` : ''}
      ${references.length ? `<ul class="sdd-citations">${references.map(ref => `<li><code>${escape(ref)}</code></li>`).join('')}</ul>` : ''}
      <p><code>${escape(path)}</code></p><p>Commit local <code>${escape(catalog.commit)}</code></p>
    </details>`;
  }

  function breadcrumbs(spec, module, func) {
    const crumb = (attribute, id, title) => `<button type="button" ${attribute}="${escape(id)}">${escape(title)}</button>`;
    const trail = [crumb('data-spec', '', 'Especificaciones')];
    if (module) trail.push(crumb('data-spec', state.spec, state.spec));
    if (func) trail.push(crumb('data-module', module.ref, module.title));
    trail.push(`<span aria-current="page">${escape((func || module || spec).title)}</span>`);
    return `<nav class="sdd-crumb" aria-label="Ubicación">${trail.join('<span aria-hidden="true">›</span>')}</nav>`;
  }

  function list(rows, empty) {
    return rows.length ? `<ul class="sdd-list">${rows.map(row => `<li>${row}</li>`).join('')}</ul>` : `<p class="sdd-copy">${empty}</p>`;
  }

  function catalogLevel() {
    return [state.spec, state.module].filter(Boolean).join('/');
  }

  function catalogMatches(row, query) {
    return [row.id, row.record?.ref, row.record?.title].some(value => value && normalize(value).includes(query));
  }

  function catalogRows() {
    const { specs, modules, functions } = catalog;
    const spec = specs[state.spec];
    const module = spec?.modules.includes(state.module) ? modules[state.module] : null;
    if (module) {
      return Object.entries(functions).filter(([, func]) => func.owner === module.ref)
        .map(([id, record]) => ({ id, record, attribute: 'data-function' }));
    }
    if (spec) return spec.modules.map(id => ({ id, record: modules[id], attribute: 'data-module' }));
    return Object.entries(specs).map(([id, record]) => ({ id, record, attribute: 'data-spec' }));
  }

  function filterResults(entries, value, empty) {
    const query = normalize(value);
    const matching = entries.filter(entry => catalogMatches(entry, query));
    return list(matching.map(({ id, record, attribute }) => {
      if (!record) return `<p class="sdd-module-intro">${escape(id)} · Ficha ausente.</p>`;
      const summary = attribute === 'data-module'
        ? `<p class="sdd-module-intro">${escape(record.description || 'Descripción aún por documentar.')}</p>` : '';
      return item(record, attribute, id) + summary;
    }), query ? 'Sin coincidencias.' : empty);
  }

  function catalogFilter(label, empty) {
    const entries = catalogRows();
    if (!entries.length) return list([], empty);
    const value = catalogFilters.get(catalogLevel()) || '';
    return `<div class="sdd-route-search sdd-catalog-search">
      <label>${label}
        <input type="search" data-catalog-filter maxlength="200" value="${escape(value)}" placeholder="ID o título">
      </label>
    </div>
    <div aria-live="polite" data-catalog-results>${filterResults(entries, value, empty)}</div>`;
  }

  function catalogue() {
    const {specs, modules, functions} = catalog;
    const spec = specs[state.spec];
    const module = spec?.modules.includes(state.module) ? modules[state.module] : null;
    const func = module && functions[state.func]?.owner === module.ref ? functions[state.func] : null;
    if (func) {
      const description = func.description || 'Explicación aún por documentar.';
      return breadcrumbs(spec, module, func) + heading(func.title, func)
        + description.split('\n').filter(Boolean).map(line => `<p class="sdd-copy">${escape(line)}</p>`).join('')
        + source(func.path, [...func.citations, ...func.dependencies],
                 func.historical ? 'Criterios registrados de esta revisión.' : 'Sección Explicación de la ficha.');
    }
    if (module) {
      return breadcrumbs(spec, module) + heading(module.title, module)
        + `<p class="sdd-copy">${escape(module.description || 'Descripción aún por documentar.')}</p>
          <section class="sdd-module"><h2>Funcionalidades del módulo</h2>
          ${catalogFilter('Buscar funcionalidades', 'Sin funcionalidades registradas.')}${source(module.path)}</section>`;
    }
    if (spec) {
      return breadcrumbs(spec) + heading(spec.title, spec)
        + `<section class="sdd-module"><h2>Módulos</h2>${catalogFilter('Buscar módulos', 'Sin módulos registrados.')}${source(spec.path)}</section>`;
    }
    return heading('Especificaciones') + catalogFilter('Buscar especificaciones', 'Sin especificaciones registradas.');
  }

  function destinos() {
    return catalog.ruta.metas.flatMap(meta => [meta, ...meta.objetivos]);
  }

  function normalize(value) {
    return value.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().trim();
  }

  function matches(value) {
    const query = normalize(value);
    if (!query) return [];
    const entries = destinos();
    const byId = entries.find(item => normalize(item.id) === query);
    if (byId) return [byId];
    const exact = entries.filter(item => normalize(item.titulo) === query);
    return exact.length ? exact : entries.filter(item => normalize(item.titulo).includes(query));
  }

  function routeRow(hito) {
    const subtitle = `<span class="sdd-meta"><code>${escape(hito.id)}</code><span>${escape(hito.estado)}</span></span>`;
    return row(hito.titulo, subtitle, 'data-target', hito.id, hito.id === state.target);
  }

  function visitable(field) {
    if (Array.isArray(field)) return field.map(visitable).filter(Boolean).join(' · ');
    return typeof field === 'string' ? field.replace(/\[([^\]]+)\]\(([^)]*)\)/g, '$1 ($2)').replaceAll('`', '') : '';
  }

  function sessions(target) {
    const unique = new Map([target, ...(target.objetivos || [])]
      .flatMap(hito => hito.sesiones || []).map(session => [session.ref, session]));
    if (!unique.size) return '';
    return `<h3>Sesiones vinculadas</h3><ul class="sdd-links">${[...unique.values()].map(session => `<li>
      <strong>${escape(session.titulo)}</strong>
      <span class="sdd-status"><code>${escape(session.ref)}</code> · Fase SDD ${escape(session.fase)}</span>
      ${[...session.funcionalidades, ...session.secciones, ...session.evidencias].map(ref => `<span class="sdd-status"><code>${escape(ref)}</code></span>`).join('')}
    </li>`).join('')}</ul>`;
  }

  function stepList(steps, title) {
    if (!steps.length) return '';
    return `<h3>${title}</h3><ol class="sdd-steps">${steps.map(step => `<li>${escape(step.titulo)}
      <span class="sdd-status">${escape(step.estado)}</span></li>`).join('')}</ol>`;
  }

  function routeDetail() {
    const target = destinos().find(entry => entry.id === state.target);
    if (!target) {
      if (!state.search) return `<p class="sdd-copy">${state.target
        ? 'El destino «' + escape(state.target) + '» ya no figura en la ruta.'
        : 'Elige una meta o un objetivo para ver su recorrido.'}</p>`;
      const candidates = matches(state.search);
      if (candidates.length) return list(candidates.map(routeRow), '');
      return `<p class="sdd-copy">No hay ruta registrada para «${escape(state.search)}».</p>`;
    }
    const steps = routeProjection?.recorrido || [];
    const done = steps.filter(entry => /^completad[oa]$/.test(normalize(entry.estado)));
    const open = steps.filter(entry => !/^completad[oa]$/.test(normalize(entry.estado)));
    const criterio = visitable(target.criterio);
    const evidencia = visitable(target.evidencia);
    const referencia = visitable(target.referencia);
    const completed = /^completad[oa]$/.test(normalize(target.estado));
    return `<p class="sdd-copy">${escape(target.titulo)}</p>
      ${completed ? '<p class="sdd-status">Ya alcanzado</p>' : '<p class="sdd-status">Resultado por comprobar</p>'}
      ${criterio ? `<h3>Criterio de logro</h3><p class="sdd-copy">${escape(criterio)}</p>` : (!completed ? '<p class="sdd-copy">Criterio de logro por documentar.</p>' : '')}
      ${referencia ? `<h3>Referencia de planificación</h3><p class="sdd-copy">${escape(referencia)}</p>` : ''}
      ${evidencia ? `<h3>Evidencia del hito</h3><p class="sdd-copy">${escape(evidencia)}</p>` : ''}
      ${stepList(done, 'Hitos cumplidos')}${stepList(open, 'Trabajo pendiente')}
      ${sessions(target)}`;
  }

  function route() {
    const hoja = catalog.ruta;
    if (hoja.error) return heading('Ruta de desarrollo') + `<p class="sdd-copy">${escape(hoja.error)}</p>${source(hoja.path)}`;
    const next = hoja.siguiente;
    const label = next ? (next.confirmar ? `Confirmar el resultado de la meta «${next.titulo}».` : next.titulo)
      + (/^bloquead[oa]$/.test(normalize(next.estado)) ? ' · Bloqueado' : '')
      : hoja.metas.length ? 'Ruta cubierta.' : 'Sin metas registradas.';
    return heading('Ruta de desarrollo') + `
      <p class="sdd-next"><strong>Siguiente hito</strong>${escape(label)}</p>
      <form class="sdd-route-search" role="search">
        <label>Ubicar meta u objetivo por ID o título
          <input type="search" name="destination" maxlength="200" value="${escape(state.search)}" placeholder="Ej. OBJ-02">
        </label>
        <button type="submit">Ubicar</button>
      </form>
      <div class="sdd-road">
        <section aria-labelledby="sdd-metas">
          <h2 id="sdd-metas">Metas</h2>
          ${list(hoja.metas.map(meta => routeRow(meta) + (meta.objetivos.length
            ? `<ol class="sdd-objectives">${meta.objetivos.map(obj => `<li>${routeRow(obj)}</li>`).join('')}</ol>` : '')),
            'Sin metas registradas.')}
        </section>
        <section class="sdd-route-detail" aria-labelledby="sdd-recorrido">
          <h2 id="sdd-recorrido" tabindex="-1">Recorrido</h2>
          <div data-route-detail>${routeDetail()}</div>
        </section>
      </div>${source(hoja.path)}`;
  }

  function show(focus) {
    for (const button of menus) {
      if (button.dataset.view === state.view) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    }
    content.innerHTML = state.view === 'ruta' ? route() : catalogue();
    if (focus) (content.querySelector(focus) || content.querySelector('h1'))?.focus();
  }

  function diagnose(message) {
    status.textContent = message;
    status.hidden = !message;
  }

  async function recorrido(focus = false) {
    const request = ++routeRequest;
    const commit = catalog.commit;
    const detail = content.querySelector('[data-route-detail]');
    if (!detail) return;
    routeProjection = null;
    try {
      if (destinos().some(hito => hito.id === state.target)) {
        const params = new URLSearchParams({ commit, destino: state.target });
        const response = await fetch('/api/ruta?' + params);
        if (response.status === 409) {
          void refresh();
          return;
        }
        if (!response.ok) throw new Error('No se pudo leer el recorrido.');
        const data = await response.json();
        if (request !== routeRequest || catalog.commit !== data.commit || !detail.isConnected) return;
        routeProjection = data;
      }
      detail.innerHTML = routeDetail();
      if (focus) content.querySelector('#sdd-recorrido').focus();
    } catch (error) {
      if (request === routeRequest) diagnose(error.message);
    }
  }

  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    try {
      const params = new URLSearchParams(catalog ? { desde: catalog.commit } : {});
      const response = await fetch('/api/captura?' + params);
      if (response.status === 204) {
        diagnose('');
        return;
      }
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo leer el registro.');
      const previous = catalog;
      const active = document.activeElement;
      const inputFocused = active?.name === 'destination';
      if (inputFocused) state.search = active.value;
      const anchor = ['spec', 'module', 'function', 'target'].find(key => active?.dataset?.[key] !== undefined);
      const focus = inputFocused ? 'input[name=destination]'
        : active?.matches?.('[data-catalog-filter]') ? '[data-catalog-filter]'
        : anchor ? `[data-${anchor}="${CSS.escape(active.dataset[anchor])}"]`
        : content.contains(active) ? 'h1' : null;
      catalog = data;
      routeProjection = null;
      if (!previous) state.target = data.ruta.siguiente?.id || '';
      root.querySelector('[data-project]').textContent = data.project;
      root.querySelector('[data-capture]').innerHTML = `<span>Commit guardado</span><code>${escape(data.commit)}</code>`;
      diagnose('');
      show(focus);
      if (state.view === 'ruta') void recorrido();
    } catch (error) {
      diagnose(error.message);
      if (!catalog) content.innerHTML = heading('Registro no disponible');
    } finally {
      refreshing = false;
    }
  }

  root.addEventListener('click', event => {
    if (!catalog) return;
    const button = event.target.closest('button');
    if (!button) return;
    const {view, spec, module, function: func, target} = button.dataset;
    if (view) {
      if (view === state.view && (view === 'ruta' || !state.spec)) return;
      state.view = view;
      if (view === 'specs') Object.assign(state, {spec: '', module: '', func: ''});
    } else if (spec !== undefined) Object.assign(state, {spec, module: '', func: ''});
    else if (module) Object.assign(state, {module, func: ''});
    else if (func) state.func = func;
    else if (target) {
      Object.assign(state, {target, search: ''});
      routeProjection = null;
    } else return;
    show(target ? '#sdd-recorrido' : 'h1');
    if (state.view === 'ruta') void recorrido();
  });

  root.addEventListener('input', event => {
    if (!event.target.matches('[data-catalog-filter]')) return;
    const value = event.target.value;
    catalogFilters.set(catalogLevel(), value);
    content.querySelector('[data-catalog-results]').innerHTML = filterResults(catalogRows(), value, '');
  });

  root.addEventListener('submit', event => {
    if (!event.target.matches('.sdd-route-search')) return;
    event.preventDefault();
    state.search = event.target.elements.destination.value.trim();
    const selection = matches(state.search);
    state.target = selection.length === 1 ? selection[0].id : '';
    routeProjection = null;
    show('#sdd-recorrido');
    void recorrido();
  });

  void refresh();
  setInterval(refresh, 2500);
})();
"""
