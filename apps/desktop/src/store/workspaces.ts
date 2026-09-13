import { atom } from 'nanostores'

import defaultWorkspaces from '@/config/workspaces.json'
import { readJson, writeJson } from '@/lib/storage'
import { $currentCwd } from '@/store/session'

export interface WorkspaceRoom {
  id: string
  name: string
  icon?: string
  topic?: string
  cwd?: string
  model?: string
}

export interface WorkspaceCategory {
  id: string
  name: string
  rooms: WorkspaceRoom[]
}

export interface WorkspacesConfig {
  version: number
  title: string
  categories: WorkspaceCategory[]
}

const STORAGE_KEY = 'stella.workspaces.config'
const ACTIVE_ROOM_KEY = 'stella.workspaces.active_room'
const COLLAPSED_CATEGORIES_KEY = 'stella.workspaces.collapsed_categories'

function loadInitialConfig(): WorkspacesConfig {
  try {
    const persisted = readJson<WorkspacesConfig>(STORAGE_KEY)
    if (persisted && Array.isArray(persisted.categories) && persisted.categories.length > 0) {
      return persisted
    }
  } catch {
    // Fall back to bundled config on read error
  }
  return defaultWorkspaces as WorkspacesConfig
}

function loadInitialActiveRoom(): string | null {
  try {
    return window.localStorage.getItem(ACTIVE_ROOM_KEY)
  } catch {
    return null
  }
}

function loadInitialCollapsedCategories(): Set<string> {
  try {
    const raw = readJson<string[]>(COLLAPSED_CATEGORIES_KEY)
    return new Set(Array.isArray(raw) ? raw : [])
  } catch {
    return new Set()
  }
}

export const $workspacesConfig = atom<WorkspacesConfig>(loadInitialConfig())
export const $activeRoomId = atom<string | null>(loadInitialActiveRoom())
export const $collapsedCategories = atom<Set<string>>(loadInitialCollapsedCategories())

export function selectRoom(room: WorkspaceRoom) {
  $activeRoomId.set(room.id)
  try {
    window.localStorage.setItem(ACTIVE_ROOM_KEY, room.id)
  } catch {
    // ignore
  }

  if (room.cwd) {
    $currentCwd.set(room.cwd)
  }
}

export function toggleCategory(categoryId: string) {
  const current = new Set($collapsedCategories.get())
  if (current.has(categoryId)) {
    current.delete(categoryId)
  } else {
    current.add(categoryId)
  }
  $collapsedCategories.set(current)
  try {
    writeJson(COLLAPSED_CATEGORIES_KEY, Array.from(current))
  } catch {
    // ignore
  }
}

export function saveWorkspacesConfig(config: WorkspacesConfig) {
  $workspacesConfig.set(config)
  try {
    writeJson(STORAGE_KEY, config)
  } catch {
    // ignore
  }
}
