import { useEffect, useRef, useState } from 'react'
import Followup, { ModelResults } from './Followup'
import './App.css'

const titles = {
  accepted: 'Análisis completado',
  uncertain: 'Resultado no concluyente',
  rejected: 'Imagen fuera del dominio',
  quality_failed: 'Calidad insuficiente',
  unavailable: 'Análisis no disponible',
}
const classes = { benign: 'Benigna', malignant: 'Maligna' }

function Icon({ name, size = 22 }) {
  const paths = {
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

const pages = { analyze: 'Análisis', people: 'Personas', followup: 'Seguimiento', compare: 'Comparaciones', reports: 'Informes y video', model: 'Evaluación' }
const pageIcons = { analyze: 'scan', people: 'people', followup: 'timeline', compare: 'compare', reports: 'report', model: 'chart' }

function currentPage() {
  const value = location.hash.slice(1)
  return Object.hasOwn(pages, value) ? value : 'analyze'
}

export default function App() {
  const [page, setPage] = useState(currentPage)
  const [selection, setSelection] = useState(['', ''])
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButton = useRef(null)
  useEffect(() => {
    const update = () => {
      setPage(currentPage())
      setMenuOpen(false)
    }
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
  const navigate = next => { location.hash = next }
  return <div className="app-shell" onKeyDown={event => {
    if (event.key === 'Escape' && menuOpen) {
      setMenuOpen(false)
      menuButton.current?.focus()
    }
  }}>
    <header className="topbar">
      <div className="topbar-inner">
        <a href="#analyze" className="brand"><span className="brand-mark"><Icon name="scan" /></span>DermaVision<span className="brand-x">X</span></a>
        <span className="local"><span /> Sesión local</span>
        <button ref={menuButton} type="button" className="mobile-menu" aria-controls="modules"
          aria-expanded={menuOpen} onClick={() => setMenuOpen(open => !open)}><Icon name="menu" /> Menú</button>
      </div>
    </header>
    <nav id="modules" className={`navigation ${menuOpen ? 'is-open' : ''}`} aria-label="Módulos de DermaVision">
      <div>{Object.entries(pages).map(([key, label]) =>
        <a key={key} href={'#' + key} onClick={() => {
          if (menuOpen) menuButton.current?.focus()
          setMenuOpen(false)
        }} aria-current={page === key ? 'page' : undefined}><Icon name={pageIcons[key]} size={19} />{label}</a>)}</div>
    </nav>
    <main>
      {page === 'analyze' ? <Analysis /> : page === 'model' ? <ModelResults /> : <Followup page={page} selection={selection}
        setSelection={setSelection} navigate={navigate} />}
    </main>
  </div>
}

function Analysis() {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [camera, setCamera] = useState(false)
  const video = useRef(null)

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

  function selectPhoto(next) {
    setFile(next)
    setPreview(next ? URL.createObjectURL(next) : '')
    setResult(null)
    setError('')
  }

  async function analyze(event) {
    event.preventDefault()
    if (!file || busy) return
    setBusy(true)
    setError('')
    setResult(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const response = await fetch('/api/analyze', { method: 'POST', body: form })
      const payload = await response.json()
      if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'No se pudo analizar la imagen.')
      setResult(payload)
    } catch (failure) {
      setError(failure.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <section className="intro">
        <p className="eyebrow">Análisis individual</p>
        <h1>Analizar una lesión</h1>
        <p>Elige una foto clara y centrada para obtener una clasificación experimental.</p>
      </section>
      <div className="workspace">
        <form className="panel" onSubmit={analyze}>
          <h2><Icon name="scan" /> Fotografía</h2>
          <input className="file-input" id="photo" type="file" accept="image/jpeg,image/png,image/webp" disabled={busy}
            onChange={(event) => selectPhoto(event.target.files[0] ?? null)} />
          {camera ? <video ref={video} className="camera-preview" muted playsInline autoPlay /> : <label className={`preview ${preview ? 'has-photo' : ''}`} htmlFor="photo">
            {preview ? <img src={preview} alt="Fotografía seleccionada para análisis" /> : <>
              <span className="icon-tile"><Icon name="upload" size={26} /></span>
              <strong>Seleccionar una foto</strong>
              <small>JPEG, PNG o WebP · hasta 12 MB</small>
            </>}
          </label>}
          <div className="actions">
            <button className="secondary" type="button" disabled={busy} onClick={() => { setError(''); setCamera(!camera) }}>{camera ? 'Cerrar cámara' : 'Usar cámara'}</button>
            {camera && <button className="secondary" type="button" onClick={takePhoto}>Capturar foto</button>}
          </div>
          {file && <div className="file-detail"><span title={file.name}>{file.name}</span><label htmlFor="photo">Cambiar foto</label></div>}
          <button disabled={!file || busy || camera}>{busy ? 'Analizando…' : 'Analizar imagen'}<Icon name="arrow" size={18} /></button>
        </form>
        <section className="panel result" aria-live="polite" aria-busy={busy}>
          <h2><Icon name="report" /> Resultado</h2>
          <div className="result-body">
          {error && <p role="alert" className="error">{error}</p>}
          {busy && <div className="result-placeholder"><span className="spinner" /><p>Verificando la calidad y el contenido de la fotografía.</p></div>}
          {!result && !busy && !error && <div className="result-placeholder"><span className="icon-tile"><Icon name="report" size={28} /></span><strong>Sin análisis todavía</strong><p>El resultado aparecerá aquí después del análisis.</p></div>}
          {result && <>
            <p className="result-title">{titles[result.state] ?? result.state}</p>
            {result.state === 'accepted' && <>
              <strong className={`classification ${result.label}`}>{classes[result.label]}</strong>
            </>}
            {(result.message || result.state === 'quality_failed') && <p>{result.message ?? result.quality.message}</p>}
            <details className="technical"><summary>Detalles del modelo</summary>
              {result.state === 'accepted' && <p>Puntuación: {new Intl.NumberFormat('es-PE', { style: 'percent', maximumFractionDigits: 1 }).format(result.score)}</p>}
              <small>Modelo: {result.experiment}</small>
            </details>
          </>}
          </div>
          <p className="note"><Icon name="info" size={18} /><span>Prototipo de investigación. El resultado no es un diagnóstico médico.</span></p>
        </section>
      </div>
    </>
  )
}
