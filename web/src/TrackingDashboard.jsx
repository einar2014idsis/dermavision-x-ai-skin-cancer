import { useEffect, useRef, useState } from 'react'
import './TrackingDashboard.css'

const indicators = [
  ['index', 'Índice de cambio visual', '/ 100', 1],
  ['area', 'Área aparente', '%', 1],
  ['asymmetry', 'Asimetría', 'Δ indicador', 3],
  ['border', 'Irregularidad de bordes', 'Δ indicador', 3],
  ['color', 'Diferencia de color', 'ΔE', 2],
  ['texture', 'Textura', 'distancia 0–1', 3],
]
const dates = new Intl.DateTimeFormat('es-PE', { day: '2-digit', month: '2-digit', year: 'numeric' })
const date = value => value ? dates.format(new Date(value)) : 'No registrado'
const number = (value, digits = 1) => new Intl.NumberFormat('es-PE', { maximumFractionDigits: digits }).format(value)
const photo = row => '/api/visits/' + row.id + '/photo'
const classification = row => {
  const value = row.metadata.classification
  return value?.state === 'accepted' ? (value.label === 'benign' ? 'Benigna' : 'Maligna')
    : ({ uncertain: 'No concluyente', rejected: 'Rechazada', quality_failed: 'Calidad insuficiente', unavailable: 'Pendiente' }[value?.state] ?? 'Pendiente')
}
function quality(row) {
  const checks = row.metadata.classification?.quality?.checks ?? row.metadata.capture_quality?.checks
  return checks?.length ? (checks.slice(0, 3).every(Boolean) ? 'Adecuada' : 'Por revisar') : 'Sin evaluación'
}

function Trend({ rows, visits, errors, selected, onSelect }) {
  const [metric, setMetric] = useState('index')
  const [, title, unit, digits] = indicators.find(item => item[0] === metric)
  const values = rows.map(row => errors[row.id] ? null : row.metrics?.[metric])
  const valid = values.filter(Number.isFinite)
  const low = Math.min(0, ...valid)
  const high = Math.max(metric === 'index' ? 10 : .01, ...valid)
  const first = Date.parse(visits[0]?.captured_at)
  const span = Date.parse(visits.at(-1)?.captured_at) - first || 1
  const y = value => 17 + (high - value) / (high - low) * 126
  const points = visits.map((visit, i) => ({
    x: 50 + 488 * (Date.parse(visit.captured_at) - first) / span,
    value: values[i],
    label: `${visit.label} · ${date(visit.captured_at)} · ${Number.isFinite(values[i]) ? number(values[i], digits) + ' ' + unit : 'Medición no disponible'} · ${errors[visit.id] ? 'Error al comparar' : rows[i]?.title ?? 'Pendiente'}`,
  }))
  return <section className="panel tracking-trend">
    <div className="panel-heading"><h2>Evolución de indicadores</h2>
      <label>Indicador<select value={metric} onChange={event => setMetric(event.target.value)}>
        {indicators.map(([key, name]) => <option key={key} value={key}>{name}</option>)}
      </select></label>
    </div>
    {valid.length === 0 && <p>Medición no disponible. Calcula las comparaciones con la primera visita.</p>}
    <svg viewBox="0 0 560 182" role="group" aria-label={`${title} por fecha de captura en ${unit}`}>
      {[high, (high + low) / 2, low].map(value => <g key={value}>
        <line x1="50" x2="538" y1={y(value)} y2={y(value)} stroke="#dce8e4" />
        <text x="44" y={y(value) + 4} textAnchor="end">{number(value, digits)}</text>
      </g>)}
      {points.map((point, i) => Number.isFinite(point.value) && Number.isFinite(points[i - 1]?.value) &&
        <line key={visits[i].id} x1={points[i - 1].x} x2={point.x} y1={y(points[i - 1].value)} y2={y(point.value)} stroke="#0c8a56" strokeWidth="2" />)}
      {points.map((point, i) => <g key={visits[i].id}>
        {Number.isFinite(point.value) && <circle tabIndex={0} role="button" aria-label={point.label}
          onClick={() => onSelect(visits[i].id)} onKeyDown={event => {
            if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(visits[i].id) }
          }} cx={point.x} cy={y(point.value)} r={selected === visits[i].id ? 7 : 5} fill="#0c8a56" stroke="white" strokeWidth="2"><title>{point.label}</title></circle>}
        {(points.length <= 5 || i === 0 || i === points.length - 1) && <text x={point.x} y="164" textAnchor="middle">{date(visits[i].captured_at).slice(0, 5)}</text>}
      </g>)}
    </svg>
    <small>{title} · {unit} · respecto a la primera visita</small>
  </section>
}

