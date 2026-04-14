import React, { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type VariantStats, type UserAssignment } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import { ArrowLeft, TrendingUp, ArrowRight, Play, Square, BarChart3, Settings, Search, User } from 'lucide-react'

/* ── helpers ── */
function pct(n: number | null | undefined) {
  if (n == null) return <span className="stat-null">—</span>
  return <span className="stat-num">{(n * 100).toFixed(1)}%</span>
}

function lift(challenger: number, current: number) {
  if (!current) return null
  const d = ((challenger - current) / current) * 100
  const color = d > 0 ? 'var(--green)' : d < 0 ? 'var(--red)' : 'var(--ink-3)'
  return (
    <span style={{ fontSize: 11, color, fontFamily: 'IBM Plex Mono', fontWeight: 500 }}>
      {d > 0 ? '+' : ''}{d.toFixed(1)}%
    </span>
  )
}

/* ── Tab bar ── */
function Tabs({
  active,
  onChange,
}: {
  active: 'results' | 'configuration'
  onChange: (t: 'results' | 'configuration') => void
}) {
  const tab = (id: 'results' | 'configuration', label: string, Icon: React.ElementType) => (
    <button
      type="button"
      data-testid={`tab-${id}`}
      onClick={() => onChange(id)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '8px 14px',
        fontSize: 13,
        fontWeight: active === id ? 500 : 400,
        color: active === id ? 'var(--ink)' : 'var(--ink-3)',
        background: 'transparent',
        border: 'none',
        borderBottom: active === id ? '2px solid var(--ink)' : '2px solid transparent',
        cursor: 'pointer',
        transition: 'all 0.12s ease',
        fontFamily: 'Geist, sans-serif',
        marginBottom: -1,
      }}
    >
      <Icon size={13} />
      {label}
    </button>
  )
  return (
    <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: 20 }}>
      {tab('results', 'Results', BarChart3)}
      {tab('configuration', 'Configuration', Settings)}
    </div>
  )
}

