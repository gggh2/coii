import { Outlet, NavLink, useLocation } from 'react-router-dom'
import { FlaskConical, DollarSign, Activity } from 'lucide-react'

export function Layout() {
  return (
    <div className="min-h-screen flex" style={{ background: 'var(--surface-2)' }}>
      {/* Sidebar — clean, white, minimal */}
      <nav
        className="flex flex-col flex-shrink-0"
        style={{
          width: 220,
          background: 'var(--surface)',
          borderRight: '1px solid var(--border)',
          position: 'sticky',
          top: 0,
          height: '100vh',
        }}
      >
        {/* Logo */}
        <div style={{ padding: '24px 20px 20px', borderBottom: '1px solid var(--border)' }}>
          <div className="flex items-center gap-2.5">
            <div
              style={{
                width: 28,
                height: 28,
                background: 'var(--ink)',
                borderRadius: 7,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Activity size={14} color="white" strokeWidth={2.5} />
            </div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, letterSpacing: '-0.02em', color: 'var(--ink)', lineHeight: 1.2 }}>
                Coii
              </div>
              <div style={{ fontSize: 10, color: 'var(--ink-3)', letterSpacing: '0.06em', textTransform: 'uppercase', fontWeight: 500 }}>
                LLM Lab
              </div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <div style={{ padding: '12px 10px', flex: 1 }}>
          <p style={{ fontSize: 10, color: 'var(--ink-4)', letterSpacing: '0.08em', textTransform: 'uppercase', fontWeight: 500, padding: '4px 10px 8px' }}>
            Workspace
          </p>
          <NavLink
            to="/experiments"
            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
          >
            <FlaskConical size={14} />
            Experiments
          </NavLink>
          <NavLink
            to="/pricing"
            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
          >
            <DollarSign size={14} />
            Pricing
          </NavLink>
        </div>

        {/* Footer */}
        <div style={{ padding: '14px 20px', borderTop: '1px solid var(--border)' }}>
          <div style={{ fontSize: 11, color: 'var(--ink-4)' }}>v0.1.0 · MIT</div>
        </div>
      </nav>

      {/* Content */}
      <main style={{ flex: 1, minWidth: 0, overflowX: 'hidden' }}>
        <Outlet />
      </main>
    </div>
  )
}
