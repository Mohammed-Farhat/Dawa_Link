import { TextInput } from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useRef, useState } from 'react'

import { api, ApiFailure, type Schemas, unwrap } from '../../api/client'
import { Banner } from '../../components/layout'
import { calendarDate, lbp } from '../../format'
import { errorMessage, strings } from '../../strings/en'
import { saveFile, sendStockFile, useStock, useWaitingUpload, type Zone } from './data'

const s = strings.pharmacy.stock
const u = strings.pharmacy.upload

type Item = Schemas['StockItem']
type Upload = Schemas['StockUpload']

const ZONES: (Zone | null)[] = [null, 'NEAR_EXPIRY', 'EARLY_RELEASE', 'PRIVATE', 'EXPIRED']
const TONE: Record<Item['zone'], string> = {
  NEAR_EXPIRY: 'green',
  EARLY_RELEASE: 'blue',
  PRIVATE: 'grey',
  EXPIRED: 'red',
  NOT_ELIGIBLE: 'red',
}

function codeOf(error: unknown): string {
  return error instanceof ApiFailure ? error.code : 'INTERNAL_ERROR'
}

/** PS-6: the pharmacy's whole stock. Private: only the pharmacy sees it. */
export function InventoryPage() {
  return (
    <main className="portal__main">
      <h1 className="page-title">{strings.pharmacy.inventory}</h1>
      <StockFile />
      <StockTable />
      <AddBox />
    </main>
  )
}

/**
 * A stock file, in two steps: it is read and summarised, and nothing changes until
 * [Apply] (SM-4). The file is the whole stock: what it doesn't name is set to 0.
 */
