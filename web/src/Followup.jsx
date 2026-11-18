import { useEffect, useRef, useState } from 'react'
import TrackingDashboard from './TrackingDashboard'
import ReportsDashboard from './ReportsDashboard'
import ComparisonDashboard from './ComparisonDashboard'
import { api, useData } from './api'
import './Followup.css'
import './People.css'


const personLabel = (p) => p.name ? p.name + ' · ' + p.code : p.code


export function ModelResults() {
  const [report, error] = useData('/model/results')
  const names = { accuracy:'Exactitud', sensitivity:'Sensibilidad', specificity:'Especificidad', f1:'F1', auc:'AUC-ROC', threshold:'Umbral experimental', coverage:'Cobertura' }
  const descriptions = {
    accuracy: 'Proporción de clasificaciones correctas.',
    sensitivity: 'Proporción de imágenes malignas detectadas.',
    specificity: 'Proporción de imágenes benignas reconocidas.',
    f1: 'Equilibrio entre precisión de los positivos y sensibilidad.',
    auc: 'Capacidad de distinguir ambas clases a través de distintos umbrales.',
    threshold: 'Puntuación a partir de la cual se marca una imagen como positiva.',
    coverage: 'Proporción de imágenes con un resultado concluyente.',
  }
  const percent = new Intl.NumberFormat('es-PE', { style: 'percent', maximumFractionDigits: 2 })
  return <section className="followup-view">
    <div className="view-heading"><div><h1>Evaluación del modelo</h1><p>Resultados guardados en el conjunto de prueba del experimento activo.</p></div></div>
    {error && <p role="alert" className="error">{error}</p>}
    {!report && !error && <p>Cargando evaluación…</p>}
    {report && <>
      <p>{report.evaluation_scope} · {report.experiment}</p>
      <div className="metric-grid">{Object.entries(names).filter(([key]) => report.metrics[key] != null).map(([key, label]) =>
        <article className="panel metric" key={key}><span>{label}</span>
          <strong>{typeof report.metrics[key] === 'number' ? percent.format(report.metrics[key]) : 'Sin dato'}</strong>
          <small>{descriptions[key]}</small></article>)}</div>
      {report.confusion_matrix?.length === 2 && <section className="panel matrix"><h2>Matriz de clasificación</h2>
        <table><thead><tr><th scope="col">Etiqueta real</th><th scope="col">Predicción benigna</th><th scope="col">Predicción maligna</th></tr></thead>
          <tbody>{report.confusion_matrix.map((row, i) => <tr key={i}><th scope="row">{i ? 'Maligna' : 'Benigna'}</th><td>{row[0]}</td><td>{row[1]}</td></tr>)}</tbody></table>
        <small>Experimento: {report.experiment}</small>
      </section>}
    </>}
  </section>
}


export function ActionForm({ title, children, action, button, encoding, className = '', disabled = false, guardChanges = false, cancel }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(event) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    setBusy(true)
    setError('')
    try {
      const result = await action(encoding === 'form' ? data : Object.fromEntries(data))
      if (guardChanges && result !== false) delete form.dataset.dirty
      if (!form.querySelector('[data-preserve]')) form.reset()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return <form className={`panel record-form ${className}`} onSubmit={submit}
    onChange={guardChanges ? event => { event.currentTarget.dataset.dirty = 'true' } : undefined}>
    {title && <h2>{title}</h2>}<fieldset disabled={busy || disabled}>{children}</fieldset>
    {error && <p role="alert" className="error">{error}</p>}
    {cancel ? <div className="form-actions">
      {cancel}
      <button disabled={busy || disabled}>{busy ? 'Procesando…' : button}</button>
    </div> : <button disabled={busy || disabled}>{busy ? 'Procesando…' : button}</button>}
  </form>
}

function VisitCamera({ onCapture }) {
  const video = useRef(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    let stream
    async function open() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
        if (active) video.current.srcObject = stream
        else stream.getTracks().forEach(track => track.stop())
      } catch {
        if (active) setError('La cámara no está disponible. Puedes seleccionar una fotografía.')
      }
    }
    open()
    return () => { active = false; stream?.getTracks().forEach(track => track.stop()) }
  }, [])
  return <div>
    {error && <p role="alert" className="error">{error}</p>}
    <video className="camera-preview" ref={video} autoPlay muted playsInline onLoadedData={() => setReady(true)} />
    <button type="button" className="secondary" disabled={!ready} onClick={() => {
      const frame = video.current
      const canvas = document.createElement('canvas')
      canvas.width = frame.videoWidth
      canvas.height = frame.videoHeight
      canvas.getContext('2d').drawImage(frame, 0, 0)
      canvas.toBlob(blob => { if (blob) onCapture(new File([blob], 'visita.jpg', { type: 'image/jpeg' })) }, 'image/jpeg', .92)
    }}>Capturar fotografía</button>
  </div>
}

