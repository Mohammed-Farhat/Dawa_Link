import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, type ReactNode, Suspense, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { useSession } from '../api/session'
import { SessionProvider } from '../api/SessionProvider'
import { CheckEmailPage, LoginPage, SignUpPage, VerifyEmailPage } from '../features/client/AccountPages'
import { AssistantPage } from '../features/client/assistant/AssistantPage'
import { HomePage } from '../features/client/HomePage'
import { MedicinesPage, MePage } from '../features/client/MedicinesPage'
import { RequestPage } from '../features/client/requests/RequestPage'
import { OfferPage } from '../features/client/search/OfferPage'
import { SearchChoicesProvider } from '../features/client/search/place'
import { SearchPage } from '../features/client/search/SearchPage'
import { TicketPage } from '../features/client/TicketPage'
import { WelcomePage } from '../features/client/WelcomePage'
import { StatusPage } from '../features/status/StatusPage'
import { strings } from '../strings/en'
import { theme } from '../theme/theme'
import { NotFoundPage } from './NotFoundPage'

// Loaded only for a pharmacist: a client's phone never downloads the pharmacy's portal
// (docs/11 §10).
const PharmacyPortal = lazy(() => import('../features/pharmacy/PharmacyPortal'))
const RegisterPharmacyPage = lazy(() => import('../features/pharmacy/RegisterPharmacyPage'))

/** The pharmacy's portal: it needs a logged-in pharmacist. */
function ForPharmacists() {
  const { me } = useSession()
  const location = useLocation()
  if (me === undefined) return null
  if (me === null) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (me.role !== 'pharmacist') return <Navigate to="/" replace />
  return (
    <Suspense fallback={null}>
      <PharmacyPortal />
    </Suspense>
  )
}

/** A page of the client's portal: it needs a logged-in client. */
function ForClients({ children }: { children: ReactNode }) {
  const { me, logout } = useSession()
  const location = useLocation()
  if (me === undefined) return null // still asking the API who we are
  if (me === null) {
    // After logging in, the client comes back to the screen they wanted (docs/11 §7).
    const wanted = location.pathname === '/' ? '/welcome' : '/login'
    return <Navigate to={wanted} replace state={{ from: location.pathname }} />
  }
  if (me.role === 'pharmacist') return <Navigate to="/pharmacy" replace />
  if (me.role !== 'client') {
    const s = strings.otherRole
    return (
      <main className="screen screen--plain">
        <h1 className="page-title">{s.title}</h1>
        <p className="soft">{s.body}</p>
        <button type="button" className="pill-button pill-button--grey" onClick={() => void logout()}>
          {strings.me.logOut}
        </button>
      </main>
    )
  }
  return <SearchChoicesProvider>{children}</SearchChoicesProvider>
}

/** A public screen: someone already logged in goes straight to Home. */
function ForVisitors({ children }: { children: ReactNode }) {
  const { me } = useSession()
  if (me === undefined) return null
  if (me !== null) return <Navigate to="/" replace />
  return <>{children}</>
}

export function AppRoutes() {
  const clients = (page: ReactNode) => <ForClients>{page}</ForClients>
  const visitors = (page: ReactNode) => <ForVisitors>{page}</ForVisitors>
  return (
    <Routes>
      <Route path="/welcome" element={visitors(<WelcomePage />)} />
      <Route path="/signup" element={visitors(<SignUpPage />)} />
      <Route path="/login" element={visitors(<LoginPage />)} />
      <Route path="/check-email" element={<CheckEmailPage />} />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route path="/" element={clients(<HomePage />)} />
      <Route path="/search" element={clients(<SearchPage />)} />
      <Route path="/listings/:id" element={clients(<OfferPage />)} />
      <Route path="/assistant" element={clients(<AssistantPage />)} />
      <Route path="/requests/:id" element={clients(<RequestPage />)} />
      <Route path="/medicines" element={clients(<MedicinesPage />)} />
      <Route path="/reservations/:id" element={clients(<TicketPage />)} />
      <Route path="/me" element={clients(<MePage />)} />
      <Route
        path="/pharmacy/signup"
        element={visitors(
          <Suspense fallback={null}>
            <RegisterPharmacyPage />
          </Suspense>,
        )}
      />
      <Route path="/pharmacy/*" element={<ForPharmacists />} />
      <Route path="/status" element={<StatusPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}

export function App() {
  const [queryClient] = useState(() => new QueryClient())
  return (
    <MantineProvider theme={theme} forceColorScheme="light">
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </SessionProvider>
      </QueryClientProvider>
    </MantineProvider>
  )
}
