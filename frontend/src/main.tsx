import '@fontsource-variable/readex-pro'
import '@mantine/core/styles.css'
import './app/global.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './app/App'
import { reloadOnceWhenAPartFails } from './components/reload'

// A tab left open across a release reloads once to fetch the new one (A#4).
reloadOnceWhenAPartFails()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