export function VisitForm({ lesion, refresh, hasVisits, linked = false }) {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState('')
  const [contour, setContour] = useState('')
  const [points, setPoints] = useState([])
  const [mode, setMode] = useState('suggest')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [camera, setCamera] = useState(false)
  const [quality, setQuality] = useState(null)
  const [checking, setChecking] = useState(false)
  const [analysis, setAnalysis] = useState(null)
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])
  useEffect(() => () => { if (contour) URL.revokeObjectURL(contour) }, [contour])

  async function choosePhoto(next) {
    setCamera(false)
    setFile(next)
    setAnalysis(null)
    setPreview(next ? URL.createObjectURL(next) : '')
    setContour('')
    setPoints([])
    setError('')
    setQuality(null)
    if (!next) return
    setChecking(true)
    try {
      const data = new FormData()
      data.append('file', next)
      setQuality((await api('/analyze/quality', { method: 'POST', data })).quality)
    } catch (failure) { setError(failure.message) } finally { setChecking(false) }
  }
  async function propose() {
    setError('')
    setBusy(true)
    try {
      const data = new FormData()
      data.append('file', file)
      setContour(URL.createObjectURL(await api('/contour', { method: 'POST', data })))
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }
  return <div className="visit-capture-form" data-dirty={linked && file ? 'true' : undefined}><ActionForm title="Fotografía de la visita" guardChanges={linked}
    button={linked ? (analysis ? 'Guardar visita y análisis' : 'Analizar fotografía') : 'Guardar visita'} encoding="form" action={async data => {
    if (checking || camera) throw new Error('Termina la captura y la revisión de calidad.')
    if (!file || (mode === 'suggest' ? !contour : points.length < 3)) throw new Error('Prepara y revisa el contorno.')
    data.set('file', file)
    if (mode === 'draw') data.set('points', JSON.stringify(points))
    data.set('confirmed', 'true')
    if (linked && !analysis) {
      setAnalysis(await api('/lesions/' + lesion + '/visit-analysis', { method: 'POST', data }))
      return false
    }
    if (analysis) data.set('analyzed', analysis.id)
    const saved = await api('/lesions/' + lesion + '/visits' + (linked ? '/analyzed' : ''), { method: 'POST', data })
    setFile(null)
    refresh(saved.id)
  }}>
    <label>Fecha y hora de la toma<input data-preserve={linked || undefined} name="date" type="datetime-local" required /></label>
    <label className="visit-upload">Fotografía de la lesión
      <span className="visit-upload-hint">Selecciona una fotografía clara de tu equipo</span>
      <input key={camera ? 'camera' : 'photo'} name="file" type="file" accept="image/jpeg,image/png,image/webp" disabled={busy || checking}
      onChange={event => choosePhoto(event.target.files[0])} /></label>
    <button type="button" className="secondary" disabled={checking || busy} onClick={() => setCamera(value => !value)}>{camera ? 'Cerrar cámara' : 'Usar cámara'}</button>
    {camera && <VisitCamera onCapture={choosePhoto} />}
    {file && <small>{file.name}</small>}
    {checking && <p role="status">Evaluando calidad de imagen…</p>}
    {quality && <p>Calidad: {quality.checks.every(Boolean) ? 'Adecuada' : quality.message} · Encuadre: {quality.framing == null ? 'Sin determinar' : quality.framing ? 'Margen suficiente' : 'Por revisar'}.</p>}
    <label>Contorno<select value={mode} onChange={event => { setMode(event.target.value); setAnalysis(null) }}><option value="suggest">Sugerir contorno</option><option value="draw">Dibujar con puntos</option></select></label>
    {preview && mode === 'suggest' && <>
      <button className="secondary" type="button" onClick={propose} disabled={busy}>{busy ? 'Buscando contorno…' : 'Ver contorno sugerido'}</button>
      <img className="visit-preview" src={contour || preview} alt={contour ? 'Contorno propuesto' : 'Fotografía seleccionada'} />
    </>}
    {preview && mode === 'draw' && <>
      <p>Marca puntos alrededor de la lesión. El último punto se unirá al primero.</p>
      <div className="drawing" onClick={event => {
        if (points.length >= 256) return
        const box = event.currentTarget.getBoundingClientRect()
        setAnalysis(null)
        setPoints([...points, [(event.clientX - box.left) / box.width, (event.clientY - box.top) / box.height]])
      }}>
        <img src={preview} alt="Fotografía para dibujar el contorno" />
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <polygon points={points.map(([x, y]) => [x * 100, y * 100].join(',')).join(' ')} />
          {points.map(([x, y], index) => <circle key={index} cx={x * 100} cy={y * 100} r="0.8" />)}
        </svg>
      </div>
      <button className="secondary" type="button" onClick={() => { setPoints(points.slice(0, -1)); setAnalysis(null) }}>Deshacer punto</button>
    </>}
    {error && <p className="error" role="alert">{error}</p>}
    {analysis && <div className="workflow-result" role="status"><strong>Resultado experimental · {
      { benign: 'Benigna', malignant: 'Maligna' }[analysis.label] ?? (analysis.state === 'quality_failed' ? 'Calidad insuficiente' : 'No concluyente')
    }</strong>{Number.isFinite(analysis.score) && <p>Puntuación para la clase maligna · {Math.round(analysis.score * 100)} %</p>}
      {analysis.message && <p>{analysis.message}</p>}<p>El resultado se incorporará al historial al guardar la visita.</p>
      <button className="secondary" type="button" onClick={() => setAnalysis(null)}>Volver a analizar</button>
    </div>}
    <label>Notas de la visita<textarea name="notes" rows={3} placeholder="Observaciones sobre la fotografía o la visita" /></label>
    <label className="check"><input type="checkbox" required /> Revisé el contorno y la fecha de la fotografía.</label>
    {hasVisits && <label className="check"><input type="checkbox" name="same_lesion" value="true" required /> Confirmo que la foto corresponde a la misma lesión.</label>}
  </ActionForm></div>
}

