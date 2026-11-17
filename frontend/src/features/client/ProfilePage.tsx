import { NativeSelect, TextInput } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { useSession } from '../../api/session'
import { ChangePassword } from '../../components/ChangePassword'
import { Banner, Screen } from '../../components/layout'
import { errorMessage, strings } from '../../strings/en'
import { useDistricts } from './data'

const m = strings.me

type Me = Schemas['Me']

/**
 * CS-13: who is logged in and what they can set: the phone, the home district (where
 * searches start when no location is shared), and whether the assistant may tell them
 * about other brands. Then notifications, the password and logging out.
 */
export function MePage() {
  const { me, logout } = useSession()
  const unread = useQuery({
    queryKey: ['notifications', 'unread'],
    queryFn: () => unwrap(api.GET('/api/v1/notifications/unread-count')),
    refetchInterval: 30_000,
  })
  return (
    <Screen>
      <h1 className="page-title">{m.title}</h1>
      {me && (
        <div className="row-card">
          <span style={{ fontSize: 18, fontWeight: 600 }}>{me.full_name}</span>
          <span className="soft">{me.email}</span>
          {me.client && (
            <span className="soft">
              {m.missedPickups(me.client.missed_pickups_30d, me.client.missed_pickups_before_pause)}
            </span>
          )}
        </div>
      )}
      <Link to="/notifications" className="row-card row-link" style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
        <span style={{ fontWeight: 600 }}>{strings.notifications.title}</span>
        {(unread.data?.count ?? 0) > 0 && (
          <span className="status-pill status-pill--blue">{strings.notifications.count(unread.data?.count ?? 0)}</span>
        )}
      </Link>
      {me?.client && <ProfileForm key={me.id} me={me} />}
      <section className="row-card" aria-labelledby="password">
        <h2 id="password" className="card__title" style={{ margin: 0 }}>
          {strings.pharmacy.settingsPage.passwordTitle}
        </h2>
        <ChangePassword />
      </section>
      <button type="button" className="pill-button pill-button--grey" onClick={() => void logout()}>
        {m.logOut}
      </button>
    </Screen>
  )
}

function ProfileForm({ me }: { me: Me }) {
  const { refresh } = useSession()
  const districts = useDistricts()
  const client = me.client
  const [phone, setPhone] = useState(me.phone ?? '')
  const [district, setDistrict] = useState(client?.district ? String(client.district.id) : '')
  const [otherBrands, setOtherBrands] = useState(client?.alternatives_ok_default ?? false)
  const [state, setState] = useState<'idle' | 'sending' | 'saved'>('idle')
  const [failed, setFailed] = useState<string | null>(null)

  async function save(event: FormEvent) {
    event.preventDefault()
    setFailed(null)
    setState('sending')
    try {
      await unwrap(
        api.PATCH('/api/v1/me/profile', {
          body: {
            phone: phone.trim() || null,
            district_id: district ? Number(district) : null,
            alternatives_ok_default: otherBrands,
          },
        }),
      )
      await refresh()
      setState('saved')
    } catch (error) {
      setFailed(error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR')
      setState('idle')
    }
  }

  const changed = () => setState('idle')
  return (
    <section className="row-card" aria-labelledby="profile">
      <h2 id="profile" className="card__title" style={{ margin: 0 }}>
        {m.profile}
      </h2>
      <form className="form" onSubmit={save} noValidate>
        <TextInput
          label={m.phone}
          description={m.phoneHint}
          size="md"
          type="tel"
          autoComplete="tel"
          value={phone}
          onChange={(event) => {
            setPhone(event.currentTarget.value)
            changed()
          }}
        />
        <NativeSelect
          label={m.homeDistrict}
          description={m.homeHint}
          size="md"
          value={district}
          onChange={(event) => {
            setDistrict(event.currentTarget.value)
            changed()
          }}
          data={[
            { value: '', label: '' },
            ...(districts.data ?? []).map((row) => ({ value: String(row.id), label: row.name })),
          ]}
        />
        <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, minHeight: 44 }}>
          <input
            type="checkbox"
            style={{ marginTop: 4 }}
            checked={otherBrands}
            onChange={(event) => {
              setOtherBrands(event.currentTarget.checked)
              changed()
            }}
          />
          <span>
            {m.otherBrands}
            <br />
            <span className="hint">{m.otherBrandsHint}</span>
          </span>
        </label>
        <div role="status" aria-live="polite">
          {state === 'saved' && <Banner tone="green">{m.saved}</Banner>}
          {failed && <Banner tone="red">{errorMessage(failed)}</Banner>}
        </div>
        <button type="submit" className="pill-button" style={{ alignSelf: 'flex-start' }} disabled={state === 'sending'}>
          {m.save}
        </button>
      </form>
    </section>
  )
}
