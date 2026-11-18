import { useId, useState } from 'react'
import { anatomyRegions, regionById, viewNames, width, height, regionCenter } from './anatomy'
import './AnatomyMap.css'

const anatomyViews = Object.keys(viewNames)
const svgViewport = '0 0 ' + width + ' ' + height
// The outline shares the coordinate system of the anatomical regions.
const silhouette = `M100 10
  C111 10 118 16 118 30 Q123 30 119 40 L116 45 Q114 54 110 57 L111 65
  Q116 70 128 74 C143 77 148 85 147 100 Q152 117 149 131
  Q154 151 157 174 L161 183 Q166 187 169 196 Q170 201 167 202
  L163 196 L164 206 Q162 212 159 209 L154 201 Q152 207 149 201 L148 193
  Q144 197 144 192 L146 185 Q142 171 139 160 Q134 150 135 143
  Q131 124 130 109 L125 93 Q124 115 129 134 Q138 158 136 180
  C137 201 133 219 131 240 Q132 256 132 272
  Q132 285 128 304 L126 326 Q123 335 127 341 L137 351 Q141 357 133 359
  L117 359 Q110 357 112 348 L114 338 Q115 331 113 324
  Q110 303 109 287 Q108 268 109 259 Q107 247 108 239
  Q104 215 103 194 Q102 181 100 176
  Q98 181 97 194 Q96 215 92 239 Q93 247 91 259
  Q92 268 91 287 Q90 303 87 324 Q85 331 86 338 L88 348
  Q90 357 83 359 L67 359 Q59 357 63 351 L73 341 Q77 335 74 326
  L72 304 Q68 285 68 272 Q68 256 69 240 C67 219 63 201 64 180
  Q62 158 71 134 Q76 115 75 93 L70 109 Q69 124 65 143
  Q66 150 61 160 Q58 171 54 185 L56 192 Q56 197 52 193 L51 201
  Q48 207 46 201 L41 209 Q38 212 36 206 L37 196 L33 202
  Q30 201 31 196 Q34 187 39 183 L43 174 Q46 151 51 131
  Q48 117 53 100 C52 85 57 77 72 74 Q84 70 89 65 L90 57
  Q86 54 84 45 L81 40 Q77 30 82 30 C82 16 89 10 100 10Z`
const bodyDetails = {
  front: 'M89 54 Q100 64 111 54 M77 76 Q91 73 97 81 M123 76 Q109 73 103 81 M78 94 Q87 104 97 99 M122 94 Q113 104 103 99 M99 131 q1 -2 2 0 M95 174 Q100 181 105 174 M73 251 q7 4 14 0 M113 251 q7 4 14 0',
  back: 'M80 85 Q82 99 93 105 M120 85 Q118 99 107 105 M100 79 Q102 104 100 132 M100 149 L100 175 M73 166 Q83 179 95 175 M127 166 Q117 179 105 175 M74 254 q7 -4 13 0 M113 254 q6 -4 13 0',
}

