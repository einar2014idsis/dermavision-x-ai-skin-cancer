import { useEffect, useRef, useState } from 'react'
import Followup, { ModelResults, PeopleAccess } from './Followup'
import { api, useData } from './api'
import Workspace from './Workspace'
import './App.css'
import './Analysis.css'

const titles = {
  accepted: 'Análisis completado',
  uncertain: 'Resultado no concluyente',
  rejected: 'Imagen fuera del dominio',
  quality_failed: 'Calidad insuficiente',
  unavailable: 'Análisis no disponible',
}
const classes = { benign: 'Patrón benigno', malignant: 'Patrón maligno' }
const percent = new Intl.NumberFormat('es-PE', { style: 'percent', maximumFractionDigits: 1 })
const qualityChecks = [[1, 'Iluminación', 'Adecuada'], [2, 'Enfoque', 'Correcto'], ['framing', 'Encuadre', 'Margen suficiente'], [0, 'Resolución', 'Suficiente']]
const analysisDate = new Intl.DateTimeFormat('es-PE', { dateStyle: 'medium', timeStyle: 'short' })

function visualRows(region) {
  return [
    ['Asimetría', region ? region.asymmetry.toFixed(2) : 'No determinada'],
    ['Bordes', region ? `Irregularidad ${region.border.toFixed(2)}` : 'No determinados'],
    ['Coloración', region ? `${region.lightness_variation.toFixed(1)} puntos de variación luminosa` : 'No determinada'],
    ['Diámetro', 'Sin escala física'],
  ]
}

function download(blob, name) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function ActivationMaps({ original, result }) {
  const [method, setMethod] = useState('occlusion')
  const [view, setView] = useState('heatmap')
  const [opacity, setOpacity] = useState(50)
  const [direction, setDirection] = useState(false)
  const signed = method === 'occlusion' && direction
  const map = method === 'gradcam' ? result.gradcam : signed ? result.signed_heatmap : result.heatmap
  return <section className="analysis-inset analysis-explanation">
    <h3>{method === 'gradcam' ? 'Mapa de activación por Grad-CAM' : 'Mapa de activación por oclusión'}</h3>
    <div className="activation-controls">
      <label>Método<select value={method} onChange={event => setMethod(event.target.value)}>
        <option value="occlusion">Oclusión</option><option value="gradcam">Grad-CAM</option>
      </select></label>
      <label>Vista<select value={view} onChange={event => setView(event.target.value)}>
        <option value="heatmap">Mapa de calor</option><option value="overlay">Superposición</option>
      </select></label>
      {method === 'occlusion' && result.signed_heatmap && <label className="activation-direction">
        <input type="checkbox" checked={direction} onChange={event => setDirection(event.target.checked)} /> Mostrar dirección del efecto
      </label>}
      {view === 'overlay' && map && <label>Opacidad {opacity} %
        <input type="range" min="0" max="100" value={opacity} onChange={event => setOpacity(Number(event.target.value))} />
      </label>}
    </div>
    <div className="analysis-image-pair">
      <figure><img src={original} alt="Fotografía original" /><figcaption>Fotografía original</figcaption></figure>
      <figure>
        {map ? <div className="activation-frame">
          {view === 'overlay' && <img src={original} alt="" />}
          <img src={map} alt={view === 'overlay' ? 'Mapa superpuesto a la fotografía' : 'Mapa de activación del modelo'}
            style={view === 'overlay' ? { opacity: opacity / 100 } : undefined} />
        </div> : <p className="heatmap-empty">Mapa no disponible para esta imagen.</p>}
        <figcaption>{view === 'overlay' ? 'Superposición' : 'Mapa de activación'}</figcaption>
      </figure>
    </div>
    {map && <div className="heatmap-legend">
      <span>{signed ? 'En contra' : 'Menor influencia'}</span>
      <span className={`heatmap-scale ${signed ? 'is-signed' : ''}`} aria-hidden="true" />
      <span>{signed ? 'A favor' : 'Mayor influencia'}</span>
    </div>}
  </section>
}

