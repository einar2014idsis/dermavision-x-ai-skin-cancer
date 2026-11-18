import { useRef, useState } from 'react'
import AnatomyMap from './AnatomyMap'
import { anatomyRegions, regionById, regionCenter, viewNames } from './anatomy'
import { ActionForm, VisitForm } from './Followup'
import { api, useData } from './api'
import './Workspace.css'

const dateTime = new Intl.DateTimeFormat('es-PE', { dateStyle: 'short', timeStyle: 'short' })
const date = value => value ? value.slice(0, 10).split('-').reverse().join('/') : 'No registrado'
const timestamp = value => value ? dateTime.format(new Date(value)) : 'No registrado'
const text = value => value || 'No registrado'
const activityNames = {
  patient: 'Registro de paciente', lesion: 'Registro de lesión', visit: 'Registro de visita',
  analysis: 'Análisis de fotografía', comparison: 'Comparación de fotografías', document: 'Generación de documento',
}
const assessment = ({ state, label } = {}) => state === 'accepted'
  ? (label === 'malignant' ? 'Experimental · maligna' : 'Experimental · benigna')
  : ({ uncertain: 'No concluyente', rejected: 'Imagen rechazada', quality_failed: 'Calidad insuficiente',
    stale: 'Requiere actualizarse' })[state] || 'Análisis pendiente'

