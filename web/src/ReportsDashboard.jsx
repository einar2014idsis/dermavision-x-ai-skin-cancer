import { useEffect, useRef, useState } from 'react'
import './ReportsDashboard.css'

const sections = [
  ['identity', 'Datos de identificación de persona y lesión'],
  ['photos', 'Fotografías del seguimiento'],
  ['classifications', 'Clasificaciones experimentales'],
  ['charts', 'Gráfico de evolución'],
  ['measurements', 'Mediciones de área, asimetría, bordes, color y textura'],
  ['maps', 'Mapas de diferencias visuales'],
  ['summary', 'Resumen descriptivo de la evolución'],
  ['observations', 'Observaciones registradas'],
]
const defaultSections = sections.map(([id]) => id)
const defaultVideo = { seconds: 4, show_date: true, show_label: true, transition: 'cut' }
const date = value => value ? value.slice(0, 10).split('-').reverse().join('/') : '—'
const elapsed = (before, after) => Math.floor((Date.parse(after + 'Z') - Date.parse(before + 'Z')) / 86400000)
const photo = visit => '/api/visits/' + visit.id + '/photo'
const caption = visit => visit.label + ' · ' + date(visit.captured_at)
const quality = visit => {
  const checks = (visit.metadata.capture_quality || visit.metadata.classification?.quality)?.checks
  return checks?.length ? (checks.every(Boolean) ? 'Calidad adecuada' : 'Calidad por revisar') : ''
}

function useReleaseUrl(url) {
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
}

function download(url, name) {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
}

function Stats({ visits, stats, Icon }) {
  const start = visits[0]?.captured_at
  const end = visits.at(-1)?.captured_at
  const days = start ? elapsed(start, end) : 0
  const cards = [
    ['scan', visits.length, 'Visitas registradas'],
    ['timeline', start ? date(start) + ' – ' + date(end) : '—', 'Periodo de seguimiento', start ? days + (days === 1 ? ' día' : ' días') : ''],
    ['compare', stats.evaluable + ' de ' + stats.pairs, 'Comparaciones evaluables'],
    ['report', stats.classified, 'Visitas con clasificación'],
  ]
  return <section className="panel report-stats">
    <h2>Resumen del seguimiento</h2>
    <dl>{cards.map(([icon, value, label, note]) => <div key={label}>
      <Icon name={icon} size={20} /><dt>{label}</dt><dd>{value}</dd>{note && <small>{note}</small>}
    </div>)}</dl>
  </section>
}