function Measurements({ rows, visits, errors, selected }) {
  return <section className="panel tracking-measurements"><h2>Mediciones por visita</h2>
    <div className="evolution-table"><table><thead><tr><th scope="col">Indicador</th>
      {visits.map((visit, i) => <th scope="col" className={selected === visit.id ? 'tracking-marked' : undefined} key={visit.id}>{visit.label || `T${i}`}</th>)}
    </tr></thead><tbody>{indicators.map(([key, name, unit, digits]) => <tr key={key}>
      <th scope="row">{name}<small>{unit}</small></th>
      {visits.map((visit, i) => {
        const value = errors[visit.id] ? null : rows[i]?.metrics?.[key]
        return <td className={selected === visit.id ? 'tracking-marked' : undefined} key={visit.id}>
          {i === 0 ? 'Ref.' : Number.isFinite(value) ? number(value, digits) : '—'}
        </td>
      })}
    </tr>)}</tbody></table></div>
    <small>Ref. = foto inicial. El área expresa una variación aparente de la región alineada.</small>
  </section>
}

function TrackingMaps({ visit, comparison, lesion, valid, activation }) {
  const [overlay, setOverlay] = useState(false)
  const [failed, setFailed] = useState(false)
  const influence = activation && visit.metadata.classification?.explanation
  return <section className="panel tracking-maps">
    <div id="tracking-activation"><h2>Mapa de activación · {visit.label}</h2>
      {influence && !failed ? <>
        <div className="tracking-map-pair">
          <figure><img src={photo(visit)} alt="" /><figcaption>Original</figcaption></figure>
          <figure><div className={overlay ? 'tracking-map-overlay' : undefined}>
            {overlay && <img src={photo(visit)} alt="" />}
            <img src={`/api/visits/${visit.id}/influence?v=${encodeURIComponent(influence.sha256 ?? '')}`}
              alt={overlay ? 'Influencia superpuesta a la fotografía' : 'Mapa de influencia de la visita'}
              onError={() => setFailed(true)} />
          </div><figcaption>{overlay ? 'Superposición' : 'Oclusión'}</figcaption></figure>
        </div>
        <label className="check"><input type="checkbox" checked={overlay} onChange={event => setOverlay(event.target.checked)} /> Superponer mapa</label>
      </> : <p>{failed ? 'El mapa guardado no pudo abrirse. Vuelve a analizar la visita.' : activation ? 'Analiza la visita para generar su mapa.' : 'Pulsa «Ver mapa de activación» en el detalle.'}</p>}
    </div>
    <div><h2>Mapa de cambios · T0 y {visit.label}</h2>
      {valid && comparison?.map_available ? <>
        <img className="tracking-change-map" src={`/api/lesions/${lesion}/comparisons/${comparison.id}/map`} alt="Diferencias visuales del par alineado" />
        <small>Cian: contorno inicial. Naranja: contorno de esta visita. Los colores cálidos indican mayor diferencia visual.</small>
      </> : <p>{visit.label === 'T0' ? 'La primera foto es la referencia.' : 'Mapa temporal no disponible. Revisa el estado de la comparación con la primera visita.'}</p>}
    </div>
  </section>
}