function VisitOptions({ row, refresh, onTrash }) {
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const classification = row.metadata.classification
  async function run(task) {
    setBusy(true)
    setMessage('')
    try { await task(); refresh() }
    catch (error) { setMessage(error.message) }
    finally { setBusy(false) }
  }
  return <div className="tracking-visit-options">
      <p>{row.identity_description}</p>
      <details><summary>Opciones de visita</summary>
        {!row.metadata.lesion_identity && <button className="secondary" disabled={busy}
          onClick={() => run(() => api('/visits/' + row.id + '/identity', { method: 'POST' }))}>Confirmar que corresponde a esta lesión</button>}
        <button className="secondary" disabled={busy} onClick={() => run(() => api('/visits/' + row.id + '/analyze', { method: 'POST' }))}>{busy ? 'Procesando…' : 'Analizar visita'}</button>
        {classification?.explanation && <details><summary>Ver mapa de influencia</summary>
          <img loading="lazy" src={'/api/visits/' + row.id + '/influence'} alt="Influencia del modelo en la visita" />
          <p>Las zonas coloreadas muestran dónde cambió la salida del modelo al ocultar regiones de la foto.</p>
        </details>}
        <ActionForm title="Editar visita" button="Guardar visita" action={async data => {
          await api('/visits/' + row.id, { method: 'PATCH', data })
          refresh()
        }}>
          <label>Fecha<input data-preserve name="date" type="datetime-local" step="1" defaultValue={row.captured_at} required /></label>
          <label>Observación<textarea name="observation" maxLength={2000} defaultValue={row.metadata.visit_notes?.observation ?? row.metadata.notes ?? ''} /></label>
        </ActionForm>
        <button className="secondary" disabled={busy} onClick={() => {
          if (window.confirm('¿Mover esta fotografía a la papelera?')) run(async () => {
            await api('/visits/' + row.id, { method: 'DELETE' })
            onTrash(row.id)
          })
        }}>Mover a papelera</button>
      </details>
      {message && <p role="alert" className="error">{message}</p>}
  </div>
}