export default function ReportsDashboard({ lesion, detail, filters, api, settings, onSettings, Icon, comparisonId }) {
  const visits = detail?.visits ?? []
  const enabled = visits.length > 0
  const selectedSections = settings?.sections ?? defaultSections
  const video = settings?.video ?? defaultVideo
  const [preview, setPreview] = useState(null)
  const [update, setUpdate] = useState(0)
  const [videoUrl, setVideoUrl] = useState('')
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selected, setSelected] = useState(0)
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const player = useRef(null)
  const videoRequest = useRef(null)
  const url = preview?.url
  useReleaseUrl(url)
  useReleaseUrl(videoUrl)
  const currentPreview = preview?.sections === selectedSections && preview?.version === update && preview?.detail === detail
  const pdfReady = currentPreview && url
  const current = visits[Math.min(selected, visits.length - 1)]
  const path = '/lesions/' + lesion + '/reports/'
  const duration = visits.length * video.seconds
  const comparison = detail?.comparisons.find(row => row.id === comparisonId)

  useEffect(() => () => videoRequest.current?.abort(), [])

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    const delay = setTimeout(async () => {
      try {
        const blob = await api(path + 'pdf', { method: 'POST', data: { sections: selectedSections }, signal: controller.signal })
        if (!controller.signal.aborted) setPreview({ sections: selectedSections, url: URL.createObjectURL(blob), version: update, detail })
      } catch (failure) {
        if (!controller.signal.aborted) setPreview({ sections: selectedSections, error: failure.message, version: update, detail })
      }
    }, 400)
    return () => {
      clearTimeout(delay)
      controller.abort()
    }
  }, [api, path, enabled, selectedSections, update, detail])

  function changeVideo(option, value) {
    setVideoUrl('')
    setTime(0)
    setPlaying(false)
    setError('')
    setNotice('')
    onSettings({ ...settings, video: { ...video, [option]: value } })
  }
  function position(index) {
    const bounded = Math.max(0, Math.min(index, visits.length - 1))
    setSelected(bounded)
    if (player.current) player.current.currentTime = bounded * video.seconds
  }
  async function run(message, action) {
    setProgress(message)
    setError('')
    setNotice('')
    try { await action() } catch (failure) { setError(failure.message) } finally { setProgress('') }
  }
  async function generate() {
    const controller = new AbortController()
    videoRequest.current = controller
    await run('Preparando fotografías y codificando el video…', async () => {
      const blob = await api(path + 'video', { method: 'POST', data: video, signal: controller.signal })
      if (controller.signal.aborted) return
      setVideoUrl(URL.createObjectURL(blob))
      setSelected(0)
      setTime(0)
      setPlaying(false)
      setNotice('Video listo para reproducir y descargar.')
    })
    videoRequest.current = null
  }
  async function exportCsv() {
    await run('Preparando las mediciones en CSV…', async () => {
      const csv = await api(path + 'csv')
      const csvUrl = URL.createObjectURL(csv)
      download(csvUrl, 'seguimiento.csv')
      setTimeout(() => URL.revokeObjectURL(csvUrl), 1000)
      setNotice('Descarga del CSV iniciada.')
    })
  }
  async function exportPdf(pair = false) {
    await run('Preparando el PDF…', async () => {
      const blob = pair ? await api('/lesions/' + lesion + '/comparisons/' + comparison.id + '/export/pdf')
        : await api(path + 'pdf?archive=true', { method: 'POST', data: { sections: selectedSections } })
      const fileUrl = URL.createObjectURL(blob)
      download(fileUrl, pair ? 'comparacion.pdf' : 'seguimiento.pdf')
      setTimeout(() => URL.revokeObjectURL(fileUrl), 1000)
      setNotice('Descarga del PDF iniciada. El documento está disponible en la ficha del paciente.')
    })
  }

  return <div className="reports-grid">
    <section className="panel report-select">
      <h2>Selección de seguimiento</h2><div>{filters}</div>
    </section>
    {!lesion && <section className="panel module-empty"><Icon name="report" size={40} /><h2>Prepara el informe y el video de una lesión</h2>
      <p>Selecciona una persona y una lesión. Después podrás revisar sus visitas reales y generar los formatos disponibles.</p></section>}
    {lesion && !detail && <p className="panel report-select" role="status">Cargando el seguimiento…</p>}
    {detail && <>
      <Stats visits={visits} stats={detail.report_stats} Icon={Icon} />
      {!enabled && <p className="panel report-select">Registra una fotografía en Seguimiento para generar un informe o video.</p>}
      <section className="panel report-pdf">
        <h2>Informe del seguimiento (PDF)</h2>
        <div className="report-split">
          <div className="report-sheet">
            {pdfReady ? <>
              <iframe title="Vista previa del informe PDF" src={url + '#view=FitH&toolbar=0'} />
              <button type="button" className="secondary" onClick={() => setExpanded(true)}>Ampliar vista previa</button>
              {expanded && <dialog ref={node => { if (node && !node.open) node.showModal() }} onClose={() => setExpanded(false)} className="report-dialog" aria-label="Vista ampliada del informe">
                <button type="button" autoFocus className="secondary" onClick={() => setExpanded(false)}>Cerrar vista previa</button>
                <iframe title="Informe PDF ampliado" src={url + '#view=FitH'} />
              </dialog>}
            </> : <p role="status">{enabled ? (currentPreview && preview?.error
              ? preview.error : 'Generando la vista previa del PDF…') : 'Vista previa disponible al registrar fotografías.'}</p>}
            {currentPreview && preview?.error &&
              <button type="button" className="secondary" onClick={() => setUpdate(value => value + 1)}>Reintentar vista previa</button>}
          </div>
          <fieldset disabled={!enabled} className="report-options">
            <legend>Contenido del informe</legend>
            {sections.map(([id, label]) => <label key={id}><input type="checkbox" checked={selectedSections.includes(id)} onChange={event => {
              setExpanded(false)
              onSettings({ ...settings, sections: event.target.checked ? [...selectedSections, id] : selectedSections.filter(item => item !== id) })
            }} /> {label}</label>)}
            <aside>Informe experimental. Describe cambios visuales y requiere revisión profesional.</aside>
          </fieldset>
        </div>
      </section>
      <section className="panel report-video">
        <h2>{visits.length === 1 ? 'Video de una visita (MP4)' : 'Video de evolución fotográfica (MP4)'}</h2>
        <div className="report-split">
          <div className="report-player">
            {videoUrl ? <video ref={player} src={videoUrl} controls preload="metadata" aria-label="Video de seguimiento"
              onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)}
              onTimeUpdate={event => {
                const seconds = event.currentTarget.currentTime
                setTime(seconds)
                setSelected(Math.min(visits.length - 1, Math.floor(seconds / video.seconds)))
              }} />
              : current ? <img src={photo(current)} alt={'Fotografía de ' + caption(current)} /> : <p>Agrega una visita en Seguimiento.</p>}
            {current && <div className="report-player-detail">
              <span>{caption(current)}</span><span>{Math.floor(time)} / {duration} s</span>
            </div>}
            {videoUrl && <div className="report-actions">
              <button type="button" className="secondary" onClick={() => {
                if (player.current.paused) player.current.play().catch(() => setError('El navegador no pudo reproducir el video.'))
                else player.current.pause()
              }}>{playing ? 'Pausar' : 'Reproducir'}</button>
              <button type="button" className="secondary" onClick={() => position(0)}>Reiniciar</button>
              <button type="button" className="secondary" disabled={selected >= visits.length - 1} onClick={() => position(selected + 1)}>Avanzar visita</button>
            </div>}
          </div>
          <fieldset className="report-options" disabled={!enabled || !!progress}>
            <legend>Configuración del video</legend>
            <label>Duración por fotografía<select value={video.seconds} onChange={event => changeVideo('seconds', Number(event.target.value))}>
              {[2, 3, 4, 5].map(value => <option value={value} key={value}>{value} segundos</option>)}
            </select></label>
            <label className="report-switch"><input type="checkbox" checked={video.show_date} onChange={event => changeVideo('show_date', event.target.checked)} /> Mostrar fecha de captura</label>
            <label className="report-switch"><input type="checkbox" checked={video.show_label} onChange={event => changeVideo('show_label', event.target.checked)} /> Mostrar identificador de visita</label>
            <label>Transición entre fotografías<select value={video.transition} disabled={visits.length < 2} onChange={event => changeVideo('transition', event.target.value)}>
              <option value="cut">Sin transición</option><option value="fade">Desvanecido suave</option>
            </select></label>
            <small>{visits.length === 1 ? 'Incluye una sola fotografía.' : 'Orden de las visitas: de la primera a la más reciente.'}</small>
          </fieldset>
        </div>
      </section>
      <section className="panel report-history">
        <h2>Historial fotográfico</h2>
        {enabled ? <ol>{visits.map((visit, index) => <li key={visit.id}>
          <button type="button" className="secondary" aria-pressed={index === selected} onClick={() => position(index)}>
            <img src={photo(visit)} alt="" loading="lazy" /><strong>{visit.label}</strong><span>{date(visit.captured_at)}</span>
            {quality(visit) && <small>{quality(visit)}</small>}
          </button>
        </li>)}</ol> : <p>Todavía no hay fotografías registradas.</p>}
      </section>
      <section className="panel report-downloads">
        <h2>Formatos de exportación</h2>
        {comparison && <p>Comparación seleccionada · {date(comparison.live_previous_date)} → {date(comparison.live_current_date)}</p>}
        <div className="report-actions">
          <button type="button" disabled={!pdfReady || !!progress} onClick={() => exportPdf()}><Icon name="report" size={16} /> Descargar informe PDF</button>
          {comparison && <button type="button" className="secondary" disabled={!!progress} onClick={() => exportPdf(true)}>Descargar informe de las dos visitas</button>}
          <button type="button" className="secondary" disabled={!enabled || !!progress} onClick={generate}>Generar video MP4</button>
          <button type="button" className="secondary" disabled={!enabled || !!progress} onClick={exportCsv}>Exportar datos CSV</button>
          {videoUrl && <button type="button" className="secondary" onClick={() => { download(videoUrl, 'seguimiento.mp4'); setNotice('Descarga del MP4 iniciada.') }}>Descargar video MP4</button>}
        </div>
        {progress && <p role="status" className="report-progress">{progress}</p>}
        {notice && <p role="status">{notice}</p>}
        {error && <p className="error" role="alert">{error}</p>}
      </section>
    </>}
  </div>
}
