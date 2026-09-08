/**
 * =============================================================================
 * NAVBAR — BARRA DI NAVIGAZIONE PRINCIPALE
 * =============================================================================
 * 
 * Componente per la navigazione principale dell'applicazione.
 * Include link a tutte le pagine e supporto per menu mobile.
 * 
 * CARATTERISTICHE:
 * - Navigazione con React Router (NavLink)
 * - Icone Lucide React per ogni sezione
 * - Menu hamburger per dispositivi mobili
 * - Evidenziazione pagina attiva
 * - Accessibilità WCAG con attributi ARIA
 * 
 * SEZIONI:
 * - Home: dashboard principale
 * - RAG: interrogazione Knowledge Base
 * - Grafo: Knowledge Graph interattivo
 * - Wiki: pagine semantiche generate
 * - KB: gestione documenti
 * - Modelli: gestione modelli LLM
 * - Monitor: metriche di sistema
 * - Admin: configurazione (icona ingranaggio)
 */

import { NavLink, useLocation } from 'react-router-dom'
import {
  Home, MessageSquare, Network, BookOpen,
  Database, Cpu, Activity, Settings
} from 'lucide-react'
import { useState } from 'react'

/**
 * Configurazione link di navigazione.
 * Ogni link ha: percorso, icona e etichetta visualizzata.
 */
const links = [
  { to: '/', icon: Home, label: 'Home' },
  { to: '/rag', icon: MessageSquare, label: 'RAG' },
  { to: '/graph', icon: Network, label: 'Grafo' },
  { to: '/wiki', icon: BookOpen, label: 'Wiki' },
  { to: '/kb', icon: Database, label: 'KB' },
  { to: '/models', icon: Cpu, label: 'Modelli' },
  { to: '/monitor', icon: Activity, label: 'Monitor' },
]

/**
 * Componente Navbar.
 * 
 * Renderizza:
 * - Logo Koji con link alla home
 * - Menu desktop con link alle sezioni
 * - Pulsante hamburger per menu mobile
 * - Link alla pagina Admin
 */
export default function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()

  return (
    <nav className="navbar" role="navigation" aria-label="Navigazione principale">
      <a href="/" className="navbar-logo" aria-label="Koji — Torna alla home">
        <span className="logo-icon" aria-hidden="true">K</span>
        Koji
      </a>

      {/* Menu desktop */}
      <ul className="navbar-links" role="menubar">
        {links.map(l => (
          <li key={l.to} role="none">
            <NavLink
              to={l.to}
              end={l.to === '/'}
              role="menuitem"
              className={({ isActive }) => isActive ? 'active' : ''}
              aria-current={location.pathname === l.to ? 'page' : undefined}
            >
              <l.icon aria-hidden="true" />
              {l.label}
            </NavLink>
          </li>
        ))}
      </ul>

      <div className="navbar-right">
        {/* Pulsante hamburger mobile */}
        <button
          className="navbar-btn"
          onClick={() => setMobileOpen(!mobileOpen)}
          aria-label={mobileOpen ? 'Chiudi menu' : 'Apri menu'}
          aria-expanded={mobileOpen}
          style={{ display: 'none' }}
        >
          {mobileOpen ? '✕' : '☰'}
        </button>

        <NavLink to="/admin" className="navbar-btn" aria-label="Amministrazione">
          <Settings size={18} />
        </NavLink>
      </div>

      {/* Menu mobile (overlay) */}
      {mobileOpen && (
        <div
          style={{
            position: 'fixed', top: '56px', left: 0, right: 0, bottom: 0,
            background: 'rgba(6,10,19,0.95)', zIndex: 999, padding: '1rem'
          }}
          role="dialog"
          aria-label="Menu di navigazione"
        >
          <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {links.map(l => (
              <li key={l.to}>
                <NavLink
                  to={l.to}
                  end={l.to === '/'}
                  onClick={() => setMobileOpen(false)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '10px',
                    padding: '12px 16px', color: 'var(--text-primary)', textDecoration: 'none',
                    borderRadius: '8px', fontSize: '0.9rem'
                  }}
                >
                  <l.icon size={18} />
                  {l.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      )}
    </nav>
  )
}