import { beforeEach, describe, expect, it, vi } from 'vitest'

import { $modelPresets, applyModelPreset, getModelPreset, modelPresetKey, setModelPreset } from './model-presets'
import { $currentFastMode, $currentReasoningEffort, setCurrentFastMode, setCurrentReasoningEffort } from './session'

describe('model presets', () => {
  beforeEach(() => {
    window.localStorage.removeItem('hermes.desktop.model-presets')
    $modelPresets.set({})
    setCurrentFastMode(false)
    setCurrentReasoningEffort('')
  })

  it('persists fast mode without any global reasoning field', () => {
    setModelPreset('anthropic', 'claude-opus-4-8', { fast: true })

    expect(getModelPreset('anthropic', 'claude-opus-4-8')).toEqual({ fast: true })
  })

  it('drops reasoning effort from legacy localStorage presets during load', async () => {
    window.localStorage.setItem(
      'hermes.desktop.model-presets',
      JSON.stringify({
        'anthropic::claude-opus-4-8': { effort: 'high', fast: true },
        'openai::gpt-5.6': { effort: 'max' }
      })
    )
    vi.resetModules()

    const loaded = await import('./model-presets')

    expect(loaded.$modelPresets.get()).toEqual({ 'anthropic::claude-opus-4-8': { fast: true } })
  })

  it('returns an empty preset for unknown models', () => {
    expect(getModelPreset('x', 'y')).toEqual({})
  })

  it('keys by provider::model', () => {
    expect(modelPresetKey('openai', 'gpt-5.5')).toBe('openai::gpt-5.5')
  })

  it('pushes only the provided dimensions to the gateway', async () => {
    const calls: { method: string; params?: Record<string, unknown> }[] = []

    const request = async <T>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params })

      return {} as T
    }

    await applyModelPreset({ effort: 'high' }, { failMessage: 'x', request, sessionId: 's1' })
    await applyModelPreset({}, { failMessage: 'x', request, sessionId: 's1' })

    expect(calls).toEqual([{ method: 'config.set', params: { key: 'reasoning', session_id: 's1', value: 'high' } }])
  })

  it('applies a fresh-draft preset locally without mutating gateway config', async () => {
    const calls: { method: string; params?: Record<string, unknown> }[] = []

    const request = async <T>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params })

      return {} as T
    }

    await applyModelPreset({ effort: 'high', fast: true }, { failMessage: 'x', request, sessionId: null })

    expect($currentReasoningEffort.get()).toBe('high')
    expect($currentFastMode.get()).toBe(true)
    expect(calls).toEqual([])
  })
})