function Link({ to, children, primary = false, ...props }) {
  return <a className={'workspace-button' + (primary ? ' primary' : '')} href={'#' + to} {...props}>{children}</a>
}
function Header({ title, description, children }) {
  return <header className="workspace-heading"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>
    {children && <div className="workspace-actions">{children}</div>}</header>
}
function Pending({ error }) {
  return <p className={error ? 'error' : undefined} role={error ? 'alert' : 'status'}>{error || 'Cargando…'}</p>
}
function Facts({ items }) {
  return <dl className="workspace-facts">{items.map(([key, value]) =>
    <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
}
function fileLink(person, item) {
  return '/api/people/' + person + '/documents/' + item.id
}
function Documents({ person, items }) {
  return items.length ? <div className="workspace-table"><table>
    <thead><tr>{['Documento', 'Lesión', 'Generado', 'Formato', 'Acciones'].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
    <tbody>{items.map(item => <tr key={item.id}><td>{item.title}</td><td>{item.lesion}</td><td>{timestamp(item.created)}</td>
      <td>{item.format.toUpperCase()}</td><td><div className="workspace-actions">
        <a target="_blank" rel="noopener noreferrer" href={fileLink(person, item) + '?preview=true'}>Abrir</a>
        <a href={fileLink(person, item)}>Descargar</a>
      </div></td></tr>)}</tbody></table></div> : <p>Aún no hay documentos guardados. Se incorporarán al generar un video o descargar un PDF.</p>
}

function Home({ Icon, selection }) {
  const [data, error] = useData('/workspace', 0)
  const [showAll, setShowAll] = useState(false)
  const [person, lesion] = selection
  const scope = person && lesion ? '/' + person + '/' + lesion : ''
  const labels = [['people', 'Pacientes registrados', 'patients'], ['scan', 'Lesiones registradas', 'lesions'],
    ['chart', 'Análisis realizados', 'analyses'], ['timeline', 'Seguimientos activos', 'followups']]
  return <>
    <div className="workspace-hero"><img className="workspace-hero-image" src="/home-banner-v4.png" alt="" /><Header title="Bienvenido a DermaVision X"
      description="Sistema de análisis experimental y seguimiento fotográfico de lesiones cutáneas." /></div>
    {error && <Pending error={error} />}
    <dl className="workspace-metrics">{labels.map(([icon, label, key]) => <div className="panel" key={key}>
      <Icon name={icon} /><dt>{label}</dt><dd>{data ? data.metrics[key] : '—'}</dd>
      {key === 'followups' && <small>Lesiones con al menos dos visitas</small>}
    </div>)}</dl>
    <div className="workspace-split">
      <section className="panel"><div className="workspace-toolbar"><h2><Icon name="timeline" /> Actividad reciente</h2>
        {data?.activity.length > 8 && <button className="secondary" onClick={() => setShowAll(value => !value)}>{showAll ? 'Ver menos' : 'Ver más'}</button>}</div>
        {!data ? <Pending error={error} /> : data.activity.length ? <div className="workspace-table"><table>
          <thead><tr>{['Fecha y hora', 'Paciente', 'Lesión', 'Actividad', 'Estado', 'Registro'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
          <tbody>{data.activity.slice(0, showAll ? undefined : 8).map((row, index) => {
            const scope = row.person_id + '/' + row.lesion_id
            const route = row.kind === 'comparison' ? 'compare/' + scope + '/' + row.item
              : row.visit_id ? 'lesion/' + scope + '/' + row.visit_id
              : row.lesion_id ? 'lesion/' + scope : 'patient/' + row.person_id
            return <tr key={row.kind + ':' + index}><td>{timestamp(row.at)}</td><td>{row.code}</td>
              <td>{row.lesion || '—'}</td><td>{activityNames[row.kind]}</td><td><span className="workspace-tag">{row.state}</span></td>
              <td>{row.kind === 'document' ? <a href={fileLink(row.person_id, { id: row.item }) + '?preview=true'} target="_blank" rel="noopener noreferrer">Ver documento</a>
                : <a href={'#' + route}>Consultar</a>}</td></tr>
          })}</tbody>
        </table></div> : <p>Aún no hay pacientes registrados.</p>}
      </section>
      <section className="panel"><h2><Icon name="arrow" /> Acciones rápidas</h2>
        <div className="workspace-quick"><Link to="people?focus=register" primary>Registrar paciente</Link>
          <Link to="people?focus=search">Buscar paciente</Link><Link to={'visit' + scope}>Registrar nueva visita</Link>
          <Link to={'followup' + scope}>Consultar seguimiento</Link><Link to={'reports' + scope}>Generar informe</Link></div>
      </section>
    </div>
  </>
}

function Patient({ person, created, Icon }) {
  const [profile, error] = useData('/people/' + person + '/profile', 0)
  if (!profile) return <Pending error={error} />
  const patient = profile.person
  return <>
    <nav className="workspace-crumbs" aria-label="Ubicación"><a href="#people">Personas</a><span>›</span><strong>{patient.code}</strong></nav>
    <Header title={'Paciente ' + patient.code} description="Consulta sus datos, lesiones registradas, visitas y documentos disponibles">
      <Link to="people">Volver al directorio</Link><Link to={'people?edit=' + person}>Editar persona</Link>
      <Link to={'new-lesion/' + person} primary>Registrar nueva lesión</Link>
    </Header>
    {created && <p className="workspace-result" role="status">Paciente registrado correctamente.</p>}
    <div className="workspace-profile">
      <section className="panel"><h2><Icon name="people" /> Información general</h2><Facts items={[
        ['Código', patient.code], ['Nombre', text(patient.name)], ['Edad o fecha de nacimiento', text(patient.birth_date)],
        ['Sexo', text(patient.sex)], ['Fecha de registro', date(patient.created)], ['Observaciones', text(patient.notes)],
      ]} /></section>
      <section className="panel"><h2><Icon name="scan" /> Lesiones registradas</h2>
        {profile.lesions.length ? <div className="workspace-table"><table>
          <thead><tr>{['Código', 'Localización', 'Visitas', 'Última fotografía', 'Acciones'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
          <tbody>{profile.lesions.map(lesion => <tr key={lesion.id}><th scope="row">{lesion.name}</th><td>{text(lesion.site)}</td>
            <td>{lesion.visits}</td><td>{date(lesion.latest)}</td><td><div className="workspace-actions">
              <a href={'#lesion/' + person + '/' + lesion.id}>Ver lesión</a>
              <a href={'#new-lesion/' + person + '/' + lesion.id}>Editar</a>
              <a href={'#followup/' + person + '/' + lesion.id}>Abrir seguimiento</a>
            </div></td></tr>)}</tbody></table></div> : <p>Este paciente todavía no tiene lesiones registradas.</p>}
      </section>
      <section className="panel"><h2><Icon name="timeline" /> Visitas realizadas</h2>
        <div className="workspace-visits">{profile.visits.map(visit => <a key={visit.id}
          href={'#lesion/' + person + '/' + visit.lesion_id + '/' + visit.id}>
          <img src={'/api/visits/' + visit.id + '/photo'} alt="" loading="lazy" />
          <span><strong>{visit.label} · {visit.lesion}</strong><br />{date(visit.captured_at)} · {text(visit.site)}<br />{assessment(visit.classification)}</span>
        </a>)}</div>{!profile.visits.length && <p>Aún no hay visitas registradas.</p>}
      </section>
      <section className="panel"><h2><Icon name="report" /> Informes disponibles</h2><Documents person={person} items={profile.documents} /></section>
    </div>
  </>
}

const anatomyGroups = Object.entries(viewNames).flatMap(([view, title]) => {
  const regions = anatomyRegions.filter(region => region.view === view)
  return [...new Set(regions.map(region => region.group))].map(group => ({
    name: title + ' · ' + group, regions: regions.filter(region => region.group === group),
  }))
})

function LesionEditor({ person, item, profile, navigate }) {
  const [marker, setMarker] = useState(item?.location || null)
  const [view, setView] = useState(regionById.get(item?.location?.region_id)?.view || item?.body_view || 'front')
  const [name, setName] = useState(item?.name ?? null)
  const [dirty, setDirty] = useState(false)
  const [description, setDescription] = useState(item?.description || '')
  const [notes, setNotes] = useState(item?.notes || '')
  const [suggestionVersion, requestSuggestion] = useState(0)
  const [suggestion, codeError] = useData(item ? null : '/people/' + person + '/lesion-code', suggestionVersion)
  const locationSelect = useRef(null)
  const legacy = item != null && !item.location
  const selected = regionById.get(marker?.region_id)
  const directory = 'patient/' + person
  const returnTo = item ? 'lesion/' + person + '/' + item.id : directory
  const [localDate] = useState(() => {
    const today = new Date()
    return new Date(today.getTime() - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
  })

  function choose(next) {
    setMarker(next)
    setView(regionById.get(next.region_id).view)
    setDirty(true)
  }
  function chooseFromSelect(value) {
    const region = regionById.get(value)
    if (region) choose(regionCenter(region))
    else {
      setMarker(null)
      setView(item?.body_view || 'front')
      setDirty(true)
    }
  }

  return <div className="lesion-editor" data-dirty={dirty ? 'true' : undefined} onChange={() => setDirty(true)}>
    <nav className="workspace-crumbs" aria-label="Ubicación"><a href="#people">Personas</a><span>›</span>
      <a href={'#' + directory}>{profile.person.code}</a><span>›</span><strong>{item ? 'Editar lesión' : 'Registrar lesión'}</strong></nav>
    <Header title={item ? 'Editar lesión ' + item.name : 'Registrar nueva lesión'}
      description="Registra la localización y las características iniciales de la lesión." />
    <div className="lesion-editor-grid">
      <ActionForm className="lesion-form" button="Guardar lesión" disabled={!item && name === null && !suggestion}
        cancel={<button type="button" className="secondary" onClick={() => navigate(returnTo)}>Cancelar</button>}
        action={async data => {
          if (!marker && !legacy) throw new Error('Selecciona una región anatómica para guardar la lesión.')
          const route = '/people/' + person + '/lesion-details' + (item ? '/' + item.id : '')
          const saved = await api(route, { method: item ? 'PUT' : 'POST', data: {
            ...data, site: selected?.label || item?.site || '', location: marker,
            body_view: selected?.view || item?.body_view || 'front', automatic_code: !item && name === null,
          } })
          setDirty(false)
          navigate('lesion/' + person + '/' + saved.id + '?saved=1', true)
        }}>
        <div className="lesion-code-row">
          <label>Código de lesión<input name="name" value={name ?? suggestion?.code ?? ''}
            onChange={event => setName(event.target.value)} maxLength={160} required /></label>
          {!item && <button type="button" className="secondary" onClick={() => {
            setName(null)
            requestSuggestion(value => value + 1)
          }}>Generar código automático</button>}
        </div>
        {codeError && <p className="error" role="alert">{codeError}</p>}
        <label>Persona asociada<input value={profile.person.code + (profile.person.name ? ' · ' + profile.person.name : '')} readOnly /></label>
        <label>Localización anatómica<select ref={locationSelect} required value={marker?.region_id || (legacy ? 'legacy' : '')}
          onChange={event => chooseFromSelect(event.target.value)}>
          <option value="" disabled>Seleccionar una región</option>
          {legacy && <option value="legacy">{item.site ? item.site + ' (ubicación histórica)' : 'Sin localización registrada'}</option>}
          {anatomyGroups.map(group => <optgroup label={group.name} key={group.name}>
            {group.regions.map(region => <option key={region.id} value={region.id}>{region.label}</option>)}
          </optgroup>)}
        </select></label>
        <label>Descripción inicial<textarea name="description" value={description}
          onChange={event => setDescription(event.target.value)} maxLength={300} required /><small className="character-count">{description.length} / 300</small></label>
        <label>Fecha de registro<input name="registered_on" type="date" defaultValue={item?.registered_on || item?.created.slice(0, 10) || localDate} required /></label>
        <label>Observaciones<textarea name="notes" value={notes} onChange={event => setNotes(event.target.value)}
          maxLength={500} /><small className="character-count">{notes.length} / 500</small></label>
      </ActionForm>
      <AnatomyMap view={view} marker={marker} legacySite={legacy ? item.site : ''} onSelect={choose}
        onView={setView} onChangeLocation={() => locationSelect.current?.focus()} />
    </div>
  </div>
}

function LesionForm({ person, lesion, navigate }) {
  const [profile, error] = useData('/people/' + person + '/profile', 0)
  if (!profile) return <Pending error={error} />
  const item = profile.lesions.find(row => row.id === lesion)
  if (lesion && !item) return <Pending error="Esta lesión no pertenece al paciente seleccionado." />
  return <LesionEditor person={person} item={item} profile={profile} navigate={navigate} />
}

function LesionProfile({ person, lesion, visit, saved, navigate, Icon }) {
  const [revision, setRevision] = useState(0)
  const [profile, error] = useData('/people/' + person + '/profile', revision)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  if (!profile) return <Pending error={error} />
  const item = profile.lesions.find(row => row.id === lesion)
  if (!item) return <Pending error="Esta lesión no pertenece al paciente seleccionado." />
  const visits = profile.visits.filter(row => row.lesion_id === lesion).reverse()
  const current = visits.find(row => row.id === visit)
  const focus = current || visits[0]
  const scope = person + '/' + lesion
  async function analyze(id) {
    setBusy(true)
    setMessage('')
    try {
      const result = await api('/visits/' + id + '/analyze', { method: 'POST' })
      setMessage(result.state === 'unavailable' ? 'El modelo no está disponible para esta visita.' : 'Análisis guardado correctamente.')
      setRevision(value => value + 1)
      if (id !== visit) navigate('lesion/' + scope + '/' + id)
    } catch (failure) { setMessage(failure.message) } finally { setBusy(false) }
  }
  return <>
    <nav className="workspace-crumbs" aria-label="Ubicación"><a href="#people">Personas</a><span>›</span>
      <a href={'#patient/' + person}>{profile.person.code}</a><span>›</span><strong>{item.name}</strong></nav>
    <Header title={'Lesión ' + item.name} description={profile.person.code + ' · ' + text(item.site)}>
      <Link to={'patient/' + person}>Volver a la ficha</Link><Link to={'new-lesion/' + scope}>Editar lesión</Link>
      <Link to={'visit/' + scope} primary>{visits.length ? 'Registrar nueva visita' : 'Registrar primera fotografía'}</Link>
    </Header>
    {saved && <p className="workspace-result" role="status">{saved === 'visit' ? 'Visita guardada correctamente.' : 'Lesión guardada correctamente.'}</p>}
    <div className="workspace-actions workspace-shortcuts">
      <Link to={'followup/' + scope + (visit ? '/' + visit : '')}>Consultar seguimiento</Link>
      {visits.length >= 2 && <Link to={'compare/' + scope}>Comparar fotografías</Link>}
      {visits.length > 0 && <Link to={'reports/' + scope}>Generar informe</Link>}
      {focus && <button className="secondary" disabled={busy} onClick={() => analyze(focus.id)}>{busy ? 'Analizando…' : 'Analizar fotografía ' + focus.label}</button>}
      <Link to="analyze">Análisis independiente</Link>
    </div>
    {message && <p className="workspace-result" role="status">{message}</p>}
    <div className="workspace-profile">
      <section className="panel"><h2><Icon name="scan" /> Resumen</h2><Facts items={[
        ['Paciente', profile.person.code], ['Localización anatómica', text(item.site)], ['Fecha de registro', date(item.registered_on || item.created)],
        ['Primera fotografía', date(visits[0]?.captured_at)], ['Visitas', visits.length], ['Descripción inicial', text(item.description)],
        ['Observaciones', text(item.notes)],
      ]} />{item.location && <AnatomyMap view={item.body_view} marker={item.location} />}</section>
      <section className="panel"><h2><Icon name="report" /> {current ? 'Fotografía ' + current.label : 'Fotografía de referencia'}</h2>
        {focus ? <><img className="workspace-focus-photo" alt={'Fotografía de la visita ' + focus.label} src={'/api/visits/' + focus.id + '/photo'} />
          <Facts items={[[ 'Captura', date(focus.captured_at)], ['Resultado', assessment(focus.classification)], ['Observaciones', text(focus.observations)]]} />
        </> : <p>Registra la primera fotografía para comenzar el seguimiento.</p>}
      </section>
      <section className="panel"><h2>Fotografías</h2>
        {visits.length === 1 && <p>Se necesita al menos una segunda visita comparable para visualizar cambios temporales.</p>}
        <div className="workspace-visits">{visits.map(row => <a key={row.id} aria-current={row.id === focus?.id ? 'true' : undefined}
          href={'#lesion/' + scope + '/' + row.id}>
          <img src={'/api/visits/' + row.id + '/photo'} alt="" loading="lazy" /><span>{row.label} · {date(row.captured_at)}<br />{assessment(row.classification)}</span>
        </a>)}</div>
        {!visits.length && <p>Aún no hay fotografías registradas.</p>}
      </section>
      <section className="panel"><h2>Informes disponibles</h2>
        <Documents person={person} items={profile.documents.filter(row => row.lesion_id === lesion)} /></section>
    </div>
  </>
}

function VisitPicker({ navigate }) {
  const [people, error] = useData('/people', 0)
  const [person, setPerson] = useState('')
  const [lesions, lesionError] = useData(person ? '/people/' + person + '/lesions' : null, 0)
  const [scope, setScope] = useState('')
  const selectedPerson = people?.find(row => row.id === person)
  const selectedLesion = lesions?.find(row => row.id === scope)
  return <><nav className="workspace-crumbs" aria-label="Ruta de navegación"><a href="#home">Inicio</a><span>›</span><a href="#followup">Seguimiento</a><span>›</span><strong>Nueva visita</strong></nav>
    <Header title="Registrar nueva visita" description="Selecciona la persona y la lesión que vas a fotografiar."><Link to="followup">Volver a seguimiento</Link></Header>
    <div className="workspace-steps" aria-label="Etapas del registro"><strong aria-current="step">1 Seleccionar persona y lesión</strong><span>2 Capturar y revisar fotografía</span><span>3 Guardar visita</span></div>
    {(error || lesionError) && <Pending error={error || lesionError} />}
    <div className="visit-selection-layout">
    <section className="panel workspace-picker">
      <h2>Persona y lesión</h2>
      <p>Elige a quién corresponde la fotografía y dónde se registrará la visita.</p>
      <label>Paciente<select value={person} onChange={event => { setPerson(event.target.value); setScope('') }}>
        <option value="">Seleccionar paciente</option>{people?.map(row => <option key={row.id} value={row.id}>{row.code} · {row.name}</option>)}</select></label>
      <label>Lesión<select disabled={!person} value={scope} onChange={event => setScope(event.target.value)}>
        <option value="">Seleccionar lesión</option>{lesions?.map(row => <option key={row.id} value={row.id}>{row.name} · {row.site}</option>)}</select></label>
      {person && !lesions && !lesionError && <p role="status">Cargando lesiones…</p>}
      {lesions?.length === 0 && <Link to={'new-lesion/' + person}>Registrar una lesión</Link>}
      {people?.length === 0 && <Link to="people?focus=register">Registrar paciente</Link>}
    </section>
    <aside className="panel visit-selection-summary" aria-live="polite">
      <span className="workspace-tag">Resumen de la visita</span>
      <h2>{selectedLesion ? selectedLesion.name : 'Prepara una nueva fotografía'}</h2>
      {selectedPerson ? <Facts items={[[ 'Persona', selectedPerson.code + ' · ' + (selectedPerson.name || 'Sin nombre') ],
        ['Lesión', selectedLesion?.name || 'Selecciona una lesión'], ['Localización', selectedLesion?.site || 'Por seleccionar']]} />
        : <p>Selecciona una persona para consultar sus lesiones disponibles.</p>}
      <p>En el siguiente paso podrás cargar una foto o usar la cámara, revisar su calidad y confirmar el contorno.</p>
    </aside>
    <div className="visit-selection-footer"><Link to="followup">Cancelar</Link>
      <button disabled={!scope || !selectedLesion} onClick={() => navigate('visit/' + person + '/' + scope)}>Continuar a captura →</button>
    </div>
    </div>
  </>
}
function VisitCapture({ person, lesion, navigate }) {
  const [profile, error] = useData('/people/' + person + '/profile', 0)
  if (!profile) return <Pending error={error} />
  const item = profile.lesions.find(row => row.id === lesion)
  if (!item) return <Pending error="Esta lesión no pertenece al paciente seleccionado." />
  const scope = person + '/' + lesion
  return <>
    <nav className="workspace-crumbs" aria-label="Ruta de navegación"><a href="#home">Inicio</a><span>›</span><a href={'#followup/' + scope}>Seguimiento</a><span>›</span><a href={'#lesion/' + scope}>{item.name}</a><span>›</span><strong>Nueva visita</strong></nav>
    <Header title={item.visits ? 'Registrar nueva visita' : 'Registrar primera fotografía'}
      description={profile.person.code + ' · ' + item.name + ' · ' + text(item.site)}><Link to={'lesion/' + scope}>Volver a la lesión</Link></Header>
    <div className="workspace-steps" aria-label="Etapas del registro"><span>1 Persona y lesión seleccionadas</span><strong aria-current="step">2 Capturar y revisar fotografía</strong><span>3 Guardar visita</span></div>
    <div className="workspace-capture-layout"><div className="workspace-capture"><VisitForm key={lesion} lesion={lesion} linked hasVisits={item.visits > 0}
      refresh={id => navigate('lesion/' + scope + '/' + id + '?saved=visit', true)} /></div>
      <aside className="panel workspace-visit-context"><h2>Contexto de la lesión</h2><Facts items={[[ 'Persona', profile.person.code + ' · ' + profile.person.name], ['Lesión', item.name], ['Localización', text(item.site)], ['Visitas anteriores', item.visits ]]}/>
        <p>Antes de guardar, revisa fecha, fotografía y contorno. El resultado experimental se incorporará a esta lesión.</p>
        <Link to={'followup/' + scope}>Consultar seguimiento</Link></aside></div>
  </>
}

function Settings({ logout, sessionEnded }) {
  const [revision, setRevision] = useState(0)
  const [data, error] = useData('/settings', revision)
  const [backupStatus, setBackupStatus] = useState('')
  const [busy, setBusy] = useState(false)
  if (!data) return <Pending error={error} />
  async function backup() {
    setBusy(true)
    setBackupStatus('')
    try {
      const blob = await api('/settings/backup')
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url; link.download = 'dermavision-respaldo.zip'; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      setBackupStatus('Descarga del respaldo verificado iniciada.')
      setRevision(value => value + 1)
    } catch (failure) { setBackupStatus(failure.message) } finally { setBusy(false) }
  }
  return <><Header title="Configuración" description="Administra la cuenta local y el archivo de DermaVision X." />
    <div className="workspace-profile">
      <section className="panel"><h2>Mi cuenta</h2><Facts items={[[ 'Usuario', data.username], ['Rol', data.role], ['Tipo de cuenta', 'Cuenta local única']]} />
        <button className="secondary" onClick={logout}>Cerrar sesión</button>
      </section>
      <ActionForm title="Cambiar contraseña" button="Actualizar contraseña" action={async data => {
        if (data.replacement !== data.confirmation) throw new Error('Las contraseñas nuevas deben coincidir.')
        await api('/settings/password', { method: 'PUT', data: { current: data.current, replacement: data.replacement } })
        sessionEnded('Contraseña actualizada. Inicia sesión con la nueva contraseña.')
      }}>
        <label>Contraseña actual<input name="current" type="password" autoComplete="current-password" required maxLength={256} /></label>
        <label>Nueva contraseña<input name="replacement" type="password" autoComplete="new-password" required minLength={10} maxLength={256} /></label>
        <label>Confirmar nueva contraseña<input name="confirmation" type="password" autoComplete="new-password" required minLength={10} maxLength={256} /></label>
      </ActionForm>
      <section className="panel"><h2>Almacenamiento y respaldo</h2><Facts items={[
        ['Estado de SQLite', data.database_ok ? 'Verificación correcta' : 'Requiere revisión'],
        ['Tamaño de la base', (data.database_bytes / 1024).toFixed(1) + ' KiB'], ['Documentos guardados', data.documents],
      ]} /><button onClick={backup} disabled={busy}>{busy ? 'Preparando respaldo…' : 'Descargar respaldo verificado'}</button>
        {backupStatus && <p role="status">{backupStatus}</p>}</section>
      <section className="panel"><h2>Información del sistema</h2><Facts items={[
        ['Aplicación', 'DermaVision X · edición local'], ['Versión declarada', data.version || 'No registrada'], ['Python', data.python],
        ['Modelo seleccionado', data.model], ['Pesos del modelo', data.model_available ? 'Disponibles' : 'Pendientes'],
      ]} /><Link to="model">Abrir Evaluación</Link>
        <h3>Actividad administrativa</h3>{data.activity.length ? <ul>{data.activity.map((row, index) =>
          <li key={index}>{timestamp(row.created)} · {row.action}</li>)}</ul> : <p>Aún no hay actividad administrativa.</p>}
      </section>
    </div>
  </>
}

export default function Workspace({ route, selection, navigate, Icon, logout, sessionEnded }) {
  const { page, person, lesion, item, params } = route
  return <section className="workspace-view">
    {page === 'home' && <Home Icon={Icon} selection={selection} />}
    {page === 'patient' && <Patient person={person} created={params.get('created')} Icon={Icon} />}
    {page === 'new-lesion' && <LesionForm person={person} lesion={lesion} navigate={navigate} />}
    {page === 'lesion' && <LesionProfile person={person} lesion={lesion} visit={item} saved={params.get('saved')} navigate={navigate} Icon={Icon} />}
    {page === 'visit' && (person && lesion ? <VisitCapture person={person} lesion={lesion} navigate={navigate} /> : <VisitPicker navigate={navigate} />)}
    {page === 'settings' && <Settings logout={logout} sessionEnded={sessionEnded} />}
  </section>
}
