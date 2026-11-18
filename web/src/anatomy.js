import atlas from './anatomy.json'

export const anatomyRegions = atlas.regions
export const regionById = new Map(anatomyRegions.map(region => [region.id, region]))
export const viewNames = { front: 'Anterior', back: 'Posterior' }
export const width = atlas.width
export const height = atlas.height

export function regionCenter(region) {
  return { region_id: region.id, x: region.center[0] / width, y: region.center[1] / height, origin: 'default' }
}
