/**
 * =============================================================================
 * KOJI FRONTEND — PUNTO DI INGRESSO DELL'APPLICAZIONE
 * =============================================================================
 * 
 * Questo file è il punto di ingresso dell'applicazione React.
 * Inizializza il rendering del componente App nel DOM.
 * 
 * CONFIGURAZIONE:
 * - React.StrictMode: abilita controlli aggiuntivi per sviluppo
 * - BrowserRouter: gestione routing lato client
 * - future flags: abilita funzionalità future di React Router
 * 
 * STILI:
 * - global.css: stili globali e variabili CSS
 * - app.css: stili specifici dell'applicazione
 */

import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './styles/global.css'
import './styles/components.css'
import './styles/app.css'

/**
 * Rendering dell'applicazione nel DOM.
 * 
 * Utilizza createRoot per il rendering concorrente di React 18+.
 * BrowserRouter abilita la navigazione SPA con supporto per route future.
 */
ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <App />
    </BrowserRouter>
  </React.StrictMode>
)