function StockFile() {
  const queryClient = useQueryClient()
  const waiting = useWaitingUpload()
  const picker = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const [applied, setApplied] = useState(false)
  const upload = waiting.data?.upload ?? null

  async function run(action: () => Promise<unknown>, done = false) {
    setBusy(true)
    setFailed(null)
    setApplied(false)
    try {
      await action()
      setApplied(done)
      await queryClient.invalidateQueries({ queryKey: ['pharmacy'] })
    } catch (error) {
      const reason = error instanceof ApiFailure ? error.details.reason : null
      setFailed(
        typeof reason === 'string' && codeOf(error) === 'UPLOAD_FAILED'
          ? u.failed(reason)
          : errorMessage(codeOf(error)),
      )
    } finally {
      setBusy(false)
      if (picker.current) picker.current.value = ''
    }
  }

  return (
    <section className="panel" aria-labelledby="stock-file">
      <h2 id="stock-file" className="panel__title">
        {u.title}
      </h2>
      <ol className="plain-steps">
        {u.steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <span className="hint">{u.expiryHint}</span>
      <span className="hint">{u.replaceHint}</span>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        <button
          type="button"
          className="pill-button pill-button--grey"
          onClick={() =>
            void run(() => saveFile('/api/v1/pharmacy/inventory/template', 'dawalink-stock-template.csv'))
          }
        >
          {u.template}
        </button>
        <label className="pill-button file-button">
          {u.choose}
          <input
            ref={picker}
            type="file"
            className="sr-only"
            accept=".csv,text/csv"
            disabled={busy}
            onChange={(event) => {
              const file = event.currentTarget.files?.[0]
              if (file) void run(() => sendStockFile(file))
            }}
          />
        </label>
      </div>
      <div role="status" aria-live="polite" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {busy && <span className="soft">{u.reading}</span>}
        {failed && <Banner tone="red">{failed}</Banner>}
        {applied && <Banner tone="green">{u.applied}</Banner>}
        {upload && !busy && (
          <UploadSummary
            upload={upload}
            onApply={() =>
              void run(
                () =>
                  unwrap(
                    api.POST('/api/v1/pharmacy/inventory/uploads/{upload_id}/apply', {
                      params: { path: { upload_id: upload.id } },
                    }),
                  ),
                true,
              )
            }
            onDiscard={() =>
              void run(() =>
                unwrap(
                  api.POST('/api/v1/pharmacy/inventory/uploads/{upload_id}/discard', {
                    params: { path: { upload_id: upload.id } },
                  }),
                ),
              )
            }
            onErrors={() =>
              void run(() =>
                saveFile(
                  '/api/v1/pharmacy/inventory/uploads/{upload_id}/errors.csv',
                  'dawalink-stock-errors.csv',
                  upload.id,
                ),
              )
            }
          />
        )}
      </div>
    </section>
  )
}

const PROBLEMS_SHOWN = 5

function UploadSummary({
  upload,
  onApply,
  onDiscard,
  onErrors,
}: {
  upload: Upload
  onApply: () => void
  onDiscard: () => void
  onErrors: () => void
}) {
  return (
    <div className="row-card" style={{ background: 'var(--page)' }}>
      <span style={{ fontWeight: 600 }}>{u.waiting(upload.file_name)}</span>
      <span>{u.rows(upload.rows_total, upload.rows_ok, upload.rows_error)}</span>
      <span>{u.changes(upload.summary)}</span>
      {upload.summary.reserved_kept > 0 && (
        <Banner tone="amber">{u.reservedKept(upload.summary.reserved_kept)}</Banner>
      )}
      {upload.errors.length > 0 && (
        <>
          <span className="hint">{u.problems}</span>
          <ul className="plain-list">
            {upload.errors.slice(0, PROBLEMS_SHOWN).map((error) => (
              <li key={error.row} style={{ fontSize: 15 }}>
                <strong>{u.row(error.row)}</strong> · {error.product}: {error.problem}
                {error.did_you_mean.length > 0 && ` · ${u.didYouMean(error.did_you_mean.join(', '))}`}
              </li>
            ))}
          </ul>
          {upload.rows_error > PROBLEMS_SHOWN && (
            <span className="hint">{u.moreProblems(upload.rows_error - PROBLEMS_SHOWN)}</span>
          )}
          <button type="button" className="text-button" style={{ alignSelf: 'flex-start', padding: 0 }} onClick={onErrors}>
            {u.errorsFile}
          </button>
        </>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        <button type="button" className="pill-button" disabled={upload.rows_ok === 0} onClick={onApply}>
          {u.apply}
        </button>
        <button type="button" className="pill-button pill-button--grey" onClick={onDiscard}>
          {u.discard}
        </button>
      </div>
    </div>
  )
}

function StockTable() {
  const [zone, setZone] = useState<Zone | null>(null)
  const [typed, setTyped] = useState('')
  const stock = useStock(zone, typed.trim())
  const items = stock.items
  return (
    <section className="panel" aria-labelledby="stock">
      <div>
        <h2 id="stock" className="panel__title">
          {s.title}
        </h2>
        <span className="hint">{s.private}</span>
      </div>
      <TextInput
        label={s.search}
        size="md"
        value={typed}
        onChange={(event) => setTyped(event.currentTarget.value)}
      />
      <div className="chips" role="group" aria-label={s.zone}>
        {ZONES.map((choice) => (
          <button
            key={choice ?? 'ALL'}
            type="button"
            className="chip"
            aria-pressed={zone === choice}
            onClick={() => setZone(choice)}
          >
            {s.zones[choice ?? 'ALL']}
          </button>
        ))}
      </div>
      {stock.loaded && items.length === 0 && (
        <span className="soft">{typed.trim() || zone ? s.noneFound : s.none}</span>
      )}
      {items.length > 0 && (
        // A wide table scrolls sideways on a phone: the region is reachable by keyboard.
        <div className="table-scroll" role="region" aria-label={s.table} tabIndex={0}>
          <table className="stock-table">
            <thead>
              <tr>
                <th scope="col">{s.product}</th>
                <th scope="col">{s.batch}</th>
                <th scope="col">{s.expiry}</th>
                <th scope="col">{s.inStock}</th>
                <th scope="col">{s.reserved}</th>
                <th scope="col">{s.zone}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <StockRow key={item.id} item={item} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {stock.hasMore && (
        <button type="button" className="text-button" onClick={stock.more}>
          {s.more}
        </button>
      )}
    </section>
  )
}

/** One box. Its quantity is corrected in place, after a sale in the shop (PF-2). */
function StockRow({ item }: { item: Item }) {
  const queryClient = useQueryClient()
  const [typed, setTyped] = useState<string | null>(null)
  const [note, setNote] = useState<{ tone: 'amber' | 'red'; text: string } | null>(null)
  const value = typed ?? String(item.qty_on_hand)
  const changed = typed !== null && typed !== String(item.qty_on_hand) && /^\d+$/.test(typed)

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!changed) return
    setNote(null)
    try {
      const done = await unwrap(
        api.PATCH('/api/v1/pharmacy/inventory/items/{item_id}', {
          params: { path: { item_id: item.id } },
          body: { qty_on_hand: Number(typed) },
        }),
      )
      setTyped(null)
      if (done.reserved_kept) setNote({ tone: 'amber', text: s.reservedKept(done.item.qty_reserved) })
      await queryClient.invalidateQueries({ queryKey: ['pharmacy'] })
    } catch (error) {
      setNote({ tone: 'red', text: errorMessage(codeOf(error)) })
    }
  }

  const status =
    item.zone !== 'NEAR_EXPIRY'
      ? s.zoneOf[item.zone]
      : item.paused
        ? s.paused
        : item.qty_available === 0
          ? s.outOfStock
          : s.zoneOf.NEAR_EXPIRY
  return (
    <>
      <tr>
        <th scope="row">
          {item.product.name}
          {item.product.strength && <span className="hint"> · {item.product.strength}</span>}
        </th>
        <td>{item.batch}</td>
        <td>
          {calendarDate(item.expiry_date)}
          <span className="hint"> · {s.daysLeft(item.days_left)}</span>
        </td>
        <td>
          <form onSubmit={save} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              className="quantity-input"
              type="text"
              inputMode="numeric"
              aria-label={s.quantityOf(item.product.name, item.batch)}
              value={value}
              onChange={(event) => setTyped(event.currentTarget.value.replace(/\D/g, ''))}
            />
            {changed && (
              <button type="submit" className="text-button" style={{ padding: 0 }}>
                {s.saveQuantity}
              </button>
            )}
          </form>
        </td>
        <td>{item.qty_reserved}</td>
        <td>
          <span className={`status-pill status-pill--${item.visible ? 'green' : item.zone === 'NEAR_EXPIRY' ? 'amber' : TONE[item.zone]}`}>
            {status}
          </span>
        </td>
      </tr>
      {note && (
        <tr>
          <td colSpan={6}>
            <Banner tone={note.tone}>{note.text}</Banner>
          </td>
        </tr>
      )}
    </>
  )
}

/** A medicine as the Ministry lists it. The same name and strength can be listed
 * several times, for other packs or makers: the pack and the public price tell them
 * apart. */
function fullName(product: Schemas['ProductSummary']): string {
  const parts = [product.name, product.strength, product.form, product.pack]
  return `${parts.filter(Boolean).join(' · ')} · ${lbp(product.public_price.lbp)}`
}

/** One box typed by hand, with the medicine chosen from the catalog (PS-6). */
function AddBox() {
  const a = s.add
  const queryClient = useQueryClient()
  const [typed, setTyped] = useState('')
  const [product, setProduct] = useState<Schemas['ProductSummary'] | null>(null)
  const [batch, setBatch] = useState('')
  const [expiry, setExpiry] = useState('')
  const [quantity, setQuantity] = useState('')
  const [state, setState] = useState<'idle' | 'added' | string>('idle')
  const wanted = typed.trim()
  const found = useQuery({
    queryKey: ['catalog', wanted],
    queryFn: () =>
      unwrap(api.GET('/api/v1/catalog/products', { params: { query: { q: wanted, limit: 6 } } })),
    enabled: product === null && wanted.length >= 2,
  })

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!product || !batch.trim() || !expiry || !/^\d+$/.test(quantity)) {
      setState('incomplete')
      return
    }
    try {
      await unwrap(
        api.POST('/api/v1/pharmacy/inventory/items', {
          body: {
            product_id: product.id,
            batch: batch.trim(),
            expiry_date: expiry,
            qty: Number(quantity),
          },
        }),
      )
      setProduct(null)
      setTyped('')
      setBatch('')
      setExpiry('')
      setQuantity('')
      setState('added')
      await queryClient.invalidateQueries({ queryKey: ['pharmacy'] })
    } catch (error) {
      setState(codeOf(error))
    }
  }

  return (
    <section className="panel" aria-labelledby="add-box">
      <h2 id="add-box" className="panel__title">
        {a.title}
      </h2>
      <form className="form" onSubmit={submit} noValidate>
        {product ? (
          <div className="row-card__top">
            <span style={{ fontWeight: 600 }}>{fullName(product)}</span>
            <button type="button" className="text-button" onClick={() => setProduct(null)}>
              {a.change}
            </button>
          </div>
        ) : (
          <>
            <TextInput
              label={a.product}
              description={a.productHint}
              size="md"
              autoComplete="off"
              value={typed}
              onChange={(event) => setTyped(event.currentTarget.value)}
            />
            <div role="status" aria-live="polite" className="chips">
              {(found.data?.items ?? []).map((row) => (
                <button
                  key={row.id}
                  type="button"
                  className="chip"
                  aria-label={a.choose(fullName(row))}
                  onClick={() => setProduct(row)}
                >
                  {fullName(row)}
                </button>
              ))}
              {found.isSuccess && found.data.items.length === 0 && (
                <span className="hint">{a.noneFound}</span>
              )}
            </div>
          </>
        )}
        <div className="field-row">
          <TextInput
            label={a.batch}
            size="md"
            autoComplete="off"
            value={batch}
            onChange={(event) => setBatch(event.currentTarget.value)}
          />
          <TextInput
            label={a.expiry}
            size="md"
            type="date"
            value={expiry}
            onChange={(event) => setExpiry(event.currentTarget.value)}
          />
          <TextInput
            label={a.quantity}
            size="md"
            inputMode="numeric"
            value={quantity}
            onChange={(event) => setQuantity(event.currentTarget.value.replace(/\D/g, ''))}
          />
        </div>
        <div role="status" aria-live="polite">
          {state === 'added' && <Banner tone="green">{a.added}</Banner>}
          {state === 'incomplete' && <Banner tone="red">{a.problem}</Banner>}
          {!['idle', 'added', 'incomplete'].includes(state) && (
            <Banner tone="red">{errorMessage(state)}</Banner>
          )}
        </div>
        <button type="submit" className="pill-button" style={{ alignSelf: 'flex-start' }}>
          {a.submit}
        </button>
      </form>
    </section>
  )
}
