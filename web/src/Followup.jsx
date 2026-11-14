import { useEffect, useState } from 'react'
import './Followup.css'

async function api(path, { method = 'GET', data } = {}) {
  const form = data instanceof FormData
  const response = await fetch('/api' + path, {
    method, body: data === undefined ? undefined : form ? data : JSON.stringify(data),
    headers: data === undefined || form ? undefined : { 'Content-Type': 'application/json' },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : 'No se pudo completar la operación.')
  }
  return response.headers.get('content-type')?.includes('application/json') ? response.json() : response.blob()
}

const dateLabel = (s) => s?.replace('T', ' ').slice(0, 16)
const personLabel = (p) => p.name ? p.name + ' · ' + p.code : p.code

export function ModelResults() {
  const [report, error] = useData('/model/results')
  const names = { accuracy:'Exactitud', sensitivity:'Sensibilidad', specificity:'Especificidad', f1:'F1', auc:'AUC-ROC', threshold:'Umbral experimental' }
  const descriptions = {
    accuracy: 'Proporción de clasificaciones correctas.',
    sensitivity: 'Proporción de imágenes malignas detectadas.',
    specificity: 'Proporción de imágenes benignas reconocidas.',
    f1: 'Equilibrio entre precisión de los positivos y sensibilidad.',
    auc: 'Capacidad de distinguir ambas clases a través de distintos umbrales.',
    threshold: 'Puntuación a partir de la cual se marca una imagen como positiva.',
  }
  const percent = new Intl.NumberFormat('es-PE', { style: 'percent', maximumFractionDigits: 2 })
  return <section className="followup-view">
    <div className="view-heading"><div><h1>Evaluación del modelo</h1><p>Resultados guardados en el conjunto de prueba del experimento activo.</p></div></div>
    {error && <p role="alert" className="error">{error}</p>}
    {!report && !error && <p>Cargando evaluación…</p>}
    {report && <>
      <div className="metric-grid">{Object.entries(names).map(([key, label]) =>
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

function useData(path, revision) {
  const [result, setResult] = useState(null)
  useEffect(() => {
    let live = true
    if (path) api(path).then(data => { if (live) setResult({ path, data, error: '' }) })
      .catch(err => { if (live) setResult({ path, data: null, error: err.message }) })
    return () => { live = false }
  }, [path, revision])
  return path && result?.path === path ? [result.data, result.error] : [null, '']
}

function ActionForm({ title, children, action, button, encoding }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(event) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    setBusy(true)
    setError('')
    try {
      await action(encoding === 'form' ? data : Object.fromEntries(data))
      if (!form.querySelector('[data-preserve]')) form.reset()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return <form className="panel record-form" onSubmit={submit}>
    <h2>{title}</h2><fieldset disabled={busy}>{children}</fieldset>
    {error && <p role="alert" className="error">{error}</p>}
    <button disabled={busy}>{busy ? 'Procesando…' : button}</button>
  </form>
}

function VisitForm({ lesion, refresh }) {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState('')
  const [contour, setContour] = useState('')
  const [points, setPoints] = useState([])
  const [mode, setMode] = useState('suggest')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])
  useEffect(() => () => { if (contour) URL.revokeObjectURL(contour) }, [contour])

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
  return <ActionForm title="Registrar fotografía" button="Guardar visita" encoding="form" action={async data => {
    if (!file || (mode === 'suggest' ? !contour : points.length < 3)) throw new Error('Prepara y revisa el contorno.')
    if (mode === 'draw') data.set('points', JSON.stringify(points))
    data.set('confirmed', 'true')
    await api('/lesions/' + lesion + '/visits', { method: 'POST', data })
    refresh()
  }}>
    <label>Fecha y hora de la toma<input name="date" type="datetime-local" required /></label>
    <label>Foto<input name="file" type="file" accept="image/jpeg,image/png,image/webp" required disabled={busy}
      onChange={event => {
        const next = event.target.files[0]
        setFile(next)
        setPreview(next ? URL.createObjectURL(next) : '')
        setContour('')
        setPoints([])
        setError('')
      }} /></label>
    <label>Contorno<select value={mode} onChange={event => setMode(event.target.value)}><option value="suggest">Sugerir contorno</option><option value="draw">Dibujar con puntos</option></select></label>
    {preview && mode === 'suggest' && <>
      <button className="secondary" type="button" onClick={propose} disabled={busy}>{busy ? 'Buscando contorno…' : 'Ver contorno sugerido'}</button>
      <img className="visit-preview" src={contour || preview} alt={contour ? 'Contorno propuesto' : 'Fotografía seleccionada'} />
    </>}
    {preview && mode === 'draw' && <>
      <p>Marca puntos alrededor de la lesión. El último punto se unirá al primero.</p>
      <div className="drawing" onClick={event => {
        if (points.length >= 256) return
        const box = event.currentTarget.getBoundingClientRect()
        setPoints([...points, [(event.clientX - box.left) / box.width, (event.clientY - box.top) / box.height]])
      }}>
        <img src={preview} alt="Fotografía para dibujar el contorno" />
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <polygon points={points.map(([x, y]) => [x * 100, y * 100].join(',')).join(' ')} />
          {points.map(([x, y], index) => <circle key={index} cx={x * 100} cy={y * 100} r="0.8" />)}
        </svg>
      </div>
      <button className="secondary" type="button" onClick={() => setPoints(points.slice(0, -1))}>Deshacer punto</button>
    </>}
    {error && <p className="error" role="alert">{error}</p>}
    <label>Notas<textarea name="notes" /></label>
    <label className="check"><input type="checkbox" required /> Revisé el contorno y confirma la lesión en la foto.</label>
  </ActionForm>
}

function Downloads({ lesion, visits }) {
  const count = visits.length
  const [error, setError] = useState('')
  const [pending, setPending] = useState('')
  async function download(kind) {
    setError('')
    setPending(kind)
    try {
      const blob = await api('/lesions/' + lesion + '/export/' + kind)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'seguimiento.' + kind
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) { setError(err.message) } finally { setPending('') }
  }
  return <section className="panel"><h2>Exportar seguimiento</h2>
    <p>Descarga las visitas y los resultados disponibles para la lesión seleccionada.</p>
    {count > 0 && <details className="technical"><summary>{count} {count === 1 ? 'visita incluida' : 'visitas incluidas'}</summary>
      <ul>{visits.map(row => <li key={row.id}>{row.label} · {dateLabel(row.captured_at)}</li>)}</ul>
    </details>}
    <div className="actions">
      <button disabled={!count || !!pending} onClick={() => download('pdf')}>{pending === 'pdf' ? 'Generando PDF…' : 'Descargar informe PDF'}</button>
      <button className="secondary" disabled={count < 2 || !!pending} onClick={() => download('mp4')}>{pending === 'mp4' ? 'Preparando video…' : 'Descargar video MP4'}</button>
    </div>
    {error && <p role="alert" className="error">{error}</p>}
    {count < 2 && <small>El video requiere al menos dos fotografías.</small>}
  </section>
}

function VisitCard({ row, refresh, onTrash, selected, selectionFull, onSelect }) {
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
  return <figure>
    <img loading="lazy" src={'/api/visits/' + row.id + '/photo'} alt={'Fotografía de ' + dateLabel(row.captured_at)} />
    <figcaption>
      <strong>{row.label} · {dateLabel(row.captured_at)}</strong>
      <label className="check visit-select"><input type="checkbox" checked={selected}
        disabled={selectionFull && !selected} onChange={onSelect} /> Seleccionar para comparar</label>
      {(row.metadata.visit_notes?.observation || row.metadata.notes) && <p>{row.metadata.visit_notes?.observation || row.metadata.notes}</p>}
      {classification && <p>{classification.state === 'accepted' ? 'Clasificación experimental: ' + (classification.label === 'benign' ? 'benigna' : 'maligna') : classification.message || 'Sin clasificación'}</p>}
      <details><summary>Opciones de visita</summary>
        <button className="secondary" disabled={busy} onClick={() => run(() => api('/visits/' + row.id + '/analyze', { method: 'POST' }))}>{busy ? 'Procesando…' : 'Analizar visita'}</button>
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
    </figcaption>
  </figure>
}

export default function Followup({ page, selection, setSelection, navigate }) {
  const [rev, setRev] = useState(0)
  const [person, lesion] = selection
  const refresh = () => setRev(value => value + 1)
  const [account, accountError] = useData('/session', rev)
  const [people, peopleError] = useData(account?.authenticated ? '/people' : null, rev)
  const [lesions, lesionsError] = useData(account?.authenticated && person ? '/people/' + person + '/lesions' : null, rev)
  const [detail, detailError] = useData(account?.authenticated && lesion ? '/lesions/' + lesion : null, rev)
  const [search, setSearch] = useState('')
  const [comparison, setComparison] = useState('')
  const [pairs, setPairs] = useState({})
  const [visitForm, setVisitForm] = useState('')
  const [trashed, setTrashed] = useState('')
  const [actionError, setActionError] = useState('')
  const currentPerson = people?.find(row => row.id === person)
  const visits = detail?.visits ?? []
  const currentLesion = lesions?.find(row => row.id === lesion)
  const selectedVisits = visits.filter(row => (pairs[lesion] ?? []).includes(row.id))
  const comparisons = detail?.comparisons ?? []
  const activeComparison = comparisons.find(row => row.id === comparison)
  const previousVisit = visits.find(row => row.id === activeComparison?.previous_id)
  const currentVisit = visits.find(row => row.id === activeComparison?.current_id)
  const error = accountError || peopleError || lesionsError || detailError || actionError

  if (!account || !account.authenticated) return <section className="followup-view">
    <h1>Archivo de seguimiento</h1><p>Accede a las personas, sus fotografías e informes.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {!account ? <p>Comprobando la cuenta local…</p> :
      <ActionForm title={account.configured ? 'Iniciar sesión' : 'Crear cuenta local'} button={account.configured ? 'Entrar' : 'Crear cuenta'} action={async data => {
        await api('/session', { method: 'POST', data })
        refresh()
      }}>
        <label>Usuario<input name="username" autoComplete="username" required maxLength={80} /></label>
        <label>Contraseña<input name="password" type="password" autoComplete={account.configured ? 'current-password' : 'new-password'} required minLength={account.configured ? 1 : 10} maxLength={256} /></label>
      </ActionForm>}
  </section>

  return <section className="followup-view">
    <div className="view-heading"><div><h1>{{people:'Personas', followup:'Seguimiento', compare:'Comparar fotografías', reports:'Informes y video'}[page]}</h1>
      <p>{{people:'Busca una persona y elige una lesión para abrir su historial.', followup:'Organiza las fotografías de cada lesión por fecha.', compare:'Elige dos visitas para revisar sus diferencias visuales.', reports:'Exporta el seguimiento de una lesión.'}[page]}</p></div>
      <button className="secondary logout" onClick={async () => {
        try {
          await api('/session', { method: 'DELETE' })
          setSelection(['', ''])
          setTrashed('')
          setActionError('')
          refresh()
        } catch (err) { setActionError(err.message) }
      }}>Cerrar sesión</button></div>
    {error && <p className="error" role="alert">{error}</p>}
    {page === 'people' ? <div className="followup-grid">
      <section className="panel"><h2>Directorio</h2>
        <label>Buscar por nombre o código<input type="search" value={search} onChange={event => setSearch(event.target.value)} /></label>
        <div className="row-list">{people?.filter(p => personLabel(p).toLowerCase().includes(search.trim().toLowerCase())).map(p =>
          <button className="list-row" key={p.id} type="button" aria-pressed={person === p.id} onClick={() => setSelection([p.id, ''])}>{personLabel(p)}<small>{p.lesion_count} lesiones</small></button>)}
          {people?.length === 0 && <p>Todavía no hay personas registradas.</p>}</div>
      </section>
      <ActionForm title={currentPerson ? 'Editar persona' : 'Nueva persona'} key={currentPerson?.id ?? 'new'} button={currentPerson ? 'Guardar cambios' : 'Crear persona'} action={async data => {
        const value = await api(person ? '/people/' + person : '/people', { method: person ? 'PUT' : 'POST', data })
        setSelection([value.id, ''])
        refresh()
      }}>
        <label>Código<input data-preserve={currentPerson ? true : undefined} name="code" defaultValue={currentPerson?.code} required /></label>
        <label>Nombre<input name="name" defaultValue={currentPerson?.name} /></label>
        <label>Notas<textarea name="notes" defaultValue={currentPerson?.notes} /></label>
        {currentPerson && <button type="button" className="secondary" onClick={() => setSelection(['', ''])}>Nueva persona</button>}
      </ActionForm>
      {currentPerson && <>
        <section className="panel"><h2>Lesiones de {personLabel(currentPerson)}</h2>
          <div className="row-list">{lesions?.map(item => <button className="list-row" key={item.id} onClick={() => {
            setSelection([person, item.id])
            navigate('followup')
          }}>{item.name}<small>{item.site || 'Abrir seguimiento'}</small></button>)}
          {lesions?.length === 0 && <p>Registra la primera lesión de esta persona.</p>}</div>
        </section>
        <ActionForm title="Nueva lesión" button="Registrar lesión" action={async data => {
          const value = await api('/people/' + person + '/lesions', { method: 'POST', data })
          setSelection([person, value.id])
          navigate('followup')
        }}><label>Nombre de la lesión<input name="name" required /></label><label>Zona del cuerpo<input name="site" /></label></ActionForm>
      </>}
    </div> : <>
      {currentPerson && <div className="breadcrumbs" aria-label="Ubicación en el archivo">
        <a href="#people">Personas</a><span>/</span>
        <span>{personLabel(currentPerson)}</span>
        {currentLesion && <><span>/</span><span>{currentLesion.name}</span><span>/</span>
          <strong>{{followup:'Seguimiento', compare:'Comparaciones', reports:'Informes y video'}[page]}</strong></>}
      </div>}
      <div className="panel filters">
        <label>Persona<select value={person} onChange={event => setSelection([event.target.value, ''])}>
          <option value="">Seleccionar persona</option>{people?.map(p => <option key={p.id} value={p.id}>{personLabel(p)}</option>)}</select></label>
        <label>Lesión<select value={lesion} disabled={!person} onChange={event => setSelection([person, event.target.value])}>
          <option value="">Seleccionar lesión</option>{lesions?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      </div>
      {!lesion && <div className="panel empty">Selecciona una persona y una lesión. Si aún no las tienes, ve a Personas.</div>}
      {lesion && page === 'followup' && <div className="followup-grid">
        <section className="panel"><div className="panel-heading"><h2>Historial fotográfico</h2>
          {visits.length > 0 && <button type="button" className="secondary" aria-expanded={visitForm === lesion}
            onClick={() => setVisitForm(visitForm === lesion ? '' : lesion)}>{visitForm === lesion ? 'Cerrar formulario' : 'Agregar visita'}</button>}</div>
          {detail && !visits.length && <p>Agrega la primera foto para iniciar el seguimiento.</p>}
          {trashed && <button className="secondary" onClick={async () => {
            try {
              await api('/visits/' + trashed + '/restore', { method: 'POST' })
              setTrashed('')
              refresh()
            } catch (err) { setActionError(err.message) }
          }}>Deshacer envío a papelera</button>}
          <div className="visit-gallery timeline">{visits.map(row =>
            <VisitCard key={row.id} row={row} refresh={refresh} onTrash={setTrashed}
              selected={selectedVisits.some(visit => visit.id === row.id)} selectionFull={selectedVisits.length === 2}
              onSelect={() => setPairs(current => {
                const ids = selectedVisits.map(visit => visit.id)
                return { ...current, [lesion]: ids.includes(row.id) ? ids.filter(id => id !== row.id) : [...ids, row.id] }
              })} />)}</div>
          {visits.length > 0 && <div className="actions followup-actions">
            {visits.length >= 2 && <button className="secondary" onClick={() => navigate('compare')}>{selectedVisits.length === 2 ? 'Comparar seleccionadas' : 'Comparar visitas'}</button>}
            <button className="secondary" onClick={() => navigate('reports')}>Exportar seguimiento</button>
          </div>}
        </section>
        {(!visits.length || visitForm === lesion) && <VisitForm key={lesion + '-' + rev} lesion={lesion} refresh={() => { setVisitForm(''); refresh() }} />}
      </div>}
      {lesion && page === 'compare' && <div className="followup-grid">
        {visits.length >= 2 ? <ActionForm title="Nueva comparación" key={lesion} button="Comparar y guardar" action={async data => {
          if (data.previous === data.current) throw new Error('Elige dos fotografías diferentes.')
          const value = await api('/comparisons', { method: 'POST', data })
          setComparison(value.id)
          refresh()
        }}>
          {['previous', 'current'].map((key, index) => <label key={key}>{index ? 'Visita posterior' : 'Visita inicial'}
            <select name={key} defaultValue={(selectedVisits.length === 2 ? selectedVisits : visits)[index].id}>{visits.map(v => <option key={v.id} value={v.id}>{v.label} · {dateLabel(v.captured_at)}</option>)}</select></label>)}
          <label>Tipo de comparación<select name="mode"><option value="longitudinal">Seguimiento temporal</option><option value="visual">Solo visual</option></select></label>
        </ActionForm> : <section className="panel">Registra dos fotos para poder compararlas.</section>}
        <section className="panel"><h2>Comparaciones guardadas</h2>
          {comparisons.length ? <label>Mostrar comparación<select value={comparison} onChange={event => setComparison(event.target.value)}>
            <option value="">Seleccionar</option>{comparisons.map(c => <option key={c.id} value={c.id}>{dateLabel(c.live_previous_date)} → {dateLabel(c.live_current_date)}</option>)}</select></label> : <p>Las comparaciones aparecerán aquí.</p>}
          {activeComparison && <><p>{activeComparison.stale_dates ? 'Las fechas cambiaron. Vuelve a comparar las visitas.' : activeComparison.result.reason || activeComparison.result.status || (activeComparison.result.comparable ? 'Comparación disponible.' : 'Revisión visual disponible.')}</p>
            <div className="visit-gallery">{[[previousVisit, 'Anterior'], [currentVisit, 'Posterior']].map(([visit, title]) => visit &&
              <figure key={title}><img src={'/api/visits/' + visit.id + '/photo'} alt={title + ' de la comparación'} />
                <figcaption>{title} · {dateLabel(visit.captured_at)}</figcaption></figure>)}</div>
            {!activeComparison.stale_dates && activeComparison.result.comparable && typeof activeComparison.result.change_index === 'number' && <p>Índice visual de cambio <strong>{activeComparison.result.change_index.toFixed(1)} / 100</strong><br /><small>Medida descriptiva de las diferencias entre fotografías.</small></p>}
            {activeComparison.overlay && <img className="visit-preview" src={'/api/lesions/' + lesion + '/comparisons/' + activeComparison.id + '/map'} alt="Mapa de diferencias de la comparación" />}</>}
        </section>
      </div>}
      {lesion && page === 'reports' && <Downloads key={lesion} lesion={lesion} visits={visits} />}
    </>}
  </section>
}