function Icon({ name, size = 22 }) {
  const paths = {
    home: 'M3 10l9-7 9 7v10H3zM9 20v-7h6v7',
    settings: 'M12 3v4m0 10v4M3 12h4m10 0h4M6 6l3 3m6 6 3 3M6 18l3-3m6-6 3-3M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z',
    scan: 'M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3M3 16v3a2 2 0 0 0 2 2h3m8 0h3a2 2 0 0 0 2-2v-3M8 12h2l2-3 2 6 2-3h1',
    upload: 'M12 16V4m-4 4 4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3',
    report: 'M6 3h8l4 4v14H6zM14 3v5h4M9 12h6m-6 4h6',
    arrow: 'M5 12h14m-5-5 5 5-5 5',
    info: 'M12 11v5m0-8h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z',
    people: 'M15 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m14-6a4 4 0 0 1 5 4v2M12 7a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0Zm4-3a3.5 3.5 0 0 1 0 7',
    timeline: 'M6 4v16m4-14h9m-9 6h7m-7 6h9M4 6h4m-4 6h4m-4 6h4',
    compare: 'M3 5h7v14H3zM14 5h7v14h-7z',
    chart: 'M4 4v16h16M8 16v-4m5 4V8m5 8V5',
    menu: 'M4 6h16M4 12h16M4 18h16',
  }
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round"><path d={paths[name]} /></svg>
}

const pages = { home: 'Inicio', people: 'Personas', analyze: 'Análisis', followup: 'Seguimiento',
  compare: 'Comparaciones', reports: 'Informes y video', model: 'Evaluación', settings: 'Configuración' }
const pageIcons = { home: 'home', analyze: 'scan', people: 'people', followup: 'timeline', compare: 'compare',
  reports: 'report', model: 'chart', settings: 'settings' }
const legacyPages = new Set(['people', 'followup', 'compare', 'reports'])
const workspacePages = new Set(['patient', 'new-lesion', 'lesion', 'visit'])

function currentRoute() {
  const [path, query] = location.hash.slice(1).split('?')
  const [key, person = '', lesion = '', item = ''] = path.split('/')
  const page = Object.hasOwn(pages, key) || workspacePages.has(key) ? key : 'home'
  return { page, person, lesion, item, params: new URLSearchParams(query), hash: location.hash }
}