export function PeopleAccess({ account, error, refresh }) {
  const [visible, setVisible] = useState(false)
  const configured = account?.configured
  return <section className="followup-view people-access">
    <ActionForm className="people-access-card" disabled={!account} button={configured === false ? 'Crear cuenta local' : 'Iniciar sesión'} action={async data => {
      await api('/session', { method: 'POST', data })
      refresh()
    }}>
      <div className="people-access-visual" aria-hidden="true"><div><strong>DermaVision X</strong><span>Captura de lesiones · Análisis experimental · Seguimiento fotográfico</span></div></div>
      <div className="people-access-fields">
      <div className="people-access-heading">
        <span className="people-emblem"><img src="/dermavision.svg" width="48" height="48" alt="" /></span>
        <h1>{configured === false ? 'Crear cuenta de administrador' : 'Bienvenido a DermaVision X'}</h1>
        <p>{configured === false ? 'Configura la cuenta local para gestionar el directorio y el historial.' : 'Plataforma de análisis experimental y seguimiento fotográfico de lesiones cutáneas.'}</p>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {!account && !error && <p role="status">Comprobando la cuenta local…</p>}
      <label>Usuario<input name="username" autoComplete="username" placeholder="Ingresa tu usuario" required maxLength={80} disabled={!account} /></label>
      <label htmlFor="people-password">Contraseña</label>
      <div className="people-password">
        <input id="people-password" name="password" type={visible ? 'text' : 'password'}
          autoComplete={configured === false ? 'new-password' : 'current-password'} placeholder="Ingresa tu contraseña"
          required minLength={configured === false ? 10 : 1} maxLength={256} disabled={!account} />
        <button type="button" className="secondary" aria-controls="people-password" aria-pressed={visible} onClick={() => setVisible(value => !value)}>
          {visible ? 'Ocultar' : 'Mostrar'}
        </button>
      </div>
      </div>
    </ActionForm>
  </section>
}

const normalizeSearch = value => value.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase().trim()
const shortDate = new Intl.DateTimeFormat('es-PE', { dateStyle: 'medium' })
const peoplePageSize = 5

function PersonDialog({ person, onClose, onSave, Icon }) {
  const dialog = useRef(null)
  const [suggestion, error] = useData(person ? null : '/people/next-code', 0)
  function close() {
    const form = dialog.current?.querySelector('form')
    if (form?.dataset.dirty === 'true' && !window.confirm('Hay cambios sin guardar. ¿Cerrar este formulario?')) return
    onClose()
  }
  const title = person ? 'Editar persona' : 'Registrar nueva persona'
  return <dialog className="people-dialog" ref={element => {
    dialog.current = element
    if (element && !element.open) element.showModal()
  }} aria-labelledby="person-dialog-title" onCancel={event => { event.preventDefault(); close() }}>
    <ActionForm className="people-register" guardChanges disabled={!person && !suggestion}
      title={<><Icon name="people" /><span id="person-dialog-title">{title}</span></>}
      button={person ? 'Guardar cambios' : 'Registrar persona'}
      cancel={<button type="button" className="secondary" onClick={close}>Cancelar</button>}
      action={async data => {
        const result = await api(person ? '/people/' + person.id : '/people', {
          method: person ? 'PUT' : 'POST', data: person ? data : { ...data, automatic_code: true },
        })
        onSave(result, person)
      }}>
      <label>Código de persona<input name="code" defaultValue={person?.code}
        {...(!person ? { readOnly: true, value: suggestion?.code || '' } : {})}
        required maxLength={160} placeholder="Generando código…" /></label>
      <label>Nombre completo<input autoFocus name="name" defaultValue={person?.name} placeholder="Opcional" maxLength={160} /></label>
      <label>Observaciones<textarea name="notes" defaultValue={person?.notes} placeholder="Opcional" maxLength={2000} /></label>
    </ActionForm>
    {error && <p className="error" role="alert">{error}</p>}
    {!person && !suggestion && !error && <p role="status">Obteniendo el código de persona…</p>}
  </dialog>
}