export default function TrackingDashboard({ initialVisit, person, lesion, detail, api, refresh, compareVisits, renderVisitActions, renderRegistration }) {
  const [selection, setSelection] = useState(initialVisit || '')
  const [playing, setPlaying] = useState(false)
  const [alignPlayback, setAlignPlayback] = useState(true)
  const [failedAlignment, setFailedAlignment] = useState('')
  const [activation, setActivation] = useState(false)
  const [errors, setErrors] = useState({})
  const [action, setAction] = useState('')
  const [error, setError] = useState('')
  const [registration, setRegistration] = useState(false)
  const [pair, setPair] = useState([])
  const strip = useRef(null)
  const visits = detail?.visits ?? []
  const timeline = detail?.timeline ?? []
  const byVisit = new Map(timeline.map(row => [row.id, row]))
  const rows = visits.map(visit => byVisit.get(visit.id))
  const currentIndex = Math.max(0, visits.findIndex(row => row.id === selection))
  const current = visits[currentIndex]
  const nextVisit = visits[currentIndex + 1]?.id
  const reference = visits[0]
  const latest = visits.at(-1)
  const point = rows[currentIndex]
  const comparison = detail?.comparisons.find(row => row.id === point?.comparison_id)
  const aligned = playing && alignPlayback && point?.state === 'available' && comparison?.result.registration?.matrix && failedAlignment !== comparison.id
  const evaluated = rows.filter(row => Number.isFinite(row?.value) && !errors[row.id])
  const last = evaluated.at(-1)
  const activePair = pair.filter(id => visits.some(visit => visit.id === id))

  useEffect(() => {
    if (!playing || !selection) return
    const timer = setTimeout(() => {
      if (nextVisit) setSelection(nextVisit)
      else setPlaying(false)
    }, 1400)
    return () => clearTimeout(timer)
  }, [playing, selection, nextVisit])

  useEffect(() => {
    const list = strip.current
    const active = list?.children[currentIndex]
    if (!active) return
    const frame = list.getBoundingClientRect()
    const card = active.getBoundingClientRect()
    if (card.left < frame.left) list.scrollLeft += card.left - frame.left
    else if (card.right > frame.right) list.scrollLeft += card.right - frame.right
  }, [currentIndex])

  function select(id) {
    setPlaying(false)
    setSelection(id)
  }
  async function run(kind, task) {
    setAction(kind)
    setError('')
    try { await task() } catch (failure) { setError(failure.message) } finally { setAction('') }
  }
  async function exportFile(kind) {
    const blob = await api(`/lesions/${lesion.id}/export/${kind}`)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `seguimiento.${kind}`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  if (!detail || !lesion) return <p role="status">Cargando seguimiento…</p>
  return <div className="tracking-dashboard">
    <div className="tracking-toolbar">
      <button type="button" aria-expanded={registration} onClick={() => setRegistration(value => !value)}>{registration ? 'Cerrar formulario' : '+ Registrar visita'}</button>
      <button type="button" className="secondary" disabled={!visits.length || !!action}
        onClick={() => run('pdf', () => exportFile('pdf'))}>{action === 'pdf' ? 'Generando informe…' : 'Generar informe (PDF)'}</button>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    {visits.length === 1 && <p>Se necesita al menos una segunda visita comparable para visualizar cambios temporales.</p>}
    {registration && renderRegistration(id => { setRegistration(false); setSelection(id) })}
    <div className="tracking-grid">
      <section className="panel tracking-info"><h2>Información del seguimiento</h2>
        {reference && <img src={photo(reference)} alt="Fotografía de referencia" />}
        <dl><dt>Código de persona</dt><dd>{person?.code || 'No registrado'}</dd>
          <dt>Lesión</dt><dd>{lesion.name}</dd><dt>Localización</dt><dd>{lesion.site || 'No registrado'}</dd>
          <dt>Inicio</dt><dd>{date(reference?.captured_at)}</dd><dt>Última visita</dt><dd>{date(latest?.captured_at)}</dd>
          <dt>Estado</dt><dd>{visits.length >= 2 ? 'Con visitas de seguimiento' : visits.length ? 'Referencia registrada' : 'Sin fotografías'}</dd></dl>
      </section>
      <section className="panel tracking-stats"><h2>Resumen del seguimiento</h2>
        <dl>{[['Visitas registradas', visits.length], ['Primera visita', date(reference?.captured_at)],
          ['Última visita', date(latest?.captured_at)], ['Comparaciones evaluables', `${evaluated.length} de ${Math.max(0, visits.length - 1)}`]].map(([label, value]) =>
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      </section>
      {current && <>
        <section className="panel tracking-timeline"><div className="panel-heading"><h2>Línea de tiempo fotográfica</h2>
          <button type="button" disabled={visits.length < 2 || !!action} onClick={() => run('timeline', async () => {
            setErrors((await api(`/lesions/${lesion.id}/timeline`, { method: 'POST' })).errors)
            refresh()
          })}>{action === 'timeline' ? 'Comparando…' : 'Calcular todas las visitas'}</button>
        </div>
          <ol ref={strip}>{visits.map((visit, i) => <li key={visit.id}>
            <button type="button" className="secondary" aria-pressed={current.id === visit.id} onClick={() => select(visit.id)}>
              <strong>{visit.label}</strong><small>{i === 0 ? 'Referencia' : 'Seguimiento'}</small>
              <img src={photo(visit)} alt="" loading="lazy" />
              <span>{date(visit.captured_at)}</span>
              <small>{classification(visit)} · Calidad: {quality(visit)}</small>
              <small>{errors[visit.id] ? 'Error al comparar' : rows[i]?.title ?? 'Pendiente'}</small>
            </button>
            <label className="check"><input type="checkbox" checked={activePair.includes(visit.id)}
              disabled={activePair.length === 2 && !activePair.includes(visit.id)}
              onChange={() => setPair(activePair.includes(visit.id) ? activePair.filter(id => id !== visit.id) : [...activePair, visit.id])} />
              Comparar {visit.label}</label>
          </li>)}</ol>
        </section>
        <section className="panel tracking-detail"><h2>Detalle de la visita seleccionada · {current.label}</h2>
          <img src={aligned ? `/api/lesions/${lesion.id}/comparisons/${comparison.id}/aligned` : photo(current)}
            onError={aligned ? () => setFailedAlignment(comparison.id) : undefined}
            alt={`Fotografía ${aligned ? 'alineada' : 'original'} de la visita ${current.label}`} />
          <dl><dt>Fecha y hora</dt><dd>{date(current.captured_at)} · {current.captured_at.slice(11, 16)}</dd>
            <dt>Clasificación experimental</dt><dd>{classification(current)}{Number.isFinite(current.metadata.classification?.score) && ` · ${number(current.metadata.classification.score * 100)} % para la clase maligna`}</dd>
            <dt>Calidad</dt><dd>{quality(current)}</dd><dt>Contorno</dt><dd>{current.metadata.mask_reviewed ? 'Revisado' : 'Pendiente'}</dd>
            <dt>Alineación frente a T0</dt><dd>{errors[current.id] || point?.title || 'Pendiente'}</dd>
            <dt>Índice descriptivo</dt><dd>{!errors[current.id] && Number.isFinite(point?.value) ? `${number(point.value)} / 100` : '—'}</dd>
            <dt>Observaciones</dt><dd>{current.metadata.visit_notes?.observation || current.metadata.notes || current.metadata.note || 'No registrado'}</dd>
          </dl>
          <button type="button" className="secondary" aria-expanded={activation} aria-controls="tracking-activation" onClick={() => setActivation(value => !value)}>{activation ? 'Ocultar mapa de activación' : 'Ver mapa de activación'}</button>
          {renderVisitActions(current)}
        </section>
        <Trend rows={rows.map(row => row ?? {})} visits={visits} errors={errors} selected={current.id} onSelect={select} />
        <TrackingMaps key={`${current.id}:${current.metadata.classification?.explanation?.sha256 ?? ''}`} visit={current} comparison={comparison} lesion={lesion.id}
          valid={!errors[current.id] && Number.isFinite(point?.value)} activation={activation} />
        <Measurements rows={rows} visits={visits} errors={errors} selected={current.id} />
        <section className="panel tracking-summary"><h2>Resumen de la evolución</h2>
          <p>Del {date(reference.captured_at)} al {date(latest.captured_at)} se registraron {visits.length} visitas. {evaluated.length} de {visits.length - 1} comparaciones con la referencia tienen medición.</p>
          {last && <p>En la última visita evaluable ({date(last.date)}), el índice fue {number(last.value)} / 100.
            {indicators.slice(1).filter(([key]) => Number.isFinite(last.metrics[key])).map(([key, label, unit, digits]) =>
              ` ${label}: ${number(last.metrics[key], digits)} ${unit}.`)}</p>}
          <small>Los resultados describen cambios visuales experimentales y no constituyen un diagnóstico médico ni determinan por sí solos la progresión de una enfermedad.</small>
        </section>
        <div className="tracking-actions">
          <button type="button" disabled={activePair.length !== 2} onClick={() => compareVisits(activePair)}>Comparar visitas</button>
          <button type="button" className="secondary" disabled={visits.length < 2} onClick={() => {
            if (!playing) setSelection(visits[0].id)
            setPlaying(value => !value)
          }}>{playing ? 'Pausar evolución' : 'Reproducir evolución'}</button>
          <label className="check"><input type="checkbox" checked={alignPlayback} onChange={event => setAlignPlayback(event.target.checked)} /> Alinear durante la reproducción</label>
          <button type="button" className="secondary" disabled={!!action} onClick={() => run('csv', () => exportFile('csv'))}>{action === 'csv' ? 'Exportando…' : 'Exportar datos (CSV)'}</button>
        </div>
      </>}
    </div>
  </div>
}
