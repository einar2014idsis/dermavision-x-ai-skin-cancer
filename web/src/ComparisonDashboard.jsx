import { useRef, useState } from 'react'
import './ComparisonDashboard.css'

const date = value => value ? value.slice(0, 10).split('-').reverse().join('/') : '—'
const visitName = visit => visit ? visit.label + ' · ' + date(visit.captured_at) : '—'
const photo = (visit, kind = 'photo') => '/api/visits/' + visit.id + '/' + kind
const numeric = (value, unit = '', signed = false) => Number.isFinite(value)
  ? (signed && value > 0 ? '+' : '') + value.toLocaleString('es-PE', { maximumFractionDigits: 2 }) + unit : '—'
const indicators = [
  ['area', 'Variación de área aparente', ' %', true, 'scan'],
  ['asymmetry', 'Cambio de asimetría', '', true, 'compare'],
  ['border', 'Cambio de bordes', '', true, 'timeline'],
  ['color', 'Diferencia de color', ' ΔE', false, 'chart'],
]
const status = row => ({ comparable: 'Evaluable', outdated: 'Requiere revisión', visual: 'Requiere revisión', rejected: 'No evaluable' })[row?.technical?.kind] ?? 'Sin analizar'
const views = [['original', 'Fotografías'], ['slider', 'Antes y después'], ['contours', 'Contornos superpuestos'],
  ['map', 'Mapa de diferencias'], ['overlay', 'Superposición']]
const warning = 'Los resultados describen diferencias visuales experimentales. No constituyen un diagnóstico médico ni determinan por sí solos la progresión de una enfermedad.'

function Picture({ visit, title, quality }) {
  const [zoom, setZoom] = useState(1)
  const dialog = useRef(null)
  return <figure className="pair-photo">
    <figcaption><strong>{title} · {visitName(visit)}</strong><span>Calidad {quality?.accepted === true ? 'aceptada' : quality?.accepted === false ? 'por revisar' : 'sin verificar'}</span></figcaption>
    <div className={'pair-photo-frame' + (zoom === 1 ? ' fitted' : '')} tabIndex={zoom > 1 ? 0 : undefined}>
      <img src={photo(visit)} alt={'Fotografía ' + title.toLowerCase() + ' ' + visit.label} style={{ width: zoom * 100 + '%' }} />
    </div>
    <div className="pair-zoom" aria-label={'Zoom de ' + visit.label}>
      <button type="button" className="secondary" aria-label={'Reducir ' + visit.label} disabled={zoom <= 1} onClick={() => setZoom(z => z - .5)}>−</button>
      <output aria-label={'Aumento de ' + visit.label}>{Math.round(zoom * 100)} %</output>
      <button type="button" className="secondary" aria-label={'Ampliar ' + visit.label} disabled={zoom >= 3} onClick={() => setZoom(z => z + .5)}>+</button>
      <button type="button" className="secondary" aria-label={'Abrir foto ' + visit.label} onClick={() => dialog.current.showModal()}>⤢</button>
    </div>
    <dialog aria-label={'Fotografía ' + visit.label} className="pair-dialog" ref={dialog}><form method="dialog"><button className="secondary">Cerrar</button></form>
      <img src={photo(visit)} alt={visitName(visit)} loading="lazy" /></dialog>
  </figure>
}

function CheckedImage({ src, alt, ...props }) {
  const [failed, setFailed] = useState(false)
  return failed ? <p role="status">La imagen no está disponible. Revisa el resultado o vuelve a analizar el par.</p>
    : <img src={src} alt={alt} onError={() => setFailed(true)} {...props} />
}