export default function App() {
  const [route, setRoute] = useState(currentRoute)
  const [selection, setSelection] = useState(() => [route.person, route.lesion])
  const [revision, setRevision] = useState(0)
  const [account, accountError] = useData('/session', revision)
  const [menuOpen, setMenuOpen] = useState(false)
  const [loginNotice, setLoginNotice] = useState('')
  const [ended, setEnded] = useState(false)
  const menuButton = useRef(null)
  const acceptedHash = useRef(location.hash)
  const bypassDraft = useRef(false)
  const page = route.page
  useEffect(() => {
    function update() {
      if (!bypassDraft.current && document.querySelector('[data-dirty=true]')
          && !window.confirm('Hay cambios sin guardar. ¿Salir de esta pantalla?')) {
        history.replaceState(null, '', acceptedHash.current || location.pathname + location.search)
        return
      }
      bypassDraft.current = false
      const next = currentRoute()
      acceptedHash.current = next.hash
      setRoute(next)
      if (next.person) setSelection([next.person, next.lesion])
      setMenuOpen(false)
    }
    function close(event) {
      if (!document.querySelector('[data-dirty=true]')) return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('hashchange', update)
    window.addEventListener('beforeunload', close)
    return () => {
      window.removeEventListener('hashchange', update)
      window.removeEventListener('beforeunload', close)
    }
  }, [])
  function navigate(next, saved = false) {
    if (saved) bypassDraft.current = true
    if (location.hash === '#' + next) {
      bypassDraft.current = false
      return
    }
    location.hash = next
  }
  function sessionEnded(message = '') {
    setEnded(true)
    setSelection(['', ''])
    setLoginNotice(message)
    setRevision(value => value + 1)
    navigate('home', true)
  }
  async function logout() {
    try { await api('/session', { method: 'DELETE' }) }
    catch (error) {
      if (!error.message.includes('Inicia sesión')) throw error
    }
    sessionEnded()
  }
  function loginComplete() {
    setEnded(false)
    setLoginNotice('')
    setRevision(value => value + 1)
    navigate('home', true)
  }
  const signedIn = account?.authenticated && !ended
  const sidebarPage = ['patient', 'new-lesion', 'lesion'].includes(page) ? 'people' : page === 'visit' ? 'followup' : page
  const shell = { analyze: 'analysis-shell', people: 'people-shell', followup: 'tracking-shell',
    compare: 'comparison-shell', reports: 'reports-shell' }[page] || 'workspace-shell'
  return <div className={'app-shell ' + (signedIn ? shell : 'workspace-shell workspace-login')} onKeyDown={event => {
    if (event.key === 'Escape' && menuOpen) {
      setMenuOpen(false)
      menuButton.current?.focus()
    }
  }}>
    <header className="topbar">
      <div className="topbar-inner">
        <a href="#home" className="brand"><span className="brand-mark"><Icon name="scan" /></span>DermaVision<span className="brand-x">X</span></a>
        <span className="local"><span /> {signedIn ? 'Sesión local' : 'Acceso local'}</span>
        {signedIn && <button ref={menuButton} type="button" className="mobile-menu" aria-controls="modules"
          aria-expanded={menuOpen} onClick={() => setMenuOpen(open => !open)}><Icon name="menu" /> Menú</button>}
      </div>
    </header>
    {signedIn && <nav id="modules" className={menuOpen ? 'navigation is-open' : 'navigation'} aria-label="Módulos de DermaVision">
      <div>{Object.entries(pages).map(([key, label]) =>
        <a key={key} href={'#' + key} onClick={() => {
          if (menuOpen) menuButton.current?.focus()
          setMenuOpen(false)
        }} aria-current={sidebarPage === key ? 'page' : undefined}><Icon name={pageIcons[key]} size={19} />{label}</a>)}</div>
    </nav>}
    <main>
      {!signedIn ? <>
        {loginNotice && <p role="status" className="workspace-result">{loginNotice}</p>}
        <PeopleAccess account={account} error={accountError} refresh={loginComplete} />
      </> : <>
        {page === 'analyze' && <Analysis />}
        {page === 'model' && <ModelResults />}
        {(!legacyPages.has(page) && page !== 'analyze' && page !== 'model') &&
          <Workspace key={page + ':' + route.person + ':' + route.lesion} route={route} selection={selection} navigate={navigate} Icon={Icon}
            logout={logout} sessionEnded={sessionEnded} />}
        <Followup page={legacyPages.has(page) ? page : null} selection={selection} setSelection={setSelection}
          navigate={navigate} Icon={Icon} account={account} onLogout={logout}
          intent={route.params.get('focus')} editPersonId={route.params.get('edit')}
          activeVisit={page === 'followup' ? route.item : ''}
          activeComparisonId={page === 'compare' ? route.item : ''}
          reportComparison={page === 'reports' ? route.item : ''} />
      </>}
    </main>
  </div>
}

function Analysis() {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [photoQuality, setPhotoQuality] = useState(null)
  const [qualityStep, setQualityStep] = useState(-1)
  const [error, setError] = useState('')
  const [camera, setCamera] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportMessage, setExportMessage] = useState('')
  const input = useRef(null)
  const video = useRef(null)
  const [cameraProgress, setCameraProgress] = useState(0)
  const [cameraNotice, setCameraNotice] = useState('')

  function selectPhoto(next) {
    setFile(next)
    setPreview(next ? URL.createObjectURL(next) : '')
    setResult(null)
    setPhotoQuality(null)
    setQualityStep(-1)
    setError('')
    setExportMessage('')
  }

  useEffect(() => {
    if (!camera) return
    let cancelled = false
    let timer
    let previous
    let stableSince = null
    const controller = new AbortController()
    async function reviewFrame() {
      try {
        const frame = video.current
        if (!frame?.videoWidth || frame.readyState < 2) return
        const canvas = document.createElement('canvas')
        canvas.width = frame.videoWidth
        canvas.height = frame.videoHeight
        canvas.getContext('2d').drawImage(frame, 0, 0)
        const sample = document.createElement('canvas')
        sample.width = 64
        sample.height = 64
        const context = sample.getContext('2d', { willReadFrequently: true })
        context.drawImage(canvas, 0, 0, 64, 64)
        const pixels = context.getImageData(0, 0, 64, 64).data
        let difference = 0
        if (previous) {
          for (let i = 0; i < pixels.length; i += 4) {
            difference += Math.abs(pixels[i] - previous[i]) + Math.abs(pixels[i + 1] - previous[i + 1]) + Math.abs(pixels[i + 2] - previous[i + 2])
          }
          difference /= 64 * 64 * 3
        }
        const stable = Boolean(previous) && difference < 6
        previous = pixels
        const sampledAt = performance.now()
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .92))
        if (!blob || cancelled) return
        const data = new FormData()
        data.append('file', blob, 'camara.jpg')
        const response = await fetch('/api/analyze/quality', { method: 'POST', body: data, signal: controller.signal })
        if (!response.ok) throw new Error('No se pudo comprobar la calidad de la cámara.')
        const review = await response.json()
        if (cancelled) return
        setPhotoQuality(review.quality)
        setQualityStep(qualityChecks.length + 1)
        const ready = review.quality.checks.every(Boolean) && review.quality.framing === true
        if (ready && stable) {
          if (stableSince === null) stableSince = sampledAt
          const progress = Math.min(1, (sampledAt - stableSince) / 2000)
          setCameraProgress(progress)
          setCameraNotice('Mantén la posición para capturar automáticamente.')
          if (progress === 1) {
            selectPhoto(new File([blob], 'captura.jpg', { type: 'image/jpeg' }))
            setPhotoQuality(review.quality)
            setQualityStep(qualityChecks.length + 1)
            setCamera(false)
            return
          }
        } else {
          stableSince = null
          setCameraProgress(0)
          setCameraNotice(ready ? 'Mantén la cámara fija durante dos segundos.' : 'Ajusta la imagen hasta completar los controles de calidad.')
        }
      } catch (failure) {
        if (!cancelled) {
          stableSince = null
          setCameraProgress(0)
          setCameraNotice(failure.message)
        }
      } finally {
        if (!cancelled) timer = setTimeout(reviewFrame, 400)
      }
    }
    timer = setTimeout(() => {
      setCameraProgress(0)
      setCameraNotice('Mantén la cámara fija sobre la lesión.')
      setPhotoQuality(null)
      setQualityStep(-1)
      reviewFrame()
    }, 0)
    return () => { cancelled = true; clearTimeout(timer); controller.abort() }
  }, [camera])

  useEffect(() => {
    if (!camera) return
    let stream
    let closed = false
    async function open() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
        if (closed) stream.getTracks().forEach(track => track.stop())
        else video.current.srcObject = stream
      } catch {
        if (!closed) {
          setError('No se pudo abrir la cámara. Revisa los permisos del navegador.')
          setCamera(false)
        }
      }
    }
    open()
    return () => {
      closed = true
      stream?.getTracks().forEach(track => track.stop())
    }
  }, [camera])

  function takePhoto() {
    const frame = video.current
    if (!frame?.videoWidth) return
    const canvas = document.createElement('canvas')
    canvas.width = frame.videoWidth
    canvas.height = frame.videoHeight
    canvas.getContext('2d').drawImage(frame, 0, 0)
    canvas.toBlob(blob => {
      if (!blob) return
      selectPhoto(new File([blob], 'captura.jpg', { type: 'image/jpeg' }))
      setCamera(false)
    }, 'image/jpeg', .92)
  }

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])

  async function analyze(event) {
    event.preventDefault()
    if (!file || busy) return
    setBusy(true)
    setError('')
    setExportMessage('')
    setResult(null)
    setPhotoQuality(null)
    setQualityStep(0)
    try {
      const form = new FormData()
      form.append('file', file)
      async function submitPhoto(path) {
        const response = await fetch(path, { method: 'POST', body: form })
        const payload = await response.json()
        if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'No se pudo analizar la imagen.')
        return payload
      }
      const review = await submitPhoto('/api/analyze/quality')
      setPhotoQuality(review.quality)
      for (let step = 1; step <= qualityChecks.length + 1; step++) {
        await new Promise(resolve => setTimeout(resolve, 250))
        setQualityStep(step)
      }
      const payload = review.state === 'quality_failed' ? review : await submitPhoto('/api/analyze')
      setResult({ ...payload, date: new Date().toISOString() })
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  const qualityComplete = qualityStep > qualityChecks.length
  const quality = qualityChecks.map(([index, label, pass], position) => {
    const active = busy && qualityStep === position
    const visible = photoQuality && qualityStep > position
    const check = visible ? (index === 'framing' ? photoQuality.framing : photoQuality.checks[index]) : null
    return { label, check, active, value: active ? 'Comprobando…' : check == null ? (visible ? 'Sin determinar' : 'Pendiente') : check ? pass : 'Revisar' }
  })
  const qualityPassed = quality.every(item => item.check === true)
  const traits = result?.state === 'accepted' ? visualRows(result.region_summary) : []

  async function exportReport() {
    setExporting(true)
    setExportMessage('')
    try {
      const lines = [
        analysisDate.format(new Date(result.date)),
        classes[result.label] ?? titles[result.state],
        ...(result.state === 'accepted' ? [
          `Puntuación benigna ${percent.format(1 - result.score)} | Puntuación maligna ${percent.format(result.score)}`,
          ...traits.map(([label, value]) => `${label}: ${value}`),
        ] : []),
        ...quality.map(({ label, value }) => `${label}: ${value}`),
        `Calidad general: ${qualityPassed ? 'Aceptable' : 'Por revisar'}`,
      ]
      const response = await fetch('/api/analyze/report', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lines }),
      })
      if (!response.ok) throw new Error('No se pudo generar el informe.')
      download(await response.blob(), 'dermavision-analisis.pdf')
      setExportMessage('Informe descargado.')
    } catch (failure) {
      setExportMessage(failure.message)
    } finally {
      setExporting(false)
    }
  }

  return (
    <>
      <section className="intro">
        <img className="analysis-hero-image" src="/dermatoscope-banner-v2.png" alt="" />
        <p className="eyebrow">Análisis individual</p>
        <h1>Analizar una lesión</h1>
        <p>Elige una foto clara y centrada para obtener una clasificación experimental.</p>
      </section>
      <div className="workspace analysis-workspace">
        <form className="panel" onSubmit={analyze}>
          <h2><Icon name="scan" /> Fotografía de la lesión</h2>
          <input ref={input} className="file-input" id="photo" type="file" accept="image/jpeg,image/png,image/webp" disabled={busy}
            onChange={(event) => selectPhoto(event.target.files[0] ?? null)} />
          {camera ? <video ref={video} className="camera-preview" muted playsInline autoPlay /> : <label className={`preview ${preview ? 'has-photo' : ''}`} htmlFor="photo">
            {preview ? <img src={preview} alt="Fotografía seleccionada para análisis" /> : <>
              <span className="icon-tile"><Icon name="upload" size={26} /></span>
              <strong>Seleccionar una foto</strong>
              <small>JPEG, PNG o WebP · hasta 12 MB</small>
            </>}
          </label>}
          <div className="actions analysis-photo-actions">
            <button className="secondary" type="button" disabled={busy} onClick={() => { setError(''); setCamera(!camera) }}>{camera ? 'Cerrar cámara' : 'Usar cámara'}</button>
            {camera ? <button className="secondary" type="button" onClick={takePhoto}>Capturar foto</button> :
              <button className="secondary" type="button" disabled={busy} onClick={() => input.current?.click()}>{file ? 'Cambiar foto' : 'Cargar foto'}</button>}
          </div>
          {camera && <div className="camera-auto-status" role="status">
            <p>{cameraNotice}</p><progress max="1" value={cameraProgress} aria-label="Estabilidad durante dos segundos" />
          </div>}
          {file && <small className="analysis-filename" title={file.name}>{file.name}</small>}
          <section className="analysis-inset quality">
            <h3><Icon name="info" size={17} /> Calidad de la imagen</h3>
            <dl aria-live="polite">{quality.map(({ label, check, active, value }) => <div key={label} className={active ? 'quality-active' : undefined}>
              <dt>{check === true && <span className="quality-tick" aria-hidden="true">✓</span>}{label}</dt>
              <dd className={check === true ? 'quality-pass' : check === false ? 'quality-fail' : ''}>{value}</dd>
            </div>)}
              <div className={`quality-overall ${busy && qualityStep === qualityChecks.length ? 'quality-active' : qualityComplete && qualityPassed ? 'quality-pass' : ''}`}>
                <dt>{qualityComplete && qualityPassed && <span className="quality-tick" aria-hidden="true">✓</span>}Calidad general</dt>
                <dd>{qualityComplete ? (qualityPassed ? 'Aceptable' : 'Por revisar') : busy && qualityStep === qualityChecks.length ? 'Resumiendo…' : 'Pendiente'}</dd>
              </div>
            </dl>
          </section>
          <button disabled={!file || busy || camera}>{busy ? 'Analizando…' : 'Analizar lesión'}<Icon name="arrow" size={18} /></button>
        </form>
        <section className="panel result" aria-live="polite" aria-busy={busy}>
          <div className="analysis-result-heading"><h2><Icon name="report" /> Resultado del análisis</h2>
            {result && <time dateTime={result.date}>{analysisDate.format(new Date(result.date))}</time>}
          </div>
          <div className="result-body">
          {error && <p role="alert" className="error">{error}</p>}
          {busy && <div className="result-placeholder"><span className="spinner" /><p>{qualityComplete ? 'Analizando la fotografía…' : 'Comprobando la calidad de la fotografía…'}</p></div>}
          {!result && !busy && !error && <div className="result-placeholder"><span className="icon-tile"><Icon name="report" size={28} /></span><strong>Sin análisis todavía</strong><p>El resultado aparecerá aquí después del análisis.</p></div>}
          {result && <>
            {result.state !== 'accepted' && <p className="result-title">{titles[result.state] ?? result.state}</p>}
            {result.state === 'accepted' && <>
              <div className={`analysis-outcome ${result.label}`}>
                <div><small>Clasificación experimental</small><strong>{classes[result.label]}</strong></div>
                <div className="analysis-score"><small>{result.label === 'malignant' ? 'Puntuación maligna' : 'Puntuación benigna'}</small>
                  <b>{percent.format(result.label === 'malignant' ? result.score : 1 - result.score)}</b></div>
              </div>
              <div className="analysis-detail-grid">
                <section className="analysis-inset">
                  <h3>Puntuaciones del modelo</h3>
                  <dl className="analysis-bars">{[['Benigna', 1 - result.score, 'benign'], ['Maligna', result.score, 'malignant']].map(([label, value, tone]) =>
                    <div key={label}><dt>{label}</dt><dd><meter min="0" max="1" value={value} aria-label={`Puntuación ${label.toLowerCase()}`} className={tone} /><strong>{percent.format(value)}</strong></dd></div>
                  )}</dl>
                </section>
                <section className="analysis-inset analysis-visual">
                  <h3>Características visuales</h3>
                  <dl>{traits.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
                </section>
                <ActivationMaps original={preview} result={result} />
              </div>
              <aside className="analysis-interpretation">
                <h3><Icon name="info" size={19} /> ¿Por qué dio este resultado?</h3>
                <p>El modelo indicó <strong>{classes[result.label].toLowerCase()}</strong> porque la puntuación maligna de <strong>{percent.format(result.score)}</strong> {result.label === 'malignant' ? 'alcanzó' : 'quedó por debajo de'} el umbral experimental de {percent.format(result.threshold)}.
                  {result.region_summary && ` En esta foto se midieron ${result.region_summary.lightness_variation.toFixed(1)} puntos de variación luminosa dentro del contorno estimado.`}</p>
              </aside>
            </>}
            {(result.message || result.state === 'quality_failed') && <p>{result.message ?? result.quality.message}</p>}
          </>}
          </div>
          <p className="note"><Icon name="info" size={18} /><span>Prototipo de investigación. El resultado no es un diagnóstico médico.</span></p>
          {result && <div className="analysis-result-actions">
            <button className="secondary" type="button" onClick={() => {
              download(new Blob([JSON.stringify({ ...result, filename: file?.name }, null, 2)], { type: 'application/json' }), 'dermavision-analisis.json')
              setExportMessage('Análisis descargado.')
            }}>Guardar análisis</button>
            <button className="secondary" type="button" disabled={exporting} onClick={exportReport}>
              {exporting ? 'Generando PDF…' : 'Generar informe (PDF)'}
            </button>
            <button className="secondary" type="button" disabled={exporting} onClick={() => {
              setCamera(false)
              selectPhoto(null)
              input.current.value = ''
              input.current.focus()
            }}>Nuevo análisis</button>
          </div>}
          {exportMessage && <small role="status">{exportMessage}</small>}
        </section>
      </div>
    </>
  )
}
