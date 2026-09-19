import { describe, expect, it } from 'vitest'

import { deriveSettingsStudioView } from './studio-view'

describe('deriveSettingsStudioView', () => {
  it('collapses configuration routes into one Studio management surface', () => {
    expect(deriveSettingsStudioView('config:model', 'accounts', 'tools')).toBe('configuration')
    expect(deriveSettingsStudioView('config:appearance', 'accounts', 'tools')).toBe('configuration')
  })

  it('keeps provider and key subviews distinct because they represent different real tasks', () => {
    expect(deriveSettingsStudioView('providers', 'accounts', 'tools')).toBe('providers-accounts')
    expect(deriveSettingsStudioView('providers', 'custom-endpoints', 'tools')).toBe('providers-custom-endpoints')
    expect(deriveSettingsStudioView('keys', 'accounts', 'settings')).toBe('keys-settings')
  })

  it('preserves other route identities rather than inventing an operational state', () => {
    expect(deriveSettingsStudioView('gateway', 'accounts', 'tools')).toBe('gateway')
    expect(deriveSettingsStudioView('sessions', 'accounts', 'tools')).toBe('sessions')
  })
})