function PairTools({ before, after, result, lesion, analyzeActivation }) {
  const [view, setView] = useState(result ? 'map' : 'original')
  const [reveal, setReveal] = useState(50)
  const [opacity, setOpacity] = useState(50)
  const [mapMode, setMapMode] = useState('map')
  const row = result
  const aligned = row?.technical.kind === 'comparable' && row.result.registration?.matrix
  const path = kind => '/api/lesions/' + lesion + '/pair-view/' + row.id + '/' + kind + (row.draft ? '?draft=true' : '')
  const artifact = after.metadata.classification?.explanation
  return <section className="panel pair-tools">
    <h2>Herramientas de visualización</h2>
    <div className="pair-tabs" role="group" aria-label="Vistas de comparación">
      {views.map(([key, title]) => <button key={key} className={view === key ? '' : 'secondary'}
        type="button" aria-pressed={view === key} onClick={() => setView(key)}>{title}</button>)}
    </div>
    {['slider', 'overlay'].includes(view) && (aligned ? <>
      <label>{view === 'slider' ? 'Revelar fotografía posterior' : 'Opacidad de la fotografía posterior'}
        <input type="range" min="0" max="100" value={view === 'slider' ? reveal : opacity}
          onChange={event => (view === 'slider' ? setReveal : setOpacity)(Number(event.target.value))} />
      </label>
      <div className="pair-layer">
        <CheckedImage src={path('previous')} alt={'Referencia alineada ' + before.label} />
        <CheckedImage src={path('current')} alt={'Fotografía alineada ' + after.label} style={view === 'slider'
          ? { clipPath: 'inset(0 ' + (100 - reveal) + '% 0 0)' } : { opacity: opacity / 100 }} />
        {view === 'slider' && <span aria-hidden="true" className="pair-split" style={{ left: reveal + '%' }} />}
      </div>
    </> : <p>Esta vista requiere una alineación aceptada.</p>)}
    {view === 'contours' && (aligned ? <figure>
      <CheckedImage src={path('contours')} alt="Los dos contornos revisados en la misma referencia espacial" />
      <figcaption><span className="pair-key green" /> Inicial · <span className="pair-key red" /> Posterior</figcaption>
    </figure> : <p>Los contornos superpuestos requieren una alineación aceptada.</p>)}
    {view === 'map' && <div className="pair-tool-grid">
      <div><h3>{row?.technical.kind === 'visual' ? 'Siluetas normalizadas' : 'Mapa de diferencias temporales'}</h3>
        {aligned && <label>Mostrar<select value={mapMode} onChange={event => setMapMode(event.target.value)}>
          <option value="map">Diferencias locales de color</option><option value="area">Cambios de área aparente</option>
          <option value="texture">Diferencias locales de textura</option>
        </select></label>}
        {row?.map_available ? <figure><CheckedImage key={mapMode} src={path(aligned ? mapMode : 'map')} alt="Diferencias visuales del par seleccionado" />
          <figcaption>{row.technical.kind === 'visual'
            ? 'Cian: solo inicial. Naranja: solo posterior. Gris: región común. Vista sin medición temporal.'
            : mapMode === 'area' ? 'Rojo: región marcada solo en la foto posterior. Azul: región marcada solo en la inicial.'
            : mapMode === 'texture' ? 'Los tonos cálidos indican mayor diferencia de textura local en la región común (distancia de histogramas LBP, 0–1).'
            : 'Cian: contorno inicial. Naranja: contorno posterior. Los tonos cálidos indican mayor diferencia local de color.'}</figcaption>
        </figure> : <p>Mapa no disponible para este resultado.</p>}
      </div>
      <div><h3>Mapa de activación · {after.label}</h3>
        {artifact ? <figure><CheckedImage key={artifact.sha256} src={photo(after, 'influence') + '?v=' + encodeURIComponent(artifact.sha256)} alt={'Influencia por oclusión de ' + after.label} />
          <figcaption>Influencia por oclusión en la clasificación de esta fotografía.</figcaption></figure>
          : <><p>Esta visita aún no tiene un mapa de activación disponible.</p>
            <button className="secondary" type="button" onClick={analyzeActivation}>Analizar la fotografía posterior</button></>}
      </div>
    </div>}
    <details><summary>Ver contornos originales</summary><div className="pair-tool-grid">
      {[before, after].map(visit => <figure key={visit.id}><CheckedImage src={photo(visit, 'contour')} alt={'Contorno original de ' + visit.label} />
        <figcaption>{visitName(visit)}</figcaption></figure>)}
    </div></details>
  </section>
}