function PeopleDirectory({ people, currentPerson, setSelection, navigate, refresh, Icon, intent, editPersonId }) {
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [requestedPage, setPage] = useState(0)
  const [editing, setEditing] = useState(editPersonId || '')
  const [registering, setRegistering] = useState(intent === 'register')
  const [notice, setNotice] = useState(null)
  const editPerson = people?.find(row => row.id === editing)
  const rows = people ?? []
  const filtered = rows.filter(row => normalizeSearch(personLabel(row)).includes(normalizeSearch(search))
    && (filter === 'all' || (filter === 'with' ? row.lesion_count > 0 : row.lesion_count === 0)))
  const pageCount = Math.max(1, Math.ceil(filtered.length / peoplePageSize))
  const currentPage = Math.min(requestedPage, pageCount - 1)
  const start = currentPage * peoplePageSize
  const visible = filtered.slice(start, start + peoplePageSize)
  const metrics = [
    ['people', 'Personas registradas', rows.length],
    ['scan', 'Lesiones registradas', rows.reduce((sum, row) => sum + row.lesion_count, 0)],
    ['chart', 'Visitas analizadas', rows.reduce((sum, row) => sum + row.analysis_count, 0)],
    ['timeline', 'Lesiones con seguimiento', rows.reduce((sum, row) => sum + row.followup_count, 0)],
  ]
  return <>
    <dl className="people-metrics">{metrics.map(([icon, label, value]) => <div className="panel people-metric" key={label}>
      <span className="people-emblem"><Icon name={icon} /></span>
      <div><dt>{label}</dt><dd>{people ? value : '—'}</dd></div>
    </div>)}</dl>
    <div className="people-directory-grid">
      <section className="panel">
        <div className="panel-heading people-directory-heading"><h2><Icon name="timeline" /> Directorio de personas</h2>
          <button type="button" onClick={() => setRegistering(true)}>+ Registrar persona</button>
        </div>
        {notice && <div className="people-notice" role="status">
          <span>{notice.message}</span><a href={'#patient/' + notice.id}>Abrir ficha</a>
        </div>}
        <div className="people-filters">
          <label>Buscar<input autoFocus={intent === "search"} type="search" placeholder="Buscar por nombre o código…" value={search}
            onChange={event => { setSearch(event.target.value); setPage(0) }} /></label>
          <label>Lesiones<select value={filter} onChange={event => { setFilter(event.target.value); setPage(0) }}>
            <option value="all">Todas las personas</option><option value="with">Con lesiones</option><option value="without">Sin lesiones</option>
          </select></label>
        </div>
        <div className="people-table">
          <table><thead><tr>{['Código', 'Nombre', 'Lesiones', 'Último análisis', 'Acciones'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
            <tbody>{visible.map(row => <tr key={row.id} className={currentPerson?.id === row.id ? 'people-selected' : undefined}>
              <th scope="row">{row.code}</th>
              <td><span className="people-initial" aria-hidden="true">{(row.name || row.code).slice(0, 1).toUpperCase()}</span>{row.name || '—'}</td>
              <td><span className="people-count">{row.lesion_count}</span></td>
              <td>{row.last_analysis ? shortDate.format(new Date(row.last_analysis)) : '—'}</td>
              <td><div className="people-row-actions">
                <button type="button" className="secondary" aria-label={`Ver ficha de ${personLabel(row)}`} onClick={() => navigate("patient/" + row.id)}>Ver ficha</button>
                <button type="button" className="secondary" aria-label={`Editar ${personLabel(row)}`} onClick={() => setEditing(row.id)}>Editar</button>
              </div></td>
            </tr>)}
            {!visible.length && <tr><td colSpan={5}>{!people ? 'Cargando directorio…' : rows.length ? 'No hay registros que coincidan con la búsqueda.' : 'Registra a la primera persona para empezar.'}</td></tr>}</tbody>
          </table>
        </div>
        <div className="people-pagination">
          <small>{filtered.length ? `${start + 1}–${start + visible.length} de ${filtered.length} registros` : '0 registros'}</small>
          {pageCount > 1 && <div><button type="button" className="secondary" disabled={!currentPage} onClick={() => setPage(currentPage - 1)}>Anterior</button>
            <span>Página {currentPage + 1} de {pageCount}</span>
            <button type="button" className="secondary" disabled={currentPage + 1 >= pageCount} onClick={() => setPage(currentPage + 1)}>Siguiente</button></div>}
        </div>
      </section>
      {(registering || editPerson) && <PersonDialog key={editPerson?.id ?? 'new'} person={editPerson} Icon={Icon}
        onClose={() => {
          setRegistering(false)
          setEditing('')
          if (editPersonId) navigate('patient/' + editPersonId, true)
        }}
        onSave={(value, edited) => {
          setSelection([value.id, ''])
          setRegistering(false)
          setEditing('')
          refresh()
          if (editPersonId) navigate('patient/' + value.id, true)
          else {
            setSearch(value.code || '')
            setFilter('all')
            setPage(0)
            setNotice({ id: value.id, message: edited ? 'Cambios guardados correctamente.' : 'Persona registrada correctamente.' })
          }
        }} />}
    </div>
  </>
}

export default function Followup({ page, selection, setSelection, navigate, Icon, account, onLogout, intent, editPersonId, activeVisit, activeComparisonId, reportComparison }) {
  const [rev, setRev] = useState(0)
  const [person, lesion] = selection
  const refresh = () => setRev(value => value + 1)
  const [people, peopleError] = useData(account?.authenticated ? '/people' : null, rev)
  const [lesions, lesionsError] = useData(account?.authenticated && person ? '/people/' + person + '/lesions' : null, rev)
  const [detail, detailError] = useData(account?.authenticated && lesion ? '/lesions/' + lesion : null, rev)
  const [comparison, setComparison] = useState('')
  const [pairs, setPairs] = useState({})
  const [reportsSettings, setReportsSettings] = useState({})
  const [trashed, setTrashed] = useState(null)
  const [actionError, setActionError] = useState('')
  const [analysisProgress, setAnalysisProgress] = useState('')
  const currentPerson = people?.find(row => row.id === person)
  const visits = detail?.visits ?? []
  const currentLesion = lesions?.find(row => row.id === lesion)
  const comparisons = detail?.comparisons ?? []
  const requested = comparisons.find(row => row.id === activeComparisonId)
  const pairIds = requested ? [requested.previous_id, requested.current_id] : (pairs[lesion] ?? [])
  const selectedVisits = visits.filter(row => pairIds.includes(row.id))
  const error = peopleError || lesionsError || detailError || actionError

  if (!page || !account?.authenticated) return null

  const filters = <>
        <label>Persona<select value={person} onChange={event => {
          const next = event.target.value
          setSelection([next, ''])
          navigate(page + (next ? '/' + next : ''))
        }}>
          <option value="">Seleccionar persona</option>{people?.map(p => <option key={p.id} value={p.id}>{personLabel(p)}</option>)}</select></label>
        <label>Lesión<select value={lesion} disabled={!person} onChange={event => {
          const next = event.target.value
          setSelection([person, next])
          navigate(page + '/' + person + (next ? '/' + next : ''))
        }}>
          <option value="">Seleccionar lesión</option>{lesions?.map(item => <option key={item.id} value={item.id}>{item.name}{item.site ? ` (${item.site})` : ''}</option>)}</select></label>
  </>

  return <section className={`followup-view ${page === 'people' ? 'people-view' : page === 'followup' ? 'tracking-view' : page === 'compare' ? 'comparison-view' : page === 'reports' ? 'reports-view' : ''}`}>
    <div className="view-heading"><div>
      <h1>{page === 'people' && <span className="people-emblem"><Icon name="people" size={29} /></span>}
        {{people:'Gestión de personas', followup:'Seguimiento longitudinal', compare:'Comparación de fotografías', reports:'Informes y video'}[page]}</h1>
      <p>{{people:'Administra los registros y abre el historial de seguimiento de cada lesión.', followup:'Analiza la evolución de una lesión cutánea a lo largo del tiempo mediante imágenes, métricas y mapas de calor.', compare:'Analiza en detalle las diferencias visuales entre dos fotografías de una misma lesión.', reports:'Genera informes detallados y videos de seguimiento de lesiones cutáneas. Consulta el historial fotográfico, los resultados experimentales de inteligencia artificial y las mediciones de cambios visuales registradas durante diferentes visitas.'}[page]}</p></div>
      <div className={page === 'people' ? 'people-session' : undefined}>
        {page === 'people' && <span><strong>Administrador</strong><small>Sesión activa</small></span>}
        <button className="secondary logout" onClick={async () => {
        try {
          await onLogout()
          setSelection(['', ''])
          setReportsSettings({})
          setTrashed(null)
          setActionError('')
          refresh()
        } catch (err) { setActionError(err.message) }
      }}>Cerrar sesión</button></div></div>
    {error && <p className="error" role="alert">{error}</p>}
    {page === 'people' ? <PeopleDirectory key={editPersonId || intent || "directory"} editPersonId={editPersonId} people={people} currentPerson={currentPerson}
      setSelection={setSelection} navigate={navigate} refresh={refresh} Icon={Icon} intent={intent} /> : <>
      <nav className="breadcrumbs" aria-label="Ruta de navegación">
        <a href="#home">Inicio</a><span>›</span>
        {currentPerson && <><a href={'#patient/' + person}>{personLabel(currentPerson)}</a><span>›</span></>}
        {currentLesion && <><a href={'#lesion/' + person + '/' + lesion}>{currentLesion.name}</a><span>›</span></>}
        <strong>{{followup:'Seguimiento', compare:'Comparaciones', reports:'Informes y video'}[page]}</strong>
      </nav>
      {page === 'followup' && <div className="panel filters">{filters}</div>}
      {!lesion && page === 'followup' && <div className="panel module-empty"><Icon name="timeline" size={40} /><h2>Selecciona una lesión para visualizar su evolución</h2>
        <p>Elige una persona y una lesión en los selectores. Aquí aparecerán sus visitas reales, fotografías y mediciones disponibles.</p>
        <a href="#people">Ir a Personas</a></div>}
      {lesion && page === 'followup' && <>
        <TrackingDashboard key={lesion + ':' + (activeVisit || '')} initialVisit={activeVisit} person={currentPerson} lesion={currentLesion} detail={detail} api={api} refresh={refresh}
          compareVisits={ids => {
            setPairs(current => ({ ...current, [lesion]: ids }))
            const saved = comparisons.filter(row => ids.includes(row.previous_id) && ids.includes(row.current_id)).at(-1)
            setComparison(saved?.id ?? '')
            navigate('compare/' + person + '/' + lesion + (saved ? '/' + saved.id : ''))
          }}
          renderVisitActions={row => <VisitOptions key={row.id} row={row} refresh={refresh}
            onTrash={id => setTrashed({ lesion, id })} />}
          renderRegistration={onSave => <VisitForm key={lesion} lesion={lesion} hasVisits={visits.length > 0}
            refresh={id => { onSave(id); refresh() }} />} />
        <div className="tracking-utilities">
          {trashed?.lesion === lesion && <button className="secondary" onClick={async () => {
            try {
              await api('/visits/' + trashed.id + '/restore', { method: 'POST' })
              setTrashed(null)
              refresh()
            } catch (err) { setActionError(err.message) }
          }}>Deshacer envío a papelera</button>}
          {!!visits.length && <button className="secondary" onClick={() => navigate('reports/' + person + '/' + lesion)}>Más opciones de exportación</button>}
        </div>
        {!!visits.some(row => !row.metadata.classification) && <section className="panel">
          <button disabled={!!analysisProgress} onClick={async () => {
            const pending = visits.filter(row => !row.metadata.classification)
            const failed = []
            setActionError('')
            try {
              for (const [index, row] of pending.entries()) {
                setAnalysisProgress(`Analizando ${index + 1} de ${pending.length}…`)
                try { await api('/visits/' + row.id + '/analyze', { method: 'POST' }) }
                catch (err) { failed.push(`${row.label}: ${err.message}`) }
              }
              if (failed.length) setActionError(failed.join(' · '))
            } finally { refresh(); setAnalysisProgress('') }
          }}>{analysisProgress || 'Analizar visitas pendientes'}</button>
          <p>Guarda la clasificación experimental y su mapa de influencia para el informe.</p>
        </section>}
      </>}
      {page === 'compare' && <ComparisonDashboard
        key={lesion + ':' + (selectedVisits.length === 2 ? selectedVisits : visits.slice(0, 2)).map(row => row.id).join(':')}
        lesion={lesion} visits={visits} comparisons={comparisons} initialPair={selectedVisits} initialSaved={requested?.id || comparison}
        api={api} refresh={refresh} filters={filters} navigate={navigate} Icon={Icon} personId={person} />}
      {page === 'reports' && <ReportsDashboard key={lesion} lesion={lesion} detail={detail}
        filters={filters} api={api} Icon={Icon} settings={reportsSettings[lesion]} comparisonId={reportComparison}
        onSettings={settings => setReportsSettings(current => ({ ...current, [lesion]: settings }))} />}
    </>}
  </section>
}
