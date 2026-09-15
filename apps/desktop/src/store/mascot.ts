import { atom } from 'nanostores'

export interface MascotPreset {
  id: string
  name: string
  description: string
  image: string
}

export const MASCOT_PRESETS: MascotPreset[] = [
  {
    id: 'stella-star',
    name: 'Astral Star (Default)',
    description: 'Official Stella 4-point cosmic star emblem',
    image: 'mascots/stella-star.png'
  },
  {
    id: 'silver-maiden',
    name: 'Silver-Haired Maiden',
    description: 'Amethyst-eyed maid aesthetic with cat ears and lavender accents',
    image: 'mascots/silver-maiden.jpg'
  },
  {
    id: 'stelle-cosy',
    name: 'Stelle (Trailblazer)',
    description: 'Peaceful chibi Stelle resting under blankets with plushie',
    image: 'mascots/stelle-cosy.jpg'
  },
  {
    id: 'robin',
    name: 'Robin (Halovian Singer)',
    description: 'Pastel periwinkle pop idol with head wings and golden halo',
    image: 'mascots/robin.png'
  }
]

const STORAGE_KEY = 'stella-mascot-id'
const CUSTOM_IMAGE_KEY = 'stella-custom-mascot-data'

function loadMascotId(): string {
  if (typeof window === 'undefined') return 'stella-star'
  return localStorage.getItem(STORAGE_KEY) || 'stella-star'
}

function loadCustomImage(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(CUSTOM_IMAGE_KEY)
}

export const $activeMascotId = atom<string>(loadMascotId())
export const $customMascotData = atom<string | null>(loadCustomImage())

export function setMascotId(id: string): void {
  $activeMascotId.set(id)
  if (typeof window !== 'undefined') {
    localStorage.setItem(STORAGE_KEY, id)
  }
}

export function setCustomMascotData(dataUrl: string): void {
  $customMascotData.set(dataUrl)
  $activeMascotId.set('custom')
  if (typeof window !== 'undefined') {
    localStorage.setItem(STORAGE_KEY, 'custom')
    localStorage.setItem(CUSTOM_IMAGE_KEY, dataUrl)
  }
}

export function resolveMascotSrc(mascotId: string, customData?: string | null): string {
  if (mascotId === 'custom' && customData) {
    return customData
  }
  const preset = MASCOT_PRESETS.find(p => p.id === mascotId)
  const relPath = preset ? preset.image : 'mascots/stella-star.png'
  const base = typeof import.meta !== 'undefined' && import.meta.env?.BASE_URL ? import.meta.env.BASE_URL : '/'
  return `${base}${relPath.replace(/^\/+/, '')}`
}
