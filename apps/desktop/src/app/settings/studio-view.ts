import type { KeysView } from './keys-settings'
import type { ProviderView } from './providers-settings'
import type { SettingsView } from './types'

// Studio styling follows the actual settings route, not a cosmetic name or
// guessed provider state. Configuration pages share one calm management canvas;
// the provider and key subviews remain distinct because their actions differ.
export function deriveSettingsStudioView(view: SettingsView, providerView: ProviderView, keysView: KeysView): string {
  if (view.startsWith('config:')) {
    return 'configuration'
  }

  if (view === 'providers') {
    return `providers-${providerView}`
  }

  if (view === 'keys') {
    return `keys-${keysView}`
  }

  return view
}
