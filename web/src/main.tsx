import React from 'react'
import ReactDOM from 'react-dom/client'
import './styles.css'
import { applyTheme, readTheme } from './theme'
import App from './App'

// Before the first paint, or a rider who chose dark watches the page flash white.
applyTheme(readTheme())

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