/* ── User lookup panel ── */
function UserLookup({ experimentName }: { experimentName: string }) {
  const [userId, setUserId] = useState('')
  const [searched, setSearched] = useState('')

  const { data, isFetching, error } = useQuery({
    queryKey: ['user-assignment', experimentName, searched],
    queryFn: () => api.sdk.userAssignment(searched, experimentName),
    enabled: !!searched,
    retry: false,
  })

  function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    if (userId.trim()) setSearched(userId.trim())
  }

  return (
    <div className="card" style={{ overflow: 'hidden' }}>
      <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8 }}>
        <User size={13} color="var(--ink-2)" />
        <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)' }}>User lookup</span>
        <span style={{ fontSize: 11, color: 'var(--ink-3)', marginLeft: 4 }}>Check which variant a user is assigned to</span>
      </div>
      <div style={{ padding: '16px 20px' }}>
        <form onSubmit={handleSearch} style={{ display: 'flex', gap: 8 }}>
          <input
            className="input-base"
            value={userId}
            onChange={e => setUserId(e.target.value)}
            placeholder="Enter user_id…"
            style={{ flex: 1, maxWidth: 320 }}
            data-testid="user-lookup-input"
          />
          <button type="submit" className="btn-ghost" style={{ gap: 6 }} disabled={isFetching}>
            <Search size={12} />
            {isFetching ? 'Looking up…' : 'Look up'}
          </button>
        </form>

        {data && searched && (
          <div style={{ marginTop: 14 }}>
            {data.assigned ? (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '12px 16px',
                background: 'var(--surface-2)',
                borderRadius: 8,
                border: '1px solid var(--border)',
              }}>
                <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--green)', flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)' }}>
                    <span style={{ fontFamily: 'IBM Plex Mono', fontSize: 12, color: 'var(--ink-2)', marginRight: 8 }}>{data.user_id}</span>
                    is in <span style={{
                      fontFamily: 'IBM Plex Mono',
                      fontSize: 12,
                      padding: '2px 8px',
                      background: 'var(--accent-light)',
                      color: 'var(--accent)',
                      borderRadius: 4,
                      fontWeight: 600,
                    }}>{data.variant}</span>
                  </div>
                  {data.variant_config && (
                    <div style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 4, fontFamily: 'IBM Plex Mono' }}>
                      {data.variant_config.provider}/{data.variant_config.model}
                    </div>
                  )}
                </div>
                <div style={{ textAlign: 'right', fontSize: 11, color: 'var(--ink-3)' }}>
                  {data.exposed_at && (
                    <>
                      <div>Exposed</div>
                      <div style={{ fontFamily: 'IBM Plex Mono' }}>{new Date(data.exposed_at).toLocaleString()}</div>
                    </>
                  )}
                </div>
              </div>
            ) : (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '12px 16px',
                background: 'var(--surface-3)',
                borderRadius: 8,
                border: '1px solid var(--border)',
                fontSize: 13,
                color: 'var(--ink-3)',
              }}>
                <Search size={13} />
                User <span style={{ fontFamily: 'IBM Plex Mono', color: 'var(--ink-2)', marginLeft: 4, marginRight: 4 }}>{data.user_id}</span> has not been assigned to this experiment yet.
              </div>
            )}
          </div>
        )}

        {error && (
          <div style={{ marginTop: 10, fontSize: 12, color: 'var(--red)' }}>
            Failed to look up user.
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Variant Performance Table (horizontal: variants as columns, metrics as rows) ── */
function VariantPerformanceTable({
  variants,
  baselineVariant,
  expStatus,
  onSwitch,
  isSwitching,
}: {
  variants: VariantStats[]
  baselineVariant: VariantStats | undefined
  expStatus: string
  onSwitch: (name: string) => void
  isSwitching: boolean
}) {
  type MetricRow = {
    label: string
    sublabel?: string
    group?: string
    render: (v: VariantStats) => React.ReactNode
  }

  const metricRows: MetricRow[] = [
    {
      label: 'Users',
      group: 'Traffic',
      render: (v) => <span className="stat-num">{v.users.toLocaleString()}</span>,
    },
    {
      label: 'LLM calls',
      group: 'Traffic',
      render: (v) => <span className="stat-num">{v.llm_calls.toLocaleString()}</span>,
    },
    {
      label: 'Conversion rate',
      group: 'Outcomes',
      render: (v) => pct(v.conversion_rate),
    },
    {
      label: 'Lift vs control',
      group: 'Outcomes',
      render: (v) =>
        baselineVariant && v.name !== baselineVariant.name
          ? lift(v.conversion_rate, baselineVariant.conversion_rate)
          : <span className="stat-null">—</span>,
    },
    {
      label: 'p-value',
      sublabel: '(95% CI)',
      group: 'Outcomes',
      render: (v) =>
        v.p_value != null
          ? <span className="stat-num" style={{ color: v.p_value < 0.05 ? 'var(--green)' : 'var(--ink-2)' }}>{v.p_value.toFixed(3)}</span>
          : <span className="stat-null">—</span>,
    },
    {
      label: 'Cost / call',
      group: 'Cost',
      render: (v) =>
        v.avg_cost_per_call != null
          ? <span className="stat-num">${v.avg_cost_per_call.toFixed(5)}</span>
          : <span className="stat-null">—</span>,
    },
    {
      label: 'Cost / conversion',
      group: 'Cost',
      render: (v) =>
        v.cost_per_conversion != null
          ? <span className="stat-num">${v.cost_per_conversion.toFixed(5)}</span>
          : <span className="stat-null">—</span>,
    },
    {
      label: 'Total cost',
      group: 'Cost',
      render: (v) =>
        v.total_cost != null
          ? <span className="stat-num">${v.total_cost.toFixed(4)}</span>
          : <span className="stat-null">—</span>,
    },
    {
      label: 'Avg latency',
      group: 'Performance',
      render: (v) =>
        v.avg_latency_ms != null
          ? <span className="stat-num">{v.avg_latency_ms.toFixed(0)} ms</span>
          : <span className="stat-null">—</span>,
    },
    {
      label: 'p50 latency',
      group: 'Performance',
      render: (v) =>
        v.p50_latency_ms != null
          ? <span className="stat-num">{v.p50_latency_ms.toFixed(0)} ms</span>
          : <span className="stat-null">—</span>,
    },
    {
      label: 'Avg input tokens',
      group: 'Tokens',
      render: (v) =>
        v.avg_input_tokens != null
          ? <span className="stat-num">{v.avg_input_tokens.toFixed(0)}</span>
          : <span className="stat-null">—</span>,
    },
    {
      label: 'Avg output tokens',
      group: 'Tokens',
      render: (v) =>
        v.avg_output_tokens != null
          ? <span className="stat-num">{v.avg_output_tokens.toFixed(0)}</span>
          : <span className="stat-null">—</span>,
    },
  ]

  // Group rows for section headers
  let lastGroup = ''

  const cellBase: React.CSSProperties = {
    padding: '10px 18px',
    borderBottom: '1px solid var(--border)',
    verticalAlign: 'middle',
    whiteSpace: 'nowrap',
  }

  return (
    <div className="card fade-up" style={{ overflow: 'hidden' }} data-testid="variant-performance-table">
      {/* Card header */}
      <div style={{
        padding: '14px 20px',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}>
        <BarChart3 size={13} color="var(--ink-2)" />
        <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)' }}>Variant performance</span>
      </div>

      {/* Scrollable table wrapper */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontSize: 13,
          tableLayout: 'auto',
        }}>
          {/* ── Header row: variants ── */}
          <thead>
            <tr style={{ background: 'var(--surface-2)' }}>
              {/* Metric label column */}
              <th style={{
                ...cellBase,
                textAlign: 'left',
                width: 160,
                minWidth: 140,
                fontSize: 11,
                fontWeight: 500,
                color: 'var(--ink-3)',
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
                borderRight: '1px solid var(--border)',
                position: 'sticky',
                left: 0,
                background: 'var(--surface-2)',
                zIndex: 1,
              }}>
                Metric
              </th>

              {variants.map((v) => (
                <th
                  key={v.name}
                  data-testid={`variant-col-${v.name}`}
                  style={{
                    ...cellBase,
                    textAlign: 'center',
                    minWidth: 170,
                    background: v.is_current ? 'var(--surface-3)' : 'var(--surface-2)',
                    borderRight: '1px solid var(--border)',
                  }}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5 }}>
                    {/* Variant name + badges */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', justifyContent: 'center' }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>{v.name}</span>
                      {v.is_current && (
                        <span style={{
                          fontSize: 10, padding: '1px 6px', borderRadius: 4,
                          background: 'var(--surface)', color: 'var(--ink-3)',
                          fontWeight: 500, letterSpacing: '0.02em',
                          border: '1px solid var(--border)',
                        }}>control</span>
                      )}
                      {v.is_significant && (
                        <span style={{
                          fontSize: 10, padding: '1px 6px', borderRadius: 4,
                          background: 'var(--green-bg)', color: 'var(--green)', fontWeight: 500,
                        }}>✓ sig.</span>
                      )}
                    </div>
                    {/* Provider pill */}
                    <span style={{
                      fontSize: 10,
                      fontFamily: 'IBM Plex Mono',
                      fontWeight: 500,
                      color: 'var(--ink-3)',
                      background: 'var(--surface-3)',
                      border: '1px solid var(--border)',
                      borderRadius: 4,
                      padding: '1px 7px',
                      letterSpacing: '0.02em',
                      textTransform: 'lowercase',
                    }}>
                      {v.provider}
                    </span>
                    {/* Model name */}
                    <span style={{
                      fontSize: 11,
                      fontFamily: 'IBM Plex Mono',
                      color: 'var(--ink-2)',
                      letterSpacing: '-0.01em',
                    }}>
                      {v.model}
                    </span>
                    {/* Switch button */}
                    {!v.is_current && expStatus === 'running' && (
                      <button
                        onClick={() => onSwitch(v.name)}
                        disabled={isSwitching}
                        style={{
                          marginTop: 2,
                          fontSize: 11, color: 'var(--accent)',
                          border: '1px solid var(--accent-light)',
                          background: 'var(--accent-light)',
                          cursor: 'pointer', fontWeight: 500,
                          fontFamily: 'Geist, sans-serif',
                          padding: '2px 8px', borderRadius: 4,
                          transition: 'all 0.1s ease',
                        }}
                        onMouseEnter={e => { e.currentTarget.style.background = '#d0e4ff'; e.currentTarget.style.borderColor = 'var(--accent)' }}
                        onMouseLeave={e => { e.currentTarget.style.background = 'var(--accent-light)'; e.currentTarget.style.borderColor = 'var(--accent-light)' }}
                      >
                        Switch →
                      </button>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>

          {/* ── Metric rows ── */}
          <tbody>
            {metricRows.map(({ label, sublabel, group, render }, idx) => {
              const isGroupStart = group !== lastGroup
              if (isGroupStart) lastGroup = group ?? ''

              return (
                <React.Fragment key={label}>
                  {/* Group section header row */}
                  {isGroupStart && (
                    <tr style={{ background: 'var(--surface-2)' }}>
                      <td
                        colSpan={variants.length + 1}
                        style={{
                          padding: '6px 18px 5px',
                          fontSize: 10,
                          fontWeight: 600,
                          color: 'var(--ink-4)',
                          letterSpacing: '0.06em',
                          textTransform: 'uppercase',
                          borderBottom: '1px solid var(--border)',
                          borderTop: idx > 0 ? '1px solid var(--border)' : undefined,
                        }}
                      >
                        {group}
                      </td>
                    </tr>
                  )}

                  {/* Metric data row */}
                  <tr
                    style={{ transition: 'background 0.1s ease' }}
                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface-2)')}
                    onMouseLeave={e => (e.currentTarget.style.background = '')}
                  >
                    {/* Metric label cell */}
                    <td style={{
                      ...cellBase,
                      textAlign: 'left',
                      borderRight: '1px solid var(--border)',
                      position: 'sticky',
                      left: 0,
                      background: 'inherit',
                      zIndex: 1,
                    }}>
                      <span style={{ fontSize: 12, color: 'var(--ink-2)', fontWeight: 400 }}>{label}</span>
                      {sublabel && (
                        <span style={{ fontSize: 10, color: 'var(--ink-4)', marginLeft: 4 }}>{sublabel}</span>
                      )}
                    </td>

                    {/* Value cells */}
                    {variants.map((v) => (
                      <td
                        key={v.name}
                        data-testid={`cell-${v.name}-${label}`}
                        style={{
                          ...cellBase,
                          textAlign: 'center',
                          borderRight: '1px solid var(--border)',
                          background: v.is_current ? 'rgba(242,241,239,0.35)' : undefined,
                        }}
                      >
                        {render(v)}
                      </td>
                    ))}
                  </tr>
                </React.Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ── Main page ── */
export function ExperimentDetailPage() {
  const { name } = useParams<{ name: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [tab, setTab] = useState<'results' | 'configuration'>('results')

  const { data: exp, isLoading } = useQuery({
    queryKey: ['experiment', name],
    queryFn: () => api.experiments.get(name!),
    refetchInterval: 15_000,
  })

  const { data: results } = useQuery({
    queryKey: ['experiment-results', name],
    queryFn: () => api.experiments.results(name!),
    refetchInterval: 30_000,
    enabled: !!exp && exp.status !== 'draft',
  })

  const startMutation = useMutation({
    mutationFn: () => api.experiments.start(name!),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['experiment', name] }); qc.invalidateQueries({ queryKey: ['experiments'] }) },
  })
  const stopMutation = useMutation({
    mutationFn: () => api.experiments.stop(name!),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['experiment', name] }); qc.invalidateQueries({ queryKey: ['experiments'] }) },
  })
  const switchMutation = useMutation({
    mutationFn: (v: string) => api.experiments.switch(name!, v),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['experiment', name] }); qc.invalidateQueries({ queryKey: ['experiments'] }) },
  })

  if (isLoading) return <div style={{ padding: '40px 32px', color: 'var(--ink-3)', fontSize: 13 }}>Loading…</div>
  if (!exp) return <div style={{ padding: '40px 32px', color: 'var(--red)', fontSize: 13 }}>Experiment not found.</div>

  // The variant marked is_current is used only for lift computation (the server sets it from experiment config)
  // We don't surface this role label in UI — Statsig-style: all variants are equal in display
  const baselineVariant = results?.variants.find(v => v.is_current)

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: '40px 32px' }}>
      {/* Breadcrumb */}
      <div className="fade-up fade-up-1" style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
        <button
          type="button"
          onClick={() => navigate('/experiments')}
          style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, color: 'var(--ink-3)', border: 'none', background: 'transparent', cursor: 'pointer', padding: '4px 6px', borderRadius: 5 }}
          onMouseEnter={e => (e.currentTarget.style.color = 'var(--ink)')}
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--ink-3)')}
        >
          <ArrowLeft size={12} /> Experiments
        </button>
        <span style={{ color: 'var(--ink-4)', fontSize: 12 }}>/</span>
        <span style={{ fontSize: 12, color: 'var(--ink-2)', fontFamily: 'IBM Plex Mono' }}>{exp.name}</span>
      </div>

      {/* Title row */}
      <div className="fade-up fade-up-1" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <h1 className="font-serif" style={{ fontSize: 26, letterSpacing: '-0.02em', color: 'var(--ink)', margin: 0 }}>
              {exp.name}
            </h1>
            <StatusBadge status={exp.status} />
          </div>
          {exp.description && (
            <p style={{ fontSize: 13, color: 'var(--ink-3)', margin: 0 }}>{exp.description}</p>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8, flexShrink: 0, marginLeft: 20 }}>
          {exp.status === 'draft' && (
            <button className="btn-success" onClick={() => startMutation.mutate()} disabled={startMutation.isPending} data-testid="start-experiment-btn">
              <Play size={12} strokeWidth={2.5} /> Start
            </button>
          )}
          {exp.status === 'running' && (
            <button className="btn-danger" onClick={() => stopMutation.mutate()} disabled={stopMutation.isPending} data-testid="stop-experiment-btn">
              <Square size={12} strokeWidth={2.5} /> Stop
            </button>
          )}
        </div>
      </div>

      {/* Recommendation banner */}
      {results?.recommendation?.action === 'switch' && (
        <div className="rec-banner fade-up fade-up-2" style={{ marginBottom: 24 }} data-testid="recommendation-banner">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
              <TrendingUp size={15} color="white" />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)', marginBottom: 2 }}>
                {results.recommendation.message}
              </div>
              {results.recommendation.cost_delta_monthly_usd !== undefined && (
                <div style={{ fontSize: 12, color: 'var(--ink-2)' }}>
                  Monthly cost impact:{' '}
                  <span className="stat-num">
                    {results.recommendation.cost_delta_monthly_usd >= 0 ? '+' : ''}${Math.abs(results.recommendation.cost_delta_monthly_usd).toFixed(2)}
                  </span>
                </div>
              )}
            </div>
            {exp.status === 'running' && results.recommendation.variant && (
              <button className="btn-primary" onClick={() => switchMutation.mutate(results.recommendation!.variant!)} disabled={switchMutation.isPending} data-testid="switch-variant-btn" style={{ flexShrink: 0 }}>
                Switch to {results.recommendation.variant} <ArrowRight size={12} />
              </button>
            )}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="fade-up fade-up-2">
        <Tabs active={tab} onChange={setTab} />
      </div>

      {/* ── Results tab ── */}
      {tab === 'results' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {exp.status === 'draft' ? (
            <div className="card" style={{ padding: '40px 32px', textAlign: 'center', color: 'var(--ink-3)', fontSize: 13 }}>
              Start the experiment to see results.
            </div>
          ) : results ? (
            <VariantPerformanceTable
              variants={results.variants}
              baselineVariant={baselineVariant}
              expStatus={exp.status}
              onSwitch={(name) => switchMutation.mutate(name)}
              isSwitching={switchMutation.isPending}
            />
          ) : (
            <div className="card" style={{ padding: '40px 32px', textAlign: 'center', color: 'var(--ink-3)', fontSize: 13 }}>
              Loading results…
            </div>
          )}

          {/* User lookup */}
          <UserLookup experimentName={exp.name} />
        </div>
      )}

      {/* ── Configuration tab ── */}
      {tab === 'configuration' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }} className="fade-up">
          {/* Meta */}
          <div className="card" style={{ overflow: 'hidden' }}>
            <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)' }}>
              <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--ink)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>General</span>
            </div>
            <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 20 }}>
              <div>
                <div className="label">Status</div>
                <StatusBadge status={exp.status} />
              </div>
              <div>
                <div className="label">Outcome events</div>
                {exp.outcome_events.length > 0
                  ? <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {exp.outcome_events.map(ev => (
                        <span key={ev} style={{ fontSize: 11, padding: '2px 7px', background: 'var(--surface-3)', borderRadius: 4, color: 'var(--ink-2)', fontFamily: 'IBM Plex Mono' }}>{ev}</span>
                      ))}
                    </div>
                  : <span style={{ fontSize: 13, color: 'var(--ink-4)' }}>None</span>}
              </div>
              <div>
                <div className="label">Attribution window</div>
                <span className="stat-num">{exp.attribution_window_hours}h</span>
              </div>
              {exp.started_at && (
                <div>
                  <div className="label">Started</div>
                  <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>{new Date(exp.started_at).toLocaleString()}</span>
                </div>
              )}
              {exp.stopped_at && (
                <div>
                  <div className="label">Stopped</div>
                  <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>{new Date(exp.stopped_at).toLocaleString()}</span>
                </div>
              )}
            </div>
          </div>

          {/* Variants */}
          <div className="card" style={{ overflow: 'hidden' }}>
            <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--ink)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Variants</span>
              <span style={{ fontSize: 11, color: 'var(--ink-3)' }}>{exp.variants.length} variants</span>
            </div>
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ textAlign: 'left' }}>Name</th>
                  <th style={{ textAlign: 'left' }}>Provider</th>
                  <th style={{ textAlign: 'left' }}>Model</th>
                  <th>Traffic</th>
                  <th style={{ textAlign: 'left' }}>Config</th>
                </tr>
              </thead>
              <tbody>
                {exp.variants.map(v => (
                  <tr key={v.name}>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontWeight: 500, color: 'var(--ink)' }}>{v.name}</span>
                        {v.is_current && (
                          <span style={{
                            fontSize: 10, padding: '1px 6px', borderRadius: 4,
                            background: 'var(--surface-3)', color: 'var(--ink-3)', fontWeight: 500,
                          }}>control</span>
                        )}
                      </div>
                    </td>
                    <td>
                      <span style={{ fontFamily: 'IBM Plex Mono', fontSize: 12, color: 'var(--ink-2)' }}>{v.provider}</span>
                    </td>
                    <td>
                      <span style={{ fontFamily: 'IBM Plex Mono', fontSize: 12, color: 'var(--ink-2)' }}>{v.model}</span>
                    </td>
                    <td>
                      <span className="stat-num">{v.traffic_pct}%</span>
                    </td>
                    <td>
                      {Object.keys(v.config).length > 0
                        ? <span style={{ fontFamily: 'IBM Plex Mono', fontSize: 11, color: 'var(--ink-3)' }}>{JSON.stringify(v.config)}</span>
                        : <span className="stat-null">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div style={{ height: 40 }} />
    </div>
  )
}
