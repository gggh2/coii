import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, type Experiment } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import { Plus, FlaskConical, ArrowRight } from 'lucide-react'

export function ExperimentsPage() {
  const { data: experiments, isLoading } = useQuery({
    queryKey: ['experiments'],
    queryFn: api.experiments.list,
    refetchInterval: 10_000,
  })

  const running = experiments?.filter(e => e.status === 'running').length ?? 0

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '40px 32px' }}>
      {/* Header */}
      <div className="fade-up fade-up-1" style={{ marginBottom: 32 }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
          <div>
            <h1
              className="font-serif"
              style={{ fontSize: 28, lineHeight: 1.15, letterSpacing: '-0.02em', color: 'var(--ink)', marginBottom: 6 }}
            >
              Experiments
            </h1>
            <p style={{ fontSize: 13, color: 'var(--ink-3)' }}>
              {running > 0
                ? <><span style={{ color: 'var(--green)', fontWeight: 500 }}>{running} running</span> · compare models, measure what matters</>
                : 'Compare models and measure business impact'}
            </p>
          </div>
          <Link to="/experiments/new" className="btn-primary" data-testid="new-experiment-btn">
            <Plus size={13} strokeWidth={2.5} />
            New experiment
          </Link>
        </div>
      </div>

      {/* Loading */}
      {isLoading && (
        <div style={{ display: 'flex', gap: 12, flexDirection: 'column' }}>
          {[1,2,3].map(i => (
            <div key={i} className="card" style={{ height: 64, background: 'var(--surface-3)', animation: 'pulse 1.5s infinite' }} />
          ))}
        </div>
      )}

      {/* Empty */}
      {!isLoading && experiments?.length === 0 && (
        <div
          className="card fade-up fade-up-2"
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            padding: '72px 32px',
            gap: 16,
            borderStyle: 'dashed',
          }}
        >
          <div style={{
            width: 44,
            height: 44,
            borderRadius: 12,
            background: 'var(--surface-3)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <FlaskConical size={20} color="var(--ink-3)" />
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 15, fontWeight: 500, color: 'var(--ink)', marginBottom: 4 }}>No experiments yet</div>
            <div style={{ fontSize: 13, color: 'var(--ink-3)' }}>Create one to start testing models against real business outcomes</div>
          </div>
          <Link to="/experiments/new" className="btn-primary" style={{ marginTop: 4 }}>
            <Plus size={13} /> Create first experiment
          </Link>
        </div>
      )}

      {/* Experiment list */}
      {experiments && experiments.length > 0 && (
        <div className="card fade-up fade-up-2" style={{ overflow: 'hidden' }}>
          {experiments.map((exp: Experiment, idx: number) => (
            <Link
              key={exp.id}
              to={`/experiments/${exp.name}`}
              data-testid={`experiment-row-${exp.name}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: '16px 20px',
                borderBottom: idx < experiments.length - 1 ? '1px solid var(--border)' : 'none',
                textDecoration: 'none',
                transition: 'background 0.1s ease',
                cursor: 'pointer',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface-2)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              {/* Status dot */}
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: statusColor(exp.status), marginRight: 14, flexShrink: 0 }} />

              {/* Name + description */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)', marginBottom: 2 }}>
                  {exp.name}
                </div>
                {exp.description && (
                  <div style={{ fontSize: 12, color: 'var(--ink-3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {exp.description}
                  </div>
                )}
              </div>

              {/* Variants count */}
              <div style={{ fontSize: 12, color: 'var(--ink-3)', marginRight: 24, flexShrink: 0 }}>
                {exp.variants.length} variants
              </div>

              {/* Outcome events */}
              {exp.outcome_events.length > 0 && (
                <div style={{ marginRight: 24, flexShrink: 0 }}>
                  {exp.outcome_events.map(ev => (
                    <span key={ev} style={{
                      fontSize: 11,
                      padding: '2px 7px',
                      background: 'var(--surface-3)',
                      borderRadius: 4,
                      color: 'var(--ink-2)',
                      fontFamily: 'IBM Plex Mono',
                      marginRight: 4,
                    }}>
                      {ev}
                    </span>
                  ))}
                </div>
              )}

              {/* Status */}
              <StatusBadge status={exp.status} />

              {/* Arrow */}
              <ArrowRight size={13} color="var(--ink-4)" style={{ marginLeft: 12, flexShrink: 0 }} />
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

function statusColor(status: string): string {
  return {
    running: 'var(--green)',
    draft: 'var(--ink-4)',
    paused: 'var(--amber)',
    completed: 'var(--accent)',
  }[status] ?? 'var(--ink-4)'
}
