import { atom } from 'nanostores'

import { persistString, storedString } from '@/lib/storage'

import { notifyError } from './notifications'
import { setCurrentFastMode, setCurrentReasoningEffort } from './session'
import { sessionTileDelegate } from './session-states'

const STORAGE_KEY = 'hermes.desktop.model-presets'

/** Per-model fast-mode preset, remembered globally across sessions and
 * re-applied whenever that model is selected. Reasoning effort is session state
 * and deliberately absent from this persisted shape. */
export interface ModelPreset {
  fast?: boolean
}

interface ModelRuntimeOptions extends ModelPreset {
  effort?: string
}

type RequestGateway = <T>(method: string, params?: Record<string, unknown>) => Promise<T>

/** Stable `provider::model` key (matches the visibility-store format). */
export const modelPresetKey = (provider: string, model: string): string => `${provider}::${model}`

function fastOnly(preset: unknown): ModelPreset {
  if (!preset || typeof preset !== 'object' || Array.isArray(preset)) {
    return {}
  }

  const fast = (preset as { fast?: unknown }).fast

  return typeof fast === 'boolean' ? { fast } : {}
}

function load(): Record<string, ModelPreset> {
  const raw = storedString(STORAGE_KEY)

  if (!raw) {
    return {}
  }

  try {
    const parsed = JSON.parse(raw)

    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return {}
    }

    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>)
        .map(([key, preset]) => [key, fastOnly(preset)] as const)
        .filter(([, preset]) => preset.fast !== undefined)
    )
  } catch {
    return {}
  }
}

export const $modelPresets = atom<Record<string, ModelPreset>>(load())

export function getModelPreset(provider: string, model: string): ModelPreset {
  return fastOnly($modelPresets.get()[modelPresetKey(provider, model)])
}

/** Merge the globally reusable fast dimension for one model and persist. */
export function setModelPreset(provider: string, model: string, patch: ModelPreset): void {
  if (patch.fast === undefined) {
    return
  }

  const key = modelPresetKey(provider, model)
  const next = { ...$modelPresets.get(), [key]: { fast: patch.fast } }

  $modelPresets.set(next)
  persistString(STORAGE_KEY, JSON.stringify(next))
}

/** Apply a model's preset to the composer, then push it to a live session.
 *  `undefined` skips that dimension; values are capability-gated upstream.
 *  Without a session the local draft still needs the preset, but must not call
 *  `config.set`: that falls back to persistent profile config when no session
 *  matches and would rewrite the user's defaults.
 *
 *  `primary: false` scopes the optimistic write to the tile's session slice —
 *  a tile's picker must not clobber the primary composer's effort/fast. */
export async function applyModelPreset(
  { effort, fast }: ModelRuntimeOptions,
  ctx: { failMessage: string; primary?: boolean; request: RequestGateway; sessionId: null | string }
): Promise<void> {
  if (ctx.primary ?? true) {
    if (effort !== undefined) {
      setCurrentReasoningEffort(effort)
    }

    if (fast !== undefined) {
      setCurrentFastMode(fast)
    }
  } else if (ctx.sessionId) {
    sessionTileDelegate()?.updateSession(ctx.sessionId, state => ({
      ...state,
      ...(effort !== undefined ? { reasoningEffort: effort } : {}),
      ...(fast !== undefined ? { fast } : {})
    }))
  }

  if (!ctx.sessionId) {
    return
  }

  try {
    if (effort !== undefined) {
      await ctx.request('config.set', { key: 'reasoning', session_id: ctx.sessionId, value: effort })
    }

    if (fast !== undefined) {
      await ctx.request('config.set', { key: 'fast', session_id: ctx.sessionId, value: fast ? 'fast' : 'normal' })
    }
  } catch (err) {
    notifyError(err, ctx.failMessage)
  }
}
