import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Plus, Trash2, ArrowLeft, Info, ChevronDown, ChevronRight, Check } from 'lucide-react'

interface VariantForm {
  name: string
  provider: string
  model: string
  traffic_pct: number
  config: string       // raw JSON string
  configOpen: boolean  // UI state: expanded?
}

function defaultVariantName(index: number): string {
  if (index === 0) return 'control'
  if (index === 1) return 'treatment'
  return `treatment_${index}`
}

const defaultVariant = (index: number): VariantForm => ({
  name: defaultVariantName(index),
  provider: 'openai',
  model: '',
  traffic_pct: 50,
  config: '{}',
  configOpen: false,
})

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
      {hint && <p style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 4 }}>{hint}</p>}
    </div>
  )
}

// ─── Custom Dropdown ──────────────────────────────────────────────────────────
// Uses position:fixed so it punches through any overflow:hidden ancestor.
interface DropdownOption { id: string; label: string }

function Dropdown({
  value, options, onChange, placeholder = 'Select…', disabled = false, testId,
}: {
  value: string
  options: DropdownOption[]
  onChange: (id: string) => void
  placeholder?: string
  disabled?: boolean
  testId?: string
}) {
  const [open, setOpen] = useState(false)
  const btnRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const [coords, setCoords] = useState({ top: 0, left: 0, width: 0 })

  const openMenu = useCallback(() => {
    if (disabled) return
    const rect = btnRef.current?.getBoundingClientRect()
    if (rect) {
      setCoords({
        top: rect.bottom + 4,
        left: rect.left,
        width: rect.width,
      })
    }
    setOpen(true)
  }, [disabled])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    function handle(e: MouseEvent) {
      if (
        menuRef.current && !menuRef.current.contains(e.target as Node) &&
        btnRef.current && !btnRef.current.contains(e.target as Node)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [open])

  // Reposition on scroll/resize
  useEffect(() => {
    if (!open) return
    function reposition() {
      const rect = btnRef.current?.getBoundingClientRect()
      if (rect) setCoords({ top: rect.bottom + 4, left: rect.left, width: rect.width })
    }
    window.addEventListener('scroll', reposition, true)
    window.addEventListener('resize', reposition)
    return () => {
      window.removeEventListener('scroll', reposition, true)
      window.removeEventListener('resize', reposition)
    }
  }, [open])

  const selected = options.find(o => o.id === value)

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        data-testid={testId}
        disabled={disabled}
        onClick={open ? () => setOpen(false) : openMenu}
        style={{
          width: '100%',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6,
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderColor: open ? 'var(--ink)' : 'var(--border)',
          borderRadius: 6, padding: '7px 10px',
          fontSize: 13, fontFamily: 'Geist, sans-serif',
          color: selected ? 'var(--ink)' : 'var(--ink-4)',
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.5 : 1,
          transition: 'border-color 0.12s',
          textAlign: 'left',
          whiteSpace: 'nowrap', overflow: 'hidden',
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', flex: 1 }}>
          {selected ? selected.label : placeholder}
        </span>
        <ChevronDown size={12} color="var(--ink-3)" style={{ flexShrink: 0, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }} />
      </button>

      {open && createPortal(
        <div
          ref={menuRef}
          style={{
            position: 'fixed',
            top: coords.top,
            left: coords.left,
            width: Math.max(coords.width, 180),
            zIndex: 9999,
            background: 'var(--surface)',
            border: '1px solid var(--border-strong)',
            borderRadius: 8,
            boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
            overflow: 'hidden',
            maxHeight: 260,
            overflowY: 'auto',
          }}
        >
          {options.length === 0 ? (
            <div style={{ padding: '10px 12px', fontSize: 12, color: 'var(--ink-4)' }}>No options</div>
          ) : options.map(opt => (
            <button
              key={opt.id}
              type="button"
              onClick={() => { onChange(opt.id); setOpen(false) }}
              style={{
                width: '100%', textAlign: 'left',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
                padding: '8px 12px', border: 'none',
                background: opt.id === value ? 'var(--surface-3)' : 'transparent',
                color: 'var(--ink)', fontSize: 13,
                fontFamily: 'Geist, sans-serif',
                cursor: 'pointer',
                transition: 'background 0.08s',
              }}
              onMouseEnter={e => { if (opt.id !== value) (e.currentTarget as HTMLElement).style.background = 'var(--surface-2)' }}
              onMouseLeave={e => { if (opt.id !== value) (e.currentTarget as HTMLElement).style.background = 'transparent' }}
            >
              <span>{opt.label}</span>
              {opt.id === value && <Check size={11} color="var(--accent)" />}
            </button>
          ))}
        </div>,
        document.body
      )}
    </>
  )
}

// ─── JSON config validity indicator ──────────────────────────────────────────
function isValidJson(s: string): boolean {
  try { JSON.parse(s); return true } catch { return false }
}

// Grid layout shared between header and rows
const GRID: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '1fr 1fr 1fr 72px 32px',
  gap: 10,
  alignItems: 'center',
}

export function CreateExperimentPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [outcomeEvents, setOutcomeEvents] = useState('')
  const [variants, setVariants] = useState<VariantForm[]>([
    { ...defaultVariant(0), traffic_pct: 50 },
    { ...defaultVariant(1), traffic_pct: 50 },
  ])
  const [error, setError] = useState('')

  const { data: providers } = useQuery({ queryKey: ['providers'], queryFn: api.registry.providers })
  const { data: allModels } = useQuery({ queryKey: ['models'], queryFn: () => api.registry.models() })

  const createMutation = useMutation({
    mutationFn: api.experiments.create,
    onSuccess: (exp: { name: string }) => {
      qc.invalidateQueries({ queryKey: ['experiments'] })
      navigate(`/experiments/${exp.name}`)
    },
    onError: (err: Error) => setError(err.message),
  })

  const totalTraffic = variants.reduce((s, v) => s + Number(v.traffic_pct), 0)
  const trafficOk = totalTraffic === 100

  function updateVariant(idx: number, field: keyof VariantForm, value: string | number | boolean) {
    setVariants(vs => vs.map((v, i) => i === idx ? { ...v, [field]: value } : v))
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!trafficOk) { setError(`Traffic must sum to 100 (currently ${totalTraffic})`); return }

    // Validate all configs
    for (const [i, v] of variants.entries()) {
      if (!isValidJson(v.config)) {
        setError(`Variant "${v.name}" has invalid JSON config`)
        return
      }
    }

    createMutation.mutate({
      name,
      description: description || undefined,
      variants: variants.map((v, i) => ({
        name: v.name,
        provider: v.provider,
        model: v.model,
        traffic_pct: Number(v.traffic_pct),
        is_current: i === 0,
        config: JSON.parse(v.config),
      })),
      outcome_events: outcomeEvents.split(',').map(e => e.trim()).filter(Boolean),
      attribution_window_hours: 168,
    })
  }

  const providerOptions: DropdownOption[] = (providers as Array<{ id: string; label: string }> | undefined)
    ?.map(p => ({ id: p.id, label: p.label })) ?? []

  const modelsForProvider = (provider: string): DropdownOption[] =>
    (allModels as Array<{ provider?: string; id: string; label: string }> | undefined)
      ?.filter(m => m.provider === provider)
      .map(m => ({ id: m.id, label: m.label })) ?? []

  return (
    <div style={{ maxWidth: 720, margin: '0 auto', padding: '40px 32px' }}>
      {/* Header */}
      <div className="fade-up fade-up-1" style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <button
            onClick={() => navigate('/experiments')}
            style={{ display: 'flex', alignItems: 'center', padding: 6, borderRadius: 6, border: 'none', background: 'transparent', cursor: 'pointer', color: 'var(--ink-3)' }}
            onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface-3)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          >
            <ArrowLeft size={15} />
          </button>
          <h1 className="font-serif" style={{ fontSize: 24, letterSpacing: '-0.02em', color: 'var(--ink)', margin: 0 }}>
            New experiment
          </h1>
        </div>
        <p style={{ fontSize: 13, color: 'var(--ink-3)', paddingLeft: 38 }}>
          Define your current model and challengers. Start it when ready to collect data.
        </p>
      </div>

      <form onSubmit={handleSubmit} data-testid="create-experiment-form" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

        {/* Basic info */}
        <div className="card fade-up fade-up-2" style={{ overflow: 'hidden' }}>
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)' }}>
            <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--ink)', letterSpacing: '0.02em', textTransform: 'uppercase' }}>
              Basics
            </span>
          </div>
          <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Field label="Experiment name">
              <input
                className="input-base"
                required
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="support-bot-v2"
                data-testid="experiment-name-input"
              />
            </Field>
            <Field label="Description">
              <textarea
                className="input-base"
                value={description}
                onChange={e => setDescription(e.target.value)}
                rows={2}
                placeholder="What are you testing?"
                style={{ resize: 'vertical' }}
              />
            </Field>
            <Field label="Outcome events" hint="Comma-separated. These are the business metrics you care about.">
              <input
                className="input-base"
                value={outcomeEvents}
                onChange={e => setOutcomeEvents(e.target.value)}
                placeholder="ticket_resolved, escalated_to_human"
                data-testid="outcome-events-input"
              />
            </Field>
          </div>
        </div>

        {/* Variants */}
        <div className="card fade-up fade-up-3" style={{ overflow: 'visible' }}>
          {/* Card header */}
          <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--ink)', letterSpacing: '0.02em', textTransform: 'uppercase' }}>
                Variants
              </span>
              <span style={{
                fontSize: 11, padding: '2px 7px', borderRadius: 99,
                fontFamily: 'IBM Plex Mono', fontWeight: 500,
                color: trafficOk ? 'var(--green)' : 'var(--red)',
                background: trafficOk ? 'var(--green-bg)' : 'var(--red-bg)',
              }}>
                {totalTraffic}% / 100%
              </span>
            </div>
            <button
              type="button"
              onClick={() => setVariants(vs => [...vs, { ...defaultVariant(vs.length), traffic_pct: 0 }])}
              style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, color: 'var(--accent)', cursor: 'pointer', border: 'none', background: 'transparent', fontFamily: 'Geist, sans-serif', fontWeight: 500 }}
            >
              <Plus size={12} /> Add variant
            </button>
          </div>

          {/* Column headers */}
          <div style={{ ...GRID, padding: '10px 20px 8px', borderBottom: '1px solid var(--border)' }}>
            {['Name', 'Provider', 'Model', 'Traffic %'].map(h => (
              <div key={h} style={{ fontSize: 11, fontWeight: 500, color: 'var(--ink-3)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>{h}</div>
            ))}
            <div />
          </div>

          {/* Variant rows */}
          {variants.map((v, idx) => {
            const isControl = idx === 0
            const configValid = isValidJson(v.config)

            return (
              <div
                key={idx}
                data-testid={`variant-${idx}`}
                style={{
                  borderBottom: idx < variants.length - 1 ? '1px solid var(--border)' : 'none',
                  background: isControl ? 'var(--surface-2)' : 'transparent',
                }}
              >
                {/* Main row */}
                <div style={{ ...GRID, padding: '10px 20px' }}>
                  {/* Name — with inline CONTROL pill */}
                  <div style={{ position: 'relative' }}>
                    <input
                      required
                      className="input-base"
                      value={v.name}
                      onChange={e => updateVariant(idx, 'name', e.target.value)}
                      data-testid={`variant-name-${idx}`}
                      style={isControl ? { paddingRight: 72 } : undefined}
                    />
                    {isControl && (
                      <span style={{
                        position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
                        fontSize: 10, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase',
                        color: 'var(--ink-2)', background: 'var(--surface-3)',
                        border: '1px solid var(--border-strong)', borderRadius: 4, padding: '2px 6px',
                        pointerEvents: 'none', userSelect: 'none',
                      }}>
                        Control
                      </span>
                    )}
                  </div>

                  {/* Provider — custom dropdown */}
                  <Dropdown
                    value={v.provider}
                    options={providerOptions}
                    onChange={val => { updateVariant(idx, 'provider', val); updateVariant(idx, 'model', '') }}
                    testId={`variant-provider-${idx}`}
                  />

                  {/* Model — custom dropdown */}
                  <Dropdown
                    value={v.model}
                    options={modelsForProvider(v.provider)}
                    onChange={val => updateVariant(idx, 'model', val)}
                    placeholder="Select model…"
                    disabled={!v.provider}
                    testId={`variant-model-${idx}`}
                  />

                  {/* Traffic % */}
                  <input
                    required type="number" min={0} max={100}
                    className="input-base"
                    value={v.traffic_pct}
                    onChange={e => updateVariant(idx, 'traffic_pct', Number(e.target.value))}
                    data-testid={`variant-traffic-${idx}`}
                    style={{ fontFamily: 'IBM Plex Mono', textAlign: 'right' }}
                  />

                  {/* Delete button */}
                  <div style={{ display: 'flex', justifyContent: 'center' }}>
                    {!isControl && variants.length > 2 ? (
                      <button
                        type="button"
                        onClick={() => setVariants(vs => vs.filter((_, i) => i !== idx))}
                        style={{ color: 'var(--ink-4)', border: 'none', background: 'transparent', cursor: 'pointer', padding: 4, borderRadius: 4, display: 'flex' }}
                        onMouseEnter={e => (e.currentTarget.style.color = 'var(--red)')}
                        onMouseLeave={e => (e.currentTarget.style.color = 'var(--ink-4)')}
                      >
                        <Trash2 size={13} />
                      </button>
                    ) : <div />}
                  </div>
                </div>

                {/* Config sub-row */}
                <div style={{ paddingLeft: 20, paddingRight: 20, paddingBottom: v.configOpen ? 12 : 0 }}>
                  <button
                    type="button"
                    onClick={() => updateVariant(idx, 'configOpen', !v.configOpen)}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 4,
                      fontSize: 11, color: configValid ? 'var(--ink-3)' : 'var(--red)',
                      border: 'none', background: 'transparent', cursor: 'pointer',
                      padding: '0 0 10px 0', fontFamily: 'Geist, sans-serif', fontWeight: 500,
                    }}
                  >
                    <ChevronRight
                      size={11}
                      style={{ transform: v.configOpen ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }}
                    />
                    Config
                    {v.config !== '{}' && (
                      <span style={{
                        fontSize: 10, padding: '1px 5px', borderRadius: 99,
                        background: configValid ? 'var(--accent-light)' : 'var(--red-bg)',
                        color: configValid ? 'var(--accent)' : 'var(--red)',
                        fontFamily: 'IBM Plex Mono',
                      }}>
                        {configValid ? 'custom' : 'invalid JSON'}
                      </span>
                    )}
                  </button>

                  {v.configOpen && (
                    <div style={{ marginBottom: 4 }}>
                      <textarea
                        value={v.config}
                        onChange={e => updateVariant(idx, 'config', e.target.value)}
                        data-testid={`variant-config-${idx}`}
                        placeholder='{ "temperature": 0.7, "system_prompt": "…" }'
                        rows={4}
                        spellCheck={false}
                        style={{
                          width: '100%',
                          background: configValid ? 'var(--surface)' : '#fff8f8',
                          border: `1px solid ${configValid ? 'var(--border)' : 'var(--red)'}`,
                          borderRadius: 6, padding: '8px 12px',
                          fontSize: 12, fontFamily: 'IBM Plex Mono',
                          color: 'var(--ink)', resize: 'vertical', outline: 'none',
                          lineHeight: 1.6, transition: 'border-color 0.12s',
                        }}
                        onFocus={e => { e.target.style.borderColor = configValid ? 'var(--ink)' : 'var(--red)' }}
                        onBlur={e => { e.target.style.borderColor = configValid ? 'var(--border)' : 'var(--red)' }}
                      />
                      {!configValid && (
                        <p style={{ fontSize: 11, color: 'var(--red)', marginTop: 4 }}>
                          Invalid JSON — check syntax
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {/* Error */}
        {error && (
          <div
            className="fade-up"
            data-testid="form-error"
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '10px 14px', background: 'var(--red-bg)',
              border: '1px solid #f0c0c0', borderRadius: 8,
              fontSize: 13, color: 'var(--red)',
            }}
          >
            <Info size={13} />
            {error}
          </div>
        )}

        {/* Actions */}
        <div className="fade-up fade-up-4" style={{ display: 'flex', gap: 10, paddingBottom: 40 }}>
          <button
            type="submit"
            className="btn-primary"
            disabled={createMutation.isPending}
            data-testid="submit-experiment-btn"
          >
            {createMutation.isPending ? 'Creating…' : 'Create experiment'}
          </button>
          <button type="button" className="btn-ghost" onClick={() => navigate('/experiments')}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}