function Body({ side, marker, onSelect, onHover }) {
  const outlineId = useId()
  function hit(event, region) {
    if (event.detail === 0) {
      onSelect(regionCenter(region))
      return
    }
    const svg = event.currentTarget.ownerSVGElement
    const transform = svg.getScreenCTM()
    if (!transform) return
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(transform.inverse())
    onSelect({ region_id: region.id, x: point.x / width, y: point.y / height, origin: 'manual' })
  }
  return <figure className="anatomy-figure">
    <svg viewBox={svgViewport} role={onSelect ? 'group' : 'img'} aria-label={'Esquema corporal · vista ' + viewNames[side].toLowerCase()}
      className={onSelect ? 'anatomy-svg is-editable' : 'anatomy-svg'}>
      {onSelect && <>
        <defs><clipPath id={outlineId}><path d={silhouette} /></clipPath></defs>
        <path className="anatomy-outline" d={silhouette} aria-hidden="true" />
        <path className="anatomy-details" d={bodyDetails[side]} aria-hidden="true" />
      </>}
      <g clipPath={onSelect ? 'url(#' + outlineId + ')' : undefined}>
      {anatomyRegions.filter(region => region.view === side).map(region => {
        const selected = marker?.region_id === region.id
        return <polygon key={region.id} points={region.polygon.map(pair => pair.join(',')).join(' ')}
          className={'anatomy-region' + (selected ? ' is-selected' : '')}
          role={onSelect ? 'button' : undefined} tabIndex={onSelect ? 0 : undefined} aria-label={region.label}
          aria-pressed={onSelect ? selected : undefined} data-region={region.id}
          onPointerEnter={onSelect ? () => onHover(region.label) : undefined}
          onPointerLeave={onSelect ? () => onHover('') : undefined}
          onFocus={onSelect ? () => onHover(region.label) : undefined}
          onBlur={onSelect ? () => onHover('') : undefined}
          onClick={onSelect ? event => hit(event, region) : undefined}
          onKeyDown={onSelect ? event => {
            if (event.key !== 'Enter' && event.key !== ' ') return
            event.preventDefault()
            onSelect(regionCenter(region))
          } : undefined}>
          <title>{region.label}</title>
        </polygon>
      })}
      </g>
      {marker && regionById.get(marker.region_id)?.view === side &&
        <g className="anatomy-marker" aria-hidden="true" data-origin={marker.origin}>
          <circle cx={marker.x * width} cy={marker.y * height} r="6.2" />
          <circle cx={marker.x * width} cy={marker.y * height} r="2.2" />
        </g>}
    </svg>
    {!onSelect && <figcaption>{viewNames[side]}</figcaption>}
  </figure>
}

export default function AnatomyMap({ view, marker, legacySite = '', onSelect, onView, onChangeLocation }) {
  const [hover, setHover] = useState('')
  const selected = regionById.get(marker?.region_id)
  return <section className="anatomy-panel" aria-label="Ubicación anatómica">
    <h2>Ubicación aproximada de la lesión</h2>
    {onSelect && <p>Selecciona en el esquema corporal la zona donde se encuentra la lesión.</p>}
    <div className={'anatomy-figures' + (!onSelect ? ' anatomy-readonly' : '')}>
      {(onSelect ? anatomyViews : [selected?.view || view]).map(side => <Body key={side} side={side}
        marker={marker} onSelect={onSelect} onHover={setHover} />)}
    </div>
    {onView && <div className="anatomy-view-buttons" role="group" aria-label="Vista del esquema corporal">
      {anatomyViews.map(side => <button type="button" className="secondary" key={side} aria-pressed={view === side}
        onClick={() => { onView(side); setHover('') }}>Vista {viewNames[side].toLowerCase()}</button>)}
    </div>}
    {onSelect && <p className="anatomy-hover" aria-live="polite">{hover || ('Vista activa · ' + viewNames[view])}</p>}
    <div className="anatomy-selection" aria-live="polite">
      <strong>Localización seleccionada</strong>
      {selected ? <dl>
        <dt>Región</dt><dd>{selected.label.split(' — ')[0]}</dd>
        <dt>Vista</dt><dd>{viewNames[selected.view]}</dd>
        <dt>Descripción</dt><dd>{selected.label}</dd>
        <dt>Punto</dt><dd>{marker.origin === 'manual' ? 'Ubicación aproximada marcada' : 'Centro predeterminado de la región'}</dd>
      </dl> : <p>{legacySite ? 'Ubicación histórica · ' + legacySite
        : onSelect ? 'Selecciona una zona del cuerpo o utiliza el campo Localización anatómica.' : 'Sin punto anatómico registrado.'}</p>}
      {onChangeLocation && <button type="button" className="secondary" onClick={onChangeLocation}>Cambiar ubicación</button>}
    </div>
  </section>
}