export default function ComparisonDashboard({ lesion, visits, comparisons, initialPair, initialSaved, api, refresh, filters, navigate, Icon, personId }) {
  const [ids, setIds] = useState(() => initialPair.length === 2 ? initialPair.map(visit => visit.id) : visits.slice(0, 2).map(visit => visit.id))
  const [mode, setMode] = useState('longitudinal')
  const [draft, setDraft] = useState(null)
  const [saved, setSaved] = useState(initialSaved || '')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [savedRow, setSavedRow] = useState(null)
  const [historyPage, setHistoryPage] = useState(0)
  const historySize = 6
  const pageCount = Math.max(1, Math.ceil(comparisons.length / historySize))
  const currentHistoryPage = Math.min(historyPage, pageCount - 1)
  const historyRows = [...comparisons].reverse().slice(currentHistoryPage * historySize, (currentHistoryPage + 1) * historySize)
  const before = visits.find(visit => visit.id === ids[0])
  const after = visits.find(visit => visit.id === ids[1])
  const pair = before && after
  const ordered = pair && after.captured_at > before.captured_at
  const row = draft || comparisons.find(item => item.id === saved) || savedRow
  const result = row?.result
  const changes = row?.technical.kind === 'comparable' ? result.changes : {}
  const days = pair ? (new Date(after.captured_at + 'Z') - new Date(before.captured_at + 'Z')) / 86400000 : null
  const interval = Number.isFinite(days) && days > 0 ? numeric(days, ' días') : '—'
  const visitMap = new Map(visits.map(visit => [visit.id, visit]))

  function choose(index, value) {
    setIds(ids.map((id, i) => i === index ? value : id))
    setDraft(null); setSaved(''); setSavedRow(null); setError(''); setNotice('')
  }
  async function run(label, action) {
    setBusy(label); setError(''); setNotice('')
    try { await action() } catch (failure) { setError(failure.message) } finally { setBusy('') }
  }
  async function analyze() {
    const value = await api('/lesions/' + lesion + '/comparison-previews', {
      method: 'POST', data: { previous: ids[0], current: ids[1], mode },
    })
    setSaved(''); setSavedRow(null); setDraft(value)
  }
  async function save() {
    const { id } = await api('/lesions/' + lesion + '/comparison-previews/' + draft.id + '/save', { method: 'POST' })
    setSavedRow({ ...draft, id, draft: false }); setDraft(null); setSaved(id)
    setNotice('Comparación guardada.'); refresh()
  }
  async function download(comparison, extension) {
    const file = await api('/lesions/' + lesion + '/comparisons/' + comparison.id + '/export/' + extension)
    const url = URL.createObjectURL(file)
    const link = document.createElement('a')
    link.href = url
    link.download = 'comparacion-' + comparison.id.slice(0, 8) + '.' + extension
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  function open(item) {
    setIds([item.previous_id, item.current_id])
    setDraft(null); setSavedRow(null); setSaved(item.id); setNotice(''); setError('')
    setMode(item.result.requested_mode || item.result.mode || 'longitudinal')
  }

  return <div className="comparison-dashboard">
    <section className="panel pair-select">
      <h2>Selección de fotografías</h2>
      <form onSubmit={event => { event.preventDefault(); if (ordered && !busy) run('Analizando diferencias…', analyze) }}>
        {filters}
        {['Fotografía inicial', 'Fotografía posterior'].map((label, index) => <label key={label}>{label}
          <select required value={ids[index] || ''} onChange={event => choose(index, event.target.value)} disabled={!visits.length || Boolean(busy)}>
            <option value="">Seleccionar fotografía</option>
            {visits.map(visit => <option key={visit.id} value={visit.id}>{visitName(visit)}</option>)}
          </select></label>)}
        <button type="submit" disabled={!ordered || Boolean(busy)}><Icon name="scan" size={17} /> Analizar diferencias</button>
      </form>
      {visits.length >= 2 && <label className="pair-mode">Tipo de comparación
        <select value={mode} disabled={Boolean(busy)} onChange={event => setMode(event.target.value)}>
          <option value="longitudinal">Seguimiento temporal</option><option value="visual">Solo visual</option>
        </select></label>}
      {pair && !ordered && <p role="status">La fotografía posterior debe tener una fecha de captura posterior a la inicial.</p>}
      {lesion && visits.length < 2 && <p>Registra dos fotografías de esta lesión para compararlas.</p>}
      {busy && <p role="status">{busy}</p>}{notice && <p role="status">{notice}</p>}{error && <p className="error" role="alert">{error}</p>}
    </section>
    {!pair && <div className="panel module-empty"><Icon name="compare" size={40} /><h2>Selecciona dos fotografías de la misma lesión</h2>
      <p>Elige una persona, su lesión y dos visitas en orden cronológico para calcular las diferencias visuales disponibles.</p></div>}
    {pair && <>
      <section className="panel pair-visual">
        <h2>Comparación visual</h2>
        <div className="pair-photos">
          <Picture key={'a-' + before.id} visit={before} title="Fotografía inicial" quality={result?.capture_quality?.[0]} />
          <Picture key={'b-' + after.id} visit={after} title="Fotografía posterior" quality={result?.capture_quality?.[1]} />
        </div>
        <div className="pair-badges">
          <span>Intervalo: <strong>{interval}</strong></span>
          <span>Calidad: <strong>{result?.capture_quality?.length === 2 && result.capture_quality.every(item => item.accepted) ? 'Aceptada' : result?.capture_quality?.some(item => !item.accepted) ? 'Requiere revisión' : 'Sin verificar para el par'}</strong></span>
          <span title="El sistema comprueba la ficha de la lesión. La identidad visual requiere confirmación del usuario.">Identidad: <strong>{after.metadata.lesion_identity?.status === 'user_declared' ? 'Declarada por el usuario' : 'Misma ficha'}</strong></span>
          <span>Contornos: <strong>{before.metadata.mask_reviewed && after.metadata.mask_reviewed ? 'Revisados' : 'Pendientes'}</strong></span>
          <span>Alineación: <strong>{row?.technical.kind === 'comparable' ? 'Aceptada' : result?.registration ? 'Revisar' : 'Sin verificar'}</strong></span>
        </div>
      </section>
      <PairTools key={row?.id || ids.join(':')} before={before} after={after} result={row} lesion={lesion}
        analyzeActivation={() => !busy && run('Analizando la fotografía posterior…', async () => {
          const classification = await api('/visits/' + after.id + '/analyze', { method: 'POST' })
          refresh()
          if (row && ordered) await analyze()
          if (!classification.explanation) setNotice('La fotografía no produjo un mapa de activación. Revisa su clasificación y calidad en Seguimiento.')
        })} />
      <section className="panel pair-highlights" aria-label="Indicadores de la comparación">
        <div className="pair-metrics">{indicators.map(([key, label, unit, signed, icon]) => <div key={key}>
          <Icon name={icon} size={21} /><strong>{numeric(changes?.[key], unit, signed)}</strong><span>{label}</span>
        </div>)}</div>
      </section>
      <section className="panel pair-results">
        <h2>Mediciones detalladas</h2>
        {row?.measurements.length ? <div className="pair-table">
          {row.technical.kind === 'visual' && <p>Descriptores de las regiones marcadas. La variación de área temporal queda sin medir.</p>}
          <table><thead><tr><th>Indicador</th><th>{visitName(before)}</th><th>{visitName(after)}</th><th>Diferencia</th></tr></thead>
            <tbody>{row.measurements.map(([name, a, b, value, note]) => <tr key={name}><th scope="row">{name}<small>{note}</small></th><td>{a}</td><td>{b}</td><td>{value}</td></tr>)}</tbody></table>
        </div> : <p>{row?.technical.reason || 'Analiza el par para ver las mediciones.'}</p>}
      </section>
      <section className="panel pair-summary">
        <h2><Icon name="report" size={20} /> Resumen de la comparación</h2>
        <p>{visitName(before)} → {visitName(after)} {ordered && '(' + interval + ')'}</p>
        <span className={'pair-state ' + (row?.technical.kind || '')}>{status(row)}</span>
        {row && <p>{row.description}</p>}
        {row?.technical.kind === 'comparable' && <dl>{indicators.map(([key, label, unit, signed]) => Number.isFinite(changes[key]) &&
          <div key={key}><dt>{label}</dt><dd>{numeric(changes[key], unit, signed)}</dd></div>)}
          {Number.isFinite(changes.texture) && <div><dt>Diferencia de textura (0–1)</dt><dd>{numeric(changes.texture)}</dd></div>}
        </dl>}
        <aside>{warning}</aside>
      </section>
    </>}
    {lesion && <section className="panel pair-history">
      <h2>Comparaciones guardadas</h2>
      {comparisons.length ? <div className="pair-table"><table>
        <thead><tr><th>Código</th><th>Inicial</th><th>Posterior</th><th>Fecha de análisis</th><th>Estado</th><th>Acciones</th></tr></thead>
        <tbody>{historyRows.map(item => <tr key={item.id} aria-selected={item.id === saved}>
          <td title={item.id}>{item.id.slice(0, 8)}</td><td>{visitName(visitMap.get(item.previous_id))}</td><td>{visitName(visitMap.get(item.current_id))}</td>
          <td>{date(item.created)}</td><td><span className={'pair-state ' + item.technical.kind}>{status(item)}</span></td>
          <td><details className="pair-row-menu"><summary>Acciones<span className="sr-only"> de {item.id.slice(0, 8)}</span></summary>
            <div className="pair-actions"><button type="button" className="secondary" disabled={Boolean(busy)} onClick={() => open(item)}>Ver detalles</button>
            <button type="button" className="secondary" disabled={Boolean(busy)} onClick={() => run('Generando PDF…', () => download(item, 'pdf'))}>Generar informe</button></div></details></td>
        </tr>)}</tbody></table></div> : <p>Aún no hay comparaciones guardadas para esta lesión.</p>}
      {pageCount > 1 && <div className="pair-pagination" aria-label="Paginación del historial">
        <button type="button" className="secondary" disabled={!currentHistoryPage} onClick={() => setHistoryPage(currentHistoryPage - 1)}>Anterior</button>
        <span aria-live="polite">Página {currentHistoryPage + 1} de {pageCount}</span>
        <button type="button" className="secondary" disabled={currentHistoryPage + 1 >= pageCount} onClick={() => setHistoryPage(currentHistoryPage + 1)}>Siguiente</button>
      </div>}
    </section>}
    <section className="panel pair-footer">
      <h2>Acciones</h2>
      <div className="pair-actions">
        <button type="button" disabled={!draft || Boolean(busy)} onClick={() => run('Guardando…', save)}>Guardar comparación</button>
        <button type="button" className="secondary" disabled={!row || Boolean(draft || busy)} onClick={() => run('Generando PDF…', () => download(row, 'pdf'))}>Generar informe (PDF)</button>
        {row && !draft && personId && <button type="button" className="secondary"
          onClick={() => navigate('reports/' + personId + '/' + lesion + '/' + row.id)}>Abrir en Informes</button>}
        <button type="button" className="secondary" disabled={!row || Boolean(draft || busy)} onClick={() => run('Exportando CSV…', () => download(row, 'csv'))}>Exportar datos (CSV)</button>
        <button type="button" className="secondary" onClick={() => navigate(personId && lesion ? 'followup/' + personId + '/' + lesion : 'followup')}>← Volver a Seguimiento</button>
      </div>
      {draft && <small>Guarda este análisis para exportar sus resultados.</small>}
      {busy && <p role="status">{busy}</p>}{notice && <p role="status">{notice}</p>}{error && <p className="error" role="alert">{error}</p>}
    </section>
  </div>
}
